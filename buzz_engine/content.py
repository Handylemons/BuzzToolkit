"""Question model, clean-up and validation, and conversion to the pack builder's JSON.

A question (dict):
  kind        "standard" (4 answers, one right) | "picture" (standard + image) |
              "all_that_apply" (4 answers, any number right) | "point_stealer" (4 pictures)
  question    text shown (and read by the host)
  correct     right answer (standard/picture)       answers + right[] for all_that_apply
  wrong       3 wrong answers                        images[4] + correct index for point_stealer
  category, difficulty ("easy"|"medium"|"hard"), image (path/URL), source (where it came from)
"""
import hashlib
import html
import os
import re
import shutil
import unicodedata

MAX_Q, MAX_A = 93, 30          # longest question / answer the pack builder accepts (retail layout)
DIFFICULTY = {"easy": 1, "medium": 2, "hard": 3, "1": 1, "2": 2, "3": 3}
CATEGORIES = ["Knowledge", "TVCinema", "Lifestyle", "Music"]     # menu channels a pack sits in

_PUNCT = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'",
          "“": '"', "”": '"', "„": '"', "″": '"', "–": "-", "—": "-",
          "−": "-", "…": "...", " ": " ", " ": " ", "​": ""}


def clean(s, uppercase=False):
    """HTML entities, typographic punctuation and exotic characters -> what the game's font has
    (Latin-1). Accented Latin letters are kept; anything else is transliterated or dropped."""
    s = html.unescape(str(s or ""))
    s = "".join(_PUNCT.get(c, c) for c in s)
    out = []
    for c in s:
        if ord(c) < 256:
            out.append(c)
        else:
            d = unicodedata.normalize("NFKD", c)
            out.append("".join(x for x in d if ord(x) < 128))
    s = re.sub(r"\s+", " ", "".join(out)).strip()
    return s.upper() if uppercase else s


def key(q):
    """Duplicate detection key (question text, case/punctuation-insensitive)."""
    return re.sub(r"[^a-z0-9]", "", q["question"].lower())


def normalise(q, uppercase=False):
    q = dict(q)
    q.setdefault("kind", "picture" if q.get("image") else "standard")
    q["question"] = clean(q.get("question"), uppercase)
    if q["kind"] in ("standard", "picture"):
        q["correct"] = clean(q.get("correct"), uppercase)
        q["wrong"] = [clean(w, uppercase) for w in q.get("wrong", [])]
    elif q["kind"] == "all_that_apply":
        q["answers"] = [clean(a, uppercase) for a in q.get("answers", [])]
    if q.get("difficulty") is not None:
        q["difficulty"] = {1: "easy", 2: "medium", 3: "hard"}.get(DIFFICULTY.get(str(q["difficulty"]).lower()), None)
    return q


def problems(q):
    """-> list of reasons this question can't go in a pack (empty = OK)."""
    p = []
    if not q["question"]:
        p.append("empty question")
    if len(q["question"]) > MAX_Q:
        p.append("question longer than %d characters" % MAX_Q)
    if q["kind"] in ("standard", "picture"):
        ans = [q["correct"]] + q["wrong"]
        if len(q["wrong"]) < 3:
            p.append("needs 3 wrong answers (has %d)" % len(q["wrong"]))
        if any(not a for a in ans):
            p.append("empty answer")
        if any(len(a) > MAX_A for a in ans):
            p.append("answer longer than %d characters" % MAX_A)
        if len({a.lower() for a in ans[:4]}) < min(4, len(ans)):
            p.append("duplicate answers")
        if q["kind"] == "picture" and not q.get("image"):
            p.append("picture question without an image")
    elif q["kind"] == "all_that_apply":
        if len(q.get("answers", [])) != 4 or len(q.get("right", [])) != 4:
            p.append("all-that-apply needs 4 answers with right/wrong flags")
        elif any(len(a) > MAX_A for a in q["answers"]):
            p.append("answer longer than %d characters" % MAX_A)
    elif q["kind"] == "point_stealer":
        if len(q.get("images", [])) != 4:
            p.append("point stealer needs 4 pictures")
    return p


