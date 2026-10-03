# zstd XCFramework

Builds and publishes a static `ZstdC.xcframework` for
[`hdxl-swift-zstd`](https://github.com/plx/hdxl-swift-zstd). The source version is
pinned in [`zstd-version.json`](zstd-version.json): zstd **1.5.7**, commit
`f8745da6ff1ad1e7bab384bd1f9d742439278e99`.

The package includes compression, decompression, dictionary training, and native
multithreading. It uses the upstream release source, with no patches to its
headers. The module includes `zstd.h`, `zstd_errors.h`, and `zdict.h`.

## Build

Install full Xcode with the Apple platform SDKs and select it using
`DEVELOPER_DIR` or `xcode-select`. Python 3 and Swift are required.

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/build.py
```

Build products go to `dist/`. The build pins source identity, cross-compiles each
architecture, creates static archives, combines architectures within each
platform variant, creates the XCFramework, and performs native/Swift smoke
checks. It emits the archive, its checksum, source provenance, and toolchain
metadata. Run `python3 scripts/build.py --help` for local-source and subset-build
options. Subset builds are useful for iteration and must not be published as full
releases.

| Platform | Minimum deployment | Architectures |
| --- | --- | --- |
| macOS | 13 | arm64, x86_64 |
| iOS | 16 | arm64 |
| iOS Simulator | 16 | arm64, x86_64 |
| Mac Catalyst | 16 | arm64, x86_64 |
| tvOS | 16 | arm64 |
| tvOS Simulator | 16 | arm64, x86_64 |
| watchOS | 9 | arm64_32 |
| watchOS Simulator | 9 | arm64, x86_64 |
| visionOS | 1 | arm64 |
| visionOS Simulator | 1 | arm64 |

## Swift imports and window inspection

`ZstdC.apinotes` conservatively annotates native nullability: context creation
remains nullable because it can fail. It also imports `ZSTD_defaultCLevel()` as
`zstdDefaultCompressionLevel()`. The Swift smoke test calls that spelling, so a
missing or misplaced API notes file fails the build. Raw pointers remain raw;
the high-level Swift package provides ownership and buffer safety.

`ZstdC_frameWindowSize` returns the declared window size from a complete standard
or skippable frame header. It encapsulates `ZSTD_getFrameHeader` and its
static-only struct inside a stable, small helper interface compiled with the
pinned engine. This is needed because upstream streaming decompression can take
a one-shot fast path that bypasses the native window-limit check. The Swift
wrapper checks headers before decoding to enforce a consistent window policy.

## Publishing

Tags have the form `zstd-1.5.7-1`; the final number is a packaging revision.
Commit and review changes, then push a new tag. GitHub Actions builds all slices,
checks the tag against the pinned version, creates a build provenance
attestation, and publishes a release with immutable versioned assets. Never
replace an existing archive: publish a new packaging revision and update the
Swift package's URL/checksum together.

```sh
swift package compute-checksum dist/ZstdC.xcframework.zip
```

Manual local builds can also be published after all checks pass; their metadata
identifies the local toolchain. Only Actions-built assets receive the workflow
attestation. This repository's build code is BSD 3-Clause licensed; bundled zstd
code retains its upstream BSD/GPL licensing and notices.
