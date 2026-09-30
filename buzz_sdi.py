"""Build Buzz picture sets (QUESTIONASSETS/VIDEO/picsNNN.sdi) in the retail layout.

A picture set is a CRI Sofdec MPEG-1 program stream (made with "Sofdec CRAFT"), one frame per
picture at 25 fps. Retail layout (PACK0017 pics001/002/003, all verified):
  0x000 SDI header (0x800 bytes, big-endian):
        0x10 width 640, 0x14 height 368, 0x18 640*368, 0x1C 25000 (fps*1000),
        0x30 FILE SIZE IN BYTES, 0x34 picture count, 0x40 "SDIVIDEO",
        0x4C CHECKSUM of bytes 0..0x4B (crc32 ^ 0x05432108, checked by EBOOT FUN_00304cd4),
        0x50 (count+1) x u32 offsets: sector where picture k starts (last = file size)
  0x800 lead-in, 3 sectors: system header + padding + private-stream-2 "SofdecStream"/"@CRITAGS"
        metadata. Per-file values in it: little-endian u32s (duration ms = count*40, count,
        largest frame bytes, average frame bytes) and ASCII fields (count x3, last index).
  then  one continuous MPEG-1 video stream, every 2048-byte sector = pack header (12 bytes,
        SCR ~ sector*97/7) + one video PES of 2030 bytes (12-byte header + 2018 payload).
        The PES where picture k starts carries PTS = DTS = k*3600 (90 kHz, 40 ms per frame);
        the others carry 9 stuffing bytes + STD buffer + 0x0F. Video: 640x368, frame rate
        code 3 (25 fps), aspect code 12, I-frames only.
Picture numbers in the round index (.kaq media entries) are frame indices; our builder keeps
picture 0 as a "missing picture" frame and puts the pack's images at 1..n.

Writing header 0x30 as size/256 (an earlier bug) made the game read the header and never show a
picture.
"""
import os
import shutil
import struct
import subprocess
import tempfile
import zlib

import buzz_tools
SECTOR, PAYLOAD = 2048, 2018
PTS_STEP = 3600                                   # 90 kHz ticks per frame at 25 fps


def encode_frames(png_paths):
    """-> list of MPEG-1 video elementary-stream chunks, one per picture (each starts with a
    sequence header, so any picture can be decoded on its own)."""
    with tempfile.TemporaryDirectory() as td:
        for k, p in enumerate(png_paths):                      # numbered sequence at a fixed 25 fps
            shutil.copyfile(p, os.path.join(td, "f%03d.png" % k))
        out = os.path.join(td, "v.m1v")
        subprocess.run([buzz_tools.ffmpeg(), "-v", "error", "-y", "-framerate", "25", "-i", os.path.join(td, "f%03d.png"),
                        "-vf", "scale=640:368,setsar=10000/10950,format=yuv420p",
                        "-c:v", "mpeg1video", "-g", "1", "-q:v", "2", "-f", "mpeg1video", out], check=True)
        es = open(out, "rb").read()
    starts, i = [], 0
    while True:
        i = es.find(b"\x00\x00\x01\xb3", i)
        if i < 0:
            break
        starts.append(i)
        i += 4
    assert len(starts) == len(png_paths), "expected one sequence header per picture, got %d" % len(starts)
    return [es[s:e] for s, e in zip(starts, starts[1:] + [len(es)])]


def _scr_bytes(scr):
    return bytes([0x21 | ((scr >> 29) & 0x0E), (scr >> 22) & 0xFF, ((scr >> 14) & 0xFE) | 1,
                  (scr >> 7) & 0xFF, ((scr << 1) & 0xFE) | 1])


def _ts_bytes(prefix, ts):
    return bytes([prefix | ((ts >> 29) & 0x0E) | 1, (ts >> 22) & 0xFF, ((ts >> 14) & 0xFE) | 1,
                  (ts >> 7) & 0xFF, ((ts << 1) & 0xFE) | 1])


def _sector(index, payload, pts=None, mux=b"\x88\x1e\x73"):
    pack = b"\x00\x00\x01\xba" + _scr_bytes(round(index * 97 / 7)) + mux
    if pts is None:
        hdr = b"\xff" * 9 + b"\x60\x2e\x0f"
    else:
        hdr = b"\x60\x2e" + _ts_bytes(0x30, pts) + _ts_bytes(0x10, pts)
    assert len(payload) == PAYLOAD
    return pack + b"\x00\x00\x01\xe0" + struct.pack(">H", len(hdr) + PAYLOAD) + hdr + payload


def _set_ascii(buf, off, value):
    """Fixed-width ASCII field: value, NUL, then spaces (retail CRITAGS layout)."""
    end = buf.index(0, off) + 1
    while end < len(buf) and buf[end] == 0x20:
        end += 1
    width = end - off
    new = value.encode() + b"\x00"
    buf[off:end] = new + b" " * (width - len(new))


