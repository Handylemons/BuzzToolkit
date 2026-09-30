"""Step 2 of the host-voice trainer: turn the corpus into Chatterbox training features (GPU).

    tools/clone_venv/Scripts/python.exe -m voice_trainer.features --work <dir>

Per clip (exactly what Chatterbox computes for a reference at inference time):
  tokens   S3 speech tokens, 25 Hz, from the 16 kHz audio (s3gen.tokenizer)
  mel      S3Gen 80-bin mel at 24 kHz (50 Hz frames, = 2 x tokens; audio padded to 40 ms)
  xvec     CAMPPlus speaker x-vector (s3gen.speaker_encoder, 16 kHz) - S3Gen conditioning
  ve       voice-encoder speaker embedding (256) - T3 conditioning
  text     T3 text tokens of the normalised transcript (question clips / exact text only)
Written to <work>/features/shard_NNN.pt (lists of dicts, 500 clips per shard) + speakers.json
(cosine similarity of each clip's x-vector to the host centroid, used to drop other voices).
"""
import argparse
import glob
import json
import os
import sys

import librosa
import numpy as np
import soundfile as sf
import torch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from chatterbox.tts import ChatterboxTTS, punc_norm  # noqa: E402

SHARD = 500


def norm_text(t):
    """Same normalisation as buzz_voice.host_line (ALL CAPS -> sentence case) + Chatterbox's."""
    t = t.strip()
    if t.isupper():
        t = t.lower()
        t = t[:1].upper() + t[1:]
    return punc_norm(t)


@torch.inference_mode()
def extract(model, wav24, text):
    dev = model.device
    n = len(wav24) // 960 * 960                       # 40 ms multiple -> mel = 2 x tokens exactly
    wav24 = wav24[:n]
    wav16 = librosa.resample(wav24, orig_sr=24000, target_sr=16000)
    s3 = model.s3gen
    w24 = torch.from_numpy(wav24).float().to(dev)[None]
    w16 = torch.from_numpy(wav16).float().to(dev)[None]
    mel = s3.mel_extractor(w24)[0]                                   # (80, T)
    tok, tl = s3.tokenizer(w16)
    tok = tok[0, :tl[0]]
    T = min(len(tok), mel.shape[1] // 2)
    tok, mel = tok[:T], mel[:, :2 * T]
    xvec = s3.speaker_encoder.inference(w16)[0]
    ve = model.ve.embeds_from_wavs([wav16], sample_rate=16000)[0]
    item = {"tokens": tok.short().cpu(), "mel": mel.half().cpu(), "xvec": xvec.float().cpu(),
            "ve": torch.from_numpy(np.asarray(ve)).float()}
    if text:
        item["text"] = model.tokenizer.text_to_tokens(norm_text(text))[0].short().cpu()
    return item


def main(work):
    out_dir = os.path.join(work, "features")
    os.makedirs(out_dir, exist_ok=True)
    man = [json.loads(l) for l in open(os.path.join(work, "manifest.jsonl"), encoding="utf-8")]
    man = [m for m in man if m["dur"] <= 20.0]
    done = set()
    for f in glob.glob(os.path.join(out_dir, "shard_*.pt")):
        done |= {it["id"] for it in torch.load(f)}
    todo = [m for m in man if m["id"] not in done]
    print("clips %d, already done %d, to do %d" % (len(man), len(done), len(todo)), flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    shard_no = len(glob.glob(os.path.join(out_dir, "shard_*.pt")))
    buf = []
    for i, m in enumerate(todo):
        wav, sr = sf.read(os.path.join(work, "audio", m["id"] + ".flac"), dtype="float32")
        item = extract(model, wav, m["text"] if m.get("text_exact") else None)
        item.update(id=m["id"], kind=m["kind"], dur=m["dur"], raw_text=m.get("text"))
        buf.append(item)
        if len(buf) == SHARD or i == len(todo) - 1:
            torch.save(buf, os.path.join(out_dir, "shard_%03d.pt" % shard_no))
            shard_no += 1
            buf = []
            print("  %d/%d" % (i + 1, len(todo)), flush=True)
    speakers(work)


def speakers(work):
    """Cosine similarity of every clip's x-vector to the centroid of the question readings
    (all read by the host) -> speakers.json. Commentary can include other characters."""
    items = []
    for f in sorted(glob.glob(os.path.join(work, "features", "shard_*.pt"))):
        items += [(it["id"], it["kind"], it["xvec"]) for it in torch.load(f)]
    X = torch.stack([F / F.norm() for _, _, F in items])
    q = torch.tensor([k == "question" for _, k, _ in items])
    c = X[q].mean(0)
    c = c / c.norm()
    sims = (X @ c).tolist()
    qs = sorted(s for s, isq in zip(sims, q.tolist()) if isq)
    floor = qs[int(0.01 * len(qs))]                     # 1st percentile of the host's own clips
    json.dump({"floor": floor, "sim": {i: round(s, 4) for (i, _, _), s in zip(items, sims)}},
              open(os.path.join(work, "speakers.json"), "w"))
    com = [s for s, isq in zip(sims, q.tolist()) if not isq]
    print("speaker floor %.3f; commentary kept %d of %d" % (floor, sum(s >= floor for s in com), len(com)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    main(ap.parse_args().work)
