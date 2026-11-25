"""Step 4 of the host-voice trainer: LoRA fine-tune of Chatterbox's T3 (text -> speech tokens) on
the host's question readings, so the cadence, accent and intonation follow him.

    tools/clone_venv/Scripts/python.exe -m voice_trainer.train_t3 --work <dir> [--steps 500]

Each sample is laid out exactly as at inference: [conditioning | SOT text EOT | SOS speech EOS]
(per sample, right-padded as a whole - Chatterbox's own T3.loss pads text in the middle and
compares logits to unshifted targets, so it is not used). Conditioning = voice-encoder embedding
of the clip + a 150-token speech prompt cut from OTHER host clips (as the reference clip is at
inference) + emotion 0.5. 10% of samples drop the text (keeps the classifier-free-guidance path).
LoRA (peft) on the Llama attention + MLP; saves <work>/models/t3_lora/ (best validation loss). An
interrupted run carries on from t3_lora/resume.pt (written every 15 min); t3_lora/t3.done marks a finished stage.
"""
import argparse
import math
import os
import random
import sys
import time

import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from chatterbox.models.t3.modules.cond_enc import T3Cond  # noqa: E402
from peft import LoraConfig, get_peft_model  # noqa: E402
from voice_trainer.data import work_lang  # noqa: E402
from voice_trainer.features import load_model  # noqa: E402
from voice_trainer.data import (autocast, batches, describe, eta, free_cache, load_items, pick_device,  # noqa: E402
                                record_speed, save_atomic)

PLEN = 150


def prompt_tokens(pool, rng):
    toks = []
    while sum(len(t) for t in toks) < PLEN:
        toks.append(rng.choice(pool)["tokens"].long())
    return torch.cat(toks)[:PLEN]


def step_loss(t3, items, pool, rng, dev, drop_text=0.1):
    hp = t3.hp
    B = len(items)
    cond = T3Cond(speaker_emb=torch.stack([it["ve"] for it in items]).to(dev),
                  cond_prompt_speech_tokens=torch.stack([prompt_tokens(pool, rng) for _ in items]).to(dev),
                  emotion_adv=0.5 * torch.ones(B, 1, 1, device=dev))
    cond_emb = t3.prepare_conditioning(cond)                               # (B, Lc, D)
    seqs, spans, targets = [], [], []
    for i, it in enumerate(items):
        text = torch.cat([torch.tensor([hp.start_text_token]), it["text"].long(), torch.tensor([hp.stop_text_token])]).to(dev)
        sp = torch.cat([torch.tensor([hp.start_speech_token]), it["tokens"].long(), torch.tensor([hp.stop_speech_token])]).to(dev)
        te = t3.text_emb(text[None])[0] + t3.text_pos_emb(text[None])[0]
        if rng.random() < drop_text:
            te = te * 0
        se = t3.speech_emb(sp[None])[0] + t3.speech_pos_emb(sp[None])[0]
        seqs.append(torch.cat([cond_emb[i], te, se]))
        s0 = cond_emb.shape[1] + len(text)
        spans.append((s0, len(sp)))
        targets.append(sp)
    L = max(len(s) for s in seqs)
    D = seqs[0].shape[1]
    emb = torch.zeros(B, L, D, device=dev, dtype=seqs[0].dtype)
    att = torch.zeros(B, L, dtype=torch.long, device=dev)
    for i, s in enumerate(seqs):
        emb[i, :len(s)] = s
        att[i, :len(s)] = 1
    h = t3.tfmr(inputs_embeds=emb, attention_mask=att, use_cache=False, return_dict=True).last_hidden_state
    logits, tgt = [], []
    for i, (s0, n) in enumerate(spans):
        logits.append(t3.speech_head(h[i, s0:s0 + n - 1]))                # predicts tokens 1..n-1
        tgt.append(targets[i][1:])
    return F.cross_entropy(torch.cat(logits).float(), torch.cat(tgt))


