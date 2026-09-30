# Buzz Toolkit roadmap

## Done

* Pack generator: questions (files, online sources, hand-written), pictures, Point Stealer picture
  answers, All That Apply, per-pack running order (tested in-game), language selection, host
  voice on/off, **Generate → PKG** (own PKG writer; confirmed installing and playing on RPCS3).
* Host voice: trained on the host's own lines from your disc; every line speech-checked; retail
  loudness; own ATRAC3 encoder with Sony-style bit allocation and gain control.
* Online server: self-hosted MyBuzz (online quizzes, leaderboards, buddies), start/stop and
  friend setup in the app, **Publish to MyBuzz**.
* No game files shipped: keys, plans and voices come from each user's own copy.
* **Second Best**, the first brand-new round (see below), is built and its scoring rule is
  confirmed from the game log, but it is **not offered in this release** (hidden from round
  selection until it is finished).

## Next

0. **Finish Second Best and offer it in round selection.** Hidden in 0.1.0
   (`"hidden": True` in `buzz_engine/rounds.py`). Remaining: the Custom Game menu entry (parked). The menu's round list is built by
   `Menu.Home.DefineDefaultGameStates`, which is not loaded yet when the toolkit's start-up script
   runs (log: `[BuzzEngine] Custom Game menu not loaded yet`). Fix: attach the menu entry once the
   menu script has loaded (hook `IncludeScript` for `MenuBranch_Home`, or retry from the launch
   hook), then re-test. Also: remember its on/off setting between sessions.

1. **PKG on real hardware**: test on a HEN/CFW PS3 (RPCS3 confirmed).
2. **Toolkit polish**: a first-run wizard, progress for long
   voice builds, backup/restore of every game file the toolkit changes.
3. **Picture-set header built from scratch** (the last built-in constant from the game's encoder).
4. **More languages for the trained voice** (trainer `--lang`, multilingual base model).
5. **Online matches**: live games against remote friends (the Medius lobby / game-room stage the
   game never reaches today).

## New question and round formats

Buzz's round types are fixed in the game's code, but a lot of popular quiz formats can be built
from question styles, media and running orders. Grouped by what they need:

### Content only (no game research needed)

| Format | How it maps onto Buzz |
|---|---|
| **Themed round presets** ("Millionaire ladder", "University Challenge", "Speed round") | Running orders + question difficulty; e.g. easy → hard ordering for a ladder feel |
| **Odd one out, Anagrams, Missing vowels** (*Only Connect*), **Fill in the blank**, **What comes next?** | Question templates that generate the four answers |
| **Which year? / Real or fictional? / Spell it right** | Templates (these exist as categories on the disc) |
| **Emoji puzzles, logos, famous faces, flags, maps ("Where is this?")** | Picture questions, with generators from open data (Wikidata / Wikimedia; mind image rights) |
| **Jeopardy-style reversed clues** | "This is the answer, what was the question?" wording |
| **Family Fortunes / Feud "top answer"** | "What was the most popular answer?" four-choice questions from survey data |
| **Higher or lower** on numbers (populations, heights, box office) | Four-choice ranges ("Under 1m / 1-5m / …") from open data |
| **Pack-from-anything**: paste an article or notes and get questions | Language-model question writer (optional, uses your own API key) |

### Needs a little game research

| Format | What has to be found out |
|---|---|
| **True or False** (and two-way *Higher or Lower*) | Whether the game accepts two-answer questions (the index stores an answer count; untested below 4). Fallback: "True / False" plus two joke answers. |
| **Picture reveal** (*Catchphrase*, *Tipping Point*-style): pixelate, blocks, sliding blocks, zoom out, swirl, distort, fade | The game already has these seven reveal effects; find the per-question field that picks one |
| **Name that tune / music intro rounds** | Music questions exist in retail packs (stereo ATRAC3 clips); needs a stereo encoder |
| **Movie and TV clip questions** | Video questions exist (Sofdec clips); extend the picture writer to video |
| **Sequential "ladder" rounds** | The online (UCQ) round types play questions in order; check whether packs can use them |
| **Custom host lines**: player names, round intros, reactions | The disc has name and commentary tables; with the trained voice, new lines could be spoken |

### Brand-new rounds (Taskmaster-style)

Each Buzz round is a Lua script in the game's GLOBALSCRIPTS (`passthebombround.clu`,
`fastestfingerfirstroundps3.clu`, ...) that directs ready-made game functions. The toolkit already
rebuilds GLOBALSCRIPTS from the user's own copy, so a new round = a new generated round script,
registered as a round type and dropped into running orders. The game's code has the building
blocks (names found in the EBOOT; each still to be confirmed in-game):

* scores: `GetContestantGameScore`, `GetContestantRoundScore`, `SetContestantIterationScore`, `ClearContestantScoreToZero`
* time: `GetTimeNow`, `GetTimeSeconds`, `GetTimeDifference`, `GetContestantLastAnswerInputTime`, `GetContestantAnswerTimeTakenSeconds`
* raw buttons: `GetButtonPress`, `IsButtonPressed`, `WasButtonPressed`, `WhichPadButtonWasPressed`, `ClearContestantLastButtonPresses`, `ActiveContestantBuzzed`
* screen: `SetTextString`, `ShowTextOnPodium` (per player), `SetupAnswerBarWithTextString` (relabel the four answers), `SetBackgroundTexture_ToCorrect/Incorrect`, `Start/StopCountdownTimer`
* host: the trained voice can speak each new round's rules and callouts

| Round | Idea | How it would work | Difficulty |
|---|---|---|---|
| **Second Best** (Taskmaster's "Tall Poppy") | Fastest correct answer scores 0 if it would put that player in 1st place; every other correct answer scores normally | **Built** (`buzz_engine/custom_rounds.py`): Fastest Finger's question loop + a scoring hook after each judgement | Built, hidden in 0.1.0 - works in pack running orders; Custom Game menu entry parked |
| **The 11-Second Slam** (blind clock) | "Press your buzzer exactly 17.5 seconds from now", no clock, dark screen | Skip the countdown; log each player's press time against the start time; reveal times on the podiums; score by closeness | Low-medium |
| **Snort, Raspberry, Whistle** (colour sequence) | Flash a colour sequence, players replay it; first mistake locks you out, sequences get longer | Show the sequence (answer-bar colours or text), then read button presses in a loop; wrong press = error sound and lockout | Medium |
| **Strike the Bell** (name a word by letter) | Category + letter; first to buzz shouts a word; the others vote VALID / FAKE | Buzz-in phase (red button), 2-second window, then a vote with the answer bars relabelled; majority scores; letter advances | Medium-high (several phases) |
| **Tug of War** (sort under pressure) | Items drop one by one; tap the right bucket colour; each hit pulls the rope | Buckets = the four answer colours, items as question text, continuous button reading; the rope shown with existing visuals (score bars / podium text) since the game has no rope asset | High (visuals are the hard part) |

Second Best proved the custom-round pipeline in-game (new round type id 20, scripts in
GLOBALSCRIPTS, scores set from Lua). Next: **The 11-Second Slam**, then the input-heavy rounds.

### Online extras

* Live online matches (see Next).
* A community pack hub, like UltraStar's song databases: share `.buzz.txt` files (text only, no
  game data), browse and rate them from the app.
* Daily / weekly server quiz with a leaderboard; per-pack leaderboards; quiz ratings and play
  counts from real players (the MyBuzz formats already carry them).
