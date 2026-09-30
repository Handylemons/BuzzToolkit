"""Build a Buzz! Quiz World DLC quiz pack FROM SCRATCH - no retail pack is read.

    python build_pack.py content/dlc/hp_years1to3.json

Every file is generated: Lua scripts (compiled to the game's bytecode), pack name text, round
string tables, question indexes (.kaq/.qak), picture sets, the pack card texture, host speech
(TTS via buzz_voice, silent where no voice is configured) and the credits page. Output: dlc_test/<LANG>PACK<nnnn>.DAT (plain) and .EDAT (installable).

Content JSON keys: pack_number, key_tag (unused here), subject_key, round_name, category
(Knowledge / Lifestyle / Music / TVCinema), text{subject, description, menu_name}, topic, images,
standard[[q, correct, w, w, w]], picture[[image#, q, correct, w, w, w]],
all_that_apply[[q, [ans, bool] x4]], point_stealer[[q, correct image#, image#, image#, image#]],
optional pack_image (path) and slots{text, picture, all_that_apply, point_stealer} (filler counts),
optional rounds{"4p": [...], "8p": [...]} = the pack's own line-up in the Pack Game menu: round
names in order, {"random": [names]} for a random pick (buzz_engine.rounds), Final Countdown last;
optional voice{engine ("clone:buzz_host" | "kokoro:bm_george" | "onecore:George"), speed,
clone{exaggeration, cfg, temperature, seed} (Chatterbox options), vocab (spelling hints for the
speech-recognition check of cloned lines), warmth (dB of low lift / half as much top cut),
rounds (default
["point_stealer"]; also "standard", "picture", "all_that_apply"), pronounce{word: respelling},
say{on-screen question: spoken line}}. Set BUZZ_NO_VOICE=1 for a quick silent build.
Formats: buzz_index (question index), buzz_text (string tables), buzz_sdi (pictures), buzz_ete
(pack card), buzz_lua (scripts), buzz_pak (container), edat_tool (encryption).
"""
import json
import os
import struct
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter

import buzz_ete
import buzz_index
import buzz_lua
import buzz_rsf
import buzz_sdi
import buzz_voice
import edat_tool
from buzz_pak import Entry, write_pak
from buzz_text import encode_all

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = "GBR"                            # default pack language (see LANGUAGES)
# Pack language codes: the game loads <CODE>PACKnnnn.EDAT for its language; the same code is the
# folder prefix inside the pack, the index language field and part of the content id (checked on
# the disc packs INEPACK0100 / ESPPACK0100 / PRTPACK0100 and retail GBR / DEU DLC).
# whisper = speech-recognition language used to check generated host lines.
LANGUAGES = {
    "GBR": {"name": "English (UK)", "whisper": "en"}, "INE": {"name": "English (international)", "whisper": "en"},
    "ESP": {"name": "Spanish", "whisper": "es"}, "PRT": {"name": "Portuguese", "whisper": "pt"},
    "DEU": {"name": "German", "whisper": "de"}, "FRA": {"name": "French", "whisper": "fr"},
    "ITA": {"name": "Italian", "whisper": "it"}, "NLD": {"name": "Dutch", "whisper": "nl"},
    "SWE": {"name": "Swedish", "whisper": "sv"}, "DAN": {"name": "Danish", "whisper": "da"},
    "FIN": {"name": "Finnish", "whisper": "fi"}, "NOR": {"name": "Norwegian", "whisper": "no"},
    "POL": {"name": "Polish", "whisper": "pl"},
}
KLIC = None                              # game klicensee: buzz_engine.keys (from the user's EBOOT)
MAX_Q, MAX_A = 93, 30
SUBJECT_ID = 115                       # question category item defined by questioncategories.clu
INTROS = ["HERE'S A QUESTION ON %s. PLACE YOUR BETS!",
          "THIS ONE'S ON %s. WHAT WILL YOU BET?",
          "NEXT UP IS A QUESTION ON %s. HOW MUCH ARE YOU PREPARED TO RISK?"]
