"""Decrypt or encrypt a Lineage2Ver111 file. The implementation lives in tools/l2mod (l2mod.crypto.ver111).

    python l2ver111.py decrypt interface.u interface.dec.u
    python l2ver111.py encrypt interface.dec.u interface.u
    python l2ver111.py roundtrip interface.u      # proves decrypt + encrypt gives the same bytes
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "l2mod"))

from l2mod.crypto.ver111 import (DEFAULT_FOOTER, FOOTER_LEN, HEADER, KEY, decrypt, encrypt,  # noqa: E402,F401
                                 footer_of)


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
