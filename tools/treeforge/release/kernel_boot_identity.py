"""Source-traced running-kernel measurements; no compilation or provider mutation."""
import hashlib
from pathlib import Path
import struct
import subprocess


def build_id(elf: bytes) -> bytes:
    if elf[:6] != b'\x7fELF\x02\x01' or len(elf) < 64:
        raise ValueError('expected little-endian ELF64 vmlinux')
    offset = struct.unpack_from('<Q', elf, 40)[0]
    size, count = struct.unpack_from('<HH', elf, 58)
    if size != 64 or not 1 <= count <= 4096 or offset + size*count > len(elf):
        raise ValueError('invalid vmlinux section table')
    ids = []
    for i in range(count):
        p = offset + size*i
        if struct.unpack_from('<I', elf, p+4)[0] != 7:  # SHT_NOTE
            continue
        start, length = struct.unpack_from('<QQ', elf, p+24)
        if start+length > len(elf):
            raise ValueError('invalid vmlinux note bounds')
        end = start+length
        while start+12 <= end:
            names, descs, kind = struct.unpack_from('<III', elf, start)
            name = start+12; desc = name+((names+3)&~3)
            next_note = desc+((descs+3)&~3)
            if next_note > end:
                raise ValueError('invalid vmlinux note')
            if kind == 3 and elf[name:name+names] == b'GNU\0':
                ids.append(elf[desc:desc+descs])
            start = next_note
    if len(ids) != 1 or not 16 <= len(ids[0]) <= 64:
        raise ValueError('one GNU kernel build ID required')
    return ids[0]


def measure(generation: Path, boot: Path) -> dict | None:
    raw = generation/'raw'
    # Older saved generations stay usable by the legacy install path. They do
    # not acquire invented measurements and cannot authorize storage-v1 writes.
    if not (raw/'vmlinux').is_file():
        return None
    elf = (raw/'vmlinux').read_bytes(); ident = build_id(elf)
    image = (raw/'Image').read_bytes(); compressed = (raw/'Image.lz4').read_bytes()
    data = boot.read_bytes()
    if data[:8] != b'ANDROID!' or struct.unpack_from('<I', data, 40)[0] not in (3,4):
        raise ValueError('kernel measurement requires Android boot v3/v4')
    length = struct.unpack_from('<I', data, 8)[0]
    if data[4096:4096+length] != compressed:
        raise ValueError('retained kernel differs from boot payload')
    unpacked = subprocess.check_output(['lz4','-d','-c',str(raw/'Image.lz4')])
    note = struct.pack('<III',4,len(ident),3)+b'GNU\0'+ident
    if unpacked != image or image.count(note) != 1:
        raise ValueError('retained Image/build ID does not match boot kernel')
    footer = data[-64:]; original = int.from_bytes(footer[12:20],'big')
    if footer[:4] != b'AVBf' or not 4096+length <= original <= len(data)-64:
        raise ValueError('invalid measured boot AVB payload size')
    sha = lambda b: hashlib.sha256(b).hexdigest()
    return {'schema':'treeforge.kernel.boot-identity.v1', 'gnu_build_id':ident.hex(),
            'boot_payload_bytes':original, 'boot_payload_sha256':sha(data[:original]),
            'boot_kernel_sha256':sha(compressed), 'image_sha256':sha(image),
            'vmlinux_sha256':sha(elf)}
