"""Minimal PNG writer/reader (stdlib zlib). 8-bit RGB, no interlace, filter 0.

Byte stability: the pixel data and the chunk layout are deterministic. The
IDAT payload is zlib level 9, and *its* bytes depend on the zlib build (zlib vs.
zlib-ng can emit different, equally valid streams). That's why Forge's
determinism claim for previews is the pixel hash, not the PNG file hash.
"""

from __future__ import annotations

import struct
import zlib

from forge.errors import RenderError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(width: int, height: int, rgb: bytes, text: dict[str, str] | None = None) -> bytes:
    if len(rgb) != width * height * 3:
        raise RenderError(f"pixel buffer is {len(rgb)} bytes; expected {width * height * 3}")
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))
    out = [PNG_SIGNATURE, _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))]
    for key in sorted(text or {}):
        value = text[key]
        if not (key.isascii() and value.isascii() and 0 < len(key) < 80 and "\0" not in key + value):
            raise RenderError(f"PNG text chunk must be ASCII without NUL: {key!r}")
        out.append(_chunk(b"tEXt", key.encode("ascii") + b"\0" + value.encode("ascii")))
    out.append(_chunk(b"IDAT", zlib.compress(raw, 9)))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def decode_png(data: bytes) -> tuple[int, int, bytes, dict[str, str]]:
    """Decode the PNG subset encode_png writes. Verifies CRCs. Raises RenderError otherwise."""
    if not data.startswith(PNG_SIGNATURE):
        raise RenderError("not a PNG file")
    pos, idat, text, header = len(PNG_SIGNATURE), [], {}, None
    while pos < len(data):
        if pos + 8 > len(data):
            raise RenderError("truncated PNG chunk header")
        (length,), kind = struct.unpack(">I", data[pos:pos + 4]), data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        if len(body) != length or zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise RenderError(f"bad PNG chunk {kind!r}")
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"tEXt":
            k, _, v = body.partition(b"\0")
            text[k.decode("latin-1")] = v.decode("latin-1")
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None or header[2:] != (8, 2, 0, 0, 0):
        raise RenderError(f"unsupported PNG header {header!r}")
    width, height = header[0], header[1]
    raw = zlib.decompress(b"".join(idat))
    stride = width * 3
    if len(raw) != height * (stride + 1):
        raise RenderError("PNG image data has the wrong size")
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        if raw[start] != 0:
            raise RenderError(f"unsupported PNG filter {raw[start]} on row {y}")
        rows.append(raw[start + 1:start + 1 + stride])
    return width, height, b"".join(rows), text