def build_sdi(template, png_paths):
    """template: retail .sdi bytes (PACK0017 pics001). -> (sdi bytes, picture count)."""
    count0 = struct.unpack(">I", template[0x34:0x38])[0]
    first = struct.unpack(">I", template[0x50:0x54])[0]            # end of lead-in
    # The game reads [offsets[k], offsets[k+1] + 0x1000): picture k plus two more sectors. A
    # real picture must never be the last segment or that read runs past EOF and the picture
    # is not shown (seen with picture 10). Append a guard frame (copy of picture 0).
    frames = encode_frames(list(png_paths) + [png_paths[0]])
    n = len(frames)

    lead = bytearray(template[0x800:first])
    # binary Sofdec info: <duration ms> <count> <largest frame> <average frame>, little-endian
    key = struct.pack("<II", count0 * 40, count0)
    p = lead.find(key)
    assert p > 0 and lead.find(key, p + 1) < 0, "Sofdec info block not found"
    lead[p:p + 16] = struct.pack("<IIII", n * 40, n, max(map(len, frames)), sum(map(len, frames)) // n)
    # ASCII copies: three "count" fields and one "last index" field (offsets from retail pics001)
    for off, val in ((0x1068, n), (0x1092, n), (0x10E6, n - 1), (0x11D5, n)):
        old = count0 if val == n else count0 - 1
        assert lead[off:off + len(str(old)) + 1] == ("%d\x00" % old).encode(), "CRITAGS field moved at %#x" % off
        _set_ascii(lead, off, str(val))

    body = bytearray(lead)
    sector = len(template[:first]) // SECTOR                     # sectors before the video
    offsets = []
    for k, f in enumerate(frames):
        offsets.append(0x800 + len(body))
        for j in range(0, len(f), PAYLOAD):
            chunk = f[j:j + PAYLOAD]
            if j + PAYLOAD >= len(f) and k == n - 1:
                chunk += b"\x00\x00\x01\xb7"                     # sequence end after the last picture
            chunk = chunk[:PAYLOAD] if len(chunk) > PAYLOAD else chunk + b"\x00" * (PAYLOAD - len(chunk))
            body += _sector(sector, chunk, pts=k * PTS_STEP if j == 0 else None)
            sector += 1
    # trailing padding sectors (retail files end in 0xFF padding) so even the guard frame's
    # extra-sector read stays inside the file
    for _ in range(2):
        pack = b"\x00\x00\x01\xba" + _scr_bytes(round(sector * 97 / 7)) + b"\x88\x1e\x73"
        body += pack + b"\x00\x00\x01\xbe" + struct.pack(">H", SECTOR - 18) + b"\xff" * (SECTOR - 18)
        sector += 1
    total = 0x800 + len(body)
    offsets.append(total)

    hdr = bytearray(template[:0x800])
    hdr[0x30:0x34] = struct.pack(">I", total)
    hdr[0x34:0x38] = struct.pack(">I", n)
    table = b"".join(struct.pack(">I", o) for o in offsets)
    hdr[0x50:0x800] = (table + bytes(0x800 - 0x50))[:0x800 - 0x50]
    # 0x4C = header checksum: EBOOT FUN_00304cd4 rejects the stream unless it equals
    # FUN_0024f0cc(header[0:0x4C]) == zlib.crc32(...) ^ 0x05432108 (verified on retail)
    hdr[0x4C:0x50] = struct.pack(">I", (zlib.crc32(bytes(hdr[:0x4C])) ^ 0x05432108) & 0xFFFFFFFF)
    return bytes(hdr) + bytes(body), n

# ---------------------------------------------------------------------------------------------
# Template-free picture sets. The Sofdec lead-in (3 sectors: system header + padding,
# private-stream-2 "SofdecStream" block, "@CRITAGS" block) is container metadata written by CRI's
# encoder; it is kept here as a compact generic constant (a 6-frame set named "pics003") and every
# per-file field (name, frame counts, durations, frame sizes) is rewritten by build_sdi().
LEADIN_6 = (
    "eNrtmM1O20AQx8dGLXCCYy+p1uLSk9m1nSiJEAJMQpHIh2LLEidEwZEiEYISlGfgUXgDJJDKnZcgT4AqtQduYda7ju1Dq/bWVvNTvLvj/c8mO15pJgYw7i0wwLj5OAEwHmAVB6Y1n81sNL8uP6/NCYIgCIL4zwCd/0sq/z8uv0CBYNQ/j8+C63F8OmQ5zJKavxqcTTh3mT3pnzucV3lZVITj8qI/83u7zXDTH11ORhcxi+Kx7di1mlStKJ0J2fhXmGAYP16fkvE3vN7j9T0G+FCCf5KtoNk66Trbdtjq5uP3+Jv+ufhP8/4zmM8/GVdLBiytY8iAIAiCIIqo/F/T+d/c8XuH4e5BAByRiTxoRs2wp22R2CArAMw2SY92Pex0wVUmQ1k9/QCPuFPGO1CBtHI4ZAwc1wMpF9p/398Hof0zZbZ+A+f7eh5/30kQNZgrCwg0gBWpeCh0K1VgEU/nyjnRaBqPIdenoraQOwRW7I7bi0VYu5PpVSuwPRaLu0nz2e+0gaNh64X+sMdC4OBo8AX3xz1bVGW860HPX8RXZ3z7dDqA4n5VpB0vF2wdv72wBZ72t9gGZ5bFfoau2BoX8ZAF10NIn7MET8idOg+N5DzI71PnJbPla6N3t/TaiCAI4u/+//8GRwMZyQ==")


def _sdi_header(count, first):
    h = bytearray(0x800)
    struct.pack_into(">I", h, 0x00, 1)
    struct.pack_into(">I", h, 0x0C, 0xA00)
    struct.pack_into(">IIII", h, 0x10, 640, 368, 640 * 368, 25000)
    struct.pack_into(">IIII", h, 0x20, 30000000, 0x50, 0x800, 0x800)
    struct.pack_into(">II", h, 0x30, 0, count)
    h[0x40:0x48] = b"SDIVIDEO"
    for i in range(count + 1):
        struct.pack_into(">I", h, 0x50 + 4 * i, first)
    return h


def placeholder_png(path, text="PICTURE MISSING"):
    """Our own frame 0 ('missing picture'), 640x368 with the 8-pixel black strip."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 368), (0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 639, 359), fill=(24, 28, 44))
    d.rectangle((20, 20, 619, 339), outline=(90, 100, 130), width=4)
    w = d.textlength(text) if hasattr(d, "textlength") else 6 * len(text)
    d.text(((640 - w) / 2, 172), text, fill=(200, 205, 220))
    im.save(path)
    return path


def build_picture_set(png_paths, name="pics001"):
    """Build a picture set with no retail file involved. -> (sdi bytes, frame count)"""
    import base64
    lead = zlib.decompress(base64.b64decode(LEADIN_6))
    assert len(name) == 7, "picture set names are 7 characters (pics001)"
    lead = lead.replace(b"pics003", name.encode())
    template = bytes(_sdi_header(6, 0x800 + len(lead))) + lead
    return build_sdi(template, png_paths)


def make_composite(pngs, out):
    """Point Stealer sheet: 2x2 grid of four 640x368 picture frames (answer order: top-left,
    top-right, bottom-left, bottom-right, as in retail pics002), keeping the 8-pixel black strip."""
    from PIL import Image
    canvas = Image.new("RGB", (640, 368), (0, 0, 0))
    for i, p in enumerate(pngs):
        im = Image.open(p).convert("RGB").crop((0, 0, 640, 360)).resize((318, 178), Image.LANCZOS)
        canvas.paste(im, ((i % 2) * 322, (i // 2) * 182))
    canvas.save(out)
    return out


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp", ".gif")


def fit_frame(src, dst):
    """Any picture -> a 640x368 game frame: cover-crop to 640x360 from the centre (no stretching)
    plus the 8-pixel black strip the game expects at the bottom. 640x368 input is kept as is."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if im.size == (640, 368):
        im.save(dst)
        return dst
    w, h = im.size
    scale = max(640 / w, 360 / h)
    im = im.resize((max(640, round(w * scale)), max(360, round(h * scale))), Image.LANCZOS)
    x, y = (im.width - 640) // 2, (im.height - 360) // 2
    frame = Image.new("RGB", (640, 368), (0, 0, 0))
    frame.paste(im.crop((x, y, x + 640, y + 360)), (0, 0))
    frame.save(dst)
    return dst


def prepare_pictures(img_dir, names, work):
    """Pack picture names -> ready 640x368 frames in work/frames (placeholder cards for pictures not
    added yet, so a pack can be built while its pictures are still being collected).
    -> (frame paths, names still missing)"""
    out_dir = os.path.join(work, "frames")
    os.makedirs(out_dir, exist_ok=True)
    frames, missing = [], []
    for n in names:
        src = next((os.path.join(img_dir, n + e) for e in IMAGE_EXTS if os.path.exists(os.path.join(img_dir, n + e))), None)
        dst = os.path.join(out_dir, n + ".png")
        if src:
            fit_frame(src, dst)
        else:
            placeholder_png(dst, "PICTURE NEEDED: " + n.upper())
            missing.append(n)
        frames.append(dst)
    return frames, missing
