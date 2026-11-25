"""Step 3 of the host-voice trainer: fine-tune Chatterbox's S3Gen flow (speech tokens -> mel) on
the host's voice. This is what makes it SOUND like him (timbre, warmth, recording character).

    tools/clone_venv/Scripts/python.exe -m voice_trainer.train_s3gen --work <dir> [--steps 1500]

Trains the flow encoder + CFM decoder with the model's own flow-matching loss
(CausalMaskedDiffWithXvec.compute_loss: random 0-30% mel prompt, 20% condition dropout for CFG).
The HiFi-GAN vocoder stays frozen. Saves <work>/models/s3gen_flow.pt (best validation loss). An interrupted run carries on from
<work>/models/s3gen_resume.pt (written every 15 min); s3gen.done marks a finished stage.
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
from voice_trainer.data import (autocast, batches, describe, eta, free_cache, load_items, pick_device,  # noqa: E402
                                record_speed, save_atomic)


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
    dev = pick_device()
    print(describe(dev), flush=True)
    model = ChatterboxTTS.from_pretrained(device=dev)
    flow = model.s3gen.flow
    del model.t3
    free_cache(dev)
    flow.train()
    params = [p for p in flow.parameters() if p.requires_grad]
    print("flow params %.1fM" % (sum(p.numel() for p in params) / 1e6), flush=True)
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.01, betas=(0.9, 0.98))
    warm = min(200, max(1, a.steps // 5))
    sched = lambda s: min(1.0, s / warm) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(s, a.steps) / a.steps)))
    lr_s = torch.optim.lr_scheduler.LambdaLR(opt, sched)
    out = a.out or os.path.join(a.work, "models")
    os.makedirs(out, exist_ok=True)
    final, resume, done = (os.path.join(out, n) for n in ("s3gen_flow.pt", "s3gen_resume.pt", "s3gen.done"))
    val_batches = batches(val, a.max_frames, shuffle=False)
    tval = [0.0]

    def validate():
        t = time.time()
        flow.eval()
        torch.manual_seed(0)
        tot, n = 0.0, 0
        with torch.no_grad(), autocast(dev):
            for b in val_batches:
                tot += flow.compute_loss(collate(b), dev)["loss"].item()
                n += 1
        flow.train()
        tval[0] += time.time() - t
        return tot / max(n, 1)

    step, epoch, skip, run = 0, 0, 0, 0.0
    if os.path.exists(resume):
        ck = torch.load(resume, map_location="cpu", weights_only=False)
        flow.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        lr_s.load_state_dict(ck["sched"])
        step, epoch, skip, best, run = ck["step"], ck["epoch"], ck["batch"], ck["best"], ck["run"]
        torch.set_rng_state(ck["rng"])
        print("resuming from step %d of %d (saved %s)" % (step, a.steps, time.ctime(os.path.getmtime(resume))), flush=True)
    else:
        best = validate()
        print("val loss before: %.4f" % best, flush=True)

    def save_resume(bi):
        save_atomic({"model": flow.state_dict(), "opt": opt.state_dict(), "sched": lr_s.state_dict(), "step": step,
                     "epoch": epoch, "batch": bi + 1, "best": best, "run": run, "rng": torch.get_rng_state()}, resume)

    start, t0, last_save, stop = step, time.time(), time.time(), False
    while step < a.steps and not stop:
        for bi, b in enumerate(batches(train, a.max_frames, seed=epoch)):
            if bi < skip:
                continue
            with autocast(dev):
                loss = flow.compute_loss(collate(b), dev)["loss"]
            if not torch.isfinite(loss):
                raise SystemExit("loss became NaN/inf at step %d - try --precision fp32 (or --no-miopen on AMD)" % step)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            lr_s.step()
            step += 1
            run = 0.98 * run + 0.02 * loss.item() if step > 1 else loss.item()
            rate = (step - start) / max(1e-6, time.time() - t0 - tval[0])
            if step % 50 == 0:
                print("step %d  loss %.4f  lr %.2e  %.2f steps/s  ~%s left" % (step, run, lr_s.get_last_lr()[0], rate,
                      eta((a.steps - step) / rate)), flush=True)
            stop = bool(a.max_minutes) and time.time() - t0 > 60 * a.max_minutes
            if step % a.eval_every == 0 or step == a.steps or stop:
                v = validate()
                better = v < best
                print("step %d  val loss %.4f%s" % (step, v, "  (best, saved)" if better or a.save_final else ""), flush=True)
                if better or a.save_final:
                    best = min(best, v)
                    torch.save(flow.state_dict(), final)
            if step < a.steps and not stop and (step % a.eval_every == 0 or time.time() - last_save > 60 * a.save_every_min):
                save_resume(bi)
                last_save = time.time()
            if step >= a.steps or stop:
                break
        skip = 0
        if not stop and step < a.steps:
            epoch += 1
    if step > start:
        record_speed(a.work, "s3gen_steps_per_s", round((step - start) / max(1e-6, time.time() - t0 - tval[0]), 4), dev)
    if not os.path.exists(final):                       # validation never improved: keep the last weights
        torch.save(flow.state_dict(), final)
    if os.path.exists(resume):
        os.remove(resume)
    open(done, "w").write("%d steps" % step)
    print("done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-frames", type=int, default=2400, help="speech tokens per batch (25/s)")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--out", default=None, help="model folder (default <work>/models)")
    ap.add_argument("--save-every-min", type=float, default=15, help="resume checkpoint interval")
    ap.add_argument("--max-minutes", type=float, default=0, help="stop early after this long (preview)")
    ap.add_argument("--save-final", action="store_true", help="save the last weights even if not the best (preview)")
    main(ap.parse_args())
