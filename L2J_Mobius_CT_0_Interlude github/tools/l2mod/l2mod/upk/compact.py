"""Unreal compact indices and the small readers shared by the package code."""
import struct


def read_ci(d, p):
    """Returns (value, new position)."""
    b = d[p]
    p += 1
    neg = b & 0x80
    v = b & 0x3F
    if b & 0x40:
        shift = 6
        while True:
            b = d[p]
            p += 1
            v |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
    return (-v if neg else v), p


def write_ci(v):
    neg = v < 0
    v = abs(v)
    out = bytearray([(0x80 if neg else 0) | (v & 0x3F) | (0x40 if v >= 0x40 else 0)])
    v >>= 6
    while v:
        out.append((v & 0x7F) | (0x80 if v >= 0x80 else 0))
        v >>= 7
    return bytes(out)


class Reader:
    """A cursor over bytes."""

    def __init__(self, data, pos=0, end=None):
        self.d = data
        self.p = pos
        self.end = len(data) if end is None else end

    def ci(self):
        v, self.p = read_ci(self.d, self.p)
        return v

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def u64(self):
        v = struct.unpack_from("<Q", self.d, self.p)[0]
        self.p += 8
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def fstring(self):
        """An FString: compact length including the null; negative means UTF-16."""
        n = self.ci()
        if n < 0:
            s = self.raw(-n * 2).decode("utf-16-le")
        else:
            s = self.raw(n).decode("latin1")
        return s[:-1] if s.endswith("\0") else s

    def left(self):
        return self.end - self.p


def write_fstring(s, wide=None):
    if wide is None:
        wide = any(ord(c) > 0xFF for c in s)
    if not s:
        return write_ci(0)
    if wide:
        return write_ci(-(len(s) + 1)) + (s + "\0").encode("utf-16-le")
    return write_ci(len(s) + 1) + (s + "\0").encode("latin1")