def main(a):
    train, val = load_items(a.work, need_text=True)
    pool, _ = load_items(a.work)                          # any host clip can serve as the prompt
    print("train %d clips (%.1f h), val %d" % (len(train), sum(i["dur"] for i in train) / 3600, len(val)), flush=True)
    dev = pick_device()
    print(describe(dev), flush=True)
    model = load_model(work_lang(a.work)[1])
    t3 = model.t3
    del model.s3gen
    free_cache(dev)
    for p in t3.parameters():
        p.requires_grad_(False)
    t3.tfmr = get_peft_model(t3.tfmr, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05,
                                                 target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                                 "gate_proj", "up_proj", "down_proj"]))
    t3.tfmr.print_trainable_parameters()
    t3.train()
    params = [p for p in t3.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
    warm = min(100, max(1, a.steps // 5))
    sched = lambda s: min(1.0, s / warm) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(s, a.steps) / a.steps)))
    lr_s = torch.optim.lr_scheduler.LambdaLR(opt, sched)
    out = a.out or os.path.join(a.work, "models", "t3_lora")
    os.makedirs(out, exist_ok=True)
    resume, done = os.path.join(out, "resume.pt"), os.path.join(out, "t3.done")
    val_b = batches(val, a.max_frames, shuffle=False)
    tval = [0.0]

    def validate():
        t = time.time()
        t3.eval()
        vrng = random.Random(0)
        tot = 0.0
        with torch.no_grad(), autocast(dev):
            for b in val_b:
                tot += step_loss(t3, b, pool, vrng, dev, drop_text=0).item()
        t3.train()
        tval[0] += time.time() - t
        return tot / max(len(val_b), 1)

    rng = random.Random(1)
    step, epoch, skip, run, saved = 0, 0, 0, 0.0, False
    if os.path.exists(resume):
        ck = torch.load(resume, map_location="cpu", weights_only=False)
        bad = t3.load_state_dict(ck["lora"], strict=False).unexpected_keys
        if bad:
            raise SystemExit("resume file does not match this model (%s...) - delete %s" % (bad[0], resume))
        opt.load_state_dict(ck["opt"])
        lr_s.load_state_dict(ck["sched"])
        step, epoch, skip, best, run, saved = ck["step"], ck["epoch"], ck["batch"], ck["best"], ck["run"], ck["saved"]
        rng.setstate(ck["py_rng"])
        torch.set_rng_state(ck["rng"])
        print("resuming from step %d of %d (saved %s)" % (step, a.steps, time.ctime(os.path.getmtime(resume))), flush=True)
    else:
        best = validate()
        print("val loss before: %.4f" % best, flush=True)

    def save_resume(bi):
        lora = {n: p.detach().cpu() for n, p in t3.named_parameters() if p.requires_grad}
        save_atomic({"lora": lora, "opt": opt.state_dict(), "sched": lr_s.state_dict(), "step": step, "epoch": epoch,
                     "batch": bi + 1, "best": best, "run": run, "saved": saved, "py_rng": rng.getstate(),
                     "rng": torch.get_rng_state()}, resume)

    start, t0, last_save, stop = step, time.time(), time.time(), False
    while step < a.steps and not stop:
        for bi, b in enumerate(batches(train, a.max_frames, seed=epoch)):
            if bi < skip:
                continue
            with autocast(dev):
                loss = step_loss(t3, b, pool, rng, dev)
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
            if step % a.log_every == 0:
                print("step %d  loss %.4f  lr %.2e  %.3f steps/s  ~%s left" % (step, run, lr_s.get_last_lr()[0], rate,
                      eta((a.steps - step) / rate)), flush=True)
            stop = bool(a.max_minutes) and time.time() - t0 > 60 * a.max_minutes
            if step % a.eval_every == 0 or step == a.steps or stop:
                v = validate()
                better = v < best
                print("step %d  val loss %.4f%s" % (step, v, "  (best, saved)" if better or a.save_final else ""), flush=True)
                if better or a.save_final:
                    best = min(best, v)
                    t3.tfmr.save_pretrained(out)
                    saved = True
            if step < a.steps and not stop and (step % a.eval_every == 0 or time.time() - last_save > 60 * a.save_every_min):
                save_resume(bi)
                last_save = time.time()
            if step >= a.steps or stop:
                break
        skip = 0
        if not stop and step < a.steps:
            epoch += 1
    if step > start:
        record_speed(a.work, "t3_steps_per_s", round((step - start) / max(1e-6, time.time() - t0 - tval[0]), 5), dev)
    if not saved:                                       # validation never improved: keep the last weights
        t3.tfmr.save_pretrained(out)
    if os.path.exists(resume):
        os.remove(resume)
    open(done, "w").write("%d steps" % step)
    print("done", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-frames", type=int, default=1600, help="speech tokens per batch (25/s)")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--out", default=None, help="LoRA folder (default <work>/models/t3_lora)")
    ap.add_argument("--log-every", type=int, default=50)
    ap.add_argument("--save-every-min", type=float, default=15, help="resume checkpoint interval")
    ap.add_argument("--max-minutes", type=float, default=0, help="stop early after this long (preview)")
    ap.add_argument("--save-final", action="store_true", help="save the last weights even if not the best (preview)")
    main(ap.parse_args())
