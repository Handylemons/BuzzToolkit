"""Pack info image (GRAPHICS/Pack####Textures.ete) - built from our own artwork.

Layout (reversed from every retail pack, all identical apart from the image and hash):
  "segs" container: 4s magic, u16 4, u16 segment count, u32 total decompressed, u32 file size,
    then per segment (u16 compressed size, u16 decompressed size (0 = 65536), u32 offset | 1),
    segment data raw-deflate, each starting 16-byte aligned (first at 0x30 for 3 segments).
  decompressed payload (138,496 bytes):
    0x00 RS texture package header: u32 2, u16 1 (textures), u16 0x18 (entry size),
         entry: u32 0, u32 NAME HASH, u32 0x78 (GTF offset relative to the entry), 12 zero bytes,
         zero padding to 0x80
    0x80 GTF (PS3 texture) header: u32 0x01080000, u32 data size, u32 1 texture,
         u32 id 0, u32 data offset 0x80 (from the GTF start), u32 data size,
         CellGcmTexture: format 0xA6 (DXT1, linear), mipmaps 1, dimension 2, cubemap 0,
         remap 0x0000AAE4, width 576, height 480, depth 1, location 0, pad, pitch 1152, offset 0
    0xB0 padding to 0x100 with 'P' (0x50) bytes
    0x100 DXT1 blocks (576x480 -> 138,240 bytes), row-major
  NAME HASH: an affine CRC-32 of the texture name. Every retail pack satisfies
    hash = crc32(name + ".gtf") ^ 0xB9F803E9 for names "BZ3_InfoPackImage_Pack%04d"
    (exact for any same-length name, which is all we need).
"""
import struct
import zlib

import numpy as np
from PIL import Image

W, H = 576, 480


def name_hash(name):
    return (zlib.crc32((name + ".gtf").encode()) ^ 0xB9F803E9) & 0xFFFFFFFF


def _rgb565(c):
    c = np.clip(np.rint(c), 0, 255).astype(np.int32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _unpack565(v):
    r = ((v >> 11) & 31) * 255 // 31
    g = ((v >> 5) & 63) * 255 // 63
    b = (v & 31) * 255 // 31
    return np.stack([r, g, b], -1).astype(np.float32)


def dxt1_encode(img):
    """Simple DXT1 (BC1) encoder: per 4x4 block, endpoints from the principal axis extremes,
    4-colour mode, nearest-colour indices."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w, _ = a.shape
    blocks = a.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    mean = blocks.mean(1, keepdims=True)
    cen = blocks - mean
    cov = np.einsum("bni,bnj->bij", cen, cen)
    axis = np.ones((len(blocks), 3), np.float32)
    for _ in range(8):                                        # power iteration
        axis = np.einsum("bij,bj->bi", cov, axis)
        axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-9
    proj = np.einsum("bni,bi->bn", cen, axis)
    lo = mean[:, 0] + axis * proj.min(1, keepdims=True)
    hi = mean[:, 0] + axis * proj.max(1, keepdims=True)
    c0, c1 = _rgb565(hi), _rgb565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    same = c0 == c1                                            # flat block: keep 4-colour mode
    c0 = np.where(same & (c0 < 0xFFFF), c0 + 1, c0)
    c1 = np.where(same & (c0 == 0xFFFF) & (c1 == 0xFFFF), c1 - 1, c1)
    p0, p1 = _unpack565(c0), _unpack565(c1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)          # (b,4,3)
    d = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)            # (b,16,4)
    idx = d.argmin(-1).astype(np.uint32)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((len(blocks), 8), np.uint8)
    out[:, 0] = c0 & 0xFF; out[:, 1] = c0 >> 8                                 # little-endian words
    out[:, 2] = c1 & 0xFF; out[:, 3] = c1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> (8 * k)) & 0xFF
    return out.tobytes()


def _segs(payload):
    chunks = [payload[i:i + 0x10000] for i in range(0, len(payload), 0x10000)]
    comp = []
    for c in chunks:
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp.append(co.compress(c) + co.flush())
    n = len(chunks)
    pos = (16 + 8 * n + 15) & ~15
    table, body = b"", b""
    for c, cc in zip(chunks, comp):
        table += struct.pack(">HHI", len(cc), len(c) & 0xFFFF, pos | 1)
        pad = (-(len(cc)) % 16)
        body += cc + bytes(pad)
        pos += len(cc) + pad
    head = struct.pack(">4sHHII", b"segs", 4, n, len(payload), 0)
    data = bytearray(head + table)
    data += bytes(((16 + 8 * n + 15) & ~15) - len(data))
    data += body
    data = data[:len(data) - (-len(comp[-1]) % 16)] if False else data
    struct.pack_into(">I", data, 12, len(data))
    return bytes(data)


def build_ete(image, texture_name):
    """image: PIL image or path (any size; fitted to 576x480). -> .ete bytes"""
    im = Image.open(image) if isinstance(image, str) else image
    im = im.convert("RGB").resize((W, H), Image.LANCZOS)
    dxt = dxt1_encode(im)
    assert len(dxt) == W * H // 2
    rs = struct.pack(">IHH", 2, 1, 0x18) + struct.pack(">III", 0, name_hash(texture_name), 0x78) + bytes(12)
    rs += bytes(0x80 - len(rs))
    gtf = struct.pack(">III", 0x01080000, len(dxt), 1) + struct.pack(">III", 0, 0x80, len(dxt))
    gtf += struct.pack(">BBBBIHHHBBII", 0xA6, 1, 2, 0, 0x0000AAE4, W, H, 1, 0, 0, W * 2, 0)
    assert len(gtf) == 0x30, len(gtf)
    gtf += b"P" * (0x80 - len(gtf))              # retail pads the GTF header to 0x80 with 'P'
    return _segs(rs + gtf + dxt)


def read_ete(data):
    """-> (name hash, decoded PIL image) for checking."""
    import io
    magic, flags, nseg, total, fsize = struct.unpack(">4sHHII", data[:16])
    out = b""
    for i in range(nseg):
        csz, dsz, off = struct.unpack(">HHI", data[16 + 8 * i:24 + 8 * i])
        raw = data[off - 1:off - 1 + csz] if off & 1 else data[off:off + csz]
        out += zlib.decompress(raw, -15) if off & 1 else raw
    h = struct.unpack(">I", out[0x0C:0x10])[0]
    dxt = out[0x100:0x100 + W * H // 2]
    dds = bytearray(b"DDS " + struct.pack("<7I", 124, 0x1007, H, W, len(dxt), 0, 0) + bytes(44))
    dds += struct.pack("<2I4s5I", 32, 4, b"DXT1", 0, 0, 0, 0, 0) + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    im = Image.open(io.BytesIO(bytes(dds) + dxt)); im.load()
    return h, im, out
