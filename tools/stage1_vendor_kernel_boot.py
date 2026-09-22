#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(block)

    return h.hexdigest()


def run(
    args: list[str | Path],
    *,
    capture: bool = False,
) -> str:
    cmd = [str(x) for x in args]

    print(
        "+ " + " ".join(cmd),
        flush=True,
    )

    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if p.stdout:
        print(
            p.stdout,
            end="",
        )

    if p.returncode != 0:
        raise RuntimeError(
            "command failed "
            f"(rc={p.returncode}): "
            + " ".join(cmd)
        )

    if capture:
        return p.stdout

    return ""


def load_json(path: Path) -> dict:
    value = json.loads(
        path.read_text()
    )

    if not isinstance(value, dict):
        raise RuntimeError(
            f"{path}: expected JSON object"
        )

    return value


def decompress_ramdisk(
    path: Path,
    lz4: Path,
) -> tuple[bytes, str]:
    data = path.read_bytes()

    if data.startswith(
        (b"070701", b"070702")
    ):
        return data, "raw"

    if data.startswith(
        b"\x1f\x8b"
    ):
        return (
            gzip.decompress(data),
            "gzip",
        )

    magic = data[:4]

    if magic in (
        bytes.fromhex("02214c18"),
        bytes.fromhex("04224d18"),
    ):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)

            src = d / "ramdisk.lz4"
            dst = d / "ramdisk.cpio"

            src.write_bytes(data)

            run([
                lz4,
                "-d",
                "-f",
                src,
                dst,
            ])

            kind = (
                "lz4-legacy"
                if magic
                == bytes.fromhex(
                    "02214c18"
                )
                else "lz4-frame"
            )

            return (
                dst.read_bytes(),
                kind,
            )

    raise RuntimeError(
        f"{path}: unsupported ramdisk "
        f"compression magic "
        f"{data[:8].hex()}"
    )


def cpio_field(
    header: bytes,
    offset: int,
) -> int:
    return int(
        header[
            offset:offset + 8
        ],
        16,
    )


def parse_newc(
    blob: bytes,
) -> list[dict]:
    records: list[dict] = []

    pos = 0

    while pos + 110 <= len(blob):
        header = blob[
            pos:pos + 110
        ]

        magic = header[:6]

        if magic not in (
            b"070701",
            b"070702",
        ):
            raise RuntimeError(
                "unexpected data inside "
                f"newc archive at offset {pos}"
            )

        record = {
            "magic": magic,
            "ino": cpio_field(
                header,
                6,
            ),
            "mode": cpio_field(
                header,
                14,
            ),
            "uid": cpio_field(
                header,
                22,
            ),
            "gid": cpio_field(
                header,
                30,
            ),
            "nlink": cpio_field(
                header,
                38,
            ),
            "mtime": cpio_field(
                header,
                46,
            ),
            "filesize": cpio_field(
                header,
                54,
            ),
            "devmajor": cpio_field(
                header,
                62,
            ),
            "devminor": cpio_field(
                header,
                70,
            ),
            "rdevmajor": cpio_field(
                header,
                78,
            ),
            "rdevminor": cpio_field(
                header,
                86,
            ),
            "namesize": cpio_field(
                header,
                94,
            ),
            "check": cpio_field(
                header,
                102,
            ),
        }

        name_start = pos + 110
        name_end = (
            name_start
            + record["namesize"]
        )

        raw_name = blob[
            name_start:name_end
        ]

        if not raw_name.endswith(
            b"\0"
        ):
            raise RuntimeError(
                "invalid newc pathname"
            )

        name = (
            raw_name[:-1]
            .decode(
                "utf-8",
                errors="strict",
            )
        )

        data_start = (
            name_end + 3
        ) & ~3

        data_end = (
            data_start
            + record["filesize"]
        )

        payload = blob[
            data_start:data_end
        ]

        pos = (
            data_end + 3
        ) & ~3

        if name == "TRAILER!!!":
            break

        record["name"] = name
        record["data"] = payload

        records.append(record)

    return records


def format_field(
    value: int,
) -> bytes:
    return (
        f"{value:08x}"
        .encode("ascii")
    )


