"""Minimal ATRAC3 encoder for Buzz host speech: mono, 152-byte frames (1024 samples each).

Nothing public produces this frame size (atracdenc only writes 192/212/272-byte channel units),
so this encodes the exact bitstream ffmpeg's atrac3 decoder reads (libavcodec/atrac3.c):

  channel sound unit = 6 bits 0x28, 2 bits coded QMF bands, gain control (3-bit point count per
  band, all 0 here), 5 bits tonal components (0 here), then the spectrum:
  5 bits num_subbands-1, 1 bit coding mode (0 = VLC), 3-bit selector per subband,
  6-bit scale factor per coded subband, then the quantised coefficients.

Signal path is the inverse of the decoder: 3 QMF analysis splits -> 4 bands of 256 samples,
512-point MDCT per band (odd bands reversed), per-subband scale factor + quantiser chosen by a
rate/distortion (Lagrangian) search that fills the 1216-bit budget.

encode(samples) takes 48 kHz mono int16-range floats and returns the raw frame bytes.
"""
import numpy as np

FRAME = 1024
BLOCK = 152
BITS = BLOCK * 8

SUBBAND_TAB = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256,
               288, 320, 352, 384, 416, 448, 480, 512, 576, 640, 704, 768, 896, 1024]
MAX_QUANT = [0.0, 1.5, 2.5, 3.5, 4.5, 7.5, 15.5, 31.5]
MANT_MAX = [0, 1, 2, 3, 4, 7, 15, 31]              # largest |mantissa| each VLC table can code
SF_TABLE = np.array([2.0 ** ((i - 15) / 3.0) for i in range(64)])

QMF_HALF = [-0.00001461907, -0.00009205479, -0.000056157569, 0.00030117269,
            0.0002422519, -0.00085293897, -0.0005205574, 0.0020340169,
            0.00078333891, -0.0042153862, -0.00075614988, 0.0078402944,
            -0.000061169922, -0.01344162, 0.0024626821, 0.021736089,
            -0.007801671, -0.034090221, 0.01880949, 0.054326009,
            -0.043596379, -0.099384367, 0.13207909, 0.46424159]
QMF_WIN = np.array([x * 2.0 for x in QMF_HALF] + [x * 2.0 for x in reversed(QMF_HALF)])

