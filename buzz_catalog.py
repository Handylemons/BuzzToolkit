"""Quiz catalogue + SVML renderers for the Buzz! Quiz World fake server.

Every format here was reversed from EBOOT_patched.elf (see MYBUZZ_SVML_MAP.md):

* Data lists are flat <MYBUZZ_V1 type="..."> siblings under <SVML>. Each type is parsed by
  its own handler and appended to its OWN container on the MyBuzz manager, so one response
  may safely mix types:
      QUIZITEM2009  name* quizid(int)* filename* + description author playcount(int)
                    agecat(int) rating(float) userrating(float) difficulty(int)
      TAG2009       name*                                  (tag list entry, M+0x20)
      PLAYLIST2009  name* description* playlistid(int)*    (M+0x28)
      CATEGORY2009  name* categoryId(str)*                 (M+0x44)
      BUDDY2009     name* accountId(int)*                  (M+0x2c)
* Landing page is flat <LANDING type="..."> siblings (all attrs required):
      NEWS name | STATS sofa single quizcount (ints) | POPULARQUIZ / RECENTQUIZ name
      timesplayed(int) rating(float) | WORLDQUIZ name author
* Quiz content must be a BARE document whose top element is <root>, with
  <round version="1.0" type="standard">, 4 <answer>s per question, and correctness carried
  by the correct="true" ATTRIBUTE on <answer> (the <answercorrect> child is ignored).

Quiz packs live in content/packs/*.json:
    {"pack": "Harry Potter", "category": "Film & TV", "author": "Buzz",
     "tags": ["harry potter"],
     "quizzes": [{"name": "...", "description": "...", "tags": [...],
                  "questions": [{"question": {"text": "..."}, "correctAnswer": "...",
                                 "incorrectAnswers": ["..", "..", ".."],
                                 "difficulty": "easy|medium|hard"}, ...]}]}
"""
import datetime
import glob
import html
import json
import os
import random
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PACK_DIR = os.environ.get("BUZZ_PACK_DIR", os.path.join(HERE, "content", "packs"))
DATA_DIR = os.environ.get("BUZZ_DATA_DIR", os.path.join(HERE, "server_data"))
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
COMMUNITY_FILE = os.environ.get("BUZZ_COMMUNITY", os.path.join(HERE, "content", "community.json"))
# Online high-score boards (menubranch_home.lua): names must contain STC or OTE and match
# these keys, which the script maps to the subtitles AllTime / ThisWeek / Friends.
LB_GAMES = ("STC", "OTE")          # Stop The Clock, Over The Edge
LB_KINDS = ("topN_AllTime", "topN_Weekly", "buddy_AllTime")
LB_SIZE = 10

AGECAT = 7            # the game sends agecat=7 on every MyBuzz request
MIN_LIST = 16         # NUM_REQUIRED_FOR_UCQ_GAME (quizsupportcode_ucq.lua)
DIFF_NAME = {"easy": "EASY", "medium": "MEDIUM", "hard": "HARD"}
DIFF_NUM = {"easy": 1, "medium": 2, "hard": 3}


