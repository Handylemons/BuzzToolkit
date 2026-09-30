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