def select(questions, uppercase=False, limit=None, difficulty=None, categories=None):
    """Normalise, drop invalid and duplicate questions -> (kept, rejected[(question, reasons)])."""
    kept, rejected, seen = [], [], set()
    for q in questions:
        q = normalise(q, uppercase)
        if difficulty and q.get("difficulty") and q["difficulty"] not in difficulty:
            continue
        if categories and q.get("category") and not any(c.lower() in q["category"].lower() for c in categories):
            continue
        why = problems(q)
        k = key(q)
        if not why and k in seen:
            why = ["duplicate question"]
        if why:
            rejected.append((q, why))
            continue
        seen.add(k)
        kept.append(q)
        if limit and len(kept) >= limit:
            break
    return kept, rejected


def slug(s, n):
    return (re.sub(r"[^a-z0-9]", "", s.lower()) or "custom")[:n]


def new_pack(title, pack_number, category="Knowledge", description=None, uppercase=True):
    """Metadata for a new pack JSON (content lists empty)."""
    if category not in CATEGORIES:
        raise ValueError("category must be one of %s" % ", ".join(CATEGORIES))
    t = clean(title, True)
    name = slug(title, 10) + str(pack_number)
    return {
        "pack_number": int(pack_number),
        "text": {"subject": t, "description": clean(description or ("QUESTIONS ON " + t), True),
                 "menu_name": t},
        "topic": t,
        "subject_key": "SUBJECT_" + re.sub(r"[^A-Z0-9]+", "_", t).strip("_")[:40],
        "round_name": name,
        "key_tag": str(pack_number),
        "category": category,
        "content_suffix": (slug(title, 5).upper() + "XXXXX")[:5],
        "uppercase": uppercase,
        "images": [], "standard": [], "picture": [], "all_that_apply": [], "point_stealer": [],
    }


def _image_file(src, images_dir, cache_dir=None):
    """Copy/download an image into the pack's images folder as PNG -> file stem."""
    from PIL import Image
    os.makedirs(images_dir, exist_ok=True)
    stem = "img_" + hashlib.sha1(str(src).encode()).hexdigest()[:10]
    dst = os.path.join(images_dir, stem + ".png")
    if not os.path.exists(dst):
        if re.match(r"https?://", str(src)):
            import urllib.request
            tmp = dst + ".download"
            req = urllib.request.Request(src, headers={"User-Agent": "BuzzPackEngine/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            Image.open(tmp).convert("RGB").save(dst)
            os.remove(tmp)
        else:
            Image.open(src).convert("RGB").save(dst)
    return stem


def add_to_pack(pack, questions, pack_dir):
    """Append normalised questions to a pack JSON dict (pictures copied into pack_dir/images)."""
    img_dir = os.path.join(pack_dir, "images")

    def image_no(src):
        stem = _image_file(src, img_dir)
        pack.setdefault("image_sources", {})[stem] = str(src)
        if stem not in pack["images"]:
            pack["images"].append(stem)
        return pack["images"].index(stem) + 1

    from .importers import credit
    credits = pack.setdefault("credits", [])
    for q in questions:
        c = credit(q.get("source", ""))
        if c and c not in credits:
            credits.append(c)
        k = q["kind"]
        if k == "standard":
            pack["standard"].append([q["question"], q["correct"]] + q["wrong"][:3])
        elif k == "picture":
            pack["picture"].append([image_no(q["image"]), q["question"], q["correct"]] + q["wrong"][:3])
        elif k == "all_that_apply":
            pack["all_that_apply"].append([q["question"]] + [[a, bool(r)] for a, r in zip(q["answers"], q["right"])])
        elif k == "point_stealer":
            nums = [image_no(i) for i in q["images"]]
            c = q.get("correct", 0)
            pack["point_stealer"].append([q["question"], nums[c]] + [n for i, n in enumerate(nums) if i != c])
    return pack


def report(pack):
    """Human summary: how many questions feed each round type."""
    from .rounds import selectable
    counts = {"standard": len(pack["standard"]), "picture": len(pack["picture"]),
              "all_that_apply": len(pack["all_that_apply"]), "point_stealer": len(pack["point_stealer"])}
    lines = ["questions: %s" % ", ".join("%s %d" % kv for kv in counts.items())]
    for t, info in selectable().items():
        n = sum(counts[k] for k in info["uses"])
        state = "OK" if n >= info["min"] else ("repeats questions" if n else "NO QUESTIONS")
        lines.append("  %-16s %4d  %s" % (info["name"], n, state))
    return "\n".join(lines)
