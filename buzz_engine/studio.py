"""Buzz Pack Studio: the engine's app. A local web page (only reachable from this PC).

    python -m buzz_engine studio          -> opens http://127.0.0.1:8765 in the browser

Projects live in content/packs/<id>/ (pack.json + images/ + output/). Every action is a small JSON
API over the engine modules (importers, content, rounds, generate, voices, plans).
"""
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import build_pack  # noqa: E402
from buzz_engine import content, game_update, importers, online, pack_numbers, plans, rounds, voices  # noqa: E402
from buzz_engine.generate import generate, install_edat  # noqa: E402

PROJECTS = os.path.join(ROOT, "content", "projects")    # pack projects (content/packs = online catalogue)
SETTINGS = os.path.join(HERE, "settings.json")
JOBS = {}

PRESETS = {
    "Classic (4 rounds)": ["Point Builder", {"random": ["Over the Edge", "Pie Fight", "Boiling Point"]},
                           {"random": ["Pass the Bomb", "Fastest Finger", "High Stakes"]}, "Stop the Clock"],
    "Quick (2 rounds)": ["Point Builder", {"random": ["Pie Fight", "Pass the Bomb"]}],
    "Action": ["Stop the Clock", "Pie Fight", "Pass the Bomb", "Over the Edge"],
    "Brainy": ["Point Builder", "Stop the Clock", "Fastest Finger", "Boiling Point", "High Stakes"],
    "Long (6 rounds)": ["Point Builder", "Pie Fight", "Fastest Finger", "On the Spot", "Pass the Bomb", "Over the Edge"],
}


def settings():
    return json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {}


def save_settings(s):
    json.dump(s, open(SETTINGS, "w"), indent=1)


def project_path(pid):
    if not re.fullmatch(r"[a-z0-9_]+", pid or ""):
        raise ValueError("bad project id")
    return os.path.join(PROJECTS, pid, "pack.json")


def load(pid):
    return json.load(open(project_path(pid), encoding="utf-8"))


