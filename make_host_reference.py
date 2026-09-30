"""Build the host voice reference for the cloning TTS from the user's OWN game files.

    python make_host_reference.py dlc_test/GBRPACK0017.DAT            -> voice_refs/buzz_host.wav
    python make_host_reference.py pack.DAT --pick 63904,63905 --out voice_refs/x.wav

Input: a decrypted retail pack (.DAT = the zip inside the EDAT). Its host question clips
(QUESTIONASSETS/SPEECH/QUESTIONS/ONDEMAND/*.rsf) are decoded with ffmpeg and a few typical
question readings are joined with short gaps into ~10 s, which is what Chatterbox conditions on.
Default pick: the first clips (by speech id) lasting 4.5-6 s. Also writes <out>.txt listing the
clips and their question text.
"""
import argparse
import io
import os
import wave
import zipfile

import numpy as np

import buzz_index
import buzz_rsf
import buzz_text

HERE = os.path.dirname(os.path.abspath(__file__))


def host_clips(pack_path):
    """-> {speech id: (rsf bytes, question text)}"""
    z = zipfile.ZipFile(pack_path)
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
    out = {}
    for n in names:
        if "/ONDEMAND/" in n and n.endswith(".rsf"):
            sid = int(os.path.basename(n)[:-4]) - 6000000000
            out[sid] = (z.read(n), text.get(sid, ""))
    return out


def build_reference(pack_path, out_path, pick=None, target=10.0, gap=0.25):
    clips = host_clips(pack_path)
    if pick:
        chosen = pick
    else:
        chosen, total = [], 0.0
        for sid in sorted(clips):
            dur = (len(clips[sid][0]) - 32) / 152 * 1024 / 48000
            if 4.5 <= dur <= 6.0:
                chosen.append(sid)
                total += dur + gap
                if total >= target:
                    break
    parts = []
    for sid in chosen:
        x = np.array(buzz_rsf.decode(clips[sid][0]), np.float64)
        loud = np.nonzero(np.abs(x) > 500)[0]
        parts += [x[max(0, loud[0] - 1200):loud[-1] + 2400], np.zeros(int(gap * 48000))]
    x = np.concatenate(parts[:-1])
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())
    with open(os.path.splitext(out_path)[0] + ".txt", "w", encoding="utf-8") as f:
        f.write("source: %s\n" % os.path.basename(pack_path))
        for sid in chosen:
            f.write("%d\t%s\n" % (sid, clips[sid][1]))
    return out_path, chosen, len(x) / 48000


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("--out", default=os.path.join(HERE, "voice_refs", "buzz_host.wav"))
    ap.add_argument("--pick", default="", help="comma-separated speech ids to use instead of the default pick")
    ap.add_argument("--lang", help="pack language code of this voice (GBR, ESP, PRT, DEU, ...)")
    a = ap.parse_args()
    pick = [int(s) for s in a.pick.split(",") if s]
    path, chosen, dur = build_reference(a.pack, a.out, pick or None)
    if a.lang:
        import json
        info_path = os.path.join(os.path.dirname(os.path.abspath(a.out)), "info.json")
        info = json.load(open(info_path)) if os.path.exists(info_path) else {}
        info.update(lang=a.lang.upper(), source=os.path.basename(a.pack), reference_clips=chosen)
        json.dump(info, open(info_path, "w"), indent=1)
    print("%s: %.1f s from clips %s" % (path, dur, chosen))
