"""Buzz! Quiz World custom pack engine.

  python -m buzz_engine new "Harry Potter" --number 98 --category TVCinema \
        --from questions.csv --from "opentdb:amount=50&category=10" -o packs/hp/pack.json
  python -m buzz_engine add packs/hp/pack.json --from more.xml
  python -m buzz_engine check packs/hp/pack.json
  python -m buzz_engine rounds packs/hp/pack.json --4p "Point Builder, random(Over the Edge|Pie Fight), Point Stealer"
  python -m buzz_engine build packs/hp/pack.json [--no-voice] [--install]
  python -m buzz_engine plans --set pack="Point Builder, Point Stealer, random(Pie Fight|Pass the Bomb)" [--install]
  python -m buzz_engine export packs/hp/pack.json -o hp.buzz.txt   (shareable text, no game data)
  python -m buzz_engine sources             (Open Trivia DB categories)
  python -m buzz_engine studio              (the app: everything above behind one page)

Settings (paths) live in buzz_engine/settings.json: {"rpcs3": "<RPCS3 folder>"}.
"""
import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from buzz_engine import content, importers, plans, rounds  # noqa: E402

SETTINGS = os.path.join(HERE, "settings.json")


def settings():
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as f:
            return json.load(f)
    return {}


def rpcs3_dir(a=None):
    d = (a and getattr(a, "rpcs3", None)) or settings().get("rpcs3")
    if not d or not os.path.isdir(d):
        sys.exit("RPCS3 folder not set: pass --rpcs3 or put {\"rpcs3\": \"...\"} in %s" % SETTINGS)
    return d


def installed_packs(r):
    base = os.path.join(r, "dev_hdd0", "game", "BCES00098", "USRDIR")
    return sorted(int(m.group(1)) for d in (os.listdir(base) if os.path.isdir(base) else [])
                  for m in [re.match(r"PACK(\d{4})$", d)] if m)


def parse_lineup(text):
    """'Point Builder, random(Over the Edge|Pie Fight), Point Stealer' -> plan spec list."""
    out = []
    for part in re.findall(r"random\([^)]*\)|[^,]+", text):
        part = part.strip().strip(",").strip()
        if not part:
            continue
        m = re.match(r"random\((.*)\)$", part, re.I)
        out.append({"random": [x.strip() for x in m.group(1).split("|")]} if m else part)
    return out


def load_pack(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_pack(pack, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pack, f, indent=1, ensure_ascii=False)


def import_into(pack, sources, pack_path, a):
    qs = []
    for s in sources:
        got = importers.load(s)
        print("  %-50s %d questions" % (s[:50], len(got)))
        qs += got
    existing = importers.parse_json(dict(pack, _dir=os.path.dirname(os.path.abspath(pack_path))))
    seen = {content.key(content.normalise(q)) for q in existing}
    kept, rejected = content.select(qs, uppercase=pack.get("uppercase", True), limit=a.limit,
                                    difficulty=a.difficulty and a.difficulty.split(","),
                                    categories=a.only_category and a.only_category.split(","))
    kept = [q for q in kept if content.key(q) not in seen]
    content.add_to_pack(pack, kept, os.path.dirname(os.path.abspath(pack_path)))
    print("added %d questions, skipped %d" % (len(kept), len(rejected)))
    reasons = {}
    for _, why in rejected:
        for w in why:
            reasons[w] = reasons.get(w, 0) + 1
    for w, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print("  skipped %4d: %s" % (n, w))


def source_headers(sources):
    """Pack details from .buzz.txt headers (#TITLE:, #PACK:, ...) of local text sources."""
    meta = {}
    for s in sources:
        if os.path.isfile(s) and s.lower().endswith(".txt"):
            with open(s, encoding="utf-8-sig", errors="replace") as f:
                for k, v in importers.header(f.read()).items():
                    meta.setdefault(k, v)
    return meta


def cmd_new(a):
    meta = source_headers(a.sources)
    title = a.title or meta.get("title")
    number = a.number or (int(meta["pack"]) if meta.get("pack") else None)
    if not title or not number:
        sys.exit("need a title and --number (or #TITLE:/#PACK: headers in a .buzz.txt source)")
    category = a.category or meta.get("category") or "Knowledge"
    pack = content.new_pack(title, number, category, a.description or meta.get("description"),
                            uppercase=not a.keep_case)
    if meta.get("author"):
        pack["author"] = meta["author"]
    for players in ("4p", "8p"):
        if meta.get("rounds" + players):
            pack.setdefault("rounds", {})[players] = parse_lineup(meta["rounds" + players])
    voice = a.voice or meta.get("voice")
    if voice:
        pack["voice"] = {"engine": voice, "rounds": ["standard", "picture", "all_that_apply", "point_stealer"]}
    import_into(pack, a.sources, a.out, a)
    save_pack(pack, a.out)
    print("wrote", a.out)
    print(content.report(pack))


def cmd_add(a):
    pack = load_pack(a.pack)
    import_into(pack, a.sources, a.pack, a)
    save_pack(pack, a.pack)
    print(content.report(pack))


def cmd_check(a):
    pack = load_pack(a.pack)
    print(content.report(pack))
    for players in ("4p", "8p"):
        spec = pack.get("rounds", {}).get(players)
        if spec:
            print("pack game %s: %s" % (players, rounds.describe(rounds.parse_plan(spec))))


def cmd_rounds(a):
    if not a.pack:
        for k, v in rounds.selectable().items():
            print("  %-16s (%s) uses %s" % (v["name"], k, "/".join(v["uses"])))
        return
    pack = load_pack(a.pack)
    r = pack.setdefault("rounds", {})
    for players, text in (("4p", a.four), ("8p", a.eight)):
        if text:
            r[players] = parse_lineup(text)
            print("%s: %s" % (players, rounds.describe(rounds.parse_plan(r[players]))))
    save_pack(pack, a.pack)


def cmd_build(a):
    import build_pack
    if a.no_voice:
        os.environ["BUZZ_NO_VOICE"] = "1"
    res = build_pack.build(os.path.abspath(a.pack))
    print(res)
    if a.install:
        install(res["edat"], load_pack(a.pack)["pack_number"], a)


def install(edat, number, a):
    r = rpcs3_dir(a)
    d = os.path.join(r, "dev_hdd0", "game", "BCES00098", "USRDIR", "PACK%04d" % number)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(edat))
    shutil.copy(edat, dst)
    print("installed", dst)