def save(pid, pack):
    p = project_path(pid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(pack, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def other_projects(pid=None):
    """[(title, pack)] of every project except pid."""
    out = []
    for d in os.listdir(PROJECTS) if os.path.isdir(PROJECTS) else []:
        if d == pid:
            continue
        try:
            p = load(d)
            out.append((p["text"]["menu_name"], p))
        except Exception:
            pass
    return out


def used_numbers():
    return set(pack_numbers.installed(settings().get("rpcs3"))) | {int(p["pack_number"]) for _, p in other_projects()}


def free_number():
    return pack_numbers.free_number(settings().get("rpcs3"), [p["pack_number"] for _, p in other_projects()])


def number_conflicts(pid, pack):
    return pack_numbers.conflicts(pack, settings().get("rpcs3"), other_projects(pid))


def hook_installed():
    r = settings().get("rpcs3")
    if not r:
        return False
    return os.path.exists(os.path.join(r, "dev_hdd0", "game", "BCES00645", "USRDIR", "Patched", "GLOBALSCRIPTS.SDAT.before_engine"))


def lineup_text(spec):
    out = []
    for x in spec or []:
        out.append({"random": [rounds.ROUND_TYPES[rounds.round_type(r)]["name"] for r in x["random"]]}
                   if isinstance(x, dict) else rounds.ROUND_TYPES[rounds.round_type(x)]["name"])
    return out


def project_view(pid):
    pack = load(pid)
    counts = {"standard": len(pack["standard"]), "picture": len(pack["picture"]),
              "all_that_apply": len(pack["all_that_apply"]), "point_stealer": len(pack["point_stealer"])}
    rounds_status = []
    for t, info in rounds.selectable().items():
        n = sum(counts[k] for k in info["uses"])
        rounds_status.append({"type": t, "name": info["name"], "questions": n, "min": info["min"],
                              "state": "ok" if n >= info["min"] else ("low" if n else "none")})
    qs = []
    for i, q in enumerate(pack["standard"]):
        qs.append({"kind": "standard", "i": i, "q": q[0], "a": q[1:5]})
    for i, q in enumerate(pack["picture"]):
        qs.append({"kind": "picture", "i": i, "q": q[1], "a": q[2:6], "img": pack["images"][q[0] - 1]})
    for i, q in enumerate(pack["all_that_apply"]):
        qs.append({"kind": "all_that_apply", "i": i, "q": q[0], "a": [a for a, _ in q[1:5]], "right": [bool(t) for _, t in q[1:5]]})
    for i, q in enumerate(pack["point_stealer"]):
        qs.append({"kind": "point_stealer", "i": i, "q": q[0], "imgs": [pack["images"][n - 1] for n in q[1:5]]})
    return {"id": pid, "title": pack["text"]["menu_name"], "description": pack["text"]["description"],
            "number": pack["pack_number"], "category": pack["category"], "language": pack.get("language", "GBR"),
            "audio": pack.get("audio", True), "author": pack.get("author", ""), "uppercase": pack.get("uppercase", True),
            "rounds4p": lineup_text(pack.get("rounds", {}).get("4p")), "rounds8p": lineup_text(pack.get("rounds", {}).get("8p")),
            "counts": counts, "rounds_status": rounds_status, "questions": qs, "credits": pack.get("credits", []),
            "outputs": sorted(os.listdir(os.path.join(PROJECTS, pid, "output"))) if os.path.isdir(os.path.join(PROJECTS, pid, "output")) else [],
            "number_conflicts": number_conflicts(pid, pack), "free_number": free_number()}


def state():
    vs = voices.list_voices()
    langs = [{"code": k, "name": v["name"], "voice": (voices.voice_for(k) or {}).get("name")}
             for k, v in build_pack.LANGUAGES.items()]
    projects = []
    for d in sorted(os.listdir(PROJECTS)) if os.path.isdir(PROJECTS) else []:
        try:
            p = load(d)
            projects.append({"id": d, "title": p["text"]["menu_name"], "number": p["pack_number"],
                             "questions": len(p["standard"]) + len(p["picture"]) + len(p["all_that_apply"]) + len(p["point_stealer"])})
        except Exception:
            pass
    from buzz_engine import keys
    k = keys.load()
    from buzz_engine import __version__
    import buzz_tools
    return {"ffmpeg": buzz_tools.find_ffmpeg(), "version": __version__, "keys_ready": bool(k.get("klic") and k.get("svomac_salt")), "projects": projects, "languages": langs, "voices": vs, "categories": content.CATEGORIES,
            "round_types": [{"type": k, "name": v["name"], "uses": v["uses"]} for k, v in rounds.selectable().items()],
            "presets": {k: lineup_text(v) for k, v in PRESETS.items()}, "rpcs3": settings().get("rpcs3", ""),
            "hook": hook_installed(), "free_number": free_number(),
            "update": game_update.status(settings().get("rpcs3"))}


def save_upload(pid, name, b64):
    """Uploaded file (base64) -> path inside the project's uploads folder."""
    d = os.path.join(PROJECTS, pid, "uploads")
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name)) or "upload"
    p = os.path.join(d, safe)
    with open(p, "wb") as f:
        f.write(base64.b64decode(b64.split(",", 1)[-1]))
    return p


# ------------------------------------------------------------------------------ actions
def act_new(a):
    title = a["title"].strip()
    if not title:
        raise ValueError("give the pack a name")
    number = int(a.get("number") or free_number())
    if number in used_numbers():
        raise ValueError("pack number %d is already used" % number)
    pid = content.slug(title, 24) + "_%d" % number
    pack = content.new_pack(title, number, a.get("category") or "Knowledge", a.get("description"))
    pack["language"] = a.get("language", "GBR")
    pack["audio"] = True
    pack["rounds"] = {"4p": PRESETS["Classic (4 rounds)"]}
    save(pid, pack)
    return {"id": pid}


