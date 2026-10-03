"""Portable tests for build integrity; actual Apple compilation runs in CI."""
import io
import json
from pathlib import Path
import plistlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import build


class BuildIntegrityTests(unittest.TestCase):
    def test_pin_is_complete(self):
        self.assertRegex(build.PIN["commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(build.PIN["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(build.PIN["tag"], "v" + build.PIN["version"])

    def test_device_and_simulator_are_separate(self):
        self.assertEqual(len(build.PLATFORMS), 10)
        self.assertEqual(build.triple("ios", "arm64"), "arm64-apple-ios16.0")
        self.assertEqual(build.triple("ios-simulator", "arm64"), "arm64-apple-ios16.0-simulator")
        self.assertEqual(build.triple("catalyst", "arm64"), "arm64-apple-ios16.0-macabi")
        self.assertEqual(build.triple("visionos", "arm64"), "arm64-apple-xros1.0")
        # arm64 requires watchOS 26, so cannot quietly claim the watchOS 9 baseline.
        self.assertEqual(build.PLATFORMS["watchos"][3], ("arm64_32",))

    def test_sha256_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "sample"
            file.write_bytes(b"abc")
            expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            self.assertEqual(build.sha256(file), expected)
            self.assertEqual(build.file_manifest(root, [file]), {"sample": expected})

    def make_archive(self, root, name, kind=tarfile.REGTYPE):
        archive = root / "source.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind == tarfile.REGTYPE:
                entry.size = 3
                tar.addfile(entry, io.BytesIO(b"abc"))
            else:
                entry.linkname = "../../escape"
                tar.addfile(entry)
        return archive

    def test_safe_extract_regular_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_archive(root, "zstd/lib/zstd.h")
            build.safe_extract(archive, root / "extracted")
            self.assertEqual((root / "extracted/zstd/lib/zstd.h").read_bytes(), b"abc")

    def test_extracts_only_requested_library_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_archive(root, "zstd/tests/unneeded-link", tarfile.SYMTYPE)
            build.safe_extract(archive, root / "extracted", ("zstd/lib", "zstd/LICENSE"))
            self.assertFalse((root / "extracted/zstd/tests/unneeded-link").exists())

    def test_rejects_traversal_absolute_paths_and_links(self):
        for name, kind in [("../escape", tarfile.REGTYPE), ("/tmp/escape", tarfile.REGTYPE),
                           ("zstd/link", tarfile.SYMTYPE), ("zstd/link", tarfile.LNKTYPE)]:
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = self.make_archive(root, name, kind)
                with self.assertRaisesRegex(ValueError, "Unsafe source archive entry"):
                    build.safe_extract(archive, root / "extracted")

    def test_rejects_cached_source_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / f"zstd-{build.PIN['version']}.tar.gz").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                build.fetch_source(root)

    def test_rejects_wrong_or_dirty_upstream_checkout(self):
        with patch.object(build, "run", return_value="incorrect"):
            with self.assertRaisesRegex(ValueError, "Expected upstream commit"):
                build.verify_checkout(Path("."))
        with patch.object(build, "run", side_effect=[build.PIN["commit"], " M lib/zstd.h"]):
            with self.assertRaisesRegex(ValueError, "must be clean"):
                build.verify_checkout(Path("."))
        with patch.object(build, "run", side_effect=[build.PIN["commit"], ""]):
            build.verify_checkout(Path("."))

    def test_zip_is_stable_and_spm_layout_is_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            framework = root / "ZstdC.xcframework"
            framework.mkdir()
            (framework / "Info.plist").write_bytes(b"plist")
            (framework / "LICENSE").write_bytes(b"license")
            first, second = root / "first.zip", root / "second.zip"
            build.deterministic_zip(framework, first)
            build.deterministic_zip(framework, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), ["ZstdC.xcframework/Info.plist", "ZstdC.xcframework/LICENSE"])
                self.assertEqual(archive.getinfo(archive.namelist()[0]).date_time, (2025, 2, 19, 0, 0, 0))

    def test_rejects_invalid_xcframework_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Info.plist").write_bytes(plistlib.dumps({"AvailableLibraries": []}))
            with self.assertRaisesRegex(ValueError, "wrong number"):
                build.validate_framework(root, ["macos"])
            item = {"SupportedPlatform": "ios", "SupportedArchitectures": ["arm64"]}
            (root / "Info.plist").write_bytes(plistlib.dumps({"AvailableLibraries": [item]}))
            with self.assertRaisesRegex(ValueError, "Unexpected XCFramework slice"):
                build.validate_framework(root, ["macos"])


if __name__ == "__main__":
    unittest.main()