# round file -> (package number in roundpackages, round type tag) - retail order
ROUNDS = [("stoptheclock", 1), ("passthebomb", 2), ("piefight", 3), ("highstakes", 4),
          ("pointstealer", 5), ("finalcountdown", 6), ("fastestfinger", 7), ("allthatapply", 8),
          ("pointbuilder", 9)]
TEXT_TAGS = [7, 6, 4, 2, 3, 9, 1]      # retail tag order for text questions (incl. High Stakes)
PIC_TAGS = [7, 4, 9]                   # media questions: Point Builder, High Stakes, Fastest Finger
DEFAULT_SLOTS = {"text": 60, "picture": 30, "all_that_apply": 20, "point_stealer": 20}


def check(s, limit, what):
    if len(s) > limit or s != s.upper():
        raise ValueError("%s must be upper case and <= %d chars: %r" % (what, limit, s))
    return s


def text_key_hash(key):
    import zlib
    v = (zlib.crc32(key.encode("ascii")) ^ 0x05432108) & 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


# ----------------------------------------------------------------------------- scripts
def scripts(num, name, category, subject_key, rounds=None, files=None):
    """files: round files the pack has (Point Stealer / All That Apply are optional)."""
    files = set(files or [r for r, _ in ROUNDS])
    L = buzz_lua.call
    tex = "BZ3_InfoPackImage_Pack%04d" % num
    games = ["p%dPackGame1p" % num, "p%dPackGame4p" % num, "p%dPackGame8p" % num]
    pack = "PACK%04d" % num
    out = {}
    out["SCRIPTS/register.clu"] = L("IncludeScript", "Generated/AddPackInfo")
    out["SCRIPTS/packswitch.clu"] = ("PackSwitch = {}\nfunction PackSwitch.SwitchToPack()\n"
                                     '  IncludeScript("QuestionCategories")\n'
                                     '  IncludeScript("QuestionDifficulty")\n'
                                     '  IncludeScript("QuestionReveals")\nend\n')
    out["SCRIPTS/questioncategories.clu"] = (L("ClearAllQuestionCategoryItems")
                                             + L("AddQuestionCategoryItem", SUBJECT_ID, "UNCATEGORISED", "QC_UNCATEGORISED", 67))
    out["SCRIPTS/questiondifficulty.clu"] = (L("ClearAllQuestionDifficultyReferences")
                                             + "".join(L("AddQuestionDifficultyReference", n, i + 1)
                                                       for i, n in enumerate(["Easy", "Medium", "Hard"])))
    out["SCRIPTS/questionreveals.clu"] = (L("ClearAllQuestionRevealReferences")
                                          + "".join(L("AddQuestionRevealReference", n, i + 1) for i, n in enumerate(
                                              ["Pixellate", "Blocks", "Sliding Blocks", "Zoom Out", "Swirly", "Distort", "Fade"])))
    rp = ""
    for rnd, idx in ROUNDS:
        if rnd not in files:
            continue
        pkg = "%s_%s" % (name, rnd)
        rp += L("PackageData.NewPackage", pkg) + L("PackageData.AddRoundFile", idx, 0, pkg, pkg)
    out["SCRIPTS/roundpackages.clu"] = rp
    out["SCRIPTS/GENERATED/roundpackages.clu"] = rp
    out["SCRIPTS/GENERATED/addpackinfo.clu"] = (
        L("PackageData.NewPackage", pack + "ICONS")
        + L("PackageData.NewLocalisedEdgePackage", "", "Pack%04dTextures" % num)
        + L("PackageData.AddTexture", tex, 1, 1, 1280, 720, tex)
        + L("PackageData.LoadPackage", pack + "ICONS")
        + "local ok = AddPackInfo(1000, %d, %d, %s, %s, %s, 5, %s, %s, %s, %s, %s, \"\")\n" % (
            num, num, buzz_lua.lua_str("PackTitlePk%dPack" % num), buzz_lua.lua_str(pack), buzz_lua.lua_str(category),
            buzz_lua.lua_str(games[0]), buzz_lua.lua_str(games[1]), buzz_lua.lua_str(games[2]),
            buzz_lua.lua_str("PackDescPk%dPack" % num), buzz_lua.lua_str(tex))
        + 'if true == ok then\n  IncludeScript("Generated/RoundSetup")\n  IncludeScript("Generated/RoundPackages")\nend\n')
    # games + round registrations (same structure as every retail pack)
    rs = L("AddGame", games[0], num * 1000, "1PPACKSPECIFIC", "Max1Player", 0, -1, 1, 1, 4)
    rs += L("AddGamePlanRounds", games[0], "TriggerFinger", 0) * 3
    rs += L("AddGame", games[1], num * 1000 + 1, "4PPACKSPECIFIC", "Max4Players", 0, -1, 1, 1, 4)
    for r, x in (("PointBuilder", 0), ("PassTheBomb", 0), ("FastestFingerFirst", 0), ("PieFight", 0),
                 ("PointStealer", 0), ("BetIt", 0), ("FinalCountdown", 8)):
        if r != "PointStealer" or "pointstealer" in files:
            rs += L("AddGamePlanRounds", games[1], r, x)
    rs += L("AddGame", games[2], num * 1000 + 2, "8PPACKSPECIFIC", "Max8Players", 0, -1, 1, 1, 4)
    for r, x in (("PointBuilder", 0), ("TriggerFinger", 0), ("BetIt", 0), ("FinalCountdown", 8)):
        rs += L("AddGamePlanRounds", games[2], r, x)
    four = [("BetIt", "highstakes", "RoundPlanNonAsset", 4), ("FastestFingerFirst", "fastestfinger", "RoundPlanNonAsset", 6),
            ("FinalCountdown", "finalcountdown", "RoundPlanFinalCountdown", 30), ("PassTheBomb", "passthebomb", "RoundPlanNonAsset", 9999),
            ("PieFight", "piefight", "RoundPlanNonAsset", 9999), ("PointBuilder", "pointbuilder", "RoundPlanNonAsset", 6),
            ("PointStealer", "pointstealer", "RoundPlanNonAsset", 4)]
    eight = [("PointBuilder", "pointbuilder", "RoundPlanNonAsset", 6), ("TriggerFinger", "stoptheclock", "RoundPlanNonAsset", 6),
             ("BetIt", "highstakes", "RoundPlanNonAsset", 4), ("FinalCountdown", "finalcountdown", "RoundPlanFinalCountdown", 30)]
    regs = [(g, "TriggerFinger", "stoptheclock", "RoundPlanNonAsset", 6, 1)
            for g in ("ChannelHopperGame1p", "%sGame1p" % category, games[0])]
    for g in ("ChannelHopperGame4p", "%sGame4p" % category, games[1]):
        regs += [(g, t, f, p, n, 2) for t, f, p, n in four]
    for g in ("ChannelHopperGame8p", "%sGame8p" % category, games[2]):
        regs += [(g, t, f, p, n, 2) for t, f, p, n in eight]
    regs += [("NetworkGame", "TriggerFinger", "stoptheclock", "RoundPlanNonAsset", 6, 2),
             ("NetworkGame", "AllThatApply", "allthatapply", "RoundPlanNonAsset", 6, 2),
             ("NetworkGame", "BetIt", "highstakes", "RoundPlanNonAsset", 6, 2)]
    # custom round types in this pack's running order get the same question file as the round
    # they are built on (Second Best plays Fastest Finger's questions)
    custom = {"SecondBest": ("fastestfinger", "RoundPlanNonAsset", 6)}
    wanted = set()
    for spec in (rounds or {}).values():
        for step in spec:
            for r in (step["random"] if isinstance(step, dict) else [step]):
                from buzz_engine.rounds import round_type
                if round_type(r) in custom:
                    wanted.add(round_type(r))
    for t in sorted(wanted):
        f, p, n = custom[t]
        for g, k in ((games[1], 2), (games[2], 2), ("%sGame4p" % category, 2), ("ChannelHopperGame4p", 2)):
            regs.append((g, t, f, p, n, k))
    regs = [r for r in regs if r[2] in files]
    for i, (g, t, f, p, n, k) in enumerate(regs):
        rs += L("AddRound", num * 1000 + 300 + i, g, category, t, subject_key, pack, "%s_%s" % (name, f),
                p, "NULL_EVENT_PLAN", n, 0, k, "902403300")
    # per-pack line-ups for the "Pack Game" menu (buzz_engine.plans; used when the engine
    # GLOBALSCRIPTS is installed, ignored otherwise)
    from buzz_engine.plans import pack_plan_lua
    for players, game in (("4p", games[1]), ("8p", games[2])):
        if rounds and rounds.get(players):
            rs += pack_plan_lua(game, rounds[players])
    out["SCRIPTS/GENERATED/roundsetup.clu"] = rs
    return {k: buzz_lua.compile_lua(v) for k, v in out.items()}


