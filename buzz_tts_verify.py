"""Check generated host lines with speech recognition (openai-whisper, runs in tools/clone_venv).

    tools/clone_venv/Scripts/python.exe buzz_tts_verify.py jobs.json [--model small.en]

jobs.json: [{"text": "...", "wav": "clip.wav", "vocab": optional spelling hints}, ...]. The
intended sentence itself is NOT given to the recogniser (it would "hear" it regardless). Prints
one JSON line per job with the transcript and a word error rate against the intended text, so
buzz_voice can regenerate a take that skipped, repeated or invented words (cloning TTS
occasionally does). Numbers are compared as words ("4" == "four").
"""
import argparse
import json
import re

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + _num(n % 100))
    if 1100 <= n < 2100 and n % 100 != 0 and not (2000 <= n < 2010):     # years: nineteen ninety
        return _num(n // 100) + " " + (_num(n % 100) if n % 100 >= 10 else "oh " + _num(n % 100))
    if n < 1000000:
        return _num(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + _num(n % 1000))
    return str(n)


# Whisper writes American spellings and mishears a few homophones in a British accent; these are
# not errors in the generated speech (seen on the Harry Potter pack: colours/colors, which/witch).
_SAME = {"colour": "color", "colours": "colors", "coloured": "colored", "favourite": "favorite",
         "favourites": "favorites", "honour": "honor", "neighbour": "neighbor", "grey": "gray",
         "centre": "center", "theatre": "theater", "metre": "meter", "defence": "defense",
         "organisation": "organization", "realise": "realize", "witch": "which", "whose": "who's"}


def words(s):
    s = s.lower().replace("-", " ")
    s = re.sub(r"\d+", lambda m: " " + _num(int(m.group())) + " ", s)
    return [_SAME.get(w, w) for w in re.findall(r"[a-z\u00c0-\u024f']+", s)]


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


if __name__ == "__main__":
    import librosa
    import whisper
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("--model", default=None)
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    model = whisper.load_model(a.model or ("small.en" if a.lang == "en" else "small"))
    for job in json.load(open(a.jobs, encoding="utf-8")):
        audio = librosa.load(job["wav"], sr=16000, mono=True)[0]      # whisper's loader needs ffmpeg on PATH
        hyp = model.transcribe(audio, language=a.lang, fp16=False, temperature=0.0,
                               initial_prompt=job.get("vocab"))["text"].strip()
        print(json.dumps({"wav": job["wav"], "text": job["text"], "heard": hyp, "wer": round(wer(job["text"], hyp), 3)}),
              flush=True)
