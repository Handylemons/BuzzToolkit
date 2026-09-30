"""Custom rounds: new round types added to the game from the user's own files.

A Buzz round is a Lua start script + a question-loop script in GLOBALSCRIPTS, registered with
AddRoundType. A custom round here reuses an existing round's loop and adds its own rule through a
hook, so none of the game's code is copied:

SECOND BEST (idea from Taskmaster's "Tall Poppy")
  Fastest Finger scoring (faster correct answers score more), with one catch: the FASTEST correct
  answer scores 0 if those points would put that player in 1st place overall (or keep them there).
  Every other correct answer scores as normal, the leader included - so the leader keeps scoring,
  just never top points, and 2nd place is tempted to hold back.

Installed pieces (all rebuilt from the user's files, originals backed up):
  * GLOBALSCRIPTS: secondbestroundstart.clu + secondbestround.clu (ours), and AddRoundType for
    "SecondBest" appended to the generated gameplans.clu (the game runs it right after its own
    round-type list)
  * Patched/INE.EDAT (+ ESP/PRT): menu text RoundNameSecondBest = "Second Best" + Custom Game subtitles
  * Custom Game menu: a Second Best on/off entry (added to the menu's round table at start-up)
Every scoring decision is printed to the TTY log ([SecondBest] ...).
"""
import io
import os
import shutil
import zipfile

ROUND_TYPE_ID = 20          # retail uses 1-19

START_LUA = r'''
-- Second Best: start script (intro, then the question loop "SecondBestRound")
function startScript()
  coroutineScript = coroutine.create(function()
    BuzzEngine_SecondBestRoundNo = GetCurrentRoundInGame()
    SetFollowOnScript("SecondBestRound")
    if not GetShouldSkipNextRound() then
      local notFirst = GetCurrentRoundInGame() ~= 1
      DoStandardPreIntroMultiplayerRoundSetup(nil, notFirst)
      DoRoundIntroduction("FastestFingerFirst", "802391300", CurrentRoundMayContainAssets())
      DoStandardPostIntroMultiplayerRoundSetup()
    end
  end)
end
'''

ROUND_LUA = r'''
-- Second Best: Fastest Finger's question loop + the Second Best scoring rule, applied right
-- after each question is judged (where Pass the Bomb and Boiling Point adjust scores too).
IncludeScript("FastestFingerFirstRoundPS3")

function BuzzEngine_ApplySecondBest()
  local n = GetNumberOfContestantsCurrentlyPlayingIncludingLeftPlayers()
  local before, gain, fastest, bestTime = {}, {}, nil, nil
  for i = 1, n do
    before[i] = GetContestantGameScore(i)
    gain[i] = GetContestantIterationScore(i)
    local t = GetContestantAnswerTimeTakenSeconds(i) or 999
    print(string.format("[SecondBest] player %d: total %d, this question %d, time %.2f", i, before[i], gain[i], t or -1))
    if gain[i] > 0 and not HasContestantLeftGame(i) then
      if fastest == nil or gain[i] > gain[fastest] or (gain[i] == gain[fastest] and t < bestTime) then
        fastest, bestTime = i, t
      end
    end
  end
  if fastest == nil then return end
  local mine = before[fastest] + gain[fastest]
  for j = 1, n do
    if j ~= fastest and before[j] + gain[j] >= mine then
      print(string.format("[SecondBest] fastest player %d stays behind (%d) - keeps %d", fastest, mine, gain[fastest]))
      return
    end
  end
  print(string.format("[SecondBest] fastest player %d would lead with %d - scores 0 instead of %d", fastest, mine, gain[fastest]))
  SetContestantIterationScore(fastest, 0)
  CalculatePositions()
end

local ffStart = startScript
function startScript()
  if AssetPresentation ~= nil and AssetPresentation.OnJudgementEnded ~= nil and not AssetPresentation.BuzzEngineWrapped then
    local original = AssetPresentation.OnJudgementEnded
    AssetPresentation.OnJudgementEnded = function(...)
      local r = original(...)
      if BuzzEngine_SecondBestRoundNo ~= nil and GetCurrentRoundInGame() == BuzzEngine_SecondBestRoundNo then
        BuzzEngine_ApplySecondBest()
      end
      return r
    end
    AssetPresentation.BuzzEngineWrapped = true
  end
  ffStart()
end
'''