# ----------------------------------------------------------------------------- pack card
def pack_card(C, images, out_path):
    """576x480 pack card in the retail style: gradient ground, rounded framed picture card."""
    cols = {"TVCinema": ((60, 16, 70), (190, 90, 40)), "Music": ((40, 18, 8), (230, 120, 20)),
            "Knowledge": ((10, 30, 70), (40, 140, 200)), "Lifestyle": ((20, 60, 30), (120, 190, 60))}
    top, bot = cols.get(C.get("category", "Knowledge"), cols["Knowledge"])
    W, H = 576, 480
    im = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(im)
    for y in range(H):
        t = y / (H - 1)
        px.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bot)))
    if C.get("pack_image"):
        art = Image.open(C["pack_image"]).convert("RGB")
    else:                                   # 2x2 collage of the pack's first pictures
        art = Image.new("RGB", (640, 360))
        for i, p in enumerate(images[:4]):
            art.paste(Image.open(p).convert("RGB").crop((0, 0, 640, 360)).resize((320, 180)), ((i % 2) * 320, (i // 2) * 180))
    x0, y0, x1, y1 = 160, 66, 494, 398
    card = art.resize((x1 - x0, y1 - y0))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card.size[0] - 1, card.size[1] - 1), 22, fill=255)
    shadow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x0 + 6, y0 + 10, x1 + 6, y1 + 10), 22, fill=150)
    im.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(10)))
    im.paste(card, (x0, y0), mask)
    ImageDraw.Draw(im).rounded_rectangle((x0, y0, x1, y1), 22, outline=(255, 255, 255), width=5)
    refl = card.transpose(Image.FLIP_TOP_BOTTOM).crop((0, 0, card.size[0], 80))
    fade = Image.linear_gradient("L").resize((card.size[0], 80)).point(lambda v: max(0, 90 - v))
    im.paste(refl, (x0, y1 + 8), fade)
    im.save(out_path)
    return out_path


