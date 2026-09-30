"""Buzz! round question index: .kaq (big-endian) / .qak (little-endian mirror).

Complete parser + writer. `write(parse(kaq), ">") == kaq` and `write(parse(kaq), "<") == qak`
for every retail round file (see validate()).

File layout (offsets absolute):
  0x000 u16 0xFFFE BOM, u16 1, u16 1002, u16 0, u32 section count (11), u32 section table offset
  0x010 u16 1, u16 pack number, 0x014 round name (192 bytes), 0x0D4 copyright (160 bytes),
  0x174 language block (8 raw bytes, "GBR\\0" + 01 00 00 00)
  0x17C section table: count x (u32 offset, u16 record count, u8 id, u8 0); empty = offset 0
  data in the order 0,1,2,3,4,5,6,8,7,9,10; sections 4-byte aligned except the u16
  sections 5 and 6 (2-byte).
Sections:
  0 media        16 B: u32 key, u32 media id, u16 ?, u16 picture/frame, 4 flag bytes
                        (flag[0]: 1 music, 2 video, 3 picture)
  1 questions    36 B: u32 qid, 4 raw ("GBR\\0"), u32 content id, 8 x u16
                        (s12 first tag, s14 link or 0xFFFF, s16 first string entry, s18 ordinal,
                         s20 (2 = Point Stealer), s22 (0x7FFE, Point Stealer block),
                         s24 first answer, s26 flags: 8 text-only, 4 pictures-as-answers),
                        8 x u8 (type 0/8 ATP/10 PS, b29 1-6, b30 difficulty 1-3, n tags,
                         has link, n string entries, 1, n answers)
  2 links         4 B: u16 media index, u8 1, u8 0
  3 string entries 8 B: u32 speech id, u16 string number (1-based), u8 role (1 question,
                        2 host intro), u8 0
  4 answers       4 B: u16 string number (Point Stealer: media index), u8 flag
                        (5 correct / 1 wrong; Point Stealer 6 / 2), u8 0
  5 subject ids   2 B per question (u16)
  6 round tags    2 B each (1 STC, 2 PTB, 3 PieFight, 4 HighStakes, 5 PointStealer,
                        6 FinalCountdown, 7 PointBuilder, 8 AllThatApply, 9 FastestFinger)
  7,8,9,10 lookup maps (7 media keys, 8 question ids, 9 subject ids, 10 tag -> bank count):
        u32 min, u32 max, u32 nbuckets, u32 bucket_off, u32 n, u32 entry_off, then n sorted
        (u32 key, u32 value), then buckets: (key[i*step], i*step) for i < n // step,
        step = isqrt(n). Empty map = 24 zero bytes.
"""
import math
import struct

REC = {0: "IIHH4s", 1: "I4sI8H8B", 2: "HBB", 3: "IHBB", 4: "HBB", 5: "H", 6: "H"}
ORDER = [0, 1, 2, 3, 4, 5, 6, 8, 7, 9, 10]
MAPS = (7, 8, 9, 10)


def _fmt(endian, sid):
    return endian + REC[sid]


def parse(k):
    e = ">" if k[:2] == b"\xff\xfe" else "<"
    bom, ver, v1002, z, nsec, tab = struct.unpack(e + "HHHHII", k[:16])
    one, pack = struct.unpack(e + "HH", k[16:20])
    m = {"ver": ver, "v1002": v1002, "z": z, "one": one, "pack": pack,
         "name": k[0x14:0xD4], "copyright": k[0xD4:0x174], "lang": k[0x174:0x17C], "sections": {}}
    for i in range(nsec):
        off, cnt, sid, pad = struct.unpack(e + "IHBB", k[tab + 8 * i:tab + 8 * i + 8])
        if sid in MAPS:
            mn, mx, nb, boff, n, eoff = struct.unpack(e + "6I", k[off:off + 24])
            pairs = [struct.unpack(e + "II", k[eoff + 8 * j:eoff + 8 * j + 8]) for j in range(n)]
            m["sections"][sid] = {"map": pairs, "minmax": (mn, mx)}
        else:
            f = _fmt(e, sid)
            size = struct.calcsize(f)
            m["sections"][sid] = [struct.unpack(f, k[off + size * j:off + size * (j + 1)]) for j in range(cnt)] if cnt else []
    return m


def _map_bytes(e, base, pairs, minmax=None):
    n = len(pairs)
    if not n:
        return bytes(24)
    step = math.isqrt(n)
    nb = n // step
    eoff = base + 24
    boff = eoff + 8 * n
    mn, mx = minmax if minmax else (min(p[0] for p in pairs), max(p[0] for p in pairs))
    out = struct.pack(e + "6I", mn, mx, nb, boff, n, eoff)
    out += b"".join(struct.pack(e + "II", *p) for p in pairs)
    out += b"".join(struct.pack(e + "II", pairs[i * step][0], i * step) for i in range(nb))
    return out


def write(m, e=">"):
    secs = m["sections"]
    tab = 0x17C
    head_len = tab + 8 * 11
    body = bytearray()
    table = {}
    pos = head_len
    for sid in ORDER:
        s = secs.get(sid, [])
        if sid in MAPS:
            pos = (pos + 3) & ~3
            body += bytes(pos - head_len - len(body))
            data = _map_bytes(e, pos, s["map"] if isinstance(s, dict) else [], s.get("minmax") if isinstance(s, dict) else None)
            table[sid] = (pos, 1)
        else:
            if not s:
                table[sid] = (0, 0)
                continue
            align = 2 if sid in (5, 6) else 4                 # u16 sections are only 2-aligned
            pos = (pos + align - 1) & ~(align - 1)
            body += bytes(pos - head_len - len(body))
            f = _fmt(e, sid)
            data = b"".join(struct.pack(f, *r) for r in s)
            table[sid] = (pos, len(s))
        body += data
        pos += len(data)
    hdr = bytearray(struct.pack(e + "HHHHII", 0xFFFE, m["ver"], m["v1002"], m["z"], 11, tab))
    hdr += struct.pack(e + "HH", m["one"], m["pack"])
    hdr += m["name"].ljust(192, b"\0")[:192] + m["copyright"].ljust(160, b"\0")[:160] + m["lang"]
    assert len(hdr) == tab
    for sid in range(11):
        off, cnt = table[sid]
        hdr += struct.pack(e + "IHBB", off, cnt, sid, 0)
    return bytes(hdr) + bytes(body)


def validate(paths):
    """Round-trip every .kaq/.qak in the given decrypted packs; returns (ok, bad) lists."""
    import buzz_pak
    ok, bad = [], []
    for p in paths:
        by = {x.name: x.data for x in buzz_pak.read_pak(p)}
        for n in sorted(by):
            if not n.lower().endswith(".kaq"):
                continue
            k, q = by[n], by.get(n[:-4] + ".qak")
            m = parse(k)
            good = write(m, ">") == k and (q is None or write(m, "<") == q)
            (ok if good else bad).append(n)
    return ok, bad
