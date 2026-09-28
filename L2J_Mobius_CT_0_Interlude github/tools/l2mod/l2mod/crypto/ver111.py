"""Lineage II "Lineage2Ver111" files: every client .u package, for example interface.u.

Layout: a 28-byte UTF-16LE header "Lineage2Ver111", the payload XORed with the single byte 0xAC, and a 20-byte plain
footer. Footer bytes 12-15 hold the CRC32 of the header plus the encrypted payload. Bytes 0-11 vary per file and are
kept as they are.
"""
import struct
import zlib

HEADER = "Lineage2Ver111".encode("utf-16-le")
KEY = 0xAC
FOOTER_LEN = 20
# The stock interface.u footer, minus its CRC.
DEFAULT_FOOTER = bytes.fromhex("00000000" "10000000" "68000000" "00000000" "00000000")


def is_ver111(raw):
    return raw.startswith(HEADER)


def xor(data):
    return bytes(b ^ KEY for b in data)


def decrypt(raw):
    if not is_ver111(raw):
        raise ValueError("not a Lineage2Ver111 file (header is %r)" % raw[:28])
    return xor(raw[len(HEADER):-FOOTER_LEN])


def footer_of(raw):
    return raw[-FOOTER_LEN:]


def encrypt(plain, footer=DEFAULT_FOOTER):
    body = HEADER + xor(plain)
    out = bytearray(footer)
    struct.pack_into("<I", out, 12, zlib.crc32(body) & 0xFFFFFFFF)
    return body + bytes(out)


def check_crc(raw):
    return struct.unpack_from("<I", raw, len(raw) - 8)[0] == zlib.crc32(raw[:-FOOTER_LEN]) & 0xFFFFFFFF
