"""Buzz! Quiz World rounds and game plans - what decides which rounds come up.

How the game picks rounds (from the decompiled GLOBALSCRIPTS: gameplans.clu, gamesetup.clu,
roundtypes.clu, NAVISLIDERMENU/MENUS/menubranch_home.clu):
  * Every mode in the menu launches a GAME PLAN DESIGN by name (Standard -> GAMEPLAN_STANDARD_4P,
    Short, Long, Action, Serious, Pick-as-you-go, and the "Pack Game" menu -> GAMEPLAN_PACK_4P/8P
    with the pack's p<N>PackGame4p/8p game). The pack's own AddGamePlanRounds list is NOT used.
  * A design is a list of steps: a fixed round (AddGamePlanDesignRound), or "one round picked at
    random from phase set n" (AddGamePlanDesignPhase). Phase sets are declared first
    (CreateGamePlanPhaseSet(n) + AddGamePlanDesignPhasedRound(type) ...).
    e.g. PACK_4P = PointBuilder, 2 x random{Eliminator, BoilingPoint, PieFight, FastestFinger},
         2 x random{PassTheBomb, PointStealerMix, FastestFinger, TriggerFinger}, FinalCountdown.
  * AddGamePlanDesignChoice("SUBJECT"|"ROUND"): what the players pick between rounds.
So controlling "which rounds come up" = writing these designs (plans.py).
"""

# Playable round types (AddRoundType in roundtypes.clu). "uses" = which question kinds of a pack
# feed the round; "min" = questions a round needs (AddRoundType iteration counts / retail
# AddRound counts), used for validation.
ROUND_TYPES = {
    "PointBuilder":       {"name": "Point Builder",   "uses": ["standard", "picture"], "min": 8},
    "FastestFingerFirst": {"name": "Fastest Finger",  "uses": ["standard", "picture"], "min": 8},
    "PassTheBomb":        {"name": "Pass the Bomb",   "uses": ["standard"], "min": 30},
    "PieFight":           {"name": "Pie Fight",       "uses": ["standard"], "min": 30},
    "PointStealerMix":    {"name": "Point Stealer",   "uses": ["point_stealer"], "min": 8},
    "BetIt":              {"name": "High Stakes",     "uses": ["standard", "picture"], "min": 6},
    "FinalCountdown":     {"name": "Final Countdown", "uses": ["standard"], "min": 30},
    "Eliminator":         {"name": "Over the Edge",   "uses": ["standard"], "min": 30},
    "OnTheSpot":          {"name": "On the Spot",     "uses": ["standard"], "min": 8},
    "BoilingPoint":       {"name": "Boiling Point",   "uses": ["standard"], "min": 30},
    "TriggerFinger":      {"name": "Stop the Clock",  "uses": ["standard"], "min": 8},
    # custom round types added by buzz_engine.custom_rounds (need the engine GLOBALSCRIPTS).
    # hidden = unfinished: not offered in the app or the round lists (packs that already name it
    # still build)
    "SecondBest":         {"name": "Second Best",     "uses": ["standard", "picture"], "min": 8, "custom": True,
                           "hidden": True},
}


def selectable():
    """Round types offered to users (unfinished custom rounds left out)."""
    return {k: v for k, v in ROUND_TYPES.items() if not v.get("hidden")}
ALIASES = {n.lower().replace(" ", ""): k for k, v in ROUND_TYPES.items() for n in (k, v["name"])}
ALIASES.update({"highstakes": "BetIt", "overtheedge": "Eliminator", "stoptheclock": "TriggerFinger",
                "pointstealer": "PointStealerMix", "fastestfinger": "FastestFingerFirst"})


def round_type(name):
    k = ALIASES.get(str(name).lower().replace(" ", "").replace("_", "").replace("-", ""))
    if not k:
        raise ValueError("unknown round %r (known: %s)" % (name, ", ".join(v["name"] for v in selectable().values())))
    return k


# Menu modes -> design names (4-player / 8-player where the game has both)
MODES = {
    "standard": ("GAMEPLAN_STANDARD_4P", "GAMEPLAN_STANDARD_8P"),
    "short": ("GAMEPLAN_SHORT_4P", "GAMEPLAN_SHORT_8P"),
    "long": ("GAMEPLAN_LONG_4P", "GAMEPLAN_LONG_8P"),
    "action": ("GAMEPLAN_ACTION_4P", "GAMEPLAN_ACTION_8P"),
    "serious": ("GAMEPLAN_SERIOUS_4P", None),
    "pack": ("GAMEPLAN_PACK_4P", "GAMEPLAN_PACK_8P"),
}


def parse_plan(spec):
    """A user plan -> normalised steps.
    spec: list of round names and {"random": [names]} (one round picked at random each time),
    or {"rounds": [...], "choice": "SUBJECT"|"ROUND", "no_easy": bool}.
    FinalCountdown is appended if missing (every retail plan ends with it)."""
    if isinstance(spec, dict):
        rounds, choice, no_easy = spec["rounds"], spec.get("choice", "SUBJECT"), spec.get("no_easy", False)
    else:
        rounds, choice, no_easy = spec, "SUBJECT", False
    steps = []
    for r in rounds:
        if isinstance(r, dict):
            steps.append(("random", [round_type(x) for x in r["random"]]))
        else:
            steps.append(("round", round_type(r)))
    if not steps or steps[-1] != ("round", "FinalCountdown"):
        steps = [s for s in steps if s != ("round", "FinalCountdown")] + [("round", "FinalCountdown")]
    return {"choice": choice.upper(), "no_easy": bool(no_easy), "steps": steps}


def plan_calls(name, plan):
    """Lua calls (as (function, args) tuples) that define one game plan design."""
    calls = [("CreateGamePlanDesign", (name,))]
    if plan["no_easy"]:
        calls.append(("SetNoEasyQuestions", ()))
    calls.append(("AddGamePlanDesignChoice", (plan["choice"],)))
    sets = []
    for kind, v in plan["steps"]:
        if kind == "random" and v not in sets:
            sets.append(v)
    for i, s in enumerate(sets, 1):
        calls.append(("CreateGamePlanPhaseSet", (i,)))
        calls += [("AddGamePlanDesignPhasedRound", (r,)) for r in s]
    pick = 3 if plan["choice"] == "ROUND" else 0          # retail: 3 in pick-as-you-go designs
    for kind, v in plan["steps"]:
        if kind == "random":
            calls.append(("AddGamePlanDesignPhase", (sets.index(v) + 1, pick)))
        else:
            calls.append(("AddGamePlanDesignRound", (v, 3 if v == "FinalCountdown" else pick)))
    calls.append(("SaveGamePlanDesign", ()))
    return calls


def describe(plan):
    out = []
    for kind, v in plan["steps"]:
        out.append(ROUND_TYPES[v]["name"] if kind == "round" else
                   "random(" + " / ".join(ROUND_TYPES[x]["name"] for x in v) + ")")
    return " -> ".join(out)
