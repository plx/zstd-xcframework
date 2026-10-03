Prebuilt static zstd 1.5.7 for Swift and Apple platforms.

The archive exposes module `ZstdC`, the stable upstream C headers, conservative
Swift API notes, and a small frame-window inspection helper. Native compression
supports multiple workers. The helper is compiled against the exact pinned
upstream revision and hides zstd's static-only frame header layout.

Minimum deployments: macOS 13, iOS/Mac Catalyst 16, tvOS 16, watchOS 9, visionOS 1.
Device and simulator libraries are packaged separately; universal variants
contain their supported architectures. See `provenance.json` for the exact
source commit, source hashes, architecture matrix, and toolchain used.

Use `swift package compute-checksum ZstdC.xcframework.zip` to verify the SwiftPM
checksum. Upstream license texts are included in the distribution. Source and
build scripts are available in this repository; assets are never overwritten.
