"""Question importers: turn almost any quiz data into engine questions (see content.py).

    load(source) -> list of question dicts

source can be a file path, an http(s) URL, or an online source spec:
  opentdb:amount=50&category=9&difficulty=easy      Open Trivia DB API (CC BY-SA 4.0)
  opentriviaqa:movies                                 OpenTriviaQA category file (CC BY-SA 4.0)
  triviaapi:limit=50&categories=history              The Trivia API (CC BY-NC 4.0: non-commercial)
Files are recognised by extension and content:
  .csv/.tsv   header row; columns found by name: question, correct/answer, wrong1..3 /
              incorrect_answers ("|"-separated), category, difficulty, image, type
  .txt        Aiken (A./B./C./D. + "ANSWER: B"), OpenTriviaQA ("#Q", "^ answer", "A ..."),
              "Q:/A:/-" blocks (a .buzz.txt may start with #TITLE:/#CATEGORY:/... headers,
              see header()), or pipe lines
              "question | correct | wrong | wrong | wrong"
  .xml        Buzz online quiz XML (<root><round><question>, correct="true" answers),
              Moodle XML (<quiz><question type="multichoice">), or any XML whose question
              elements hold a question text and answer/option children (correct marked by an
              attribute or a separate <correct>/<answer> element)
  .json       OpenTDB / Trivia API responses, our pack JSON, or a list of objects with
              question / correct / incorrect keys
"""
import base64
import csv
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "BuzzPackEngine/1.0 (custom quiz packs for Buzz! Quiz World)"}

# attribution for the pack credits page, by question "source" prefix
LICENCES = {
    "opentdb": "Open Trivia Database (opentdb.com) - CC BY-SA 4.0",
    "opentriviaqa": "OpenTriviaQA (github.com/uberspot/OpenTriviaQA) - CC BY-SA 4.0",
    "triviaapi": "The Trivia API (the-trivia-api.com) - CC BY-NC 4.0, non-commercial use only",
}


def credit(source):
    return LICENCES.get(str(source).split(":")[0])


# ------------------------------------------------------------------------------ online sources
def _get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def opentdb(amount=50, category=None, difficulty=None, token=True):
    """Open Trivia DB (opentdb.com): multiple-choice questions, max 50 per call, one call per
    5 seconds; a session token avoids repeats across calls. Licence CC BY-SA 4.0."""
    out, tok = [], None
    if token:
        tok = _get_json("https://opentdb.com/api_token.php?command=request").get("token")
    left = int(amount)
    while left > 0:
        q = {"amount": min(50, left), "type": "multiple", "encode": "base64"}
        if category:
            q["category"] = category
        if difficulty:
            q["difficulty"] = difficulty
        if tok:
            q["token"] = tok
        data = _get_json("https://opentdb.com/api.php?" + urllib.parse.urlencode(q))
        if data.get("response_code") != 0:            # 1 = not enough questions, 4 = token exhausted
            break
        out += parse_opentdb(data, b64=True)
        left -= len(data["results"])
        if left > 0:
            time.sleep(5.2)
    return out


OPENTRIVIAQA = "https://raw.githubusercontent.com/uberspot/OpenTriviaQA/master/categories/"


