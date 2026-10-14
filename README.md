# TreeForge Kernel

Reproducible kernel build and release tooling for the Pixel Tablet (`tangorpro`).

## Target

    Device:             Pixel Tablet
    Codename:           tangorpro
    Architecture:       arm64
    SoC:                Google GS201
    Android baseline:   Android 15
    Kernel base:        android-15.0.0_r0.94
    Canonical profile:  treeforge-bootstrap

`VERSION` is authoritative for the TreeForge release identity.

## Build

`kernelctl` is the supported host interface.

    ./kernelctl setup
    ./kernelctl build \
        --profile treeforge-bootstrap \
        --signing treeforge

Use `./kernelctl --help` for the full command surface.

Kernel builds do not flash the device.

## Source

Google kernel source is pinned by the repository source locks. TreeForge changes are applied as tracked profile patches.

`treeforge-bootstrap` is the canonical combined profile for Android and ChromiumOS.

Panthor uses the Linux v7.0 Panthor 1.7 source as a tracked patch series. A second source tree is not vendored. Upstream identity and patch hashes are recorded in `provenance/upstream/linux-v7.0-panthor.json`.

## Providers

A release contains:

    boot.img
    module-provider.json
    treeforge-kernel-modules-*.tar.zst
    treeforge-kernel-panthor-*.tar.zst
    SHA256SUMS

The Android module provider is one coherent `vendor_kernel_boot`, `vendor_dlkm`, and `system_dlkm` family.

Each kernel generation preserves the matching signed four-module Panthor family. Releases never mix modules across kernel generations.

Kernel module signatures belong to the kernel build. Pixel Partitioner preserves the `.ko` bytes exactly. Owner AVB does not re-sign kernel modules.

Android carrier images are reconstructed from the current device. Non-module content is preserved, the provider module tree is replaced, module metadata is regenerated, and Owner AVB is applied locally.

Proprietary carrier images are not release assets.

## Release

Prepare and verify local assets:

    ./release

Publish those exact prepared assets:

    ./release publish

Publish does not rebuild or regenerate release assets. It requires a clean `main` matching `origin/main`.

## Layout

    kernelctl
        Build and source controller.

    profiles/
        TreeForge kernel profiles and patches.

    provenance/
        Source locks and upstream provenance.

    tools/treeforge/release/
        Release packaging.

    out/
        Generated output.

    .smoke/
        Local audits.
