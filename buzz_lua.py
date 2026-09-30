"""Compile Lua 5.1 source into Buzz! .clu bytecode (big-endian, 4-byte size_t, 4-byte float
numbers): luac51.exe (stock x86 Lua 5.1, stripped) -> lua51_transcode.transcode()."""
import os
import subprocess
import tempfile

import lua51_transcode

HERE = os.path.dirname(os.path.abspath(__file__))
LUAC = os.path.join(HERE, "luac51.exe")


def compile_lua(source):
    with tempfile.TemporaryDirectory() as td:
        src, out = os.path.join(td, "s.lua"), os.path.join(td, "s.luac")
        with open(src, "w", encoding="latin-1", newline="\n") as f:
            f.write(source)
        r = subprocess.run([LUAC, "-s", "-o", out, src], capture_output=True, text=True)
        if r.returncode:
            raise ValueError("luac: " + r.stderr.strip())
        data = open(out, "rb").read()
    return lua51_transcode.transcode(data, ">", 4, 4, 4, 0)


def lua_str(s):
    """Quote a Python string as a Lua string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def call(fn, *args):
    def val(a):
        if isinstance(a, str):
            return lua_str(a)
        if isinstance(a, bool):
            return "true" if a else "false"
        return repr(a)
    return "%s(%s)\n" % (fn, ", ".join(val(a) for a in args))