def esc(s):
    return html.escape(str(s), quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "misc"


def _xml(lines):
    return "\r\n".join(lines) + "\r\n"


class Catalog:
    def __init__(self, pack_dir=PACK_DIR):
        self.pack_dir = pack_dir
        self._lock = threading.Lock()
        self.reload()
        self.stats = self._load_stats()

    # ------------------------------------------------------------------ loading
    def reload(self):
        quizzes, packs = [], []
        for path in sorted(glob.glob(os.path.join(self.pack_dir, "*.json"))):
            try:
                pack = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError) as e:
                print("[catalog] skipping %s: %s" % (path, e))
                continue
            if pack.get("enabled", True) is False:      # toggleable packs
                continue
            pid = len(packs) + 1
            pname = pack.get("pack") or os.path.splitext(os.path.basename(path))[0]
            parent = pack.get("category", "General")
            packs.append({"id": pid, "name": pname, "category": parent,
                          "description": pack.get("description", pname)})
            for q in pack.get("quizzes", []):
                qs = [x for x in q.get("questions", []) if self._valid_question(x)]
                if not qs:
                    continue
                diffs = [DIFF_NUM.get(x.get("difficulty", "medium"), 2) for x in qs]
                quizzes.append({
                    "id": len(quizzes) + 1,
                    "name": q["name"],
                    "description": q.get("description", q["name"]),
                    "author": q.get("author", pack.get("author", "Buzz")),
                    "pack": pid,
                    "parent": parent,
                    "category": q.get("category", pname),
                    "tags": sorted(set(q.get("tags", []) + pack.get("tags", []))),
                    "difficulty": max(1, min(3, round(sum(diffs) / len(diffs)))),
                    "questions": qs,
                })
        self.quizzes, self.packs = quizzes, packs
        self.by_id = {q["id"]: q for q in quizzes}
        try:
            self.community = json.load(open(COMMUNITY_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            self.community = {}
        self.community.setdefault("buddies", [])
        self.community.setdefault("players", [])
        # credit each quiz to the simulated buddy who "made" it, so authors look real
        owner = {n.lower(): b["name"] for b in self.community["buddies"] for n in b.get("quizzes", [])}
        for q in self.quizzes:
            q["author"] = owner.get(q["name"].lower(), q["author"])

    @staticmethod
    def _valid_question(x):
        try:
            return (x["question"]["text"].strip() and x["correctAnswer"]
                    and len(x["incorrectAnswers"]) >= 3)
        except (KeyError, TypeError, AttributeError):
            return False

    # ------------------------------------------------------------------ stats
    def _load_stats(self):
        try:
            return json.load(open(STATS_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            return {"quizzes": {}, "totals": {"plays": 0, "ratings": 0}}

    def _save_stats(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=1)
        os.replace(tmp, STATS_FILE)

    def _qstat(self, qid):
        return self.stats["quizzes"].setdefault(str(qid), {"plays": 0, "ratings": [],
                                                           "last_played": 0})

    def record_play(self, qid):
        with self._lock:
            s = self._qstat(qid)
            s["plays"] += 1
            s["last_played"] = int(time.time())
            self.stats["totals"]["plays"] += 1
            self._save_stats()

    def record_rating(self, qid, rating, correct=None):
        with self._lock:
            s = self._qstat(qid)
            s["ratings"].append(float(rating))
            if correct is not None:
                s.setdefault("correct", []).append(float(correct))
            self.stats["totals"]["ratings"] += 1
            self._save_stats()

    def plays(self, qid):
        return self.stats["quizzes"].get(str(qid), {}).get("plays", 0)

    def rating(self, qid):
        r = self.stats["quizzes"].get(str(qid), {}).get("ratings", [])
        return round(sum(r) / len(r), 2) if r else 0.0

    # ------------------------------------------------------------------ lookups
    def resolve(self, qid):
        """Quiz for an id. Padded list entries use id + k*1000, so map those back."""
        if not self.quizzes:
            return None
        try:
            qid = int(qid)
        except (TypeError, ValueError):
            return self.quizzes[0]
        return self.by_id.get(qid) or self.by_id.get((qid - 1) % 1000 % len(self.quizzes) + 1)

    def categories(self, parent=None):
        """Top level = pack 'category'; children = the pack names under that parent."""
        if parent is None:
            names = sorted({q["parent"] for q in self.quizzes})
            return [(slug(n), n) for n in names]
        names = sorted({q["category"] for q in self.quizzes if slug(q["parent"]) == parent})
        return [(slug(parent) + "." + slug(n), n) for n in names]

    def quizzes_in_category(self, cat_id):
        if "." in cat_id:
            p, c = cat_id.split(".", 1)
            return [q for q in self.quizzes if slug(q["parent"]) == p and slug(q["category"]) == c]
        return [q for q in self.quizzes if slug(q["parent"]) == cat_id]

    def tags(self):
        return sorted({t for q in self.quizzes for t in q["tags"]})

    def quizzes_with_tag(self, tag):
        t = tag.lower()
        return [q for q in self.quizzes if t in (x.lower() for x in q["tags"])]

    def quizzes_in_playlist(self, pid):
        return [q for q in self.quizzes if q["pack"] == int(pid)]

    def popular(self, n=5):
        return sorted(self.quizzes, key=lambda q: (-self.plays(q["id"]), q["id"]))[:n]

    def recent(self, n=5):
        last = lambda q: self.stats["quizzes"].get(str(q["id"]), {}).get("last_played", 0)
        played = [q for q in self.quizzes if last(q)]
        return (sorted(played, key=last, reverse=True) + self.quizzes[::-1])[:n]

    # ------------------------------------------------------------------ renderers
    def _quiz_item(self, q, list_id=None):
        return ('  <MYBUZZ_V1 type="QUIZITEM2009" name="%s" quizid="%d" filename="%d" '
                'description="%s" author="%s" playcount="%d" agecat="%d" rating="%.1f" '
                'userrating="0.0" difficulty="%d" />'
                % (esc(q["name"]), list_id or q["id"], list_id or q["id"], esc(q["description"]),
                   esc(q["author"]), self.plays(q["id"]), AGECAT, self.rating(q["id"]) or 5.0,
                   q["difficulty"]))

    def quiz_list(self, quizzes, title="Quizzes", pad=False):
        """QUIZITEM2009 list. pad=True repeats entries (ids +1000*k, resolved back by
        resolve()) so channel games still reach NUM_REQUIRED_FOR_UCQ_GAME = 16."""
        items = [(q, q["id"]) for q in quizzes]
        k = 1
        while pad and items and len(items) < MIN_LIST:
            items += [(q, q["id"] + 1000 * k) for q in quizzes][:MIN_LIST - len(items)]
            k += 1
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>',
             '  <MYBUZZ_V1 type="TAG2009" name="%s" />' % esc(title)]
        L += [self._quiz_item(q, lid) for q, lid in items]
        L.append('</SVML>')
        return _xml(L)

    def tag_list(self):
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        L += ['  <MYBUZZ_V1 type="TAG2009" name="%s" />' % esc(t) for t in self.tags()]
        L.append('</SVML>')
        return _xml(L)

    def playlist_list(self):
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        L += ['  <MYBUZZ_V1 type="PLAYLIST2009" name="%s" description="%s" playlistid="%d" />'
              % (esc(p["name"]), esc(p["description"]), p["id"]) for p in self.packs]
        L.append('</SVML>')
        return _xml(L)

    def category_list(self, parent=None):
        """Category entries; below a parent also include that branch's quizzes (each type
        lands in its own container, so the game reads whichever the screen needs)."""
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        L += ['  <MYBUZZ_V1 type="CATEGORY2009" name="%s" categoryId="%s" />' % (esc(n), esc(cid))
              for cid, n in self.categories(parent)]
        if parent is not None:
            L += [self._quiz_item(q) for q in self.quizzes_in_category(parent)]
        L.append('</SVML>')
        return _xml(L)

    # ------------------------------------------------------------------ buddies
    def buddy_list(self):
        """BUDDY2009 entries (name*, accountId*) for 'My Friends' Quizzes'."""
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        L += ['  <MYBUZZ_V1 type="BUDDY2009" name="%s" accountId="%d" />'
              % (esc(b["name"]), int(b["accountId"])) for b in self.community["buddies"]]
        L.append('</SVML>')
        return _xml(L)

    def buddy_quizzes(self, account_id):
        for b in self.community["buddies"]:
            if int(b["accountId"]) == int(account_id):
                wanted = [n.lower() for n in b.get("quizzes", [])]
                return b, [q for q in self.quizzes if q["name"].lower() in wanted]
        return None, []

    # ------------------------------------------------------------------ leaderboards
    def record_score(self, game, name, score):
        """A real score (from a game upload), merged into the online boards."""
        with self._lock:
            self.stats.setdefault("scores", {}).setdefault(game, []).append(
                {"name": name, "score": int(score), "ts": int(time.time())})
            self._save_stats()

    def _board(self, game, kind):
        gi = LB_GAMES.index(game)
        rows = [(p[0], int(p[1 + gi])) for p in self.community["players"]]
        buddies = [(b["name"], int(b.get(game.lower(), 0))) for b in self.community["buddies"]]
        real = [(s["name"], s["score"]) for s in self.stats.get("scores", {}).get(game, [])]
        if kind == "buddy_AllTime":
            rows = buddies
        elif kind == "topN_Weekly":
            # a fresh-feeling weekly board: a per-ISO-week subset of players at reduced scores
            year, week, _ = datetime.date.today().isocalendar()
            rnd = random.Random("%s-%d-%d" % (game, year, week))
            rows = [(n, int(s * rnd.uniform(0.55, 0.95))) for n, s in rows + buddies
                    if rnd.random() < 0.7]
            week_start = time.time() - 7 * 86400
            real = [(s["name"], s["score"]) for s in self.stats.get("scores", {}).get(game, [])
                    if s["ts"] >= week_start]
        else:
            rows = rows + buddies
        best = {}
        for n, s in rows + real:
            best[n] = max(s, best.get(n, 0))
        return sorted(best.items(), key=lambda r: -r[1])[:LB_SIZE]

    def leaderboards(self):
        """All online high-score boards. Each OPTION starts a board (FUN_001fede0) and
        the ENTRY rows that follow are appended to it (FUN_001fe9f0)."""
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        for game in LB_GAMES:
            for kind in LB_KINDS:
                L.append('  <LEADERBOARD type="OPTION" name="%s_%s" />' % (kind, game))
                L += ['  <LEADERBOARD type="ENTRY" name="%s" rank="%d" pts="%d" />'
                      % (esc(n), i, s) for i, (n, s) in enumerate(self._board(game, kind), 1)]
        L.append('</SVML>')
        return _xml(L)

    def leaderboard_menu(self, board_url):
        """MENUITEM list (name*, actionparam*) for the leaderboard menu screen; actionparam
        is the URL DownloadLeaderboardTags fetches for that board."""
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>']
        for game in LB_GAMES:
            for kind in LB_KINDS:
                L.append('  <LEADERBOARD type="MENUITEM" name="%s_%s" actionparam="%s?board=%s_%s" />'
                         % (kind, game, esc(board_url), kind, game))
        L.append('</SVML>')
        return _xml(L)

    def leaderboard_single(self, name):
        game = name.rsplit("_", 1)[-1] if name else ""
        kind = name.rsplit("_", 1)[0] if name else ""
        if game not in LB_GAMES or kind not in LB_KINDS:
            return self.leaderboards()
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>',
             '  <LEADERBOARD type="OPTION" name="%s" />' % esc(name)]
        L += ['  <LEADERBOARD type="ENTRY" name="%s" rank="%d" pts="%d" />' % (esc(n), i, s)
              for i, (n, s) in enumerate(self._board(game, kind), 1)]
        L.append('</SVML>')
        return _xml(L)

    def landing_page(self, news=None):
        news = news or os.environ.get(
            "BUZZ_NEWS", "Welcome back to Buzz! Quiz World online - %d quizzes available."
            % len(self.quizzes))
        L = ['<?xml version="1.0" encoding="UTF-8"?>', '<SVML>',
             '  <LANDING type="NEWS" name="%s" />' % esc(news),
             '  <LANDING type="STATS" sofa="%d" single="%d" quizcount="%d" />'
             % (self.stats["totals"]["plays"], self.stats["totals"]["plays"], len(self.quizzes))]
        for t, qs in (("POPULARQUIZ", self.popular()), ("RECENTQUIZ", self.recent())):
            L += ['  <LANDING type="%s" name="%s" timesplayed="%d" rating="%.1f" />'
                  % (t, esc(q["name"]), self.plays(q["id"]), self.rating(q["id"]) or 5.0)
                  for q in qs]
        if self.quizzes:
            q = self.popular(1)[0]
            L.append('  <LANDING type="WORLDQUIZ" name="%s" author="%s" />'
                     % (esc(q["name"]), esc(q["author"])))
        L.append('</SVML>')
        return _xml(L)

    def quiz_content(self, qid):
        """Bare <root> content for one quiz (what the play parser reads)."""
        q = self.resolve(qid)
        if q is None:
            return None
        rnd = random.Random(q["id"])
        L = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<root version="1.0">', '  <round version="1.0" type="standard">']
        for x in q["questions"]:
            answers = [(x["correctAnswer"], True)] + [(a, False) for a in x["incorrectAnswers"][:3]]
            rnd.shuffle(answers)
            L.append('    <question difficulty="%s">' % DIFF_NAME.get(x.get("difficulty", "medium"), "MEDIUM"))
            L.append('      <questiontext>%s</questiontext>' % esc(x["question"]["text"]))
            L.append('      <answerset>')
            for text, ok in answers:
                c = "true" if ok else "false"
                L.append('        <answer correct="%s"><answertext>%s</answertext>'
                         '<answercorrect>%s</answercorrect></answer>' % (c, esc(text), c))
            L.append('      </answerset>')
            L.append('    </question>')
        L += ['  </round>', '</root>']
        return _xml(L)


_CATALOG = None
_SIG = None


def _signature():
    return sorted((os.path.basename(p), os.path.getmtime(p)) for p in glob.glob(os.path.join(PACK_DIR, "*.json")))


def get_catalog():
    """The catalogue, reloaded whenever a pack file is added/changed/removed (Buzz Pack Studio
    publishes quizzes into PACK_DIR while the server runs)."""
    global _CATALOG, _SIG
    sig = _signature()
    if _CATALOG is None:
        _CATALOG = Catalog()
    elif sig != _SIG:
        with _CATALOG._lock:
            _CATALOG.reload()
    _SIG = sig
    return _CATALOG
