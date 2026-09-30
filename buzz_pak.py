"""Read/write Buzz pack containers (INEPACKxxxx.PAK / decrypted <LANG>PACKxxxx.EDAT).

Layout reproduced from retail packs (verified byte-identical against GBRPACK0017):
  * 9 zero bytes, then an uncompressed (STORED) zip,
  * every offset inside the zip is ABSOLUTE - it counts the 9-byte prefix
    (Python's zipfile writes zip-relative offsets; the game reads offsets literally and
    silently drops a pack whose offsets are 9 bytes short),
  * each file's data starts on a 16-byte boundary (zero padding before its local header),
  * no extra fields, version 20, internal_attr/external_attr copied per entry.

    from buzz_pak import read_pak, write_pak
    entries = read_pak("GBRPACK0017.DAT")          # list of Entry(name, data, meta)
    write_pak("out.DAT", entries)
"""
import struct
import time
import zipfile
import zlib
from dataclasses import dataclass, field

PREFIX = b"\x00" * 9
ALIGN = 16


@dataclass
class Entry:
    name: str
    data: bytes
    date_time: tuple = field(default_factory=lambda: time.localtime()[:6])
    internal_attr: int = 1
    external_attr: int = 0x20
    volume: int = 0            # central-directory "disk number start": 0 in DLC packs, varies in GLOBALSCRIPTS.PAK


def read_pak(path):
    z = zipfile.ZipFile(path)
    out = []
    for zi in sorted(z.infolist(), key=lambda x: x.header_offset):
        out.append(Entry(zi.filename, z.read(zi.filename), zi.date_time,
                         zi.internal_attr, zi.external_attr, zi.volume))
    return out


def _dos(dt):
    y, mo, d, h, mi, s = dt
    return ((h << 11) | (mi << 5) | (s // 2)), (((y - 1980) << 9) | (mo << 5) | d)


def write_pak(path, entries, tail_pad=0):
    """tail_pad: zero bytes before the central directory (disc GLOBALSCRIPTS.PAK has 16)."""
    buf = bytearray()                  # zero padding before each header aligns its data to 16 bytes;
                                       # for the first file that is the 7-15 byte "prefix" retail files have
    central = bytearray()
    for e in entries:
        name = e.name.encode("ascii")
        pad = (-(len(buf) + 30 + len(name))) % ALIGN
        buf += b"\x00" * pad
        offset = len(buf)
        crc = zlib.crc32(e.data) & 0xFFFFFFFF
        dtime, ddate = _dos(e.date_time)
        buf += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, dtime, ddate, crc,
                           len(e.data), len(e.data), len(name), 0)
        buf += name + e.data
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, dtime, ddate,
                               crc, len(e.data), len(e.data), len(name), 0, 0, e.volume,
                               e.internal_attr, e.external_attr, offset)
        central += name
    buf += b"\x00" * tail_pad
    cd_offset = len(buf)
    buf += central
    buf += struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries),
                       len(central), cd_offset, 0)
    with open(path, "wb") as f:
        f.write(buf)
    return len(buf)
