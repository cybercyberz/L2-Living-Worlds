"""Stage-5 gates: .dat tables decrypt, parse and write back exactly; edits encrypt for this client's key."""
import os
import tempfile
import unittest

from l2mod import dat, patch, stock
from l2mod.crypto import ver41x

TABLES = ["sysstring-e.dat", "npcname-e.dat", "itemname-e.dat", "questname-e.dat", "skillname-e.dat",
          "systemmsg-e.dat"]


class Stage5Dat(unittest.TestCase):
    def test_tables_roundtrip(self):
        """Each table parses completely (to the SafePackage trailer) and writes back byte for byte."""
        for name in TABLES:
            with self.subTest(name):
                plain = dat.decrypt(stock.stock_bytes(name))
                self.assertEqual(dat.Table.read(name, plain).to_bytes(), plain)

    def test_reencrypt_is_exact(self):
        """Re-encrypting a stock table's own stream with the l2encdec key rebuilds the stock file exactly,
        footer CRC included: this is the key and format the client reads."""
        raw = stock.stock_bytes("sysstring-e.dat")
        n, d = ver41x.L2ENCDEC_MODULUS, ver41x.L2ENCDEC_DECRYPT_EXPONENT
        stream = bytearray()
        for blk in ver41x._blocks(raw):
            m = pow(int.from_bytes(blk, "big"), d, n).to_bytes(128, "big")
            s = m[3]
            start = 128 - s - ((124 - s) % 4)
            stream += m[start:start + s]
        out = bytearray(raw[:28])
        for i in range(0, len(stream), 124):
            chunk = stream[i:i + 124]
            blk = bytearray(128)
            blk[3] = len(chunk)
            st = 128 - len(chunk) - ((124 - len(chunk)) % 4)
            blk[st:st + len(chunk)] = chunk
            out += pow(int.from_bytes(blk, "big"), ver41x.L2ENCDEC_ENCRYPT_EXPONENT, n).to_bytes(128, "big")
        import struct
        import zlib
        out += b"\0" * 12 + struct.pack("<I", zlib.crc32(bytes(out))) + b"\0" * 4
        self.assertEqual(bytes(out), raw)

    def test_edit_and_clone(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".l2patch", delete=False, encoding="utf-8")
        f.write('package itemname-e.dat\nset 57 name = "Gold Coin"\nclone 57 as 60000\n'
                'set 60000 description = "l2mod test"\n')
        f.close()
        try:
            data, _ = patch.build("itemname-e.dat", [patch.PatchFile(f.name)])
        finally:
            os.unlink(f.name)
        t = dat.Table.read("itemname-e.dat", dat.decrypt(data))
        self.assertEqual(t.find(57)["name"], "Gold Coin")
        self.assertEqual(t.find(60000)["description"], "l2mod test")
        self.assertEqual(t.find(60000)["name"], "Gold Coin")


if __name__ == "__main__":
    unittest.main()
