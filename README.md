# TreeForge Kernel

TreeForge Kernel is the reproducible kernel build and packaging project for the Pixel Tablet (`tangorpro`).

The project keeps Android boot compatibility while carrying the kernel functionality required by TreeForge Bootstrap and the ChromiumOS port.

## Current target

    Device:             Pixel Tablet
    Codename:           tangorpro
    Architecture:       arm64
    SoC:                Google GS201
    Android baseline:   Android 15
    Kernel release:     android-15.0.0_r0.94
    Canonical profile:  treeforge-bootstrap

The canonical TreeForge kernel profile is `treeforge-bootstrap`.

It combines the accepted Bootstrap framebuffer path, Android compatibility, ChromiumOS userspace prerequisites, Linux v7.0 Panthor work, and GS201 GPU clock/DVFS support into one coherent profile.

## Build interface

`kernelctl` is the supported host interface.

Typical workflow:

    ./kernelctl setup
    ./kernelctl build --profile treeforge-bootstrap

Use:

    ./kernelctl --help
    ./kernelctl setup --help
    ./kernelctl build --help
    ./kernelctl normalize --help
    ./kernelctl flash --help

for the current command surface.

`setup` reconstructs the pinned kernel workspace, `build` builds a selected profile, `normalize` returns managed source to its pinned pristine state, and `flash` consumes a verified TreeForge kernel package.

## Profiles and source ownership

TreeForge kernel changes are expressed as profile-owned patches over pinned source revisions.

Important rules:

- patches contain source-tree changes only;
- profile metadata, patch series, hashes, and source locks remain outside patch contents;
- when a change belongs to source already owned by an existing patch, it is folded into that owning patch rather than layered as a conflicting child patch;
- generated build output is not source;
- proprietary Google/vendor source and binary dependencies are not redistributed merely to make the public repository self-contained.

The `treeforge-bootstrap` profile is the canonical combined profile for current Pixel Tablet work.

## Android and ChromiumOS compatibility

The unified kernel must continue to boot the Android path used by TreeForge Bootstrap.

ChromiumOS support is added without treating Android as disposable. The current profile therefore includes the required ChromiumOS userspace primitives and the Panthor/GS201 work while preserving the Android boot contract.

## Panthor

The current development line carries the Linux v7.0 Panthor 1.7 integration used for the ChromiumOS GPU bring-up.

Panthor work is kept as a coherent source family. Kernel module release assets, when legally redistributable, must be published as a matching set for the same kernel generation rather than mixed across builds.

## Signing

TreeForge kernel packaging supports AOSP and TreeForge signing identities.

The TreeForge path uses the owner AVB identity supplied by Pixel Partitioner. Private keys are not stored in this repository and plaintext private key material is not intended to persist after the signing process exits.

## Local release packaging

`kernelctl release` produces release assets locally from a completed
TreeForge kernel generation. It never creates repositories, pushes tags,
publishes releases, uploads assets, or otherwise performs a GitHub action.

Example:

    ./kernelctl release \
        --version r0.94-v1.0b1 \
        --generation out/source/20261006-164804-0400

The module provider is always generated as one coherent family from the
selected generation; it is not a delta package of only newly changed
modules. If the generation contains the complete Panthor module family,
a separate matching Panthor provider archive is emitted as well.