def cmd_plans(a):
    r = rpcs3_dir(a)
    target = os.path.join(r, "dev_hdd0", "game", "BCES00645", "USRDIR", "Patched", "GLOBALSCRIPTS.SDAT")
    base = target + ".before_engine"
    overrides = {}
    for item in a.set or []:
        mode, text = item.split("=", 1)
        overrides[mode.strip()] = parse_lineup(text)
    for mode, spec in overrides.items():
        print("%-8s %s" % (mode, rounds.describe(rounds.parse_plan(spec))))
    out = os.path.join(ROOT, "dlc_test", "GLOBALSCRIPTS_engine.sdat")
    src = base if os.path.exists(base) else target
    plans.build_globalscripts(src, out, overrides, custom_rounds=True)
    print("built", out)
    if a.install:
        if not os.path.exists(base):
            shutil.copy(target, base)                      # keep the pre-engine file to rebuild from
        shutil.copy(out, target)
        print("installed", target, "(original kept as %s)" % os.path.basename(base))


def cmd_export(a):
    """Pack JSON -> shareable .buzz.txt (headers + Q/A blocks; pictures as their original
    URL/path, so a shared file carries no game or image data)."""
    pack = load_pack(a.pack)
    src = pack.get("image_sources", {})
    L = ["#TITLE:%s" % pack["text"]["menu_name"], "#PACK:%d" % pack["pack_number"],
         "#CATEGORY:%s" % pack["category"], "#DESCRIPTION:%s" % pack["text"]["description"]]
    if pack.get("author"):
        L.append("#AUTHOR:%s" % pack["author"])
    for players in ("4p", "8p"):
        spec = pack.get("rounds", {}).get(players)
        if spec:
            L.append("#ROUNDS%s:%s" % (players.upper(), ", ".join(
                "random(%s)" % "|".join(x["random"]) if isinstance(x, dict) else x for x in spec)))
    for c in pack.get("credits", []):
        L.append("#CREDIT:%s" % c)
    L.append("")
    for q in pack["standard"]:
        L += ["Q: " + q[0], "A: " + q[1]] + ["- " + w for w in q[2:5]] + [""]
    for q in pack["picture"]:
        stem = pack["images"][q[0] - 1]
        L += ["Q: " + q[1], "IMG: " + src.get(stem, stem + ".png"), "A: " + q[2]] + ["- " + w for w in q[3:6]] + [""]
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("wrote %s (%d standard + %d picture questions)" % (a.out, len(pack["standard"]), len(pack["picture"])))


def cmd_generate(a):
    from buzz_engine.generate import generate
    r = generate(os.path.abspath(a.pack), language=a.language, audio=not a.no_voice)
    print("PKG:", r["pkg"])


