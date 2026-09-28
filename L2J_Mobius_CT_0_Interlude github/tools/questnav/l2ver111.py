"""Decrypt or encrypt a Lineage II "Lineage2Ver111" file (for example the Interlude interface.u).

Ver111 is a 28-byte UTF-16LE header, "Lineage2Ver111", the payload XORed with the single byte 0xAC, and a 20-byte
plain footer. Footer bytes 12-15 hold the CRC32 of the header plus the encrypted payload; the rest is kept as is.

    python l2ver111.py decrypt interface.u interface.dec.u
    python l2ver111.py encrypt interface.dec.u interface.u
    python l2ver111.py roundtrip interface.u      # proves decrypt + encrypt gives the same bytes
"""
import struct
import sys
import zlib

HEADER = "Lineage2Ver111".encode("utf-16-le")
KEY = 0xAC
FOOTER_LEN = 20
# The footer of the stock Interlude interface.u, minus its CRC.
DEFAULT_FOOTER = bytes.fromhex("00000000" "10000000" "68000000" "00000000" "00000000")


def xor(data):
    return bytes(b ^ KEY for b in data)


def decrypt(raw):
    if not raw.startswith(HEADER):
        raise SystemExit("not a Lineage2Ver111 file (header is %r)" % raw[:28])
    return xor(raw[len(HEADER):-FOOTER_LEN])


def footer_of(raw):
    return raw[-FOOTER_LEN:]


def encrypt(plain, footer=DEFAULT_FOOTER):
    body = HEADER + xor(plain)
    out = bytearray(footer)
    struct.pack_into("<I", out, 12, zlib.crc32(body) & 0xFFFFFFFF)
    return body + bytes(out)


def main(argv):
    if len(argv) < 3:
        raise SystemExit(__doc__)
    mode, src = argv[1], argv[2]
    raw = open(src, "rb").read()
    if mode == "roundtrip":
        plain = decrypt(raw)
        ok = encrypt(plain, footer_of(raw)) == raw
        print("package magic %s, %d bytes, roundtrip %s" % (plain[:4].hex(), len(plain), "OK" if ok else "FAILED"))
        return 0 if ok else 1
    if len(argv) < 4:
        raise SystemExit(__doc__)
    out = decrypt(raw) if mode == "decrypt" else encrypt(raw) if mode == "encrypt" else None
    if out is None:
        raise SystemExit("mode must be decrypt, encrypt or roundtrip")
    open(argv[3], "wb").write(out)
    print("wrote %s (%d bytes)" % (argv[3], len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
