import struct, sys

# Reads a Lua 5.1 bytecode chunk with arbitrary header widths/endianness,
# and re-emits it with a different set of header widths/endianness.
# Structure per http://www.lua.org/source/5.1/lundump.c.html

class Reader:
    def __init__(self, data, endian, int_sz, size_t_sz, num_sz, integral):
        self.d = data
        self.p = 0
        self.endian = endian  # '<' or '>'
        self.int_sz = int_sz
        self.size_t_sz = size_t_sz
        self.num_sz = num_sz
        self.integral = integral

    def bytes(self, n):
        b = self.d[self.p:self.p+n]
        self.p += n
        return b

    def byte(self):
        b = self.d[self.p]
        self.p += 1
        return b

    def int_(self):
        b = self.bytes(self.int_sz)
        return int.from_bytes(b, 'little' if self.endian == '<' else 'big')

    def size_t(self):
        b = self.bytes(self.size_t_sz)
        return int.from_bytes(b, 'little' if self.endian == '<' else 'big')

    def number(self):
        b = self.bytes(self.num_sz)
        if self.integral:
            return int.from_bytes(b, 'little' if self.endian == '<' else 'big'), b
        fmt = ('<' if self.endian == '<' else '>') + ('f' if self.num_sz == 4 else 'd')
        return struct.unpack(fmt, b)[0], b

    def string(self):
        n = self.size_t()
        if n == 0:
            return None
        s = self.bytes(n)  # includes trailing NUL
        return s[:-1]  # strip NUL

    def instr(self):
        b = self.bytes(4)  # always 4 bytes regardless of word size
        return int.from_bytes(b, 'little' if self.endian == '<' else 'big')


class Writer:
    def __init__(self, endian, int_sz, size_t_sz, num_sz, integral):
        self.out = bytearray()
        self.endian = endian
        self.int_sz = int_sz
        self.size_t_sz = size_t_sz
        self.num_sz = num_sz
        self.integral = integral

    def bytes_(self, b):
        self.out += b

    def byte(self, v):
        self.out.append(v & 0xff)

    def int_(self, v):
        self.out += v.to_bytes(self.int_sz, 'little' if self.endian == '<' else 'big')

    def size_t(self, v):
        self.out += v.to_bytes(self.size_t_sz, 'little' if self.endian == '<' else 'big')

    def number(self, val, raw_bytes_from_src, src_integral):
        if self.integral:
            self.out += int(val).to_bytes(self.num_sz, 'little' if self.endian == '<' else 'big')
        else:
            fmt = ('<' if self.endian == '<' else '>') + ('f' if self.num_sz == 4 else 'd')
            self.out += struct.pack(fmt, float(val))

    def string(self, s):
        if s is None:
            self.size_t(0)
        else:
            b = s + b'\x00'
            self.size_t(len(b))
            self.out += b

    def instr(self, v):
        self.out += v.to_bytes(4, 'little' if self.endian == '<' else 'big')


def transcode_function(r, w):
    # source name
    w.string(r.string())
    w.int_(r.int_())  # linedefined
    w.int_(r.int_())  # lastlinedefined
    w.byte(r.byte())  # nups
    w.byte(r.byte())  # numparams
    w.byte(r.byte())  # is_vararg
    w.byte(r.byte())  # maxstacksize

    sizecode = r.int_()
    w.int_(sizecode)
    for _ in range(sizecode):
        w.instr(r.instr())

    sizek = r.int_()
    w.int_(sizek)
    for _ in range(sizek):
        t = r.byte()
        w.byte(t)
        if t == 0:  # nil
            pass
        elif t == 1:  # boolean
            w.byte(r.byte())
        elif t == 3:  # number
            val, raw = r.number()
            w.number(val, raw, r.integral)
        elif t == 4:  # string
            w.string(r.string())
        else:
            raise Exception(f"unknown constant type {t} at {r.p}")

    sizep = r.int_()
    w.int_(sizep)
    for _ in range(sizep):
        transcode_function(r, w)

    sizelineinfo = r.int_()
    w.int_(sizelineinfo)
    for _ in range(sizelineinfo):
        w.int_(r.int_())

    sizelocvars = r.int_()
    w.int_(sizelocvars)
    for _ in range(sizelocvars):
        w.string(r.string())
        w.int_(r.int_())  # startpc
        w.int_(r.int_())  # endpc

    sizeupvalues = r.int_()
    w.int_(sizeupvalues)
    for _ in range(sizeupvalues):
        w.string(r.string())


def transcode(data, target_endian, target_int_sz, target_size_t_sz, target_num_sz, target_integral):
    assert data[0:4] == b'\x1bLua'
    version = data[4]
    fmt = data[5]
    src_endian = '<' if data[6] == 1 else '>'
    src_int_sz = data[7]
    src_size_t_sz = data[8]
    src_instr_sz = data[9]
    src_num_sz = data[10]
    src_integral = data[11]
    assert src_instr_sz == 4, "unexpected instruction size"

    r = Reader(data[12:], src_endian, src_int_sz, src_size_t_sz, src_num_sz, src_integral)
    w = Writer(target_endian, target_int_sz, target_size_t_sz, target_num_sz, target_integral)

    transcode_function(r, w)

    header = bytearray()
    header += b'\x1bLua'
    header.append(version)
    header.append(fmt)
    header.append(1 if target_endian == '<' else 0)
    header.append(target_int_sz)
    header.append(target_size_t_sz)
    header.append(4)  # instruction size
    header.append(target_num_sz)
    header.append(target_integral)

    return bytes(header) + bytes(w.out)


if __name__ == '__main__':
    in_path, out_path = sys.argv[1], sys.argv[2]
    data = open(in_path, 'rb').read()
    # target = Buzz's PS3 format: big-endian, size_t=4, lua_Number=4 (float), non-integral
    result = transcode(data, '>', 4, 4, 4, 0)
    open(out_path, 'wb').write(result)
    print(f"wrote {len(result)} bytes to {out_path}")