# ----------------------------------------------------------------------------- question index
def index_file(num, pack_name, rnd, slots, bank_counts, media_list, speech_base, lang="GBR"):
    """slots: list of dicts {kind, strings, speech, answers, tags, link, s22}; returns
    (kaq, qak, strings)."""
    strings, recs, sents, answers, subjects, tags, links = [], [], [], [], [], [], []
    for i, s in enumerate(slots):
        first_string = len(strings) + 1
        strings += s["strings"]
        s12, s16, s24 = len(tags), len(sents), len(answers)
        tags += [(t,) for t in s["tags"]]
        roles = [1, 2] if s["kind"] in ("standard", "picture") else [1]
        for j, role in enumerate(roles):
            sents.append((s["speech"], first_string + j, role, 0))
        for a in s["answers"]:
            if s["kind"] == "point_stealer":
                answers.append((a[0], a[1], 0))
            else:
                answers.append((first_string + len(roles) + a[0], a[1], 0))
        s14 = 0xFFFF
        if s["kind"] == "picture":
            s14 = len(links)
            links.append((s["link"], 1, 0))
        kind = s["kind"]
        s26 = {"standard": 8, "picture": 0, "all_that_apply": 8, "point_stealer": 12}[kind]
        b28 = {"standard": 0, "picture": 0, "all_that_apply": 8, "point_stealer": 10}[kind]
        recs.append((s["qid"], lang.encode() + b"\0", s["content"], s12, s14, s16, i,
                     2 if kind == "point_stealer" else 0, s.get("s22", 0x7FFE), s24, s26,
                     b28, 1 + i % 6, s.get("difficulty", 2), len(s["tags"]), 1 if kind == "picture" else 0,
                     len(roles), 1, len(s["answers"])))
        subjects.append((SUBJECT_ID,))
    media = media_list or []
    m = {"ver": 1, "v1002": 1002, "z": 0, "one": 1, "pack": num,
         "name": ("%s_%s" % (pack_name, rnd)).encode(),
         # identical in all 63 retail indexes; kept in case the engine checks it
         "copyright": b"(C) Copyright Relentless Software ltd., all rights reserved. ",
         "lang": lang.encode() + b"\x00\x01\x00\x00\x00",
         "sections": {0: media, 1: recs, 2: links, 3: sents, 4: answers, 5: subjects, 6: tags,
                      7: {"map": sorted((mm[0], 0) for mm in media)},
                      8: {"map": sorted((r[0], 0) for r in recs)},
                      9: {"map": [(SUBJECT_ID, 0)]},
                      10: {"map": sorted(bank_counts.items())}}}
    return buzz_index.write(m, ">"), buzz_index.write(m, "<"), strings


