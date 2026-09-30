"""Step 1 of the host-voice trainer: collect every host line from the user's OWN game files.

    python -m voice_trainer.corpus --disc "L:/.../Buzz Quiz World (Europe) (EnEsPt)" \
        [--pack dlc_test/GBRPACK0017.DAT ...] [--question-pak <path to INEPACK0100.PAK>] --work <dir>

Sources (nothing is bundled with the tool, everything is read from the user's copy):
  * disc question pack  PS3_GAME/USRDIR/PACK0100/INEPACK0100.PAK
        QUESTIONASSETS/SPEECH/QUESTIONS/ONDEMAND/<6000000000+speech id>.rsf, text = the role-1
        (question) sentence of that speech id in ROUNDS/*.kaq + .hdr/.hst string tables
  * disc commentary     PS3_GAME/USRDIR/GAME/INE.PAK
        AUDIO/COMMENTARY/{ONDEMAND,PRELOADED}/9xxxxxxxNN.rsf, text = COMMENTARY/comments.dat line
        8xxxxxxx (NN = recorded variant; variants may differ slightly from the script line)
  * decrypted DLC packs (.DAT) - same layout as the question pack
Output in <work>: audio/<id>.flac (24 kHz mono) + manifest.jsonl
  {"id", "kind": question|commentary, "text", "text_exact", "dur", "source"}
All clips of one source are decoded in a single ffmpeg pass: frames are concatenated with silent
frames in between, so each clip decodes exactly as it would alone and is cut out afterwards.
"""
import argparse
import io
import json
import os
import re
import struct
import subprocess
import sys
import zipfile

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import buzz_index  # noqa: E402
import buzz_rsf  # noqa: E402
import buzz_text  # noqa: E402

OUT_RATE = 24000
GAP = 4                                   # silent frames between clips in the decode stream


def question_clips(z):
    """-> list of (id, member, text) for a question pack (disc or DLC zip)."""
    names = z.namelist()
    text = {}
    for n in names:
        if n.endswith(".kaq"):
            m = buzz_index.parse(z.read(n))
            strs = buzz_text.decode_all(z.read(n[:-4] + ".hdr"), z.read(n[:-4] + ".hst"))
            for sid, si, role, _ in m["sections"][3]:
                if role == 1:
                    s = strs[si - 1]
                    text.setdefault(sid, s[1] if isinstance(s, tuple) else s)
    out = []
    for n in names:
        if "/QUESTIONS/ONDEMAND/" in n.upper().replace("\\", "/") and n.lower().endswith(".rsf"):
            sid = int(os.path.basename(n)[:-4]) - 6000000000
            out.append(("q%d" % sid, n, text.get(sid)))
    return out


def commentary_clips(z):
    names = z.namelist()
    script = {}
    cd = [n for n in names if n.upper().endswith("COMMENTARY/COMMENTS.DAT")]
    if cd:
        for cid, _, line in re.findall(r"^(\d{6,}),(\d+),(.*?)\r", z.read(cd[0]).decode("latin-1"), re.M):
            script[cid] = line.strip()
    out = []
    for n in names:
        if "/AUDIO/COMMENTARY/" in n.upper() and n.lower().endswith(".rsf"):
            f = os.path.basename(n)[:-4]
            out.append(("c" + f, n, script.get("8" + f[1:-2])))
    return out


def decode_many(rsfs):
    """Decode many .rsf clips (same rate/block size) in one ffmpeg run -> list of float arrays at
    OUT_RATE."""
    rate, ba, _ = buzz_rsf.parse(rsfs[0])
    silent = buzz_rsf.SILENT_FRAME if ba == 152 else b"\x00" * ba
    body, spans = bytearray(), []
    for r in rsfs:
        _, b2, frames = buzz_rsf.parse(r)
        assert b2 == ba, "mixed frame sizes"
        start = len(body) // ba
        body += frames
        spans.append((start, len(frames) // ba))
        body += silent * GAP
    hdr = bytearray(buzz_rsf.speech_header(len(body), rate))
    hdr[0x10:0x14] = struct.pack(">I", ba)
    wav = buzz_rsf.to_wav(bytes(hdr) + bytes(body))
    pcm = subprocess.run([__import__("buzz_tools").ffmpeg(), "-v", "error", "-i", "-", "-ac", "1", "-ar", str(OUT_RATE),
                          "-f", "s16le", "-"], input=wav, capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768.0
    k = OUT_RATE / rate * 1024                       # output samples per frame
    out = []
    for start, n in spans:
        a, b = int(round(start * k)), int(round((start + n + GAP - 1) * k))
        out.append(x[a:b])
    return out


def trim(x, thr=0.01, pad=0.08):
    loud = np.nonzero(np.abs(x) > thr)[0]
    if not len(loud):
        return x[:0]
    p = int(pad * OUT_RATE)
    return x[max(0, loud[0] - p):loud[-1] + p]


def build(sources, work):
    os.makedirs(os.path.join(work, "audio"), exist_ok=True)
    man_path = os.path.join(work, "manifest.jsonl")
    done = set()
    if os.path.exists(man_path):
        done = {json.loads(l)["id"] for l in open(man_path, encoding="utf-8")}
    man = open(man_path, "a", encoding="utf-8")
    total = 0
    for path, kind in sources:
        z = zipfile.ZipFile(path)
        clips = question_clips(z) if kind == "question" else commentary_clips(z)
        clips = [c for c in clips if c[0] not in done]
        print("%s: %d %s clips" % (os.path.basename(path), len(clips), kind), flush=True)
        for i in range(0, len(clips), 400):
            batch = clips[i:i + 400]
            rsfs = [z.read(m) for _, m, _ in batch]
            groups = {}
            for c, r in zip(batch, rsfs):                      # group by (rate, block align)
                groups.setdefault(buzz_rsf.parse(r)[:2], []).append((c, r))
            for items in groups.values():
                for (cid, member, text), x in zip([c for c, _ in items], decode_many([r for _, r in items])):
                    x = trim(x)
                    if len(x) < 0.3 * OUT_RATE:
                        continue
                    sf.write(os.path.join(work, "audio", cid + ".flac"), x, OUT_RATE)
                    man.write(json.dumps({"id": cid, "kind": kind, "text": text,
                                          "text_exact": kind == "question" and bool(text),
                                          "dur": round(len(x) / OUT_RATE, 3),
                                          "source": os.path.basename(path)}) + "\n")
                    total += 1
            man.flush()
            print("  %d/%d" % (min(i + 400, len(clips)), len(clips)), flush=True)
    man.close()
    return total


def find_sources(disc, packs, question_pak=None):
    u = os.path.join(disc, "PS3_GAME", "USRDIR")
    src = []
    qp = question_pak or os.path.join(u, "PACK0100", "INEPACK0100.PAK")
    if os.path.exists(qp):
        src.append((qp, "question"))
    cp = os.path.join(u, "GAME", "INE.PAK")
    if os.path.exists(cp):
        src.append((cp, "commentary"))
    src += [(p, "question") for p in packs]
    return src


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--disc", required=True, help="extracted game folder (contains PS3_GAME)")
    ap.add_argument("--pack", action="append", default=[], help="decrypted DLC pack (.DAT), repeatable")
    ap.add_argument("--question-pak", default=None, help="override the disc question pack path")
    ap.add_argument("--work", required=True)
    a = ap.parse_args()
    srcs = find_sources(a.disc, a.pack, a.question_pak)
    for s in srcs:
        print("source:", s)
    print("clips written:", build(srcs, a.work))