REGISTER_LUA = r'''
-- Buzz engine custom round types
AddRoundType(%d, "SecondBest", "RoundNameSecondBest", 3, "SecondBestRoundStart", "RoundPlanPreferAssets",
  "AnswerOrderRANDOM", "PointsBased", "FastestFingerFirst", "Normal", RoundThemeTuneNames.FastestFingerFirst,
  "MusicStartBedFF", "802442200", 8, 0, 1, 0, 2, 1, 2)

-- Custom Game menu: the round list is a Lua table built by Menu.Home.DefineDefaultGameStates (the
-- menu scripts load at the splash screen, before this runs). Add our rounds before Final
-- Countdown; the menu turns enabled entries into GAMEPLAN_CUSTOM by round id. The saved on/off
-- state for our ids is kept in Lua (the game's own store is sized for the retail rounds).
BuzzEngineCustomRounds = {
  {id = %d, title = "RoundNameSecondBest", on = "MainMenu_CustomGame_SecondBestOn_Subtitle",
   off = "MainMenu_CustomGame_SecondBestOff_Subtitle"},
}
BuzzEngineCustomEnabled = BuzzEngineCustomEnabled or {}
if CustomGame ~= nil and not BuzzEngineCustomGameWrapped then
  local getR, setR = CustomGame.GetCustomGameRoundByType, CustomGame.SetCustomGameRoundByType
  CustomGame.GetCustomGameRoundByType = function(p, id)
    if id >= 20 then return BuzzEngineCustomEnabled[p .. ":" .. id] == true end
    return getR(p, id)
  end
  CustomGame.SetCustomGameRoundByType = function(p, id, on)
    if id >= 20 then BuzzEngineCustomEnabled[p .. ":" .. id] = (on == true) return end
    return setR(p, id, on)
  end
  BuzzEngineCustomGameWrapped = true
end
if Menu ~= nil and Menu.Home ~= nil and Menu.Home.DefineDefaultGameStates ~= nil then
  if not Menu.Home.BuzzEngineWrapped then
    local define = Menu.Home.DefineDefaultGameStates
    Menu.Home.DefineDefaultGameStates = function(...)
      local r = define(...)
      for _, key in ipairs({"CustomGameState_4P", "CustomGameState_8P"}) do
        local st, players = Menu.Home[key], (key == "CustomGameState_4P") and 4 or 8
        if st ~= nil then
          for _, c in ipairs(BuzzEngineCustomRounds) do
            local exists = false
            for _, e in ipairs(st) do if e._RoundID == c.id then exists = true end end
            if not exists then
              table.insert(st, #st, {_DisplayTitle = c.title, _ToggleStrings = {c.on, c.off}, _RoundID = c.id,
                                     _IsEnabled = CustomGame.GetCustomGameRoundByType(players, c.id)})
            end
          end
        end
      end
      return r
    end
    Menu.Home.BuzzEngineWrapped = true
    print("[BuzzEngine] custom rounds added to the Custom Game menu")
  end
else
  print("[BuzzEngine] Custom Game menu not loaded yet - custom rounds not added to it")
end
''' % (ROUND_TYPE_ID, ROUND_TYPE_ID)

SCRIPTS = {"Global/SCRIPTS/secondbestroundstart.clu": START_LUA, "Global/SCRIPTS/secondbestround.clu": ROUND_LUA}
TEXT = {"RoundNameSecondBest": "Second Best",
        # menu subtitles use a literal "\\n" for the line break, like the game's own
        "MainMenu_CustomGame_SecondBestOn_Subtitle":
            "Currently: On\\nThe fastest right answer wins big - unless it would put you in first place!",
        "MainMenu_CustomGame_SecondBestOff_Subtitle":
            "Currently: Off\\nThe fastest right answer wins big - unless it would put you in first place!"}
