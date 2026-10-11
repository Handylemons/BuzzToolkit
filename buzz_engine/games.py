"""The Buzz! Quiz World builds the toolkit can target, and what differs between them.

A pack is only installable if it names the right DLC container, carries a content id naming that
same container, and uses a language code the build actually ships. Those three things vary per
build and nothing else does - the klicensee and the whole online stack are shared - so they live
here rather than being hardcoded in the builder and the installer.

Verified on 2026-10-11 by booting both builds and reading what the game asks for:
BCES00645 and BCES00647 report the SAME klicensee, and the same Medius appId (22814), so a pack
built for one decrypts on the other and one server serves both.
"""
import os

# Each build's packs install under a shared "Buzz!: Quiz TV" game-data title, NOT the Quiz World
# title - and the id of that title differs per build. The game resolves its DLC path from
# cellGameDataCheckCreate2(dirName=<dlc_title>); if that directory has no PARAM.SFO the check
# fails and the game probes the literal string "DLCHDD_PATH_NOT_SET_YET/", finding no pack at all.
GAMES = {
    "BCES00644": {
        "name": "Buzz!: Quiz World (En, Fr, De, It, Nl)",
        "dlc_title": "BCES00098",
        "languages": ["GBR", "FRA", "DEU", "ITA", "NLD"],
        "disc_languages": ["INE", "FRA", "DEU", "ITA", "NLD"],
        "default_language": "GBR",
    },
    "BCES00645": {
        "name": "Buzz!: Quiz World (En, Es, Pt)",
        "dlc_title": "BCES00098",
        "languages": ["GBR", "ESP", "PRT"],
        "disc_languages": ["INE", "ESP", "PRT"],
        "default_language": "GBR",
    },
    "BCES00647": {
        "name": "Buzz!: Quiz World (Pl, Ru, El, Hr, Cs)",
        "dlc_title": "BCES00195",
        "languages": ["RUS", "POL", "GRC", "CRO", "CZE"],
        "disc_languages": ["RUS", "POL", "GRC", "CRO", "CZE"],
        # the build ships five, but runs Russian regardless of RPCS3's system language
        "default_language": "RUS",
    },
}
DEFAULT_GAME = "BCES00645"
DLC_TITLE_NAME = "Buzz!: Quiz TV"          # the TITLE field inside the container's PARAM.SFO


def game_for_language(lang):
    """-> title id of the build that ships this pack language, or None if several do.

    GBR is shipped by both BCES00644 and BCES00645, so this is genuinely ambiguous for English -
    use container_for_language() when all you need is where to install, which is well defined
    even then because those two builds share a container.
    """
    lang = (lang or "").upper()
    hits = [t for t, g in GAMES.items() if lang in g["languages"]]
    return hits[0] if len(hits) == 1 else None


def container_for_language(lang):
    """-> the DLC container this pack language installs into, or None if the language is unknown
    or its builds disagree. Several builds may share one container, and then the language is
    still unambiguous for installing even though the build is not."""
    lang = (lang or "").upper()
    cs = {g["dlc_title"] for g in GAMES.values() if lang in g["languages"]}
    return cs.pop() if len(cs) == 1 else None


def resolve(pack=None, lang=None, rpcs3=None):
    """-> (title id, dlc_title) for a pack.

    An explicit `game` or `dlc_title` on the pack wins. Otherwise the language picks the build,
    since the two tested builds share no language code. Failing that, whichever build is actually
    installed in RPCS3 decides, and only then the default.
    """
    pack = pack or {}
    if pack.get("dlc_title"):                       # caller was explicit about the container
        t = next((k for k, g in GAMES.items() if g["dlc_title"] == pack["dlc_title"]), None)
        return t, pack["dlc_title"]
    if pack.get("game") in GAMES:
        return pack["game"], GAMES[pack["game"]]["dlc_title"]
    lang = (lang or pack.get("language") or "").upper()
    t = game_for_language(lang)
    if t:
        return t, GAMES[t]["dlc_title"]
    c = container_for_language(lang)
    if c:
        # the language does not name one build, but every build that has it agrees on the
        # container - which is all the installer needs. Name a build only if one is installed.
        here = [g for g in installed_games(rpcs3) if GAMES[g]["dlc_title"] == c]
        return (here[0] if here else None), c
    found = installed_games(rpcs3)
    if len(found) == 1:                     # only one build here, so there is no ambiguity
        return found[0], GAMES[found[0]]["dlc_title"]
    if not lang:
        return DEFAULT_GAME, GAMES[DEFAULT_GAME]["dlc_title"]
    # Guessing here produces a pack that installs into a container the game never reads, which
    # looks like "the pack just does not appear" - so say so instead.
    raise ValueError(
        "no known Buzz build uses pack language %r, so there is no way to tell which DLC "
        "container it belongs in. Known codes: %s. (INE is the English code used by the DISC "
        "archive; English DLC packs use GBR.) Set \"game\" or \"dlc_title\" on the pack to "
        "override." % (lang, ", ".join(sorted(all_languages()))))


def installed_games(rpcs3):
    """-> [title id] of the Buzz builds actually present in this RPCS3.

    Looks for the build itself, not its DLC container: BCES00644 and BCES00645 share one
    container, so the container's presence cannot tell them apart. A build counts as present if
    its game-data/update folder exists under dev_hdd0/game, or a disc is registered for it in
    config/games.yml (RPCS3 keeps ISOs there rather than in dev_hdd0).
    """
    if not rpcs3:
        return []
    out = []
    reg = ""
    for y in (os.path.join(rpcs3, "config", "games.yml"), os.path.join(rpcs3, "games.yml")):
        if os.path.isfile(y):
            try:
                with open(y, encoding="utf-8", errors="replace") as f:
                    reg += f.read()
            except OSError:
                pass
    for t in GAMES:
        if os.path.isdir(os.path.join(rpcs3, "dev_hdd0", "game", t)) or (t + ":") in reg:
            out.append(t)
    return sorted(out)


def installed_containers(rpcs3):
    """-> [dlc title] of the DLC containers that exist in this RPCS3."""
    if not rpcs3:
        return []
    seen = {g["dlc_title"] for g in GAMES.values()}
    return sorted(d for d in seen
                  if os.path.isdir(os.path.join(rpcs3, "dev_hdd0", "game", d)))


def ensure_dlc_container(rpcs3, dlc_title):
    """Create the DLC game-data title if it is not there, and return its path.

    Making the folder is not enough: without a PARAM.SFO the game's data check fails and no pack
    in it is ever seen. An existing PARAM.SFO is left alone - the real one may carry store
    metadata we should not clobber.
    """
    import buzz_pkg
    d = os.path.join(rpcs3, "dev_hdd0", "game", dlc_title)
    os.makedirs(os.path.join(d, "USRDIR"), exist_ok=True)
    sfo = os.path.join(d, "PARAM.SFO")
    if not os.path.exists(sfo):
        with open(sfo, "wb") as f:
            f.write(buzz_pkg.param_sfo([
                ("CATEGORY", "GD"), ("PARENTAL_LEVEL", 5), ("PS3_SYSTEM_VER", "02.4000"),
                ("TITLE", DLC_TITLE_NAME), ("TITLE_ID", dlc_title), ("VERSION", "01.00")]))
    return d


def all_languages():
    """Every pack language code the toolkit can actually target."""
    return sorted({l for g in GAMES.values() for l in g["languages"]})


def languages(game=None):
    return GAMES.get(game or DEFAULT_GAME, GAMES[DEFAULT_GAME])["languages"]
