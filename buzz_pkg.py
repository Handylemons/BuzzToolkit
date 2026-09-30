"""PS3 PKG (NPDRM package) reader/writer for installing custom DLC packs.

Layout (big-endian; psdevwiki "PKG files", checked against community DLC packages):
  0x00 magic 7F 50 4B 47   0x04 u16 revision (0x8000 finalized/retail, 0x0000 debug)
  0x06 u16 type (1 = PS3)  0x08 u32 metadata offset (0xC0)  0x0C u32 metadata count
  0x10 u32 metadata size   0x14 u32 item count   0x18 u64 total size
  0x20 u64 data offset     0x28 u64 data size    0x30 content id (0x30, NUL padded)
  0x60 digest (0x10)       0x70 data IV (0x10)   0x80 header CMAC (0x10)
  0x90 NPDRM signature (0x28)                    0xB8 header SHA-1 (8)
  0xC0 metadata: repeated (u32 id, u32 size, data)
  data (encrypted): item_count x (u32 name off, u32 name size, u64 data off, u64 data size,
    u32 flags, u32 0), then names and file data, 16-byte aligned; offsets are relative to the
    data area. Finalized packages: AES-128-CTR with the PS3 package key, counter = data IV + block.
    Debug packages: SHA-1 keystream over (digest-derived block + 64-bit block counter).
  trailer: SHA-1 of everything before it (0x20 bytes incl. padding).
"""
import hashlib
import struct

PS3_PKG_KEY = bytes.fromhex("2E7B71D7C9C9A14EA3221F188828B8F8")
META_NAMES = {1: "drm type", 2: "content type", 3: "package flags", 4: "package size", 5: "make revision/version",
              6: "version/title", 7: "qa digest", 8: "system/app version", 9: "unk9", 0xA: "install dir",
              0xB: "unkB", 0xC: "unkC", 0xD: "item entries", 0xE: "sfo info", 0xF: "unkF", 0x10: "unk10"}


def _aes_ctr(key, iv, data, start_block=0):
    from Crypto.Cipher import AES
    ctr = (int.from_bytes(iv, "big") + start_block) & ((1 << 128) - 1)
    return AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=ctr).encrypt(data)


def _debug_stream(digest, data, start_block=0):
    base = bytearray(0x40)
    base[0x00:0x08] = digest[0:8]
    base[0x08:0x10] = digest[0:8]
    base[0x10:0x18] = digest[8:16]
    base[0x18:0x20] = digest[8:16]
    out = bytearray(len(data))
    for i in range(0, len(data), 16):
        blk = start_block + i // 16
        base[0x38:0x40] = blk.to_bytes(8, "big")
        ks = hashlib.sha1(base).digest()[:16]
        chunk = data[i:i + 16]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)


