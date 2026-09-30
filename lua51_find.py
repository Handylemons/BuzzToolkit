"""Minimal Lua 5.1 chunk walker for Buzz .clu (big-endian, int/size_t/instr/number = 4 bytes,
float numbers). Yields every function prototype with its code (file offset per instruction)
and constants, so single instructions can be patched in place."""
import struct

OP = ["MOVE", "LOADK", "LOADBOOL", "LOADNIL", "GETUPVAL", "GETGLOBAL", "GETTABLE", "SETGLOBAL",
      "SETUPVAL", "SETTABLE", "NEWTABLE", "SELF", "ADD", "SUB", "MUL", "DIV", "MOD", "POW", "UNM",
      "NOT", "LEN", "CONCAT", "JMP", "EQ", "LT", "LE", "TEST", "TESTSET", "CALL", "TAILCALL",
      "RETURN", "FORLOOP", "FORPREP", "TFORLOOP", "SETLIST", "CLOSE", "CLOSURE", "VARARG"]


def decode(i):
    return OP[i & 0x3F], (i >> 6) & 0xFF, (i >> 23) & 0x1FF, (i >> 14) & 0x1FF   # op, A, B, C


def encode(op, a, b, c):
    return OP.index(op) | (a << 6) | (c << 14) | (b << 23)


def functions(d):
    assert d[:12] == bytes.fromhex("1b4c7561510000040404 0400".replace(" ", ""))
    p = 12
    out = []

    def u32():
        nonlocal p
        v = struct.unpack(">I", d[p:p + 4])[0]; p += 4; return v

    def string():
        nonlocal p
        n = u32(); s = d[p:p + n]; p += n
        return s[:-1] if n else None

    def func(path):
        nonlocal p
        string(); u32(); u32(); p += 4
        n = u32(); code = [(p + 4 * i, struct.unpack(">I", d[p + 4 * i:p + 4 * i + 4])[0]) for i in range(n)]; p += 4 * n
        consts = []
        for _ in range(u32()):
            t = d[p]; p += 1
            if t == 0: consts.append(None)
            elif t == 1: consts.append(bool(d[p])); p += 1
            elif t == 3: consts.append(struct.unpack(">f", d[p:p + 4])[0]); p += 4
            elif t == 4: consts.append(string())
            else: raise ValueError("const type %d" % t)
        out.append({"path": path, "code": code, "consts": consts})
        for k in range(u32()):
            func(path + [k])
        n = u32(); p += 4 * n                           # lineinfo (count read first)
        for _ in range(u32()):
            string(); p += 8                            # locvars
        for _ in range(u32()):
            string()                                    # upvalue names
    func([])
    return out
