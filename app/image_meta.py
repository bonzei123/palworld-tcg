from __future__ import annotations

import struct
from pathlib import Path


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 24:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    return None


def is_landscape(path: Path) -> bool:
    size = image_size(path)
    return bool(size and size[0] > size[1])


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    n = len(data)
    while i + 8 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        if marker in {0xD8, 0xD9} or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    if kind == b"VP8 " and len(data) >= 30:
        w = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        h = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return w, h
    if kind == b"VP8L" and len(data) >= 25:
        bits = struct.unpack("<I", data[21:25])[0]
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return w, h
    return None
