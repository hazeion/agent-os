"""Small parent-side structural validator for transformed WebP output."""

from __future__ import annotations


MAXIMUM_OUTPUT_BYTES = 512 * 1024
MAXIMUM_OUTPUT_DIMENSION = 1_200
_FORBIDDEN_CHUNKS = {b"ANIM", b"ANMF", b"EXIF", b"ICCP", b"XMP "}


def valid_transformed_webp(data: object) -> bool:
    if not isinstance(data, bytes) or not 20 <= len(data) <= MAXIMUM_OUTPUT_BYTES:
        return False
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or int.from_bytes(data[4:8], "little") != len(data) - 8:
        return False
    position = 12
    image_chunks = 0
    width = height = 0
    while position < len(data):
        if position + 8 > len(data):
            return False
        kind = data[position : position + 4]
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        start = position + 8
        end = start + size
        padded_end = end + (size & 1)
        if end > len(data) or padded_end > len(data) or kind in _FORBIDDEN_CHUNKS:
            return False
        payload = data[start:end]
        if kind == b"VP8X":
            if size != 10 or payload[0] & 0xEF:
                return False
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
        elif kind == b"VP8 ":
            image_chunks += 1
            if size < 10 or payload[3:6] != b"\x9d\x01\x2a":
                return False
            width = int.from_bytes(payload[6:8], "little") & 0x3FFF
            height = int.from_bytes(payload[8:10], "little") & 0x3FFF
        elif kind == b"VP8L":
            image_chunks += 1
            if size < 5 or payload[0] != 0x2F:
                return False
            width = 1 + payload[1] + ((payload[2] & 0x3F) << 8)
            height = 1 + (payload[2] >> 6) + (payload[3] << 2) + ((payload[4] & 0x0F) << 10)
        position = padded_end
    return position == len(data) and image_chunks == 1 and 1 <= width <= MAXIMUM_OUTPUT_DIMENSION and 1 <= height <= MAXIMUM_OUTPUT_DIMENSION


__all__ = ["valid_transformed_webp"]