def emit_newc_record(
    record: dict,
    payload: bytes | None = None,
) -> bytes:
    if payload is None:
        payload = record["data"]

    name = (
        record["name"]
        .encode("utf-8")
        + b"\0"
    )

    checksum = (
        sum(payload) & 0xFFFFFFFF
        if record["magic"]
        == b"070702"
        else 0
    )

    header = b"".join([
        record["magic"],
        format_field(
            record["ino"]
        ),
        format_field(
            record["mode"]
        ),
        format_field(
            record["uid"]
        ),
        format_field(
            record["gid"]
        ),
        format_field(
            record["nlink"]
        ),
        format_field(
            record["mtime"]
        ),
        format_field(
            len(payload)
        ),
        format_field(
            record["devmajor"]
        ),
        format_field(
            record["devminor"]
        ),
        format_field(
            record["rdevmajor"]
        ),
        format_field(
            record["rdevminor"]
        ),
        format_field(
            len(name)
        ),
        format_field(
            checksum
        ),
    ])

    output = bytearray()

    output += header
    output += name

    while len(output) % 4:
        output += b"\0"

    output += payload

    while len(output) % 4:
        output += b"\0"

    return bytes(output)


def emit_trailer(
    magic: bytes,
) -> bytes:
    return emit_newc_record({
        "magic": magic,
        "ino": 0,
        "mode": 0,
        "uid": 0,
        "gid": 0,
        "nlink": 1,
        "mtime": 0,
        "devmajor": 0,
        "devminor": 0,
        "rdevmajor": 0,
        "rdevminor": 0,
        "name": "TRAILER!!!",
        "data": b"",
    })


def module_map(
    records: list[dict],
) -> dict[str, dict]:
    result: dict[str, dict] = {}

    for record in records:
        name = record["name"]

        if not name.endswith(
            ".ko"
        ):
            continue

        basename = Path(
            name
        ).name

        if basename in result:
            raise RuntimeError(
                "duplicate kernel module "
                f"basename: {basename}"
            )

        result[basename] = record

    return result


def record_by_basename(
    records: list[dict],
    basename: str,
) -> dict:
    hits = [
        record
        for record in records
        if Path(
            record["name"]
        ).name == basename
    ]

    if len(hits) != 1:
        raise RuntimeError(
            f"{basename}: expected "
            f"exactly one entry, "
            f"found {len(hits)}"
        )

    return hits[0]


def load_order(
    records: list[dict],
) -> list[str]:
    record = record_by_basename(
        records,
        "modules.load",
    )

    return [
        Path(
            line.strip()
        ).name
        for line
        in record["data"]
        .decode(
            "utf-8",
            errors="strict",
        )
        .splitlines()
        if line.strip()
    ]


def verify_header(
    text: str,
    contract: dict,
) -> None:
    header = contract["header"]

    expected = [
        (
            "vendor boot image header version",
            str(header["version"]),
        ),
        (
            "page size",
            f"0x{header['page_size']:08x}",
        ),
        (
            "kernel load address",
            f"0x{header['kernel_offset']:08x}",
        ),
        (
            "ramdisk load address",
            f"0x{header['ramdisk_offset']:08x}",
        ),
        (
            "kernel tags load address",
            f"0x{header['tags_offset']:08x}",
        ),
        (
            "dtb size",
            str(header["dtb_size"]),
        ),
        (
            "dtb address",
            f"0x{header['dtb_offset']:016x}",
        ),
        (
            "vendor bootconfig size",
            str(
                header[
                    "bootconfig_size"
                ]
            ),
        ),
    ]

    for key, value in expected:
        needle = (
            f"{key}: {value}"
        )

        if needle not in text:
            raise RuntimeError(
                "input vendor_kernel_boot "
                "header contract mismatch: "
                f"missing {needle!r}"
            )


def unpack_image(
    image: Path,
    output: Path,
    unpack_bootimg: Path,
    contract: dict,
) -> None:
    output.mkdir(
        parents=True,
        exist_ok=False,
    )

    text = run(
        [
            unpack_bootimg,
            "--boot_img",
            image,
            "--out",
            output,
        ],
        capture=True,
    )

    verify_header(
        text,
        contract,
    )

    if not (
        output / "vendor_ramdisk00"
    ).is_file():
        raise RuntimeError(
            "vendor_ramdisk00 missing "
            "after unpack"
        )

    if not (
        output / "dtb"
    ).is_file():
        raise RuntimeError(
            "DTB missing after unpack"
        )


