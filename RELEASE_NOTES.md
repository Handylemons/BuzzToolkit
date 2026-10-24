# Buzz Toolkit 0.1.5

**Czech and Croatian packs now have a host voice, every language on the three discs can be
voiced, and Xbox 360 Big Button pads can be your buzzers.**

## Czech and Croatian question reading
* **Fixed: custom Czech packs came out silent.** The voice engine has no Czech or Croatian, so
  these packs were built without audio, and Generate failed outright once a Czech voice existed.
* The toolkit now speaks both through its Polish voice. It first rewrites the text the way a
  Polish reader would pronounce it (`ř` → `rz`, `ě` → `je`/`ie`, `ť`/`ď`/`ň` softening, Croatian
  `đ`, `lj`, `nj`, syllabic `r`), and writes out numbers, decimals and percentages as Czech or
  Croatian words. Otherwise `2008` would be read in Polish.
* The voice is cloned from your disc's own Czech or Croatian question reader.

## Train a voice in any disc language
* The voice trainer takes `--lang` (ESP, PRT, FRA, DEU, ITA, NLD, POL, RUS, GRC, CZE, CRO). It
  learns from that language's question reader on your disc, about 5,800 lines each for Czech and
  Croatian. The trainer's end-of-run check listens in that language too.
* Trained voices are now used for every language, not just English.
* Czech and Croatian train with 1,500 delivery steps by default. Measured against the earlier 500
  steps:

| | Misheard words, untrained | 500 steps | **1,500 steps** | Real host |
|---|---|---|---|---|
| Czech | 55.4% | 31.8% | **27.3%** | 15.5% |
| Croatian | 46.8% | 26.0% | **19.6%** | 20.5% |

  Similarity to the real host: Czech 0.982 (real recordings score 0.983), Croatian 0.980 (0.987).
* **New `--retrain-t3`** trains a voice's delivery again with more steps, reusing the decoded disc
  lines. The previous training is kept.
* The README has new sections on accuracy, fixing words that come out wrong (`pronounce` and
  `say` in `pack.json`), and training further.

## Big Button buzzers
* **New: play with Xbox 360 Big Button pads** (from *Scene It?*) as the four buzzers. In the app,
  open *Big Button buzzers* and switch on. The page checks the IR receiver, its WinUSB driver and
  RPCS3's controller profile, and shows every press so you can see which pad is which player.
* Switching on maps RPCS3 players 1-4 to the pads' keys in the game's controller profile and sets
  RPCS3's Buzz! emulation to four buzzers, backing up your settings first. Switching off puts
  them back. Works with all three discs.
* The README's new *Big Button buzzers* section covers the Zadig driver step, how a press travels
  from pad to game, and a troubleshooting table.

## Real PS3 consoles
* Packages now carry the same install metadata as Sony's own Buzz DLC: firmware and app version,
  and the install folder. RPCS3 never needed it, but a console's installer may.
* A new README section, *Installing on a real PS3*, covers HEN/CFW install steps, an FTP fallback,
  a troubleshooting table of every likely failure point, and what to report. **Still untested on
  hardware.** Unmodified consoles can't install custom packages at all.

## Fixes
* **Russian and Greek voice lines are now actually checked.** The speech check only counted
  Latin letters, so every Cyrillic or Greek line scored as perfect and a mispronounced take was
  never made again. Our 12-language test caught a Greek line with two wrong words.
* Pack file names keep their letters when the pack name has accents (`ČESKÝ KVÍZ` →
  `CeskyKviz_CZE_PACK0097.pkg`, was `eskKvz`).
* Voice generation no longer crashes on progress messages Windows couldn't decode.

## Updating
* **Run `Install.bat` again** after unzipping. It installs `num2words` (Czech number reading)
  and the USB library for the Big Button buzzers.
* Voices you trained earlier still work. To get the new Czech or Croatian voices, train them with
  `--lang CZE` / `--lang CRO` (see Host voice in the README).

## Known limits
* Czech pronunciation is good but not native: about 1 word in 4 is misheard by speech
  recognition, against 1 in 6 for the real reader. Use `pronounce` for words that matter.
* Ordinals, Roman numerals and abbreviations are read as written; write them as words.
* Real-console installs are untested.
* Big Button buzzers are tested up to RPCS3 (receiver, presses, mapping and restore); a full
  four-pad game hasn't been played through yet.
* The host's spoken links around a question are still in English regardless of the pack
  language.
* Matchmaking and online multiplayer remain unavailable; only the MyBuzz quiz menus work.