def opentriviaqa(category):
    """One OpenTriviaQA category file (animals, general, geography, history, movies, music,
    science-technology, sports, television, world, ...)."""
    req = urllib.request.Request(OPENTRIVIAQA + urllib.parse.quote(category), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    return [dict(q, category=category) for q in parse_opentriviaqa(text)]


def parse_opentriviaqa(text):
    out, cur = [], None
    for l in text.splitlines():
        s = l.strip()
        if s.startswith("#Q "):
            if cur:
                out.append(cur)
            cur = {"question": s[3:], "correct": None, "options": [], "source": "opentriviaqa"}
        elif cur is not None and s.startswith("^ "):
            cur["correct"] = s[2:].strip()
        elif cur is not None and re.match(r"^[A-F] ", s):
            cur["options"].append(s[2:].strip())
        elif cur is not None and s and not cur["options"]:
            cur["question"] += " " + s                        # wrapped question text
    if cur:
        out.append(cur)
    res = []
    for q in out:
        if q["correct"] and len(q["options"]) >= 4 and q["correct"] in q["options"]:
            res.append({"question": q["question"], "correct": q["correct"], "category": q.get("category"),
                        "wrong": [o for o in q["options"] if o != q["correct"]][:3], "source": q["source"]})
    return res


def header(text):
    """.buzz.txt pack header lines (UltraStar-style), e.g.
        #TITLE:Movie Night   #CATEGORY:TVCinema   #PACK:97   #AUTHOR:name   #DESCRIPTION:...
        #ROUNDS4P:Point Builder, random(Over the Edge|Pie Fight), Point Stealer   #ROUNDS8P:...
        #VOICE:clone:voice_models/buzz_host/reference.wav   #LICENSE:CC BY-SA 4.0
    -> dict of lower-case keys."""
    meta = {}
    for l in text.splitlines():
        m = re.match(r"^#([A-Z0-9]+):(.*)$", l.strip())
        if m and m.group(1) != "Q":
            meta[m.group(1).lower()] = m.group(2).strip()
    return meta


def opentdb_categories():
    return {c["id"]: c["name"] for c in _get_json("https://opentdb.com/api_category.php")["trivia_categories"]}


def triviaapi(limit=50, categories=None, difficulties=None, tags=None, region="GB"):
    """The Trivia API v2 (the-trivia-api.com): max 50 per call."""
    out, left = [], int(limit)
    while left > 0:
        q = {"limit": min(50, left), "region": region}
        for k, v in (("categories", categories), ("difficulties", difficulties), ("tags", tags)):
            if v:
                q[k] = v
        data = _get_json("https://the-trivia-api.com/v2/questions?" + urllib.parse.urlencode(q))
        if not data:
            break
        out += parse_triviaapi(data)
        left -= len(data)
    return out


# ------------------------------------------------------------------------------ JSON
def parse_opentdb(data, b64=False):
    dec = (lambda s: base64.b64decode(s).decode("utf-8")) if b64 else (lambda s: s)
    out = []
    for r in data.get("results", []):
        if dec(r["type"]) != "multiple":
            continue
        out.append({"question": dec(r["question"]), "correct": dec(r["correct_answer"]),
                    "wrong": [dec(x) for x in r["incorrect_answers"]], "category": dec(r["category"]),
                    "difficulty": dec(r["difficulty"]), "source": "opentdb"})
    return out


def parse_triviaapi(data):
    out = []
    for r in data:
        text = r["question"]["text"] if isinstance(r.get("question"), dict) else r.get("question")
        if len(r.get("incorrectAnswers", [])) < 3:
            continue
        out.append({"question": text, "correct": r["correctAnswer"], "wrong": r["incorrectAnswers"][:3],
                    "category": r.get("category"), "difficulty": r.get("difficulty"),
                    "source": "triviaapi:%s" % r.get("id", "")})
    return out


def parse_json(data):
    if isinstance(data, dict) and "results" in data:
        return parse_opentdb(data)
    if isinstance(data, dict) and "standard" in data:                 # our pack JSON
        out = [{"question": x[0], "correct": x[1], "wrong": x[2:5], "source": "pack"} for x in data["standard"]]
        img = data.get("images", [])
        base = data.get("_dir", ".")
        out += [{"kind": "picture", "image": os.path.join(base, "images", img[x[0] - 1] + ".png"),
                 "question": x[1], "correct": x[2], "wrong": x[3:6], "source": "pack"} for x in data.get("picture", [])]
        out += [{"kind": "all_that_apply", "question": x[0], "answers": [a for a, _ in x[1:5]],
                 "right": [bool(t) for _, t in x[1:5]], "source": "pack"} for x in data.get("all_that_apply", [])]
        return out
    items = data if isinstance(data, list) else data.get("questions", data.get("items", []))
    if items and isinstance(items[0], dict) and "correctAnswer" in items[0]:
        return parse_triviaapi(items)
    return [q for q in (_from_record(r) for r in items) if q]


# ------------------------------------------------------------------------------ records (CSV / JSON objects)
_Q = ["question", "q", "text", "prompt", "question_text", "clue"]
_C = ["correct", "correct_answer", "answer", "right", "a", "correctanswer", "solution"]
_W = ["incorrect_answers", "incorrect", "wrong", "wrong_answers", "incorrectanswers", "distractors", "options_wrong"]


def _pick(r, names):
    low = {str(k).strip().lower().replace(" ", "_"): v for k, v in r.items()}
    for n in names:
        if n in low and low[n] not in (None, ""):
            return low[n]
    return None


def _from_record(r):
    q = _pick(r, _Q)
    if not q:
        return None
    c = _pick(r, _C)
    wrong = _pick(r, _W)
    if isinstance(wrong, str):
        wrong = [w.strip() for w in re.split(r"\s*\|\s*|\s*;\s*", wrong) if w.strip()]
    if not wrong:
        low = {str(k).strip().lower().replace(" ", "_"): v for k, v in r.items()}
        wrong = [low[k] for k in sorted(low) if re.fullmatch(r"(wrong|incorrect|option|distractor|false)_?\d", k) and low[k]]
    options = _pick(r, ["options", "choices", "answers"])
    if not wrong and options:
        opts = options if isinstance(options, list) else [o.strip() for o in re.split(r"\s*\|\s*", options)]
        if c is not None and str(c).strip().upper() in "ABCD" and len(str(c).strip()) == 1:
            c = opts["ABCD".index(str(c).strip().upper())]
        wrong = [o for o in opts if o != c]
    out = {"question": q, "correct": c, "wrong": list(wrong or [])[:3], "source": "record"}
    for k, names in (("category", ["category", "topic", "subject"]), ("difficulty", ["difficulty", "level"]),
                     ("image", ["image", "picture", "img", "image_url", "photo"])):
        v = _pick(r, names)
        if v:
            out[k] = v
    t = str(_pick(r, ["type", "kind"]) or "").lower()
    if out.get("image") or t == "picture":
        out["kind"] = "picture"
    return out


def parse_csv(text):
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    return [q for q in (_from_record(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect)) if q]


# ------------------------------------------------------------------------------ text
def parse_text(text):
    if re.search(r"^#Q ", text, re.M):
        return parse_opentriviaqa(text)
    lines = [l.rstrip() for l in text.splitlines() if not re.match(r"^#[A-Z0-9]+:", l.strip())]
    text = "\n".join(lines)
    out = []
    # Aiken: question line, "A. / A)" options, "ANSWER: X"
    if re.search(r"^ANSWER:\s*[A-Z]\s*$", text, re.M):
        block = []
        for l in lines + [""]:
            if not l.strip():
                continue
            m = re.match(r"^ANSWER:\s*([A-Z])\s*$", l.strip())
            if m and block:
                opts = [re.sub(r"^[A-Z][.)]\s*", "", b) for b in block[1:]]
                i = ord(m.group(1)) - 65
                if 0 <= i < len(opts):
                    out.append({"question": block[0], "correct": opts[i],
                                "wrong": [o for j, o in enumerate(opts) if j != i][:3], "source": "aiken"})
                block = []
            else:
                block.append(l.strip())
        return out
    # Q:/A:/- blocks
    if re.search(r"^Q[:.]\s", text, re.M | re.I):
        cur = None
        for l in lines:
            s = l.strip()
            if re.match(r"^Q[:.]\s", s, re.I):
                if cur:
                    out.append(cur)
                cur = {"question": s[2:].strip(), "correct": None, "wrong": [], "source": "text"}
            elif cur and re.match(r"^A[:.]\s", s, re.I):
                cur["correct"] = s[2:].strip()
            elif cur and re.match(r"^[-*]\s", s):
                cur["wrong"].append(s[2:].strip())
            elif cur and re.match(r"^(IMG|IMAGE|PIC)[:.]\s", s, re.I):
                cur["image"], cur["kind"] = s.split(":", 1)[1].strip(), "picture"
        if cur:
            out.append(cur)
        return out
    # pipe lines
    for l in lines:
        parts = [p.strip() for p in l.split("|")]
        if len(parts) >= 5 and parts[0]:
            out.append({"question": parts[0], "correct": parts[1], "wrong": parts[2:5], "source": "text"})
    return out


# ------------------------------------------------------------------------------ XML
def _txt(e):
    return "".join(e.itertext()).strip() if e is not None else ""


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "y", "correct", "right", "100")


