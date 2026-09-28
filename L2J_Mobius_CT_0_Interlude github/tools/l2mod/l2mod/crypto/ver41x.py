"""Lineage II "Lineage2Ver41x" files (the client .dat tables and some .ini): RSA blocks, then zlib.

Layout: a 28-byte UTF-16LE header "Lineage2Ver413", then 128-byte RSA blocks (textbook RSA, no padding), then a
20-byte footer. Each decrypted block holds up to 124 data bytes: block[3] is the count, and the data sits at
128 - size - ((124 - size) % 4). The joined data is a 4-byte little-endian uncompressed size followed by a zlib
stream.

A client decrypts with a modulus built into its binary and a small exponent. For the official moduli the
matching encryption exponent isn't public. This client, however, was built with the community "l2encdec" modulus
(its L2.bin carries it, and every stock .dat decrypts with it), whose encryption exponent is public. So we can both
read and write its .dat files. Re-encrypting a stock file's own data rebuilds the stock file byte for byte.

Constants: acmi's open-source L2crypt (acmi.l2.clientmod.crypt.rsa.L2Ver41x), checked by decrypting the stock files.
"""
import struct
import zlib

MODULI = {
    411: (int("8c9d5da87b30f5d7cd9dc88c746eaac5bb180267fa11737358c4c95d9adf59dd37689f9befb251508759555d6fe0eca8"
              "7bebe0a10712cf0ec245af84cd22eb4cb675e98eaf5799fca62a20a2baa4801d5d70718dcd43283b8428f1387aec6600"
              "f937bfc7bb72404d187d3a9c438f1ffce9ce365dccf754232ff6def038a41385", 16), 0x1D),
    412: (int("a465134799cf2c45087093e7d0f0f144e6d528110c08f674730d436e40827330eccea46e70acf10cdda7d8f710e3b44d"
              "cca931812d76cd7494289bca8b73823f57efc0515b97e4a2a02612ccfa719cf7885104b06f2e7e2cc967b62e3d3b1aad"
              "b925db94cbc8cd3070a4bb13f7e202c7733a67b1b94c1ebc0afcbe1a63b448cf", 16), 0x25),
    413: (int("97df398472ddf737ef0a0cd17e8d172f0fef1661a38a8ae1d6e829bc1c6e4c3cfc19292dda9ef90175e46e7394a18850"
              "b6417d03be6eea274d3ed1dde5b5d7bde72cc0a0b71d03608655633881793a02c9a67d9ef2b45eb7c08d4be329083ce4"
              "50e68f7867b6749314d40511d09bc5744551baa86a89dc38123dc1668fd72d83", 16), 0x35),
    414: (int("ad70257b2316ce09dfaf2ebc3f63b3d673b0c98a403950e26bb87379b11e17aed0e45af23e7171e5ec1fbc8d1ae32ffb"
              "7801b31266eef9c334b53469d4b7cbe83284273d35a9aab49b453e7012f374496c65f8089f5d134b0eb3d1e3b22051ed"
              "5977a6dd68c4f85785dfcc9f4412c81681944fc4b8ce27caf0242deaa5762e8d", 16), 0x25),
}
# The community "l2encdec" key pair: both halves are public, so files can be made for a client patched to use it.
L2ENCDEC_MODULUS = int(
    "75b4d6de5c016544068a1acf125869f43d2e09fc55b8b1e289556daf9b8757635593446288b3653da1ce91c87bb1a5c1"
    "8f16323495c55d7d72c0890a83f69bfd1fd9434eb1c02f3e4679edfa43309319070129c267c85604d87bb65bae205de3"
    "707af1d2108881abb567c3b3d069ae67c3a4c6a3aa93d26413d4c66094ae2039", 16)
L2ENCDEC_DECRYPT_EXPONENT = 0x1D
L2ENCDEC_ENCRYPT_EXPONENT = int(
    "30b4c2d798d47086145c75063c8e841e719776e400291d7838d3e6c4405b504c6a07f8fca27f32b86643d2649d1d5f12"
    "4cdd0bf272f0909dd7352fe10a77b34d831043d9ae541f8263c6fe3d1c14c2f04e43a7253a6dda9a8c1562cbd493c1b6"
    "31a1957618ad5dfe5ca28553f746e2fc6f2db816c7db223ec91e955081c1de65", 16)

HEADER_LEN = 28
FOOTER_LEN = 20
BLOCK = 128


class Ver41xError(Exception):
    pass


def version_of(raw):
    head = raw[:HEADER_LEN].decode("utf-16-le", "replace")
    if not head.startswith("Lineage2Ver"):
        raise Ver41xError("not a Lineage2Ver file")
    return int(head[len("Lineage2Ver"):])


def _blocks(raw):
    body = raw[HEADER_LEN:len(raw) - FOOTER_LEN]
    if len(body) % BLOCK:
        raise Ver41xError("body is not a whole number of 128-byte blocks")
    return [body[i:i + BLOCK] for i in range(0, len(body), BLOCK)]


def decrypt(raw, modulus=None, exponent=None):
    """The decompressed contents of a Ver41x file."""
    ver = version_of(raw)
    if modulus is None:
        if ver not in MODULI:
            raise Ver41xError("unknown version %d" % ver)
        modulus, exponent = MODULI[ver]
    data = bytearray()
    for blk in _blocks(raw):
        m = pow(int.from_bytes(blk, "big"), exponent, modulus).to_bytes(BLOCK, "big")
        size = m[3]
        if size > 124:
            raise Ver41xError("bad block (wrong key?)")
        start = BLOCK - size - ((124 - size) % 4)
        data += m[start:start + size]
    if len(data) < 4:
        raise Ver41xError("no data")
    want = int.from_bytes(data[:4], "little")
    try:
        out = zlib.decompress(bytes(data[4:]))
    except zlib.error as x:
        raise Ver41xError("zlib: %s (wrong key?)" % x)
    if len(out) != want:
        raise Ver41xError("size %d, header says %d" % (len(out), want))
    return out


def encrypt(plain, modulus, exponent, version=413, level=9):
    """Encrypt for a client that decrypts with `modulus` (and the exponent paired with `exponent`).
    The footer is 12 zero bytes, the CRC32 of everything before it, then 4 zero bytes, as in the stock files."""
    data = len(plain).to_bytes(4, "little") + zlib.compress(plain, level)
    out = bytearray(("Lineage2Ver%d" % version).encode("utf-16-le"))
    for i in range(0, len(data), 124):
        chunk = data[i:i + 124]
        size = len(chunk)
        blk = bytearray(BLOCK)
        blk[3] = size
        start = BLOCK - size - ((124 - size) % 4)
        blk[start:start + size] = chunk
        out += pow(int.from_bytes(blk, "big"), exponent, modulus).to_bytes(BLOCK, "big")
    return bytes(out) + b"\0" * 12 + struct.pack("<I", zlib.crc32(bytes(out)) & 0xFFFFFFFF) + b"\0" * 4
