"""Step 3 of the host-voice trainer: fine-tune Chatterbox's S3Gen flow (speech tokens -> mel) on
the host's voice. This is what makes it SOUND like him (timbre, warmth, recording character).

    tools/clone_venv/Scripts/python.exe -m voice_trainer.train_s3gen --work <dir> [--steps 1500]

Trains the flow encoder + CFM decoder with the model's own flow-matching loss
(CausalMaskedDiffWithXvec.compute_loss: random 0-30% mel prompt, 20% condition dropout for CFG).
The HiFi-GAN vocoder stays frozen. Saves <work>/models/s3gen_flow.pt (+ periodic step copies).
"""
import argparse
import math
import os
import sys
import time

import torch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from chatterbox.tts import ChatterboxTTS  # noqa: E402
from voice_trainer.data import batches, load_items  # noqa: E402


def collate(items, max_tokens=300):
    B = len(items)
    toks, mels = [], []
    for it in items:
        t, m = it["tokens"].long(), it["mel"].float()
        if len(t) > max_tokens:                                   # random crop, token-aligned
            s = torch.randint(0, len(t) - max_tokens + 1, ()).item()
            t, m = t[s:s + max_tokens], m[:, 2 * s:2 * (s + max_tokens)]
        toks.append(t)
        mels.append(m)
    T = max(len(t) for t in toks)
    tok = torch.zeros(B, T, dtype=torch.long)
    mel = torch.zeros(B, 80, 2 * T)
    for i, (t, m) in enumerate(zip(toks, mels)):
        tok[i, :len(t)] = t
        mel[i, :, :m.shape[1]] = m
    return {"speech_token": tok, "speech_token_len": torch.tensor([len(t) for t in toks]),
            "speech_feat": mel, "speech_feat_len": torch.tensor([m.shape[1] for m in mels]),
            "embedding": torch.stack([it["xvec"] for it in items])}


def main(a):
    train, val = load_items(a.work)
    print("train %d clips (%.1f h), val %d" % (len(train), sum(i["dur"] for i in train) / 3600, len(val)), flush=True)
    model = ChatterboxTTS.from_pretrained(device="cuda")
    flow = model.s3gen.flow
    del model.t3
    torch.cuda.empty_cache()
    flow.train()
    params = [p for p in flow.parameters() if p.requires_grad]
    print("flow params %.1fM" % (sum(p.numel() for p in params) / 1e6), flush=True)
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.01, betas=(0.9, 0.98))
    sched = lambda s: min(1.0, s / 200) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(s, a.steps) / a.steps)))
    lr_s = torch.optim.lr_scheduler.LambdaLR(opt, sched)
    out = a.out or os.path.join(a.work, "models")
    os.makedirs(out, exist_ok=True)
    val_batches = batches(val, a.max_frames, shuffle=False)

    def validate():
        flow.eval()
        torch.manual_seed(0)
        tot, n = 0.0, 0
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            for b in val_batches:
                tot += flow.compute_loss(collate(b), "cuda")["loss"].item()
                n += 1
        flow.train()
        return tot / max(n, 1)

    best = validate()
    print("val loss before: %.4f" % best, flush=True)
    step, epoch, t0, run = 0, 0, time.time(), 0.0
    while step < a.steps:
        for b in batches(train, a.max_frames, seed=epoch):
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = flow.compute_loss(collate(b), "cuda")["loss"]
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            lr_s.step()
            step += 1
            run = 0.98 * run + 0.02 * loss.item() if step > 1 else loss.item()
            if step % 50 == 0:
                print("step %d  loss %.4f  lr %.2e  %.1f steps/s" % (step, run, lr_s.get_last_lr()[0], step / (time.time() - t0)), flush=True)
            if step % a.eval_every == 0 or step == a.steps:
                v = validate()
                print("step %d  val loss %.4f%s" % (step, v, "  (best, saved)" if v < best else ""), flush=True)
                if v < best:
                    best = v
                    torch.save(flow.state_dict(), os.path.join(out, "s3gen_flow.pt"))
            if step >= a.steps:
                break
        epoch += 1
    print("done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-frames", type=int, default=2400, help="speech tokens per batch (25/s)")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--out", default=None, help="model folder (default <work>/models)")
    main(ap.parse_args())