def parse_xml(text):
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    tag = lambda e: e.tag.split("}")[-1].lower()
    out = []
    if tag(root) == "quiz" and root.find("question") is not None and root.find("question").get("type"):
        for q in root.iter("question"):                       # Moodle XML
            if q.get("type") != "multichoice":
                continue
            answers = q.findall("answer")
            right = [_txt(a.find("text")) for a in answers if float(a.get("fraction", "0")) > 0]
            wrong = [_txt(a.find("text")) for a in answers if float(a.get("fraction", "0")) <= 0]
            text_ = re.sub(r"<[^>]+>", "", _txt(q.find("questiontext/text")))
            if len(right) == 1:
                out.append({"question": text_, "correct": right[0], "wrong": wrong[:3], "source": "moodle"})
            elif len(right) > 1 and len(answers) == 4:
                out.append({"kind": "all_that_apply", "question": text_,
                            "answers": [_txt(a.find("text")) for a in answers],
                            "right": [float(a.get("fraction", "0")) > 0 for a in answers], "source": "moodle"})
        return out
    # generic: any element with answer-ish children
    qnames = ("question", "item", "q", "entry", "record", "trivia")
    for q in root.iter():
        if tag(q) not in qnames:
            continue
        kids = list(q)
        text_el = next((k for k in kids if tag(k) in ("text", "questiontext", "question", "q", "prompt", "title")), None)
        text_ = _txt(text_el) if text_el is not None else (q.get("text") or q.get("question") or "")
        if not text_:
            continue
        opts = [k for k in kids if tag(k) in ("answer", "option", "choice", "incorrect", "wrong", "correct")]
        right = [o for o in opts if tag(o) == "correct" or _truthy(o.get("correct", o.get("right", o.get("iscorrect", "0"))))]
        wrong = [o for o in opts if o not in right and tag(o) != "correct"]
        img = q.find("image")
        rec = {"question": text_, "source": "xml"}
        if len(right) == 1:
            rec.update(correct=_txt(right[0]), wrong=[_txt(w) for w in wrong][:3])
        elif len(right) > 1 and len(opts) == 4:
            rec.update(kind="all_that_apply", answers=[_txt(o) for o in opts], right=[o in right for o in opts])
        else:
            continue
        if img is not None and (_txt(img) or img.get("src")):
            rec.update(kind="picture", image=img.get("src") or _txt(img))
        for k in ("category", "difficulty"):
            if q.get(k) or q.find(k) is not None:
                rec[k] = q.get(k) or _txt(q.find(k))
        out.append(rec)
    return out


