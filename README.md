# TreeForge Kernel

Kernel provider for TreeForge on Pixel Tablet (tangorpro).

## Target

- Android 15
- GS201 / arm64
- Kernel base: android-15.0.0_r0.94
- Canonical profile: treeforge-bootstrap

The canonical profile supports Android Bootstrap and the kernel features required by TreeForge Alternate OS work.

## Build

Run:

    ./kernelctl setup
    ./kernelctl build --profile treeforge-bootstrap

Use `./kernelctl --help` for the full command surface.

## Provider

Kernel releases contain:

- boot.img
- module-provider.json
- module-provider archive
- SHA256SUMS
- matching Panthor module archive when available

Complete proprietary vendor_kernel_boot, vendor_dlkm, and system_dlkm images are not published.

Consumers start from the current local carrier, preserve all non-module content, replace only the provider module tree, regenerate module metadata, and apply Owner AVB locally.

This includes preserving device files such as vendor_dlkm/etc/init.insmod.tangorpro.cfg.

## Signing

Pixel Partitioner owns the TreeForge Owner AVB identity.

Private keys are not stored in this repository.

## Release

VERSION is authoritative.

Prepare a release:

    ./release

Publish an already verified release:

    ./release publish

Experimental work stays on separate branches and is not part of normal releases.