def credits_page(C):
    """Pack credits (rsml, the markup of the game's own credits): title, author, question
    sources with their licences (CC BY-SA sources require attribution)."""
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parts = []
    if C.get("credits") or C.get("author"):
        parts.append('<h1 align=center>%s</h1>\r\n<br />\r\n' % esc(C["text"]["menu_name"]))
        if C.get("author"):
            parts.append('<h2 align=center>Pack by</h2>\r\n<p align=center>%s</p>\r\n<br />\r\n' % esc(C["author"]))
        if C.get("credits"):
            parts.append('<h2 align=center>Questions</h2>\r\n' +
                         "".join('<p align=center>%s</p>\r\n' % esc(c) for c in C["credits"]) + '<br />\r\n')
    return ('\ufeff<rsml version="1000">\r\n\r\n' + "".join(parts) + '</rsml>').encode("utf-8")


VOICE_KINDS = {"standard": "standard", "picture": "picture", "all_that_apply": "ata", "point_stealer": "ps"}


def host_speech(C, speech_ids, questions):
    """-> {speech id: .rsf bytes} for the rounds listed in C["voice"]["rounds"].
    questions: speech-key kind -> on-screen question text per content item."""
    cfg = C.get("voice")
    if not cfg or os.environ.get("BUZZ_NO_VOICE"):
        return {}
    say, pron = cfg.get("say", {}), cfg.get("pronounce", {})
    lines = {}
    for rnd in cfg.get("rounds", ["point_stealer"]):
        kind = VOICE_KINDS[rnd]
        for b, text in enumerate(questions[kind]):
            if (kind, b) in speech_ids:
                lines[speech_ids[(kind, b)]] = say.get(text) or buzz_voice.host_line(text, pron)
    sids = sorted(lines)
    rsfs = buzz_voice.host_clips([lines[s] for s in sids], cfg.get("engine"), cfg.get("speed", 1.0),
                                 cfg.get("clone"), cfg.get("vocab"), cfg.get("warmth", 0.0))
    return dict(zip(sids, rsfs))