def cmd_setup(a):
    """One-time setup from the user's own game files."""
    from buzz_engine import keys
    if a.rpcs3_dir:
        s = settings()
        s["rpcs3"] = a.rpcs3_dir
        json.dump(s, open(SETTINGS, "w"), indent=1)
        print("RPCS3 folder saved")
    if a.eboot:
        print("read from your EBOOT:", ", ".join(keys.setup_from_eboot(a.eboot)))
    import buzz_tools
    if a.ffmpeg:
        s = settings()
        s["ffmpeg"] = a.ffmpeg
        json.dump(s, open(SETTINGS, "w"), indent=1)
    if a.get_ffmpeg:
        buzz_tools.download_ffmpeg()
    print("ffmpeg: %s" % (buzz_tools.find_ffmpeg() or "missing (use --get-ffmpeg)"))
    from buzz_engine import game_update
    if a.get_update:
        pkg = game_update.download()
        print("install it in RPCS3 with File > Install Packages/Raps/Edats, or: rpcs3.exe --installpkg \"%s\"" % pkg)
    st = game_update.status(settings().get("rpcs3"))
    print("game update: %s" % ("%s installed" % st["want"] if st["ok"] else
                               "%s missing (have %s; use --get-update)" % (st["want"], st["installed"] or "none")))
    ok = keys.load()
    print("pack encryption key: %s | server salt: %s" % ("ok" if ok.get("klic") else "missing",
                                                        "ok" if ok.get("svomac_salt") else "missing"))


def cmd_studio(a):
    from buzz_engine import studio
    studio.main(a.port, not a.no_browser)


def cmd_sources(a):
    for i, n in sorted(importers.opentdb_categories().items()):
        print("  opentdb category=%-3d %s" % (i, n))


def main():
    ap = argparse.ArgumentParser(prog="buzz_engine", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpcs3", help="RPCS3 folder (else settings.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def filters(p):
        p.add_argument("--from", dest="sources", action="append", default=[], help="file, URL, opentdb:..., triviaapi:...")
        p.add_argument("--limit", type=int, help="max questions to add")
        p.add_argument("--difficulty", help="easy,medium,hard")
        p.add_argument("--only-category", help="keep questions whose category contains any of these (comma list)")

    p = sub.add_parser("new")
    p.add_argument("title", nargs="?", help="pack title (or #TITLE: in a .buzz.txt source)")
    p.add_argument("--number", type=int, help="pack number, unique, 1-99 (or #PACK:)")
    p.add_argument("--category", choices=content.CATEGORIES, help="menu channel (default Knowledge)")
    p.add_argument("--description")
    p.add_argument("--keep-case", action="store_true", help="don't upper-case text (retail packs are upper case)")
    p.add_argument("--voice", help="host voice engine, e.g. clone:voice_models/buzz_host/reference.wav")
    p.add_argument("-o", "--out", required=True)
    filters(p)
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("add")
    p.add_argument("pack")
    filters(p)
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("check")
    p.add_argument("pack")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("rounds")
    p.add_argument("pack", nargs="?")
    p.add_argument("--4p", dest="four")
    p.add_argument("--8p", dest="eight")
    p.set_defaults(fn=cmd_rounds)
    p = sub.add_parser("build")
    p.add_argument("pack")
    p.add_argument("--no-voice", action="store_true")
    p.add_argument("--install", action="store_true")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("plans")
    p.add_argument("--set", action="append", help='mode="line-up" (modes: %s)' % ", ".join(rounds.MODES))
    p.add_argument("--install", action="store_true")
    p.set_defaults(fn=cmd_plans)
    p = sub.add_parser("export")
    p.add_argument("pack")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_export)
    p = sub.add_parser("generate", help="pack -> installable PKG (the Studio's Generate button)")
    p.add_argument("pack")
    p.add_argument("--language", help="3-letter pack language (GBR, ESP, PRT, DEU, ...)")
    p.add_argument("--no-voice", action="store_true")
    p.set_defaults(fn=cmd_generate)
    p = sub.add_parser("setup", help="one-time setup from your own game files")
    p.add_argument("--eboot", help="decrypted EBOOT.elf (RPCS3 > Utilities > Decrypt PS3 Binaries)")
    p.add_argument("--rpcs3-dir", help="RPCS3 folder")
    p.add_argument("--ffmpeg", help="path to ffmpeg.exe")
    p.add_argument("--get-ffmpeg", action="store_true", help="download a free (LGPL) ffmpeg into tools/ffmpeg")
    p.add_argument("--get-update", action="store_true", help="download game update 01.02 from Sony's PS3 update server")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("studio", help="open the Buzz Pack Studio app in your browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_studio)
    p = sub.add_parser("sources")
    p.set_defaults(fn=cmd_sources)
    a = ap.parse_args()
    try:
        a.fn(a)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        sys.exit("Error: %s" % e)


if __name__ == "__main__":
    main()
