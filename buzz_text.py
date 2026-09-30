"""Buzz Huffman string tables (NamedText/default.* and Rounds/*.hdr/.hst).

.hdr: b'\x00\xff' + u32be string_count + u32be total_symbols, then 6-byte entries
      (u16le char, u32be count) sorted by rising count, + 2 trailer bytes.
      0xFEFE = end-of-string symbol.
.hst: strings packed MSB-first with a Huffman code built from those counts
      (ties: leaves in table order, merged nodes queued after equal weights,
      first-popped node = bit 0); each string starts on a byte boundary.
"""
import struct

END = 0xFEFE


def parse_hdr(hdr):
    count, total = struct.unpack(">II", hdr[2:10])
    ents = [(struct.unpack("<H", hdr[i:i + 2])[0], struct.unpack(">I", hdr[i + 2:i + 6])[0])
            for i in range(10, len(hdr) - 5, 6)]
    return count, total, ents, hdr[10 + 6 * len(ents):]


def build_tree(ents):
    nodes = [[f, i, c] for i, (c, f) in enumerate(ents)]
    n = 0
    while len(nodes) > 1:
        nodes.sort(key=lambda x: (x[0], x[1]))
        a, b = nodes.pop(0), nodes.pop(0)
        n += 1
        nodes.append([a[0] + b[0], 10 ** 6 + n, (a[2], b[2])])
    return nodes[0][2]


def codes(tree, prefix=""):
    if not isinstance(tree, tuple):
        return {tree: prefix or "0"}
    d = codes(tree[0], prefix + "0")
    d.update(codes(tree[1], prefix + "1"))
    return d


def decode_all(hdr, hst):
    """Return list of (byte_offset, string) for every string in the table."""
    count, total, ents, _ = parse_hdr(hdr)
    tree = build_tree(ents)
    out, pos = [], 0
    nbits = len(hst) * 8
    while len(out) < count and pos < nbits:
        start = pos // 8
        node, chars = tree, []
        while True:
            bit = (hst[pos // 8] >> (7 - pos % 8)) & 1
            pos += 1
            node = node[bit]
            if not isinstance(node, tuple):
                if node == END:
                    break
                chars.append(chr(node))
                node = tree
        out.append((start, "".join(chars)))
        pos = (pos + 7) // 8 * 8          # next string starts on a byte boundary
    return out


def encode_all(strings, trailer=b"\x00\xfe"):
    """Build (.hdr, .hst) for a list of strings - inverse of decode_all."""
    from collections import Counter
    freq = Counter()
    seqs = []
    for s in strings:
        cs = [ord(ch) for ch in s] + [END]
        freq.update(cs)
        seqs.append(cs)
    ents = sorted(freq.items(), key=lambda cf: (cf[1], cf[0]))      # (char, count)
    total = sum(freq.values())
    hdr = b"\x00\xff" + struct.pack(">II", len(strings), total)
    hdr += b"".join(struct.pack("<H", c) + struct.pack(">I", f) for c, f in ents)
    hdr += trailer
    table = codes(build_tree(ents))
    out = bytearray()
    for cs in seqs:
        bitstr = "".join(table[c] for c in cs)
        bitstr += "0" * (-len(bitstr) % 8)                          # byte-align each string
        out += int(bitstr, 2).to_bytes(len(bitstr) // 8, "big") if bitstr else b""
    return hdr, bytes(out)
