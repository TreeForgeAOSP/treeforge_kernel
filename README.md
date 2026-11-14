# TreeForge Kernel

Reproducible kernel and signed-module provider for Pixel Tablet (`tangorpro`, GS201, arm64), based on Android 15 kernel `android-15.0.0_r0.94`.

`VERSION` is authoritative for the TreeForge release identity. The canonical Android/ChromiumOS profile is `treeforge-bootstrap`.

## Build

```sh
./kernelctl setup
./kernelctl build
```

Choose **Source** for the Google kernel or **TreeForge** for the combined Bootstrap/framebuffer and ChromiumOS/Panthor recipe. The internal TreeForge profile name remains `treeforge-bootstrap`.

Development builds check current published Framebuffer and host-tool provider releases, verify their checksums, and keep the pinned Google source and compiler versions. Host-tool updates must declare the same upstream source revisions. The existing release process continues to promote the completed generation, whose metadata records the provider identities actually used.

Sources and patches are pinned under `profiles/` and `provenance/`. Panthor 1.7 comes from the tracked Linux v7.0 patch series, not a second vendored kernel tree. Builds never flash the device.

Successful builds publish a development provider at `out/development-provider/current`; the five newest successful runs are retained. Its existing `development-provider.json` now records the GPU archive/checksum, matching boot identity, ABI, signing key, four module hashes and whether they changed since the previous export. The completion notice directs ChromiumOS to update when using changed modules. This reports producer changes; ChromiumOS compares its own imported bytes.

The existing Panthor archive is used for both development and release. New exports include the original generation's `build.json` and checksum, preserving applied patch hashes, upstream/tool provider identities and build recipe identity. New builds also record this repository's commit and dirty state. Historical builds retain unknown fields rather than borrowing today's source identity.

To promote an already packaged generation without recompiling:

```sh
./kernelctl build --development-provider-only --generation /absolute/path/to/out/source/<generation>
```

## Release

```sh
./release prepare
./release verify
./release
```

`prepare` selects a completed `treeforge-bootstrap` generation and stages `boot.img`, `module-provider.json`, the module and Panthor archives, and `SHA256SUMS`. `./release` publishes those verified bytes without rebuilding, requires clean `main` aligned with `origin/main`, and offers to advance the next development version afterward.

The module provider is one coherent `vendor_kernel_boot`, `vendor_dlkm`, and `system_dlkm` family. Each generation preserves the matching signed four-module Panthor family; never mix kernel generations.

Kernel module signatures belong to the build. Pixel Partitioner preserves `.ko` bytes exactly. Owner AVB does not re-sign kernel modules.

Android carrier images come from the device. Non-module content is preserved; module trees and metadata are reconstructed and the image family receives local Owner AVB signing. Proprietary carrier images are not released.
