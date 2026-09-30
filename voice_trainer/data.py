"""Shared dataset helpers for the host-voice trainer (features written by features.py)."""
import glob
import json
import os
import random

import torch


def load_items(work, need_text=False, min_dur=0.8, max_dur=12.0):
    """-> (train, val) lists of feature dicts: speaker-filtered, length-filtered, with a fixed
    held-out validation set (every 60th clip by id)."""
    spk = json.load(open(os.path.join(work, "speakers.json")))
    floor, sims = spk["floor"], spk["sim"]
    items = []
    for f in sorted(glob.glob(os.path.join(work, "features", "shard_*.pt"))):
        for it in torch.load(f):
            if sims.get(it["id"], 0) < floor or not (min_dur <= it["dur"] <= max_dur):
                continue
            if need_text and "text" not in it:
                continue
            items.append(it)
    items.sort(key=lambda it: it["id"])
    val = items[::60]
    vid = {it["id"] for it in val}
    return [it for it in items if it["id"] not in vid], val


def batches(items, max_frames, shuffle=True, seed=0):
    """Length-bucketed batches with at most max_frames speech tokens per batch."""
    rng = random.Random(seed)
    order = sorted(items, key=lambda it: len(it["tokens"]))
    out, cur, longest = [], [], 0
    for it in order:
        n = len(it["tokens"])
        if cur and max(longest, n) * (len(cur) + 1) > max_frames:
            out.append(cur)
            cur, longest = [], 0
        cur.append(it)
        longest = max(longest, n)
    if cur:
        out.append(cur)
    if shuffle:
        rng.shuffle(out)
    return out


def held_out_texts(work, n=12):
    """Question texts of validation clips (for listening tests / evaluation)."""
    _, val = load_items(work, need_text=True)
    return [(it["id"], it["raw_text"]) for it in val[:n]]