LANG_EDATS = ("INE", "ESP", "PRT")


def script_entries(template):
    """Compiled custom-round scripts as buzz_pak entries (attributes copied from template)."""
    import buzz_lua
    from buzz_pak import Entry
    return [Entry(name, buzz_lua.compile_lua(src), template.date_time, template.internal_attr, template.external_attr, 0)
            for name, src in SCRIPTS.items()]


def add_text(edat_path, klic):
    """Add the custom round names to a language EDAT's menu text (in place; backup kept)."""
    import buzz_text
    import edat_tool
    from buzz_pak import Entry, read_pak, write_pak
    from build_pack import text_key_hash
    raw = open(edat_path, "rb").read()
    cid = raw[0x10:0x40].rstrip(b"\0").decode()
    plain = edat_tool.decrypt(raw, klic)
    tmp = edat_path + ".tmp"
    open(tmp, "wb").write(plain)
    entries = read_pak(tmp)
    os.remove(tmp)
    by = {e.name.split("/", 1)[1]: e for e in entries}
    lang = entries[0].name.split("/")[0]
    hdr, hst, ndx = by["NAMEDTEXT/default.hdr"], by["NAMEDTEXT/default.hst"], by["NAMEDTEXT/default.ndx"]
    texts = [t[1] if isinstance(t, tuple) else t for t in buzz_text.decode_all(hdr.data, hst.data)]
    ndx_text = ndx.data.decode("utf-8-sig")
    lines = [l for l in ndx_text.split("\r\n") if l.strip()]
    have = {int(l.split()[0]) for l in lines}
    added = []
    for key, value in TEXT.items():
        h = text_key_hash(key)
        if h in have:
            continue
        texts.append(value)
        lines.append("%d %d" % (h, len(texts)))
        added.append(key)
    if not added:
        return []
    new_hdr, new_hst = buzz_text.encode_all(texts)
    new = {"NAMEDTEXT/default.hdr": new_hdr, "NAMEDTEXT/default.hst": new_hst,
           "NAMEDTEXT/default.ndx": ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8")}
    out = [Entry(e.name, new.get(e.name.split("/", 1)[1], e.data), e.date_time, e.internal_attr, e.external_attr, e.volume)
           for e in entries]
    write_pak(tmp, out, tail_pad=16)          # update-packer layout (as GLOBALSCRIPTS)
    data = open(tmp, "rb").read()
    os.remove(tmp)
    backup = edat_path + ".before_buzz_toolkit"
    if not os.path.exists(backup):
        shutil.copy(edat_path, backup)
    enc = edat_tool.encrypt(data, edat_path, klic, cid)
    assert edat_tool.decrypt(enc, klic) == data
    open(edat_path, "wb").write(enc)
    return added


def install(rpcs3):
    """Install the custom rounds into this RPCS3's game update folder."""
    from buzz_engine import keys, plans
    patched = os.path.join(rpcs3, "dev_hdd0", "game", "BCES00645", "USRDIR", "Patched")
    done = []
    target = os.path.join(patched, "GLOBALSCRIPTS.SDAT")
    base = target + ".before_engine"
    if not os.path.exists(base):
        shutil.copy(target, base)
    out = target + ".new"
    plans.build_globalscripts(base, out, {}, custom_rounds=True)
    os.replace(out, target)
    done.append("GLOBALSCRIPTS: Second Best round scripts + round type")
    for lang in LANG_EDATS:
        p = os.path.join(patched, lang + ".EDAT")
        if os.path.exists(p):
            added = add_text(p, keys.get("klic"))
            done.append("%s.EDAT: %s" % (lang, "added " + ", ".join(added) if added else "already has the round names"))
    return done