def act_save(a):
    pack = load(a["id"])
    if "title" in a:
        t = content.clean(a["title"], True)
        pack["text"]["menu_name"] = pack["text"]["subject"] = pack["topic"] = t
    if "description" in a:
        pack["text"]["description"] = content.clean(a["description"], True)
    if "number" in a:
        trial = dict(pack, pack_number=int(a["number"]))
        clash = number_conflicts(a["id"], trial)
        if clash:
            raise ValueError("%s - try %d" % ("; ".join(clash), free_number()))
        pack["pack_number"] = trial["pack_number"]
        pack["key_tag"] = str(trial["pack_number"])
        pack["round_name"] = re.sub(r"\d+$", "", pack.get("round_name", "pack")) + str(trial["pack_number"])
    for k in ("category", "language", "audio", "author"):
        if k in a:
            pack[k] = a[k]
    for players in ("4p", "8p"):
        k = "rounds" + players
        if k in a:
            steps = [s for s in a[k] if s]
            if steps:
                rounds.parse_plan(steps)                          # validates names
                pack.setdefault("rounds", {})[players] = steps
            else:
                pack.get("rounds", {}).pop(players, None)
    save(a["id"], pack)
    return project_view(a["id"])


def _import(pid, sources, limit=None):
    pack = load(pid)
    ppath = project_path(pid)
    qs = []
    for s in sources:
        qs += importers.load(s)
    existing = importers.parse_json(dict(pack, _dir=os.path.dirname(ppath)))
    seen = {content.key(content.normalise(q)) for q in existing}
    kept, rejected = content.select(qs, uppercase=pack.get("uppercase", True), limit=limit)
    dup = [q for q in kept if content.key(q) in seen]
    kept = [q for q in kept if content.key(q) not in seen]
    content.add_to_pack(pack, kept, os.path.dirname(ppath))
    save(pid, pack)
    reasons = {}
    for _, why in rejected:
        for w in why:
            reasons[w] = reasons.get(w, 0) + 1
    if dup:
        reasons["already in the pack"] = len(dup)
    return {"found": len(qs), "added": len(kept), "skipped": reasons, "project": project_view(pid)}


def act_import(a):
    sources = []
    for f in a.get("files", []):
        sources.append(save_upload(a["id"], f["name"], f["data"]))
    if a.get("online"):
        sources.append(a["online"])
    if a.get("url"):
        sources.append(a["url"])
    return _import(a["id"], sources, int(a["limit"]) if a.get("limit") else None)


def act_add(a):
    q = {"kind": a["kind"], "question": a["question"], "source": "manual"}
    if a["kind"] in ("standard", "picture"):
        q["correct"], q["wrong"] = a["answers"][0], a["answers"][1:4]
        if a["kind"] == "picture":
            q["image"] = save_upload(a["id"], a["image"]["name"], a["image"]["data"])
    elif a["kind"] == "all_that_apply":
        q["answers"], q["right"] = a["answers"], a["right"]
    elif a["kind"] == "point_stealer":
        q["images"] = [save_upload(a["id"], im["name"], im["data"]) for im in a["images"]]
        q["correct"] = int(a.get("correct", 0))
    pack = load(a["id"])
    kept, rejected = content.select([q], uppercase=pack.get("uppercase", True))
    if rejected:
        raise ValueError("; ".join(rejected[0][1]))
    content.add_to_pack(pack, kept, os.path.dirname(project_path(a["id"])))
    save(a["id"], pack)
    return project_view(a["id"])


def act_delete(a):
    pack = load(a["id"])
    del pack[a["kind"]][int(a["i"])]
    save(a["id"], pack)
    return project_view(a["id"])