def build(content_path, overrides=None):
    """content_path: pack JSON. overrides: settings applied on top without editing the file
    (e.g. {"language": "ESP", "voice": None, "_out_dir": ...}) - used by buzz_engine.generate."""
    C = json.load(open(content_path, encoding="utf-8"))
    for k, v in (overrides or {}).items():
        if v is None:
            C.pop(k, None)
        else:
            C[k] = v
    num = int(C["pack_number"])
    name = C.get("round_name", "custom%d" % num).lower()
    category = C.get("category", "Knowledge")
    subject_key = C["subject_key"]
    topic = C["topic"].upper()
    slots_cfg = dict(DEFAULT_SLOTS, **C.get("slots", {}))
    img_dir = os.path.join(os.path.dirname(os.path.abspath(content_path)), "images")
    images, missing_pictures = buzz_sdi.prepare_pictures(img_dir, C["images"], os.path.join(
        C.get("_out_dir") or os.path.join(HERE, "dlc_test"), "build_%04d" % int(C["pack_number"])))
    if missing_pictures:
        print("pictures not added yet (placeholder cards used): %s" % ", ".join(missing_pictures))
    std = [[check(x[0], MAX_Q, "question")] + [check(a, MAX_A, "answer") for a in x[1:5]] for x in C["standard"]]
    pic = [[x[0], check(x[1], MAX_Q, "question")] + [check(a, MAX_A, "answer") for a in x[2:6]] for x in C["picture"]]
    ata = [[check(x[0], MAX_Q, "question")] + [(check(a, MAX_A, "answer"), bool(t)) for a, t in x[1:5]]
           for x in C["all_that_apply"]]
    pst = [[check(x[0], MAX_Q, "question")] + [int(p) for p in x[1:5]] for x in C["point_stealer"]]
    files = {}
    lang = C.get("language", LANG).upper()
    if not (len(lang) == 3 and lang.isalpha()):
        raise ValueError("language must be a 3-letter pack code like GBR, ESP, PRT, DEU")
    P = lang + "/"

    # speech: one silent clip per question (shared by its question + host-intro lines)
    # ids kept inside retail ranges (content ids < 65536, speech ids ~190000, qids like retail);
    # the first scratch build used millions and the game failed to set up the round.
    speech_base = 190000
    silent = buzz_rsf.silent_clip()
    speech_ids = {}

    def speech_for(key):
        if key not in speech_ids:
            speech_ids[key] = speech_base + len(speech_ids)
        return speech_ids[key]

    # ---- main bank: text + picture slots, interleaved T T P
    nT = max(slots_cfg["text"], len(std))
    nP = min(max(slots_cfg["picture"], len(pic)), 3 * len(pic))     # fill slots, but repeat a picture at most 3x
    order = []
    ti = pi = 0
    while ti < nT or pi < nP:
        for _ in range(2):
            if ti < nT:
                order.append(("standard", ti % len(std))); ti += 1
        if pi < nP:
            order.append(("picture", pi % len(pic))); pi += 1
    qid_base = 20000
    content_base = 64000
    bank = []
    for k, (kind, b) in enumerate(order):
        if kind == "standard":
            q = std[b]
            strs = [q[0], INTROS[k % 3] % topic] + q[1:5]
            tags = TEXT_TAGS
        else:
            q = pic[b]
            strs = [q[1], INTROS[k % 3] % topic] + q[2:6]
            tags = PIC_TAGS
        bank.append({"kind": kind, "item": b, "strings": strs, "speech": speech_for((kind, b)),
                     "answers": [(0, 5), (1, 1), (2, 1), (3, 1)], "tags": tags,
                     "qid": qid_base + k, "content": content_base + k})
    counts = {1: nT, 2: nT, 3: nT, 6: nT, 4: nT + nP, 7: nT + nP, 9: nT + nP}

    def with_media(slots):
        """media entries for the picture slots of one file: one per image, linked per slot"""
        media, idx = [], {}
        out = []
        for s in slots:
            s = dict(s)
            if s["kind"] == "picture":
                image_no = pic[s["item"]][0]
                if image_no not in idx:
                    idx[image_no] = len(media)
                    media.append([0, 0, 0, image_no, b"\x03\x10\x04\x00"])
                s["link"] = idx[image_no]
            out.append(s)
        # media key = 1-based string entry number of the first slot's host-intro line (as retail)
        entry = 0
        for s in out:
            n_entries = 2
            if s["kind"] == "picture" and media[s["link"]][0] == 0:
                media[s["link"]][0] = entry + 2
            entry += n_entries
        media = [(k, 1000 + k, 0, pn, fl) for k, _, _, pn, fl in media]
        return out, media

    text_slots = [s for s in bank if s["kind"] == "standard"]
    per_round = {"stoptheclock": text_slots, "passthebomb": text_slots, "piefight": text_slots,
                 "finalcountdown": text_slots, "highstakes": bank, "pointbuilder": bank, "fastestfinger": bank}

    # ---- All That Apply and Point Stealer sets
    nA = min(max(slots_cfg["all_that_apply"], len(ata)), 3 * len(ata))
    atp = []
    for k in range(nA):
        q = ata[k % len(ata)]
        atp.append({"kind": "all_that_apply", "strings": [q[0]] + [a for a, _ in q[1:5]],
                    "speech": speech_for(("ata", k % len(ata))),
                    "answers": [(j, 5 if ok else 1) for j, (_, ok) in enumerate(q[1:5])],
                    "tags": [8], "qid": qid_base + 1000 + k, "content": content_base + 300 + k})
    nS = min(max(slots_cfg["point_stealer"], len(pst)), 3 * len(pst))
    ps_first_frame = 1 + 5 * ((len(images) + 4) // 5)
    ps_first_block = (ps_first_frame - 1) // 5 + 1
    ps_media = [(j + 1, 1000 + j + 1, 0, j + 1, b"\x03\x10\x04\x00") for j in range(len(images))]
    pss = []
    for k in range(nS):
        b = k % len(pst)
        q = pst[b]
        pss.append({"kind": "point_stealer", "strings": [q[0]], "speech": speech_for(("ps", b)),
                    "answers": [(p - 1, 6 if j == 0 else 2) for j, p in enumerate(q[1:5])],
                    "tags": [5], "qid": qid_base + 2000 + k, "content": content_base + 400 + k,
                    "s22": ps_first_block + b})

    # ---- round files
    round_files = [r for r, _ in ROUNDS if (r != "allthatapply" or ata) and (r != "pointstealer" or pst)]
    for rnd in round_files:
        base = "%sROUNDS/%s_%s" % (P, name, rnd)
        if rnd == "allthatapply":
            kaq, qak, strs = index_file(num, name, rnd, atp, {8: nA}, None, speech_base, lang)
        elif rnd == "pointstealer":
            kaq, qak, strs = index_file(num, name, rnd, pss, {5: nS}, ps_media, speech_base, lang)
        else:
            slots, media = with_media(per_round[rnd])
            kaq, qak, strs = index_file(num, name, rnd, slots, counts, media, speech_base, lang)
        hdr, hst = encode_all(strs)
        files[base + ".kaq"], files[base + ".qak"], files[base + ".hdr"], files[base + ".hst"] = kaq, qak, hdr, hst
    files[P + "ROUNDS/stringTables.dir"] = "".join(
        "%s_%s %d\r\n" % (name, r, 10 + i) for i, r in enumerate(sorted(round_files))).encode()

    # ---- pack name text
    texts = [C["text"]["subject"], C["text"]["description"], C["text"]["menu_name"]]
    files[P + "NAMEDTEXT/default.hdr"], files[P + "NAMEDTEXT/default.hst"] = encode_all(texts)
    keys = [subject_key, "PackDescPk%dPack" % num, "PackTitlePk%dPack" % num]
    files[P + "NAMEDTEXT/default.ndx"] = ("﻿" + "".join(
        "%d %d\r\n" % (text_key_hash(k), i + 1) for i, k in enumerate(keys))).encode("utf-8")

    # ---- scripts
    for k, v in scripts(num, name, category, subject_key, C.get("rounds"), round_files).items():
        files[P + k] = v

    # ---- pictures (identical pics001/pics002 so Point Stealer blocks resolve in either)
    work = os.path.join(HERE, "dlc_test", "build_%04d" % num)
    os.makedirs(work, exist_ok=True)
    ph = buzz_sdi.placeholder_png(os.path.join(work, "frame0.png"))
    pngs = [ph] + images
    pngs += [ph] * (ps_first_frame - len(pngs))
    from buzz_sdi import make_composite
    for b, q in enumerate(pst):
        answer_pngs = [images[p - 1] for p in q[1:5]]
        comp = make_composite(answer_pngs, os.path.join(work, "ps_%02d.png" % (b + 1))) or os.path.join(work, "ps_%02d.png" % (b + 1))
        pngs += [comp] + answer_pngs
    sdi1, nframes = buzz_sdi.build_picture_set(pngs, "pics001")
    sdi2, _ = buzz_sdi.build_picture_set(pngs, "pics002")
    files[P + "QUESTIONASSETS/VIDEO/pics001.sdi"] = sdi1
    files[P + "QUESTIONASSETS/VIDEO/pics002.sdi"] = sdi2

    # ---- host speech: TTS for the configured rounds, silence for everything else
    clips = host_speech(C, speech_ids, {"standard": [q[0] for q in std], "picture": [q[1] for q in pic],
                                        "ata": [q[0] for q in ata], "ps": [q[0] for q in pst]})
    for sid in speech_ids.values():
        files[P + "QUESTIONASSETS/SPEECH/QUESTIONS/ONDEMAND/%d.rsf" % (6000000000 + sid)] = clips.get(sid, silent)

    # ---- card, credits
    card = pack_card(C, images, os.path.join(work, "pack_card.png"))
    files[P + "GRAPHICS/Pack%04dTextures.ete" % num] = buzz_ete.build_ete(card, "BZ3_InfoPackImage_Pack%04d" % num)
    files[P + "DATA/PackCredits.html"] = credits_page(C)

    # ---- container + encryption
    order_names = sorted(files)
    entries = [Entry(n, files[n], (2026, 9, 27, 12, 0, 0), 1, 0x20) for n in order_names]
    out_dir = C.get("_out_dir") or os.path.join(HERE, "dlc_test")
    os.makedirs(out_dir, exist_ok=True)
    plain = os.path.join(out_dir, "%sPACK%04d.DAT" % (lang, num))
    edat = os.path.join(out_dir, "%sPACK%04d.EDAT" % (lang, num))
    write_pak(plain, entries)
    data = open(plain, "rb").read()
    cid = "EP9000-BCES00098_00-BQC1%s%04d%s" % (lang, num, C.get("content_suffix", "CUSTM")[:5].ljust(5, "X"))
    from buzz_engine import keys
    klic = KLIC or keys.get("klic")
    enc = edat_tool.encrypt(data, edat, klic, cid)
    assert edat_tool.decrypt(enc, klic) == data
    open(edat, "wb").write(enc)
    return {"language": lang, "content_id": cid, "missing_pictures": missing_pictures, "files": len(files), "frames": nframes, "main bank": len(bank), "atp": nA, "ps": nS,
            "speech clips": len(speech_ids), "voiced": len(clips), "edat": edat}


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "content", "dlc", "hp_years1to3.json")))
