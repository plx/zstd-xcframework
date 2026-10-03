#!/usr/bin/env python3
"""Build a pinned, static, multithreaded Zstandard XCFramework using only Xcode.

Requires Python 3.9+ and full Xcode; no CMake, Homebrew, or third-party Python packages.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PIN = json.loads((ROOT / "zstd-version.json").read_text())
# Each SDK/variant must be its own XCFramework slice; only architectures are merged.
PLATFORMS = {
    "macos": ("macosx", "macos", "13.0", ("arm64", "x86_64"), ""),
    "ios": ("iphoneos", "ios", "16.0", ("arm64",), ""),
    "ios-simulator": ("iphonesimulator", "ios", "16.0", ("arm64", "x86_64"), "simulator"),
    "catalyst": ("macosx", "ios", "16.0", ("arm64", "x86_64"), "macabi"),
    "tvos": ("appletvos", "tvos", "16.0", ("arm64",), ""),
    "tvos-simulator": ("appletvsimulator", "tvos", "16.0", ("arm64", "x86_64"), "simulator"),
    "watchos": ("watchos", "watchos", "9.0", ("arm64_32",), ""),
    "watchos-simulator": ("watchsimulator", "watchos", "9.0", ("arm64", "x86_64"), "simulator"),
    "visionos": ("xros", "xros", "1.0", ("arm64",), ""),
    "visionos-simulator": ("xrsimulator", "xros", "1.0", ("arm64",), "simulator"),
}


def run(arguments, *, capture=False, cwd=None):
    result = subprocess.run([str(a) for a in arguments], check=True, cwd=cwd,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(directory, paths):
    return {str(path.relative_to(directory)): sha256(path) for path in sorted(set(paths))}


def safe_extract(archive, destination, include_prefixes=None):
    """Reject traversal and links before extracting an untrusted source archive."""
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        if include_prefixes is not None:
            members = [m for m in members if any(m.name == p or m.name.startswith(p + "/") for p in include_prefixes)]
        root = destination.resolve()
        for member in members:
            target = (root / member.name).resolve()
            if not target.is_relative_to(root) or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe source archive entry: {member.name}")
        tar.extractall(destination, members=members)


def fetch_source(work):
    archive = work / f"zstd-{PIN['version']}.tar.gz"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        print(f"Downloading {PIN['source_url']}", flush=True)
        with urllib.request.urlopen(PIN["source_url"], timeout=120) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(archive)
    if sha256(archive) != PIN["source_sha256"]:
        raise ValueError(f"Source checksum mismatch: {archive}")
    # Re-extract each build so a modified source tree cannot bypass archive verification.
    extraction = Path(tempfile.mkdtemp(prefix="source-", dir=work))
    # Upstream CLI tests contain symlinks; only library sources and the selected
    # BSD license are needed for this artifact. Never extract unrelated entries.
    prefix = f"zstd-{PIN['version']}"
    safe_extract(archive, extraction, (prefix + "/lib", prefix + "/LICENSE"))
    return extraction / f"zstd-{PIN['version']}"


def verify_checkout(source):
    commit = run(["git", "-C", source, "rev-parse", "HEAD"], capture=True)
    if commit != PIN["commit"]:
        raise ValueError(f"Expected upstream commit {PIN['commit']}, found {commit}")
    if run(["git", "-C", source, "status", "--porcelain", "--untracked-files=all"], capture=True):
        raise ValueError("The supplied upstream git checkout must be clean")


def triple(platform, arch):
    _, osname, minimum, _, variant = PLATFORMS[platform]
    return f"{arch}-apple-{osname}{minimum}" + (f"-{variant}" if variant else "")


def sources_for(source):
    paths = []
    for directory in ("common", "compress", "decompress", "dictBuilder"):
        paths.extend((source / "lib" / directory).glob("*.c"))
    # Upstream's optimized x86_64 Huffman assembly is guarded on other architectures.
    paths.extend((source / "lib" / "decompress").glob("*.S"))
    paths.extend((ROOT / "native").glob("*.c"))
    # Archive member ordering must not depend on where --source was checked out.
    return sorted(paths, key=lambda p: ("upstream/" + str(p.relative_to(source)))
                  if p.is_relative_to(source) else "builder/" + str(p.relative_to(ROOT)))


def headers_for(source, work):
    headers = work / "headers"
    headers.mkdir(exist_ok=True)
    for name in ("zstd.h", "zstd_errors.h", "zdict.h"):
        shutil.copy2(source / "lib" / name, headers / name)
    for name in ("module.modulemap", "ZstdC.apinotes"):
        shutil.copy2(ROOT / "include" / name, headers / name)
    for path in (ROOT / "native").glob("*.h"):
        shutil.copy2(path, headers / path.name)
    return headers


def build_slice(platform, source, work, jobs):
    sdk, _, _, architectures, _ = PLATFORMS[platform]
    sdk_path = run(["xcrun", "--sdk", sdk, "--show-sdk-path"], capture=True)
    clang = run(["xcrun", "--sdk", sdk, "--find", "clang"], capture=True)
    sources = sources_for(source)
    libraries = []
    for arch in architectures:
        print(f"Compiling {platform}/{arch}", flush=True)
        objects_dir = work / platform / arch
        objects_dir.mkdir(parents=True, exist_ok=True)
        flags = ["-target", triple(platform, arch), "-isysroot", sdk_path,
                 "-O3", "-DNDEBUG", "-DZSTD_MULTITHREAD=1", "-DZSTD_LEGACY_SUPPORT=0",
                 "-fvisibility=hidden", "-fPIC", "-pthread",
                 f"-ffile-prefix-map={source}=zstd", f"-ffile-prefix-map={work}=build",
                 f"-ffile-prefix-map={ROOT}=builder",
                 "-I", source / "lib", "-I", source / "lib" / "common"]
        commands, objects = [], []
        for path in sources:
            obj = objects_dir / (path.parent.name + "_" + path.stem + ".o")
            objects.append(obj)
            commands.append([clang, *flags, "-c", path, "-o", obj])
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
            list(executor.map(run, commands))
        # Clang can silently raise a requested minimum for newer architectures.
        load_commands = run(["xcrun", "vtool", "-show-build", objects_dir / "common_zstd_common.o"], capture=True)
        minimum = re.search(r"minos\s+(\S+)", load_commands)
        if not minimum or minimum.group(1) != PLATFORMS[platform][2]:
            raise ValueError(f"Unexpected deployment target for {platform}/{arch}: {load_commands}")
        library = objects_dir / "libZstdC.a"
        run(["xcrun", "libtool", "-static", "-D", "-o", library, *objects])
        libraries.append(library)
    result = work / platform / "libZstdC.a"
    run(["xcrun", "lipo", "-create", *libraries, "-output", result])
    actual = set(run(["xcrun", "lipo", "-archs", result], capture=True).split())
    if actual != set(architectures):
        raise ValueError(f"Wrong architectures for {platform}: {actual}")
    return result


def cross_smoke(platform, work, headers, library):
    """Link the native API and typecheck its Swift import for every target."""
    sdk, _, _, architectures, _ = PLATFORMS[platform]
    sdk_path = run(["xcrun", "--sdk", sdk, "--show-sdk-path"], capture=True)
    for arch in architectures:
        target = triple(platform, arch)
        print(f"Checking C linkage and Swift 6 import: {target}", flush=True)
        run(["xcrun", "clang", "-target", target, "-isysroot", sdk_path,
             "-I", headers, ROOT / "scripts/smoke.c", library,
             "-o", work / platform / arch / "smoke-c"])
        run(["xcrun", "swiftc", "-typecheck", "-swift-version", "6",
             "-strict-concurrency=complete", "-target", target, "-sdk", sdk_path,
             "-module-cache-path", work / "module-cache", "-I", headers,
             ROOT / "scripts/smoke.swift"])


def smoke_test(work, headers, library):
    print("Running native and Swift 6 macOS smoke tests", flush=True)
    cache = work / "module-cache"
    cache.mkdir(exist_ok=True)
    c_binary = work / "smoke-c"
    swift_binary = work / "smoke-swift"
    run(["xcrun", "clang", "-I", headers, ROOT / "scripts/smoke.c", library, "-o", c_binary])
    run([c_binary])
    run(["xcrun", "swiftc", "-swift-version", "6", "-strict-concurrency=complete",
         "-module-cache-path", cache, "-I", headers, ROOT / "scripts/smoke.swift",
         library, "-o", swift_binary])
    run([swift_binary])


def deterministic_zip(directory, output):
    """Keep ordering, permissions, and ZIP timestamps stable for identical inputs."""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(str(path.relative_to(directory.parent)), (2025, 2, 19, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())


def validate_framework(framework, platforms):
    info = plistlib.loads((framework / "Info.plist").read_bytes())
    libraries = info["AvailableLibraries"]
    if len(libraries) != len(platforms):
        raise ValueError("XCFramework has the wrong number of platform variants")
    expected = {}
    for platform in platforms:
        _, osname, _, architectures, variant = PLATFORMS[platform]
        osname = {"xros": "xros", "macos": "macos"}.get(osname, osname)
        variant = "maccatalyst" if variant == "macabi" else variant
        expected[(osname, variant)] = set(architectures)
    for library in libraries:
        key = (library["SupportedPlatform"], library.get("SupportedPlatformVariant", ""))
        if expected.get(key) != set(library["SupportedArchitectures"]):
            raise ValueError(f"Unexpected XCFramework slice: {library}")
        slice_dir = framework / library["LibraryIdentifier"]
        if not (slice_dir / library["LibraryPath"]).is_file():
            raise ValueError("XCFramework library is missing")
        for header in ("zstd.h", "zstd_errors.h", "zdict.h", "ZstdSupport.h", "module.modulemap", "ZstdC.apinotes"):
            if not (slice_dir / library["HeadersPath"] / header).is_file():
                raise ValueError(f"XCFramework public header is missing: {header}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use a clean git checkout at the pinned upstream commit")
    parser.add_argument("--platform", action="append", choices=PLATFORMS, help="Repeat to select platforms; default: all")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--work", type=Path, default=ROOT / "build")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip executing macOS smoke tests")
    parser.add_argument("--dry-run", action="store_true", help="Print the pinned build matrix without downloading/building")
    args = parser.parse_args()
    platforms = list(dict.fromkeys(args.platform or PLATFORMS))
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.dry_run:
        print(json.dumps({"upstream": PIN, "targets": {p: [triple(p, a) for a in PLATFORMS[p][3]] for p in platforms}}, indent=2))
        return
    if sys.platform != "darwin":
        parser.error("Building Apple XCFrameworks requires macOS with full Xcode")
    work, output = args.work.resolve(), args.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve() if args.source else fetch_source(work)
    if args.source:
        verify_checkout(source)
    headers = headers_for(source, work)
    libraries = {p: build_slice(p, source, work, args.jobs) for p in platforms}
    for platform, library in libraries.items():
        cross_smoke(platform, work, headers, library)
    if "macos" in libraries and not args.skip_smoke:
        smoke_test(work, headers, libraries["macos"])
    # Construct in a temporary directory; retain the old deliverable until success.
    staging = Path(tempfile.mkdtemp(prefix="xcframework-", dir=work))
    framework = staging / "ZstdC.xcframework"
    command = ["xcodebuild", "-create-xcframework"]
    for library in libraries.values():
        command += ["-library", library, "-headers", headers]
    run([*command, "-output", framework])
    validate_framework(framework, platforms)
    shutil.copy2(source / "LICENSE", framework / "LICENSE-zstd")
    shutil.copy2(ROOT / "LICENSE", framework / "LICENSE-builder")
    metadata = {
        "upstream": PIN, "module": "ZstdC", "library": "static",
        "multithreaded": True, "legacy_formats": False, "optimization": "O3",
        "xcode": run(["xcodebuild", "-version"], capture=True),
        "clang": run(["xcrun", "clang", "--version"], capture=True),
        "builder_revision": run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture=True),
        "builder_dirty": bool(run(["git", "-C", ROOT, "status", "--porcelain"], capture=True)),
        "builder_files": file_manifest(ROOT, [ROOT / "scripts/build.py", ROOT / "zstd-version.json",
                         *(ROOT / "native").glob("*"), *(ROOT / "include").glob("*")]),
        "source_verification": "clean-pinned-git-checkout" if args.source else "sha256-verified-release-archive",
        "source_files": file_manifest(source, [p for p in sources_for(source) if p.is_relative_to(source)] +
                                        [source / "lib" / h for h in ("zstd.h", "zdict.h", "zstd_errors.h")]),
        "platforms": {p: {"sdk": PLATFORMS[p][0], "minimum": PLATFORMS[p][2],
                           "sdk_version": run(["xcrun", "--sdk", PLATFORMS[p][0], "--show-sdk-version"], capture=True),
                           "sdk_build": run(["xcrun", "--sdk", PLATFORMS[p][0], "--show-sdk-build-version"], capture=True),
                           "architectures": PLATFORMS[p][3]} for p in platforms},
    }
    (framework / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    final_framework = output / framework.name
    if final_framework.exists():
        shutil.rmtree(final_framework)
    shutil.move(str(framework), str(final_framework))
    archive = output / "ZstdC.xcframework.zip"
    deterministic_zip(final_framework, archive)
    checksum = sha256(archive)
    (output / "ZstdC.xcframework.zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    (output / "checksum.txt").write_text(checksum + "\n")
    (output / "provenance.json").write_text(json.dumps({**metadata, "artifact_sha256": checksum}, indent=2) + "\n")
    print(f"\nArtifact: {archive}\nSwiftPM checksum: {checksum}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