def act_generate(a):
    job = "%s_%d" % (a["id"], int(time.time()))
    JOBS[job] = {"log": [], "done": False, "result": None, "error": None}

    def run():
        j = JOBS[job]
        try:
            pack = load(a["id"])
            j["result"] = generate(project_path(a["id"]), language=a.get("language") or pack.get("language"),
                                   audio=bool(a.get("audio", pack.get("audio", True))),
                                   progress=lambda m: j["log"].append(m), rpcs3=settings().get("rpcs3"))
        except (Exception, SystemExit) as e:          # SystemExit too: a job must always finish
            j["error"] = str(e)
            j["log"].append("FAILED: %s" % e)
            if not isinstance(e, (RuntimeError, ValueError)):   # those carry a plain-English message
                j["log"].append(traceback.format_exc()[-1500:])
        j["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"job": job}


def act_install(a):
    r = settings().get("rpcs3")
    if not r:
        raise ValueError("set the RPCS3 folder first")
    res = a["result"]
    dst = install_edat(res["edat"], res["pack_number"], res["language"], r)
    return {"installed": dst}


def act_settings(a):
    s = settings()
    if "rpcs3" in a:
        if not os.path.isdir(os.path.join(a["rpcs3"], "dev_hdd0")):
            raise ValueError("that folder has no dev_hdd0 - pick the folder that contains rpcs3.exe")
        s["rpcs3"] = a["rpcs3"]
    save_settings(s)
    return state()


def act_hook(a):
    """Custom running orders in the game's scripts (also installs the unfinished custom rounds, which
    stay hidden until finished)."""
    from buzz_engine import custom_rounds
    r = settings().get("rpcs3")
    if not r:
        raise ValueError("set the RPCS3 folder first")
    custom_rounds.install(r)
    return state()


def act_open(a):
    p = a["path"]
    if not os.path.abspath(p).startswith(os.path.abspath(ROOT)):
        raise ValueError("can only open project folders")
    os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
    return {}


def act_opentdb(a):
    return {"categories": [{"id": k, "name": v} for k, v in sorted(importers.opentdb_categories().items(), key=lambda x: x[1])]}


def act_keys(a):
    from buzz_engine import keys
    keys.setup_from_eboot(a["eboot"])
    return state()


def act_update(a):
    """Game update 01.02: download it from Sony, or open RPCS3's installer on it."""
    if a.get("op") == "install":
        st = game_update.status(settings().get("rpcs3"))
        if not st["downloaded"]:
            raise ValueError("download the update first")
        game_update.install(settings().get("rpcs3"), st["downloaded"])
    else:
        game_update.download(progress=lambda m: None)
    return state()


def act_ffmpeg(a):
    import buzz_tools
    if a.get("path"):
        s = settings()
        s["ffmpeg"] = a["path"]
        save_settings(s)
    else:
        buzz_tools.download_ffmpeg(progress=lambda m: None)
    return state()


def act_publish(a):
    return online.publish(project_path(a["id"]), int(a.get("quiz_size") or 10))


def act_server(a):
    op = a.get("op", "status")
    if op == "start":
        st = online.start_server()
    elif op == "stop":
        st = online.stop_server()
    elif op == "setup":
        online.setup_server(a["eboot"])
        st = online.server_status()
    else:
        st = online.server_status()
    st["published"] = online.published()
    return st


def act_catalog(a):
    online.set_enabled(a["file"], a["enabled"])
    return {"published": online.published()}


def act_setup_pc(a):
    r = settings().get("rpcs3")
    if not r:
        raise ValueError("set the RPCS3 folder first")
    return {"done": online.setup_pc(r, a.get("server_ip") or "127.0.0.1", bool(a.get("fps60", True)))}


ACTIONS = {"new": act_new, "save": act_save, "import": act_import, "add": act_add, "delete": act_delete,
           "generate": act_generate, "install": act_install, "settings": act_settings, "hook": act_hook,
           "open": act_open, "opentdb": act_opentdb, "publish": act_publish, "server": act_server,
           "catalog": act_catalog, "setup_pc": act_setup_pc, "keys": act_keys, "ffmpeg": act_ffmpeg,
           "update": act_update}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, open(os.path.join(HERE, "studio.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._send(200, state())
            if u.path == "/api/project":
                return self._send(200, project_view(q["id"]))
            if u.path == "/api/job":
                return self._send(200, JOBS.get(q["id"], {"error": "no such job", "done": True}))
            if u.path == "/img":
                p = os.path.join(PROJECTS, q["id"], "images", re.sub(r"[^A-Za-z0-9_]", "", q["name"]) + ".png")
                return self._send(200, open(p, "rb").read(), "image/png")
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        try:
            a = json.loads(self.rfile.read(n) or b"{}")
            name = u.path.rsplit("/", 1)[-1]
            if name not in ACTIONS:
                return self._send(404, {"error": "unknown action"})
            self._send(200, ACTIONS[name](a))
        except Exception as e:
            self._send(400, {"error": str(e)})


def main(port=8765, open_browser=True):
    os.makedirs(PROJECTS, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("Buzz Pack Studio running at", url, "(Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
