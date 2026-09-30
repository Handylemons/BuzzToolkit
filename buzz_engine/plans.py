"""Game plans: write which rounds come up, globally (menu modes) and per pack.

Global: build a patched GLOBALSCRIPTS whose Global/SCRIPTS/gameplans.clu is regenerated from the
retail designs (default_plans.json, extracted from the game) with the user's overrides applied.
The rest of the archive (incl. our svoLogin patch) is kept byte-for-byte.

Per pack (experimental, needs the engine GLOBALSCRIPTS): the generated gameplans.clu also wraps
Tickets.CreateGameStartTicket, which the menu calls as (plan, game, flag) when a game starts.
When the "Pack Game" menu launches GAMEPLAN_PACK_4P/8P for a pack that registered its own
line-up in BuzzEnginePackPlans[<game name>], the wrapper builds that design on the spot and
starts it instead. Packs without a registration (and games without the engine GLOBALSCRIPTS)
behave exactly as before.
"""
import json
import os

import buzz_lua
from buzz_pak import Entry, read_pak, write_pak

from .rounds import MODES, parse_plan, plan_calls

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEPLANS = "Global/SCRIPTS/gameplans.clu"


CACHE = os.path.join(HERE, "cache", "default_plans.json")


def decode_calls(clu):
    """A flat Lua call-list chunk (like gameplans.clu) -> [(function, args)] without a
    decompiler: follow GETGLOBAL/LOADK into registers and read each CALL."""
    import lua51_find
    main = [f for f in lua51_find.functions(clu) if f["path"] == []][0]
    K, R, out = main["consts"], {}, []
    for _, ins in main["code"]:
        op, a, b, c = lua51_find.decode(ins)
        bx = (ins >> 14) & 0x3FFFF
        if op == "GETGLOBAL":
            R[a] = ("fn", K[bx])
        elif op == "LOADK":
            v = K[bx]
            R[a] = int(v) if isinstance(v, float) and v == int(v) else v
        elif op == "CALL":
            fn = R.get(a, ("fn", "?"))[1]
            out.append((fn.decode() if isinstance(fn, bytes) else fn,
                        [x.decode() if isinstance(x, bytes) else x for x in (R.get(a + 1 + i) for i in range(b - 1))]))
    return out


def default_plans(base_sdat=None):
    """The game's own plan designs, read from the user's GLOBALSCRIPTS (cached locally)."""
    if os.path.exists(CACHE) and not base_sdat:
        with open(CACHE) as f:
            return json.load(f)
    if not base_sdat:
        raise ValueError("game plans not read yet: build GLOBALSCRIPTS once with the user's file")
    entries = {e.name: e.data for e in read_pak(base_sdat)}
    designs, cur = {}, None
    for fn, args in decode_calls(entries[GAMEPLANS]):
        if fn == "CreateGamePlanDesign":
            cur = args[0]
            designs[cur] = []
        if cur:
            designs[cur].append([fn, args])
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(designs, f, indent=0)
    return designs


def _lua_call(fn, args):
    return buzz_lua.call(fn, *args)


HOOK = r'''
-- Buzz engine: per-pack game plans (see buzz_engine/plans.py)
function BuzzEngineMakePlan(t)
  CreateGamePlanDesign(t.name)
  if t.noeasy then SetNoEasyQuestions() end
  AddGamePlanDesignChoice(t.choice)
  for i, set in ipairs(t.sets) do
    CreateGamePlanPhaseSet(i)
    for _, r in ipairs(set) do AddGamePlanDesignPhasedRound(r) end
  end
  for _, s in ipairs(t.steps) do
    if s[1] == "p" then AddGamePlanDesignPhase(s[2], s[3]) else AddGamePlanDesignRound(s[2], s[3]) end
  end
  SaveGamePlanDesign()
  t.made = true
end
if Tickets ~= nil and Tickets.CreateGameStartTicket ~= nil and BuzzEngineTicketHook == nil then
  BuzzEngineTicketHook = Tickets.CreateGameStartTicket
  Tickets.CreateGameStartTicket = function(plan, game, flag)
    if (plan == "GAMEPLAN_PACK_4P" or plan == "GAMEPLAN_PACK_8P") and BuzzEnginePackPlans ~= nil then
      local t = BuzzEnginePackPlans[game]
      if t ~= nil then
        if not t.made then BuzzEngineMakePlan(t) end
        plan = t.name
      end
    end
    return BuzzEngineTicketHook(plan, game, flag)
  end
end
'''


def gameplans_source(overrides=None, hook=True, base_sdat=None):
    """overrides: {mode or design name: plan spec} (see rounds.parse_plan)."""
    designs = default_plans(base_sdat)
    for key, spec in (overrides or {}).items():
        plan = parse_plan(spec)
        names = [n for n in MODES.get(key.lower(), (key,)) if n]
        for n in names:
            designs[n] = [[fn, list(a)] for fn, a in plan_calls(n, plan)]
    src = "".join(_lua_call(fn, a) for calls in designs.values() for fn, a in calls)
    return src + (HOOK if hook else "")


def build_globalscripts(base_path, out_path, overrides=None, hook=True, custom_rounds=False):
    """Copy of base_path (the user's current GLOBALSCRIPTS .PAK/.SDAT, plain) with a regenerated
    gameplans.clu (+ the custom round types and their scripts when custom_rounds)."""
    entries = read_pak(base_path)
    src = gameplans_source(overrides, hook, base_path if not os.path.exists(CACHE) else None)
    extra = []
    if custom_rounds:
        from . import custom_rounds as cr
        src = cr.REGISTER_LUA + src
        extra = [e for e in cr.script_entries(next(e for e in entries if e.name == GAMEPLANS))]
    clu = buzz_lua.compile_lua(src)
    names = {e.name for e in extra}
    out, found = [], False
    for e in entries:
        if e.name in names:
            continue
        if e.name == GAMEPLANS:
            e = Entry(e.name, clu, e.date_time, e.internal_attr, e.external_attr, e.volume)
            found = True
        out.append(e)
    out += extra
    if not found:
        raise ValueError("%s has no %s" % (base_path, GAMEPLANS))
    write_pak(out_path, out, tail_pad=16)                  # as the disc GLOBALSCRIPTS.PAK
    return src


def pack_plan_lua(game_name, spec):
    """Lua for a pack's roundsetup script: registers its own line-up for the Pack Game menu."""
    plan = parse_plan(spec)
    calls = plan_calls("GAMEPLAN_" + game_name.upper(), plan)
    sets, steps = [], []
    cur = None
    for fn, a in calls:
        if fn == "CreateGamePlanPhaseSet":
            cur = []
            sets.append(cur)
        elif fn == "AddGamePlanDesignPhasedRound":
            cur.append(a[0])
        elif fn == "AddGamePlanDesignPhase":
            steps.append('{"p", %d, %d}' % a)
        elif fn == "AddGamePlanDesignRound":
            steps.append('{"r", "%s", %d}' % a)
    lua_sets = "{" + ", ".join("{" + ", ".join('"%s"' % r for r in s) + "}" for s in sets) + "}"
    return ('BuzzEnginePackPlans = BuzzEnginePackPlans or {}\n'
            'BuzzEnginePackPlans["%s"] = {name = "GAMEPLAN_%s", choice = "%s", noeasy = %s, sets = %s, steps = {%s}}\n'
            % (game_name, game_name.upper(), plan["choice"], "true" if plan["no_easy"] else "false",
               lua_sets, ", ".join(steps)))