def make_payload(
    args: argparse.Namespace,
    contract: dict,
) -> None:
    output = Path(
        args.output
    ).resolve()

    control = Path(
        args.control
    ).resolve()

    if output.exists():
        shutil.rmtree(output)

    output.mkdir(
        parents=True,
    )

    unpack_dir = (
        output / ".control-unpack"
    )

    unpack_image(
        control,
        unpack_dir,
        Path(args.unpack_bootimg),
        contract,
    )

    blob, compression = (
        decompress_ramdisk(
            unpack_dir
            / "vendor_ramdisk00",
            Path(args.lz4),
        )
    )

    if compression != "lz4-legacy":
        raise RuntimeError(
            "control image is not "
            "legacy-LZ4"
        )

    records = parse_newc(
        blob
    )

    modules = module_map(
        records
    )

    expected_count = (
        contract[
            "output_module_count"
        ]
    )

    if (
        len(modules)
        != expected_count
    ):
        raise RuntimeError(
            "control module count "
            f"{len(modules)} != "
            f"{expected_count}"
        )

    for removed in (
        contract[
            "remove_modules"
        ]
    ):
        if removed in modules:
            raise RuntimeError(
                "control still contains "
                f"removed module "
                f"{removed}"
            )

    replacement_names = set(
        contract[
            "replace_modules"
        ]
    )

    missing = (
        replacement_names
        - set(modules)
    )

    if missing:
        raise RuntimeError(
            "control is missing "
            "replacement modules: "
            + ", ".join(
                sorted(missing)
            )
        )

    module_dir = (
        output / "modules"
    )

    module_dir.mkdir()

    module_hashes = {}

    for name in sorted(
        replacement_names
    ):
        data = modules[
            name
        ]["data"]

        path = (
            module_dir / name
        )

        path.write_bytes(
            data
        )

        module_hashes[
            name
        ] = sha256_bytes(
            data
        )

    manifest = {
        "schema_version": 1,
        "device": contract[
            "device"
        ],
        "profile": contract[
            "profile"
        ],
        "control_image_sha256":
            sha256_file(
                control
            ),
        "control_module_count":
            len(modules),
        "control_module_names":
            sorted(modules),
        "control_load_order":
            load_order(
                records
            ),
        "replacement_module_sha256":
            module_hashes,
    }

    (
        output / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    shutil.rmtree(
        unpack_dir
    )

    print()
    print(
        "STAGE1_VKB_PAYLOAD=PASS"
    )
    print(
        f"PAYLOAD={output}"
    )
    print(
        "REPLACEMENT_MODULES="
        f"{len(module_hashes)}"
    )


def reconstruct(
    args: argparse.Namespace,
    contract: dict,
) -> None:
    source = Path(
        args.input
    ).resolve()

    payload_dir = Path(
        args.payload
    ).resolve()

    output = Path(
        args.output
    ).resolve()

    work = Path(
        args.work
    ).resolve()

    if work.exists():
        shutil.rmtree(work)

    work.mkdir(
        parents=True,
    )

    input_sha = sha256_file(
        source
    )

    accepted_inputs = set(
        contract[
            "input_sha256"
        ]
    )

    print(
        f"INPUT_SHA256={input_sha}"
    )

    if (
        input_sha
        not in accepted_inputs
    ):
        raise RuntimeError(
            "unsupported "
            "vendor_kernel_boot "
            f"input SHA256: {input_sha}"
        )

    payload_manifest = load_json(
        payload_dir
        / "manifest.json"
    )

    replacement_names = set(
        contract[
            "replace_modules"
        ]
    )

    payload_hashes = (
        payload_manifest[
            "replacement_module_sha256"
        ]
    )

    if (
        set(payload_hashes)
        != replacement_names
    ):
        raise RuntimeError(
            "payload replacement "
            "module set does not "
            "match reconstruction "
            "contract"
        )

    for name in sorted(
        replacement_names
    ):
        path = (
            payload_dir
            / "modules"
            / name
        )

        if not path.is_file():
            raise RuntimeError(
                f"payload module "
                f"missing: {name}"
            )

        actual = sha256_file(
            path
        )

        expected = (
            payload_hashes[
                name
            ]
        )

        if actual != expected:
            raise RuntimeError(
                f"payload module hash "
                f"mismatch: {name}"
            )

    unpack_dir = (
        work / "input"
    )

    unpack_image(
        source,
        unpack_dir,
        Path(args.unpack_bootimg),
        contract,
    )

    ramdisk = (
        unpack_dir
        / "vendor_ramdisk00"
    )

    dtb = (
        unpack_dir
        / "dtb"
    )

    blob, compression = (
        decompress_ramdisk(
            ramdisk,
            Path(args.lz4),
        )
    )

    if compression != "lz4-legacy":
        raise RuntimeError(
            "input ramdisk must use "
            "legacy LZ4"
        )

    records = parse_newc(
        blob
    )

    modules = module_map(
        records
    )

    if (
        len(modules)
        != contract[
            "input_module_count"
        ]
    ):
        raise RuntimeError(
            "input module count "
            f"{len(modules)} != "
            f"{contract['input_module_count']}"
        )

    for removed in (
        contract[
            "remove_modules"
        ]
    ):
        if removed not in modules:
            raise RuntimeError(
                "input is missing "
                "expected removable "
                f"module {removed}"
            )

    control_names = set(
        payload_manifest[
            "control_module_names"
        ]
    )

    projected_names = (
        set(modules)
        - set(
            contract[
                "remove_modules"
            ]
        )
    )

    if (
        projected_names
        != control_names
    ):
        raise RuntimeError(
            "input module population "
            "does not project to the "
            "accepted Stage-1 module "
            "population"
        )

    metadata_before = {}

    for name in (
        contract[
            "preserve_metadata"
        ]
    ):
        record = (
            record_by_basename(
                records,
                name,
            )
        )

        metadata_before[
            name
        ] = sha256_bytes(
            record["data"]
        )

    old_load_record = (
        record_by_basename(
            records,
            "modules.load",
        )
    )

    old_load_lines = (
        old_load_record[
            "data"
        ]
        .decode(
            "utf-8",
            errors="strict",
        )
        .splitlines()
    )

    remove_set = set(
        contract[
            "remove_modules"
        ]
    )

    filtered_load = [
        line
        for line in old_load_lines
        if (
            Path(
                line.strip()
            ).name
            not in remove_set
        )
    ]

    removed_load_count = (
        len(old_load_lines)
        - len(filtered_load)
    )

    if (
        removed_load_count
        != len(remove_set)
    ):
        raise RuntimeError(
            "modules.load removal "
            "count mismatch"
        )

    normalized_load = [
        Path(
            x.strip()
        ).name
        for x in filtered_load
        if x.strip()
    ]

    expected_load = (
        payload_manifest[
            "control_load_order"
        ]
    )

    if (
        normalized_load
        != expected_load
    ):
        raise RuntimeError(
            "input modules.load "
            "does not become the "
            "accepted Stage-1 load "
            "order after removals"
        )

    new_load_data = (
        "\n".join(
            filtered_load
        )
        + "\n"
    ).encode("utf-8")

    rebuilt = bytearray()

    replaced = set()
    removed = set()

    for record in records:
        basename = Path(
            record["name"]
        ).name

        if (
            basename in remove_set
            and record["name"]
            == f"lib/modules/{basename}"
        ):
            removed.add(
                basename
            )
            continue

        data = record[
            "data"
        ]

        if basename in replacement_names:
            data = (
                payload_dir
                / "modules"
                / basename
            ).read_bytes()

            replaced.add(
                basename
            )

        if basename == "modules.load":
            data = new_load_data

        rebuilt += (
            emit_newc_record(
                record,
                data,
            )
        )

    if replaced != replacement_names:
        raise RuntimeError(
            "not every replacement "
            "module was applied"
        )

    if removed != remove_set:
        raise RuntimeError(
            "not every requested "
            "module was removed"
        )

    rebuilt += emit_trailer(
        records[0]["magic"]
    )

    while len(rebuilt) % 4:
        rebuilt += b"\0"

    cpio = (
        work
        / "vendor_ramdisk.cpio"
    )

    compressed = (
        work
        / "vendor_ramdisk"
    )

    cpio.write_bytes(
        rebuilt
    )

    run([
        Path(args.lz4),
        "-l",
        "-12",
        "-f",
        cpio,
        compressed,
    ])

    raw_image = (
        work
        / "vendor_kernel_boot.raw.img"
    )

    header = contract[
        "header"
    ]

    run([
        Path(args.mkbootimg),
        "--header_version",
        str(
            header[
                "version"
            ]
        ),
        "--pagesize",
        hex(
            header[
                "page_size"
            ]
        ),
        "--base",
        "0x0",
        "--kernel_offset",
        hex(
            header[
                "kernel_offset"
            ]
        ),
        "--ramdisk_offset",
        hex(
            header[
                "ramdisk_offset"
            ]
        ),
        "--tags_offset",
        hex(
            header[
                "tags_offset"
            ]
        ),
        "--dtb_offset",
        hex(
            header[
                "dtb_offset"
            ]
        ),
        "--dtb",
        dtb,
        "--vendor_ramdisk",
        compressed,
        "--vendor_boot",
        raw_image,
    ])

    partition_size = contract[
        "partition_size"
    ]

    raw = raw_image.read_bytes()

    if len(raw) > partition_size:
        raise RuntimeError(
            "reconstructed image "
            "exceeds partition size"
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output.open("wb") as f:
        f.write(raw)

        remaining = (
            partition_size
            - len(raw)
        )

        zeroes = (
            b"\0"
            * (1024 * 1024)
        )

        while remaining:
            count = min(
                remaining,
                len(zeroes),
            )

            f.write(
                zeroes[:count]
            )

            remaining -= count

    verify_dir = (
        work / "verify"
    )

    unpack_image(
        output,
        verify_dir,
        Path(args.unpack_bootimg),
        contract,
    )

    if (
        sha256_file(
            verify_dir / "dtb"
        )
        != sha256_file(dtb)
    ):
        raise RuntimeError(
            "DTB identity changed"
        )

    verify_blob, verify_compression = (
        decompress_ramdisk(
            verify_dir
            / "vendor_ramdisk00",
            Path(args.lz4),
        )
    )

    if (
        verify_compression
        != "lz4-legacy"
    ):
        raise RuntimeError(
            "output compression "
            "changed"
        )

    verify_records = parse_newc(
        verify_blob
    )

    verify_modules = module_map(
        verify_records
    )

    if (
        len(verify_modules)
        != contract[
            "output_module_count"
        ]
    ):
        raise RuntimeError(
            "output module count "
            "mismatch"
        )

    if (
        set(verify_modules)
        != control_names
    ):
        raise RuntimeError(
            "output module population "
            "does not match control"
        )

    for name in sorted(
        replacement_names
    ):
        actual = sha256_bytes(
            verify_modules[
                name
            ]["data"]
        )

        expected = (
            payload_hashes[
                name
            ]
        )

        if actual != expected:
            raise RuntimeError(
                "output replacement "
                f"module mismatch: "
                f"{name}"
            )

    verify_load = load_order(
        verify_records
    )

    if (
        verify_load
        != expected_load
    ):
        raise RuntimeError(
            "output modules.load "
            "does not match control"
        )

    for name, old_hash in (
        metadata_before.items()
    ):
        record = (
            record_by_basename(
                verify_records,
                name,
            )
        )

        new_hash = sha256_bytes(
            record["data"]
        )

        if new_hash != old_hash:
            raise RuntimeError(
                "preserved metadata "
                f"changed: {name}"
            )

    print()
    print(
        "=== RECONSTRUCTION ACCEPTANCE ==="
    )

    print(
        f"INPUT_MODULES="
        f"{len(modules)}"
    )

    print(
        f"OUTPUT_MODULES="
        f"{len(verify_modules)}"
    )

    print(
        f"REPLACED_MODULES="
        f"{len(replaced)}"
    )

    print(
        "REMOVED_MODULES="
        + ",".join(
            sorted(removed)
        )
    )

    print(
        "MODULE_LOAD_ORDER=PASS"
    )

    print(
        "PRESERVED_METADATA=PASS"
    )

    print(
        "DTB_IDENTITY=PASS"
    )

    print(
        "FLAT_LAYOUT=PASS"
    )

    print(
        f"OUTPUT_BYTES="
        f"{output.stat().st_size}"
    )

    print(
        f"OUTPUT_SHA256="
        f"{sha256_file(output)}"
    )

    print(
        "STAGE1_VKB_RECONSTRUCTION=PASS"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "TreeForge Stage-1 "
            "vendor_kernel_boot "
            "payload/reconstruction tool"
        )
    )

    parser.add_argument(
        "--contract",
        required=True,
    )

    parser.add_argument(
        "--unpack-bootimg",
        required=True,
    )

    parser.add_argument(
        "--lz4",
        required=True,
    )

    sub = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )

    payload = sub.add_parser(
        "make-payload"
    )

    payload.add_argument(
        "--control",
        required=True,
    )

    payload.add_argument(
        "--output",
        required=True,
    )

    reconstruction = (
        sub.add_parser(
            "reconstruct"
        )
    )

    reconstruction.add_argument(
        "--input",
        required=True,
    )

    reconstruction.add_argument(
        "--payload",
        required=True,
    )

    reconstruction.add_argument(
        "--output",
        required=True,
    )

    reconstruction.add_argument(
        "--work",
        required=True,
    )

    reconstruction.add_argument(
        "--mkbootimg",
        required=True,
    )

    return parser


def main() -> int:
    parser = build_parser()

    args = parser.parse_args()

    contract = load_json(
        Path(args.contract)
    )

    if (
        contract.get(
            "schema_version"
        )
        != 1
    ):
        raise RuntimeError(
            "unsupported reconstruction "
            "contract schema"
        )

    if (
        args.command
        == "make-payload"
    ):
        make_payload(
            args,
            contract,
        )

    elif (
        args.command
        == "reconstruct"
    ):
        reconstruct(
            args,
            contract,
        )

    else:
        raise RuntimeError(
            f"unsupported command "
            f"{args.command}"
        )

    print(
        "TERMINAL_CLOSED=NO"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