# Buzz Toolkit 0.1.4

**Accents and non-Latin alphabets are no longer stripped out of packs.**

## Full character set support
* Questions and answers now keep every letter they were written with. Previously anything above
  Latin-1 was reduced to bare ASCII, so Polish `WISŁĄ` became `WISLA`, Czech `MĚSTO` became
  `MESTO`, and **Russian and Greek questions were emptied of text entirely**. Accented Latin was
  kept, but the moment a pack used a language outside Western Europe it was quietly mangled.
* The game stores one 16-bit character per letter in its string tables, so every script the
  toolkit targets already fitted - Latin with accents, Polish, Czech and Croatian diacritics,
  Cyrillic and Greek. Nothing in the game needed changing; the toolkit was discarding the
  characters before they ever reached it.
* Still tidied, because these have a plain equivalent the font reliably has: HTML entities,
  curly quotes, en and em dashes, ellipses, and runs of whitespace. Still removed, because they
  cannot be stored or drawn: control and formatting codes, unassigned and private-use code
  points, and emoji (which fall outside the 16-bit table).
* **Greek is uppercased the way Greek actually works** - `πόλη` becomes `ΠΟΛΗ`, not `ΠΌΛΗ`,
  since modern Greek drops the accent in all-caps. German `ß` still becomes `SS`.
* A pack can now be checked against what its game build is expected to draw, and the toolkit
  warns rather than silently deleting - the font on your disc is the authority, not us.
* `test_charset.py` covers all of this so it cannot regress unnoticed.

## Online on all three discs
* **The online login patch now works on the disc build too**, so online play no longer needs
  `BCES00645` with Sony's 01.02 update - `BCES00644` and `BCES00647` work straight from disc.
  Confirmed in game: the MyBuzz menus open against a running server on `BCES00647`.
* Finding it meant resolving where the disc build keeps the network object. The patch reads it
  through the table of contents, and that table is laid out differently between the two builds
  (`TOC+0x2d48` rather than `+0x3080`). The offset was recovered by locating the four code sites
  that load the same object on the updated build, porting each one independently, and reading
  back the offset they use - all four agree.

## Known limits
* The host's spoken links around a question are still written in English regardless of the pack
  language.
* Matchmaking and online multiplayer remain unavailable; only the MyBuzz quiz menus work.

# Buzz Toolkit 0.1.3

**60 FPS now works on all three European discs, not only the updated one.**

* All three Quiz World discs - `BCES00644` (En, Fr, De, It, Nl), `BCES00645` (En, Es, Pt) and
  `BCES00647` (Pl, Ru, El, Hr, Cs) - ship a byte-identical executable before Sony's 01.02 update
  is applied. The 60 FPS patch is now also provided for that disc build, so it applies to any of
  the three straight from disc. Previously it only worked on `BCES00645` with the update
  installed.
* The addresses for the disc build were found by matching each patch site's surrounding code
  against the updated build, then checking that the instruction at the new address is the one the
  patch expects - not by assuming a fixed offset, which does not hold between the two builds.

## Still update-only
* **The online login patch remains `BCES00645` version 01.02 only.** Its first instruction reads
  a global through the table of contents, and that table is laid out differently in the disc
  build, so reusing the patch there would read an unrelated value. It needs that one slot
  resolving before it can be offered for the other discs; until then, online play needs 645 with
  the 01.02 update.

## Reminder of what 0.1.2 added
* Packs for all three discs, with twelve pack languages: English, Spanish, Portuguese, French,
  German, Italian, Dutch, Russian, Polish, Czech, Croatian and Greek.
* *Copy straight into RPCS3* creates the DLC folder and its `PARAM.SFO` when missing.
* The self-hosted server identifies which Buzz game is connecting and routes it to that title's
  online application. Quiz TV and Ultimate Music Quiz are still not supported online.

# Buzz Toolkit 0.1.2

**Packs now work on all three European Buzz! Quiz World discs, not just one.**

## Three game builds supported
* `BCES00644` (En, Fr, De, It, Nl), `BCES00645` (En, Es, Pt) and `BCES00647` (Pl, Ru, El, Hr, Cs).
* **Nine new pack languages**: French, German, Italian, Dutch, Russian, Polish, Czech, Croatian
  and Greek, alongside the existing English, Spanish and Portuguese.
* You do not have to say which disc you have. Packs install into a shared "Buzz!: Quiz TV"
  game-data folder whose id differs per disc (`BCES00098` for the first two, `BCES00195` for the
  Pl/Ru/El/Hr/Cs one), and the pack language picks the right one on its own. A pack's content id
  names that folder too, and the game rejects a pack whose id names the wrong one - so this had
  to be right rather than guessed.