# (symbol + 31, code length) per selector, in ffmpeg's order; codes are assigned canonically in
# list order exactly like ff_vlc_init_from_lengths.
_HUFF = [
    [(31, 1), (32, 3), (33, 3), (34, 4), (35, 4), (36, 5), (37, 5), (38, 5), (39, 5)],
    [(31, 1), (32, 3), (30, 3), (33, 3), (29, 3)],
    [(31, 1), (32, 3), (30, 3), (33, 4), (29, 4), (34, 4), (28, 4)],
    [(31, 1), (32, 3), (30, 3), (33, 4), (29, 4), (34, 5), (28, 5), (35, 5), (27, 5)],
    [(31, 2), (32, 3), (30, 3), (33, 4), (29, 4), (34, 4), (28, 4), (38, 4), (24, 4), (35, 5),
     (27, 5), (36, 6), (26, 6), (37, 6), (25, 6)],
    [(31, 3), (32, 4), (30, 4), (33, 4), (29, 4), (34, 4), (28, 4), (46, 4), (16, 4), (35, 5),
     (27, 5), (36, 5), (26, 5), (37, 5), (25, 5), (38, 6), (24, 6), (39, 6), (23, 6), (40, 6),
     (22, 6), (41, 6), (21, 6), (42, 7), (20, 7), (43, 7), (19, 7), (44, 7), (18, 7), (45, 7),
     (17, 7)],
    [(31, 3), (62, 4), (0, 4), (32, 5), (30, 5), (33, 5), (29, 5), (34, 5), (28, 5), (35, 5),
     (27, 5), (36, 5), (26, 5), (37, 6), (25, 6), (38, 6), (24, 6), (39, 6), (23, 6), (40, 6),
     (22, 6), (41, 6), (21, 6), (42, 6), (20, 6), (43, 6), (19, 6), (44, 6), (18, 6), (45, 7),
     (17, 7), (46, 7), (16, 7), (47, 7), (15, 7), (48, 7), (14, 7), (49, 7), (13, 7), (50, 7),
     (12, 7), (51, 7), (11, 7), (52, 8), (10, 8), (53, 8), (9, 8), (54, 8), (8, 8), (55, 8),
     (7, 8), (56, 8), (6, 8), (57, 8), (5, 8), (58, 8), (4, 8), (59, 8), (3, 8), (60, 8),
     (2, 8), (61, 8), (1, 8)],
]
# selector 1 codes a pair of mantissas per symbol (mantissa_vlc_tab)
_PAIRS = [(0, 0), (0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def _build_codes():
    tabs = []
    for t in _HUFF:
        codes, acc = {}, 0
        for sym, ln in t:
            codes[sym - 31] = (acc >> (32 - ln), ln)
            acc += 1 << (32 - ln)
        tabs.append(codes)
    return tabs


CODES = _build_codes()
# code length lookup per selector for mantissa values (index = value + 31); sel 1 is per pair
LEN = np.zeros((8, 63), np.int64)
for _s in range(2, 8):
    for _v, (_c, _l) in CODES[_s - 1].items():
        LEN[_s, _v + 31] = _l
PAIR_LEN = np.zeros((3, 3), np.int64)
for _i, (_a, _b) in enumerate(_PAIRS):
    PAIR_LEN[_a + 1, _b + 1] = CODES[0][_i][1]


class BitWriter:
    def __init__(self):
        self.bits = []

    def put(self, value, n):
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def tobytes(self, size):
        assert len(self.bits) <= size * 8, (len(self.bits), size * 8)
        b = self.bits + [0] * (size * 8 - len(self.bits))
        return np.packbits(np.array(b, np.uint8)).tobytes()


# ---------------------------------------------------------------------------------------------
# analysis filter bank

class QMF:
    """Two-band QMF analysis matching ff_atrac_iqmf (48 taps, 46 samples of history)."""

    def __init__(self):
        self.hist = np.zeros(46)

    def analysis(self, x):
        buf = np.concatenate([self.hist, x])
        self.hist = buf[-46:]
        n = len(x) // 2
        lo = np.zeros(n)
        hi = np.zeros(n)
        even, odd = QMF_WIN[0::2], QMF_WIN[1::2]
        for j in range(n):
            seg = buf[2 * j:2 * j + 48]
            a = np.dot(seg[1::2][::-1], even)        # taps paired as in the synthesis loop
            b = np.dot(seg[0::2][::-1], odd)
            lo[j] = a + b
            hi[j] = a - b
        return lo, hi


def _mdct_basis(n=256):
    k = np.arange(n)[:, None]
    t = np.arange(2 * n)[None, :]
    return np.cos(np.pi / n * (t + 0.5 + n / 2) * (k + 0.5))


BASIS = _mdct_basis()
_i = np.arange(256)
_w = np.sin(((_i + 0.5) / 256.0 - 0.5) * np.pi) + 1.0
AWIN = np.concatenate([_w, _w[::-1]])                  # analysis window (decoder divides it out)


# ---------------------------------------------------------------------------------------------
# quantisation and bit allocation

def _quantise(coefs, sel, sf):
    step = SF_TABLE[sf] / MAX_QUANT[sel]
    m = np.clip(np.rint(coefs / step), -MANT_MAX[sel], MANT_MAX[sel]).astype(np.int64)
    return m, m * step


def _vlc_bits(m, sel):
    if sel == 1:
        return int(PAIR_LEN[m[0::2] + 1, m[1::2] + 1].sum())
    return int(LEN[sel, m + 31].sum())


# Energy-loss penalty. Plain MSE sees no benefit in coding a weak subband coarsely (the error is
# about the band's energy either way), so it leaves spectral holes that sound warbly/"robotic".
# Sony's encoder almost never does: in retail host clips 0.4% of subbands are uncoded and 65% use
# the coarsest quantiser (+-1). Counting lost energy as extra distortion reproduces that.
ENERGY_W = 8.0      # gives 5.5% uncoded / 63% +-1 subbands on host speech (retail: 0.4% / 65%)


def _options(coefs):
    """Per subband: list of (bits, distortion, sel, sf, mantissas) for sel 0..7."""
    opts = []
    for i in range(32):
        c = coefs[SUBBAND_TAB[i]:SUBBAND_TAB[i + 1]]
        energy = float(np.dot(c, c))
        row = [(0, energy * (1 + ENERGY_W), 0, 0, None)]
        peak = float(np.abs(c).max())
        if peak > 1e-9:
            sf0 = int(np.searchsorted(SF_TABLE, peak))
            for sel in range(1, 8):
                best = None
                for sf in range(sf0 - (4 if sel <= 2 else 1), sf0 + 1):   # coarse steps may undershoot the peak
                    if not 0 <= sf < 64:
                        continue
                    m, q = _quantise(c, sel, sf)
                    eq = float(np.dot(q, q))
                    d = float(np.dot(c - q, c - q)) + ENERGY_W * (energy - eq) ** 2 / max(energy, 1e-12)
                    if best is None or d < best[1]:
                        best = (_vlc_bits(m, sel) + 6, d, sel, sf, m)
                row.append(best)
        opts.append(row)
    return opts


def _weights(coefs):
    """Perceptual weight per subband: half-way between plain MSE (white noise) and noise that
    follows the spectrum (equal SNR per band). On TTS speech this keeps ~27.6 dB overall SNR
    (plain MSE 28.7, full shaping 19.6) while pushing noise under the formants."""
    e = np.array([np.mean(coefs[SUBBAND_TAB[i]:SUBBAND_TAB[i + 1]] ** 2) for i in range(32)])
    spread = np.convolve(e, [0.15, 0.3, 1.0, 0.3, 0.15], mode="same")
    return 1.0 / np.sqrt(spread + 1.0)


def _allocate(opts, weights, budget, gains=((), (), (), ())):
    gbands = max([b for b in range(4) if gains[b]], default=0)
    def pick(lam):
        choice = []
        for i, row in enumerate(opts):
            choice.append(min(row, key=lambda o: weights[i] * o[1] + lam * o[0]))
        return choice

    def total(choice):
        coded = [i for i, o in enumerate(choice) if o[2]]
        nsub = (coded[-1] + 1) if coded else 1
        bands = max((SUBBAND_TAB[nsub] - 1) >> 8, gbands)
        head = 6 + 2 + sum(3 + 9 * len(gains[b]) for b in range(bands + 1)) + 5 + 5 + 1 + 3 * nsub
        return head + sum(o[0] for o in choice[:nsub]), nsub, bands

    lo, hi = 0.0, 1e12
    best = None
    for _ in range(60):
        lam = (lo + hi) / 2 if best is not None or lo > 0 else 1.0
        ch = pick(lam)
        bits, nsub, bands = total(ch)
        if bits <= budget:
            best = (ch, nsub, bands)
            hi = lam
        else:
            lo = lam
        if hi - lo < 1e-9 * max(hi, 1e-30):
            break
    if best is None:                                      # nothing fits: code silence
        ch = [opts[i][0] for i in range(32)]
        return (ch, 1, gbands)
    # spend what the Lagrangian search left over (retail frames use 1215 of 1216 bits):
    # repeatedly take the upgrade with the best distortion drop per extra bit that still fits
    ch = list(best[0])
    used, nsub, _ = total(ch)
    while True:
        pick_ = None
        for i, row in enumerate(opts):
            cur = ch[i]
            for o in row:
                if o[0] <= cur[0]:
                    continue
                gain = weights[i] * (cur[1] - o[1])
                if gain <= 0:
                    continue
                if i < nsub:
                    bits = used + o[0] - cur[0]
                else:                                     # extends the coded range: header grows too
                    bits = total(ch[:i] + [o] + ch[i + 1:])[0]
                if bits > budget:
                    continue
                score = gain / max(bits - used, 1)
                if pick_ is None or score > pick_[0]:
                    pick_ = (score, i, o, bits)
        if pick_ is None:
            break
        ch[pick_[1]] = pick_[2]
        used, nsub, _ = total(ch)
    _, nsub, bands = total(ch)
    return ch, nsub, bands


def _write_unit(choice, nsub, bands, gains=((), (), (), ())):
    w = BitWriter()
    w.put(0x28, 6)
    w.put(bands, 2)
    for b in range(bands + 1):
        w.put(len(gains[b]), 3)                           # gain control points: level, location
        for lev, loc in gains[b]:
            w.put(lev, 4)
            w.put(loc, 5)
    w.put(0, 5)                                           # no tonal components
    w.put(nsub - 1, 5)
    w.put(0, 1)                                           # VLC coding
    for o in choice[:nsub]:
        w.put(o[2], 3)
    for o in choice[:nsub]:
        if o[2]:
            w.put(o[3], 6)
    for o in choice[:nsub]:
        sel, m = o[2], o[4]
        if not sel:
            continue
        if sel == 1:
            for a, b in zip(m[0::2], m[1::2]):
                code, ln = CODES[0][_PAIRS.index((int(a), int(b)))]
                w.put(code, ln)
        else:
            tab = CODES[sel - 1]
            for v in m:
                code, ln = tab[int(v)]
                w.put(code, ln)
    return w.tobytes(BLOCK)


# ---------------------------------------------------------------------------------------------

# Overall gain between the filter bank above and ffmpeg's decoder (IMDCT scale 1/32768, window,
# QMF): measured by encoding a sine and decoding it with ffmpeg (see calibrate()).
GAIN = -1.0 / 1024           # decoded = input (ffmpeg round trip: lag 1162 samples)


# ---------------------------------------------------------------------------------------------
# Gain control (pre-echo). The decoder (ff_atrac_gain_compensation) outputs band segment S_k as
#   (first half of IMDCT_{k+1} * L_{k+1} + second half of IMDCT_k) * g_k(n)
# where g_k is the curve sent with frame k (level 2^(4-code) held until loc*8, then an 8-sample
# ramp to the next point's level, and 1.0 after the last point) and L_{k+1} = g_{k+1}(0). So the
# encoder transforms S'_k = S_k / g_k and feeds block k+1 = [S'_k / L_{k+1}, S'_{k+1}]: a quiet
# stretch before an attack is boosted before quantisation and the decoder turns the noise there
# back down. Sony's encoder uses ~1 gain point per frame on the host clips.

def gain_curve(points):
    """Exact decoder gain curve for one band segment (256 samples)."""
    g = np.ones(256)
    pos = 0
    for i, (lev, loc) in enumerate(points):
        level = 2.0 ** (4 - lev)
        nxt = points[i + 1][0] if i + 1 < len(points) else 4
        inc = 2.0 ** (-(nxt - lev) / 8.0)
        last = loc << 3
        g[pos:last] = level
        pos = last
        for _ in range(8):
            g[pos] = level
            level *= inc
            pos += 1
    return g


ATTACK_RATIO = 4.0       # energy jump (8-sample blocks) counted as an attack (~6 dB): 0.25 pts/frame on host
                         # speech, noise before onsets -5.4 dB vs ~0 dB without gain control, SNR unchanged


def _attack(prev_seg, seg, floor):
    """One gain point attenuating the stretch before a sharp attack in this segment, or none."""
    e = (seg.reshape(32, 8) ** 2).mean(1)
    pe = (prev_seg[128:].reshape(16, 8) ** 2).mean(1).max()
    for j in range(2, 31):
        before = max(e[:j].max(), pe)
        after = e[j:j + 3].max()
        if after > floor and after > ATTACK_RATIO * max(before, 1e-20):
            d = int(np.clip(np.round(0.5 * np.log2(after / max(before, 1e-20)) - 1), 1, 6))
            return ((4 + d, j - 1),)
    return ()


def encode(samples, gain=None, gain_control=True):
    """samples: mono 48 kHz, int16 scale (floats ok). -> raw 152-byte ATRAC3 frames."""
    g = GAIN if gain is None else gain
    x = np.asarray(samples, np.float64) * g
    nframes = (len(x) + FRAME - 1) // FRAME + 3            # tail frames flush the filter delay
    x = np.concatenate([x, np.zeros(nframes * FRAME - len(x))])
    floor = 1e-4 * float(np.max(np.abs(x))) ** 2 if len(x) else 0.0   # ignore attacks below -40 dB
    q1, q2, q3 = QMF(), QMF(), QMF()
    prev_raw = np.zeros((4, 256))
    prev_mod = np.zeros((4, 256))
    out = bytearray()
    for f in range(nframes):
        lo, hi = q1.analysis(x[f * FRAME:(f + 1) * FRAME])
        b0, b1 = q2.analysis(lo)
        b3, b2 = q3.analysis(hi)                           # decoder feeds band 3 as the low input
        spec = np.zeros(FRAME)
        gains = []
        for b, band in enumerate((b0, b1, b2, b3)):
            pts = _attack(prev_raw[b], band, floor) if gain_control else ()
            gc = gain_curve(pts)
            mod = band / gc
            block = np.concatenate([prev_mod[b] / gc[0], mod]) * AWIN
            prev_raw[b], prev_mod[b] = band, mod
            gains.append(pts)
            c = BASIS @ block
            if b & 1:
                c = c[::-1]
            spec[b * 256:(b + 1) * 256] = c
        opts = _options(spec)
        choice, nsub, bands = _allocate(opts, _weights(spec), BITS, gains)
        out += _write_unit(choice, nsub, bands, gains)
    return bytes(out)