# ------------------------------------------------------------------------------ dispatcher
def load(source):
    s = str(source)
    if s.startswith("opentdb:"):
        p = dict(urllib.parse.parse_qsl(s[8:]))
        return opentdb(int(p.get("amount", 50)), p.get("category"), p.get("difficulty"))
    if s.startswith("opentriviaqa:"):
        return opentriviaqa(s[13:])
    if s.startswith("triviaapi:"):
        p = dict(urllib.parse.parse_qsl(s[10:]))
        return triviaapi(int(p.get("limit", 50)), p.get("categories"), p.get("difficulties"), p.get("tags"))
    if re.match(r"https?://", s):
        req = urllib.request.Request(s, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
        ext = os.path.splitext(urllib.parse.urlparse(s).path)[1].lower()
    else:
        with open(s, encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
        ext = os.path.splitext(s)[1].lower()
    head = raw.lstrip()[:1]
    if ext == ".json" or head in "[{":
        data = json.loads(raw)
        if isinstance(data, dict) and "standard" in data and not re.match(r"https?://", s):
            data["_dir"] = os.path.dirname(os.path.abspath(s))
        return parse_json(data)
    if ext == ".xml" or head == "<":
        return parse_xml(raw)
    if ext in (".csv", ".tsv"):
        return parse_csv(raw)
    return parse_text(raw)