* Step 1 now shows which disc your chosen language plays on and where the pack installs, before
  you generate. If a language belongs to no known disc the app says so instead of building
  something that cannot be installed.

## Send to RPCS3 creates the folder it needs
* *Copy straight into RPCS3* now creates the DLC folder when it is missing, **including its
  `PARAM.SFO`**. An empty folder is not enough: without that file the game cannot resolve its DLC
  path at all and silently finds no packs, however they are named. Installing into a fresh RPCS3
  is the difference between the pack appearing and nothing happening.
* The pack-number check now looks in every disc's folder, so a number cannot clash unseen.

## Self-hosted server
* The server recognises which Buzz game is connecting (by its Medius app id) and routes it to its
  own online application: Quiz World `22814`, Quiz TV `20984`, Ultimate Music Quiz `23324`.
  The log names the game.
* **Quiz TV and Ultimate Music Quiz are not supported online.** They share the transport and do
  reach the server, but the online content here is Quiz World's; the other two now get a clean
  "no content for this title" instead of being handed pages they cannot read and failing oddly.
  Their own content is not written.

## Also fixed
* Host-voice generation no longer fails when the toolkit and the system temp folder are on
  different drives.

## Notes
* The RPCS3 patches still apply only to `BCES00645` version 01.02. The other two discs ship a
  different executable, so 60 FPS, TTY debug output and the online login patch do not apply to
  them yet.
* As always, no game files, keys or voices are shipped - they are read from your own disc at setup.

# Buzz Toolkit 0.1.1

* **Pack numbers are protected.** Installing a pack replaces any pack with the same number, so the
  app now checks what's installed in RPCS3 (and your other packs) before it lets a number be used:
  new packs get a free number, step 1 has a pack-number field that refuses taken numbers, and
  Generate / *Copy straight into RPCS3* refuse to replace a different pack. Rebuilding the same
  pack is still allowed. Command line: `generate --allow-replace` overrides the check.

# Buzz Toolkit 0.1.0 - first release

## Setup
* `Install.bat`: one double-click sets up the app in its own environment, downloads ffmpeg and
  optionally installs the host voice (Python 3.11).
* Game update 01.02 check in the Setup box, with **Download update from Sony** (the official
  package, fetched from Sony's PS3 update server and checksum-verified; never shipped) and
  **Install update into RPCS3**. Command line: `setup --get-update`.
* Our RPCS3 patches also ship as `rpcs3_patches/buzz_toolkit_patches.yml` for manual import.

## Pack generator (offline)
* Buzz Pack Studio app (`Start Buzz Pack Studio.bat`): packs, questions, rounds, generate.
* Questions from CSV, Aiken, Q:/A: text, OpenTriviaQA text, `.buzz.txt`, Moodle XML, Buzz online
  XML, generic XML/JSON, Open Trivia DB, OpenTriviaQA and The Trivia API; checked against the
  game's limits (93 / 30 characters), duplicates removed, pictures fetched.
* Standard, picture, All That Apply and Point Stealer questions; pack card, credits page with the
  question sources' licences.
* Per-pack running orders (Pack Game menu), random picks, presets.
* Language selection (pack code GBR, ESP, PRT, DEU, ...), host voice on/off.
* **Generate → PKG** (own PKG writer, Game Data for BCES00098; installs and plays on RPCS3) or copy
  straight into RPCS3.
* Shareable `.buzz.txt` export (text only).

## Host voice
* Voice trainer (`voice_trainer.run`): fine-tunes a Chatterbox voice on the host's lines from your
  own disc in about an hour (RTX 3060; `--preset best` for a longer run); every generated line is
  checked with speech recognition and re-made if wrong.
* Own ATRAC3 encoder (the game's 152-byte mono speech format) with Sony-style bit allocation and
  gain control; retail loudness.

## Online server (self-hosted)
* MyBuzz online quizzes, leaderboards and buddies; start/stop from the app.
* **Publish to MyBuzz** turns a pack's questions into online quizzes (live, no restart).
* **Set up this PC for online play**: login fix, RPCS3 patch, network settings; friends connect
  with the host's IP. The game still boots and plays offline when the server isn't running.

## Not shipped
* No game files, keys or voices: setup reads them from the user's own copy (decrypted EBOOT,
  game scripts, disc audio). The release build audits for this.

## Known issues
See the README.
