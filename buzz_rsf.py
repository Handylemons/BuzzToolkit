"""Buzz speech/music clips (.rsf): 32-byte big-endian header + raw ATRAC3 frames.

Header (from PACK0017 speech, verified by decoding with ffmpeg):
  0x00 05 00 01 01   0x04 u16 sample rate (0xBB80 = 48000)   0x06 u16 1
  0x08 u32 data size  0x0C u32 data size  0x10 u32 block align (0x98 = 152 = mono ATRAC3 frame)
  0x14 u32 data size  0x18 03 00 00 00    0x1C 0
Data: ATRAC3 frames of `block align` bytes, 1024 samples each (mono, 48 kHz for speech).
ffmpeg decodes ATRAC3 but cannot encode it, so silence is built from frames that decode to
digital silence (found in retail clips).
"""
import os
import struct
import subprocess
import tempfile
import wave

import buzz_tools


def parse(rsf):
    rate = struct.unpack(">H", rsf[4:6])[0]
    size, ba = struct.unpack(">I", rsf[8:12])[0], struct.unpack(">I", rsf[0x10:0x14])[0]
    return rate, ba, rsf[32:32 + size]


def build(template_hdr, frames):
    h = bytearray(template_hdr[:32])
    for off in (0x08, 0x0C, 0x14):
        h[off:off + 4] = struct.pack(">I", len(frames))
    return bytes(h) + frames


def to_wav(rsf):
    """Wrap an .rsf in a RIFF/ATRAC3 header that ffmpeg can decode."""
    rate, ba, body = parse(rsf)
    extra = struct.pack("<HIHHHH", 1, 0x800, 0, 0, 1, 0)
    fmt = struct.pack("<HHIIHHH", 0x270, 1, rate, ba * rate // 1024, ba, 0, len(extra)) + extra
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"fact" + struct.pack("<II", 4, len(body) // ba * 1024)
              + b"data" + struct.pack("<I", len(body)) + body)
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def decode(rsf):
    """-> list of int16 samples."""
    with tempfile.TemporaryDirectory() as td:
        a, b = os.path.join(td, "a.wav"), os.path.join(td, "b.wav")
        open(a, "wb").write(to_wav(rsf))
        subprocess.run([buzz_tools.ffmpeg(), "-v", "error", "-y", "-i", a, "-c:a", "pcm_s16le", b], check=True)
        with wave.open(b) as w:
            n = w.getnframes()
            return list(struct.unpack("<%dh" % n, w.readframes(n)))


# Mono ATRAC3 frame that decodes to digital silence: sound unit id 0x28, 1 gain band with no
# points, no tonal components, one uncoded subband (verified with ffmpeg: peak 0).
SILENT_FRAME = b"\xa0" + bytes(151)


def speech_header(data_size, rate=48000):
    """32-byte header of a mono speech clip (152-byte ATRAC3 frames), built from scratch."""
    return (bytes([5, 0, 1, 1]) + struct.pack(">HH", rate, 1) + struct.pack(">III", data_size, data_size, 0x98)
            + struct.pack(">I", data_size) + bytes([3, 0, 0, 0]) + bytes(4))


def silent_clip(frames=16):
    """A short silent host-speech clip (mono ATRAC3, 48 kHz), no template needed."""
    body = SILENT_FRAME * frames
    return speech_header(len(body)) + body