def crypt(hdr, data, start=0):
    """En/decrypt part of the data area (start = byte offset inside it, 16-aligned)."""
    if hdr["revision"] & 0x8000:
        return _aes_ctr(PS3_PKG_KEY, hdr["iv"], data, start // 16)
    return _debug_stream(hdr["digest"], data, start // 16)


def read_header(buf):
    (magic, rev, typ, moff, mcount, msize, items, total, doff, dsize) = struct.unpack(">IHHIIIIQQQ", buf[:0x30])
    assert magic == 0x7F504B47, "not a PKG"
    h = {"revision": rev, "type": typ, "meta_off": moff, "meta_count": mcount, "meta_size": msize,
         "items": items, "total": total, "data_off": doff, "data_size": dsize,
         "content_id": buf[0x30:0x60].rstrip(b"\0").decode(), "digest": buf[0x60:0x70], "iv": buf[0x70:0x80]}
    meta, p = [], moff
    for _ in range(mcount):
        mid, sz = struct.unpack(">II", buf[p:p + 8])
        meta.append((mid, buf[p + 8:p + 8 + sz]))
        p += 8 + sz
    h["meta"] = meta
    return h


def read(path, max_data=1 << 20):
    """-> (header dict, [(name, flags, data size, data or None)]); file data is decrypted only for
    files up to max_data bytes (packages can be gigabytes)."""
    f = open(path, "rb")
    head = f.read(0x1000)
    h = read_header(head)

    def area(off, size):
        a = off & ~15
        f.seek(h["data_off"] + a)
        return crypt(h, f.read(off + size - a), a)[off - a:off - a + size]

    table = area(0, h["items"] * 0x20)
    files = []
    for i in range(h["items"]):
        noff, nsz, doff, dsz, flags, _ = struct.unpack(">IIQQII", table[i * 0x20:(i + 1) * 0x20])
        name = area(noff, nsz).decode("utf-8", "replace")
        data = area(doff, dsz) if 0 < dsz <= max_data else (b"" if not dsz else None)
        files.append((name, flags, dsz, data))
    f.seek(0, 2)
    h["file_size"] = f.tell()
    f.seek(h["total"] - 0x20 if h["total"] >= 0x20 else 0)
    h["trailer"] = f.read(0x20)
    f.close()
    return h, files


def describe(path):
    h, files = read(path)
    print("%s\n  revision %#06x type %d content id %s items %d total %d data @%#x size %d"
          % (path, h["revision"], h["type"], h["content_id"], h["items"], h["total"], h["data_off"], h["data_size"]))
    for mid, d in h["meta"]:
        print("  meta %#x %-20s %s" % (mid, META_NAMES.get(mid, "?"), d.hex() if len(d) <= 48 else d[:48].hex() + "..."))
    print("  file size %d, trailer %s" % (h["file_size"], h["trailer"].hex()))
    for name, flags, size, data in files[:40]:
        print("  %#010x %11d  %s" % (flags, size, name))
    if len(files) > 40:
        print("  ... %d more" % (len(files) - 40))
    return h, files


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        describe(p)


# ------------------------------------------------------------------------------ writing
# item flags (seen in official and community packages): low byte = type, 0x80000000 = the
# installer may overwrite an existing file (PARAM.SFO is written without it, so installing a pack
# never replaces the title's existing PARAM.SFO).
T_EBOOT, T_EDAT, T_FILE, T_DIR, T_SDAT = 1, 2, 3, 4, 9
OVERWRITE = 0x80000000


def param_sfo(entries):
    """PARAM.SFO writer. entries: [(key, value)] - str (utf-8, NUL terminated) or int (u32);
    written sorted by key like Sony's tools."""
    entries = sorted(entries)
    keys, data, index = b"", b"", b""
    for k, v in entries:
        if isinstance(v, int):
            fmt, raw, mx = 0x0404, struct.pack("<I", v), 4
        else:
            raw = v.encode("utf-8") + b"\0"
            fmt, mx = 0x0204, max(4, (len(raw) + 3) & ~3)
            if k == "TITLE":
                mx = 128
            elif k == "TITLE_ID":
                mx = 16
            elif k in ("VERSION", "APP_VER", "PS3_SYSTEM_VER"):
                mx = max(mx, 8)
        index += struct.pack("<HHIII", len(keys), fmt, len(raw), mx, len(data))
        keys += k.encode() + b"\0"
        data += raw + bytes(mx - len(raw))
    kt = 20 + len(index)
    keys += bytes((-len(keys)) % 4)
    dt = kt + len(keys)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, kt, dt, len(entries)) + index + keys + data


def build(path, content_id, files, finalized=True, content_type=4, version="01.00"):
    """files: [(path inside the title folder, data, flags)] - parent directories are added.
    Writes a PS3 PKG; returns its size."""
    assert len(content_id) == 36, "content id must be 36 characters"
    items, seen = [], set()
    for name, data, flags in files:
        parts = name.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in seen:
                seen.add(d)
                items.append((d, b"", OVERWRITE | T_DIR))
        items.append((name, data, flags))
    # data area: entry table, then each name and file 16-byte aligned (as Sony's tools lay it out)
    table = bytearray(len(items) * 0x20)
    body = bytearray()
    pos = len(table)
    offs = []
    for name, data, flags in items:
        nb = name.encode("utf-8")
        noff = pos
        body += nb + bytes((-len(nb)) % 16)
        pos = len(table) + len(body)
        doff = pos
        body += data + bytes((-len(data)) % 16)
        pos = len(table) + len(body)
        offs.append((noff, len(nb), doff, len(data), flags))
    for i, (noff, nsz, doff, dsz, flags) in enumerate(offs):
        struct.pack_into(">IIQQII", table, i * 0x20, noff, nsz, doff, dsz, flags, 0)
    plain = bytes(table) + bytes(body)
    data_off = 0x140
    total = data_off + len(plain) + 0x20
    digest = hashlib.sha1(plain).digest()[:16]
    iv = hashlib.sha1(b"iv" + plain[:0x1000] + content_id.encode()).digest()[:16]
    rev = 0x8000 if finalized else 0x0000
    maj, mnr = (int(x) for x in version.split("."))
    meta = [(1, struct.pack(">I", 3)),                      # DRM: free (no licence needed)
            (2, struct.pack(">I", content_type)),           # 4 = game data (installs into the title)
            (3, struct.pack(">I", 0x0E)),                   # package flags (as community DLC packages)
            (4, struct.pack(">Q", total)),
            (5, struct.pack(">HBB", 0x1732, maj, mnr))]     # make_package_npdrm revision, pkg version
    mbytes = b"".join(struct.pack(">II", i, len(d)) + d for i, d in meta)
    hdr = bytearray(data_off)
    struct.pack_into(">IHHIIIIQQQ", hdr, 0, 0x7F504B47, rev, 1, 0xC0, len(meta), len(mbytes), len(items),
                     total, data_off, len(plain))
    hdr[0x30:0x30 + 36] = content_id.encode()
    hdr[0x60:0x70] = digest
    hdr[0x70:0x80] = iv
    hdr[0xB8:0xC0] = hashlib.sha1(bytes(hdr[:0x80])).digest()[:8]
    hdr[0xC0:0xC0 + len(mbytes)] = mbytes
    h = {"revision": rev, "digest": digest, "iv": iv}
    out = bytes(hdr) + crypt(h, plain)
    out += hashlib.sha1(out).digest() + bytes(12)
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


BUZZ_DLC_TITLE = "BCES00098"      # Buzz!: Quiz TV game data - where Quiz World looks for packs


def build_pack_pkg(path, content_id, edats, version="01.00", finalized=True):
    """A custom quiz pack as an installable PKG. edats: {"PACK0099/GBRPACK0099.EDAT": bytes, ...}
    (one pack can carry several language files). Includes a PARAM.SFO for BCES00098 that is only
    written if the folder has none (no overwrite flag), so an existing install is untouched."""
    sfo = param_sfo([("CATEGORY", "GD"), ("PARENTAL_LEVEL", 5), ("PS3_SYSTEM_VER", "02.4000"),
                     ("TITLE", "Buzz!: Quiz TV"), ("TITLE_ID", BUZZ_DLC_TITLE), ("VERSION", "01.00")])
    files = [("PARAM.SFO", sfo, T_FILE)]
    files += [("USRDIR/" + name, data, OVERWRITE | T_EDAT) for name, data in sorted(edats.items())]
    return build(path, content_id, files, finalized=finalized, version=version)
