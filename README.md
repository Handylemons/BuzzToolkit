# Buzz Toolkit 0.1.1

Make your own quiz packs for **Buzz! Quiz World** (PS3, BCES00645) and host your own Buzz! online
server, for playing on RPCS3 or a modded PS3.

Two halves, one app (**Buzz Pack Studio**):

* **Pack generator (offline).** Add questions and pictures, choose the rounds and language, switch the
  host's voice on or off, press **Generate**, get a `.pkg`. Packs install like real DLC and play
  with no network at all.
* **Online server (self-hosted).** Your own replacement for the old Buzz! servers: MyBuzz online
  quizzes, leaderboards and buddies for you and your friends. Publish any pack's questions to it
  as online quizzes.

The toolkit ships **no game files**. Everything it needs from the game (the key packs are encrypted
with, the server's signing value, the round plans, the host's voice) is read from **your own
copy** during setup.

## What you need

* A Windows 10 or 11 PC
* **RPCS3** with Buzz! Quiz World (BCES00645) set up in it. The game's **update 01.02** is
  needed too; the app checks for it and can download it from Sony for you (step 5).
* About 1 GB of free disk space (about 8 GB more for the optional host voice)
* For the host voice (optional): an NVIDIA graphics card. Without one, packs still build, just
  without the host reading the questions.

## Getting started

You only do this once.

### 1. Install Python 3.11

Download **Python 3.11** from
[python.org/downloads/release/python-3119](https://www.python.org/downloads/release/python-3119/)
(scroll down to *Files* and pick **Windows installer (64-bit)**). Run it and, on the first
screen, tick **Add python.exe to PATH**, then click **Install Now**.

Use 3.11 even if you already have a newer Python: the host voice only works on 3.11. The two can
sit side by side.

### 2. Unzip the toolkit

Unzip `BuzzToolkit-0.1.1.zip` somewhere with space, for example `C:\BuzzToolkit`. Avoid putting it
inside a OneDrive or other synced folder.

### 3. Run Install.bat

Double-click **Install.bat** in the toolkit folder. It:

* sets up the app in its own folder (`tools\venv`), so it doesn't touch anything else on your PC
* downloads **ffmpeg** (a free audio/video tool the app uses)
* asks whether to install the **host voice**. Answer **Y** for the voice (about 6 GB, takes a while)
  or **N** to skip it; you can run Install.bat again later to add it.

If Windows shows "Windows protected your PC", click **More info → Run anyway**.

### 4. Find your game's EBOOT and decrypt it

The app reads the keys it needs from your own copy of the game, from a file called `EBOOT.BIN`.

1. **If your game is an `.iso` file, extract it first.** Install [7-Zip](https://www.7-zip.org/)
   (free), right-click the `.iso` → **7-Zip → Extract to "Buzz Quiz World\"**. You get a normal
   folder. (If your game is already a folder, skip this.)
2. **Open the game folder, then `PS3_GAME`, then `USRDIR`.** `EBOOT.BIN` is in there.
3. **Decrypt it:** in RPCS3 open **Utilities → Decrypt PS3 Binaries**, pick that `EBOOT.BIN` and
   let it finish. A new file, `EBOOT.elf`, appears in the same `USRDIR` folder.
4. **Copy the folder's path:** in the `USRDIR` window, click the address bar at the top (the path
   turns blue) and press **Ctrl+C**. It looks like
   `L:\Games\Buzz Quiz World\PS3_GAME\USRDIR`. You'll paste it in the next step, as it is, with
   no quotes.

### 5. Open the app and finish setup

Double-click **Start Buzz Pack Studio.bat**. The app opens in your web browser at
`http://127.0.0.1:8765`. Keep the black window open while you use the app; closing it stops the
app.

In the app's **Setup** box (left-hand side):

1. **RPCS3 folder:** open the folder that has `rpcs3.exe` in it, click its address bar, press
   **Ctrl+C**, paste it into the box (**Ctrl+V**) and press **Save folder**.
2. **Game update 01.02:** the toolkit is built on this official update. A green **Game update
   01.02 installed** label means you already have it. If not:
   1. Press **Download update from Sony**. The app fetches the official update (22 MB) straight
      from Sony's PS3 update server and checks it. The toolkit never includes Sony's files.
   2. Close RPCS3, then press **Install update into RPCS3**. RPCS3 opens and installs it.
   3. Press **Save folder** again to re-check; the label turns green.

   (Or install it yourself: RPCS3 → **File → Install Packages/Raps/Edats** and pick the file in the
   toolkit's `tools\downloads` folder.)
3. **Your decrypted EBOOT:** paste the `USRDIR` path from step 4 and press **Read game keys**.
   A green **Game keys read from your EBOOT** label confirms it.
4. Optional: **Turn on custom running orders**, so each pack plays its own rounds in the game's
   *Pack Game* menu. It changes one game script and keeps a backup.

You're ready to make packs. From now on, just double-click **Start Buzz Pack Studio.bat**.

## Make a pack

1. **Create** a pack (name on the left).
2. **Pack**: channel, language, "made by", pack number, host voice on/off.
3. **Questions**: drop in files (CSV, text, Moodle XML, Buzz online XML, JSON), pull from
   Open Trivia DB / OpenTriviaQA / The Trivia API, or write your own (picture questions and
   Point Stealer picture answers included). The app checks the game's limits
   (93 characters per question, 30 per answer).
4. **Rounds**: the running order: fixed rounds or random picks, as many as you like, then the
   Final Countdown. The **Question coverage** box underneath is only a check: it shows how many
   of your questions each round can use. You don't set those numbers; the game picks questions
   for each round itself. If a round shows *repeats* or *none*, add more questions of that kind.
5. **Generate**: builds the pack and a `.pkg`. Install it in RPCS3 with
   **File → Install Packages/Raps/Edats** (or press *Copy straight into RPCS3*).

### Pack numbers

Every pack has a number (1 to 999), and **no two packs can share one**. The game keeps each pack in
a folder named after its number, so installing a pack **replaces any other pack with the same
number**, including official DLC. That happens whether you use *Copy straight into RPCS3* or
RPCS3's *File → Install Packages*.

The app protects you from this:

* A new pack gets a free number automatically, skipping numbers already installed in RPCS3 or used
  by your other packs. **Set your RPCS3 folder first**, so it can see what's installed.
* You can change the number in step 1. Numbers that are already taken are refused, and the app
  suggests a free one.
* **Generate** and **Copy straight into RPCS3** refuse to go ahead if a *different* pack with that
  number is installed. Rebuilding and reinstalling the *same* pack is fine; the app recognises it.

If you install a PKG by hand, check its number first. The file name ends in it, for example
`PubQuiz_GBR_PACK0096.pkg` is pack 96.

Example question files are in `examples/`. A `.buzz.txt` file is the easiest way to share a pack
as plain text (see `examples/pub_quiz.buzz.txt`).

## Rounds and running orders

Every pack can have its own running order for the game's **Pack Game** menu: any of the game's
rounds, in any order, with optional random picks, ending with the Final Countdown. It needs the
one-time **Turn on custom running orders** step in the app's Setup box.

## Host voice

With the voice switched on, the host reads every question. Voices are made from your own game,
once per language; after that, voicing a pack takes minutes. Both commands below are typed in a
Command Prompt opened in the toolkit folder (type `cmd` in the folder's address bar and press Enter).

* **Quick (a few minutes, any language on your disc):** clones the host from a short sample.
  `tools\venv\Scripts\python make_host_reference.py <disc>/PS3_GAME/USRDIR/PACK0100/ESPPACK0100.PAK --out voice_models/buzz_host_ESP/reference.wav --lang ESP`
* **Trained (about 1 hour, runs unattended):** learns the host's voice and delivery from every
  line on your disc. Much closer to the real host.
  `tools\clone_venv\Scripts\python -m voice_trainer.run --disc "<extracted game folder>" --work <scratch folder> --name buzz_host`
  Add `--preset best` for a longer run (about 1 h 40 min); in our tests it sounded no better than
  the default.

Times measured on an RTX 3060 (12 GB). Faster cards are quicker; CPU-only training is not practical.

Every generated line is checked with speech recognition and re-made if words are wrong.

## Online server

**The server is optional.** Your packs play offline without it. If you've run *Set up this PC for
online play* and the server isn't running, the game shows a "can't connect" message when it
starts; press the button to close it and carry on playing offline. Start the server only when
you want MyBuzz online quizzes.

Open **Online server** in the app.

1. **Start server** (first time: give it your `EBOOT.elf` if you haven't already).
2. **Set up this PC for online play**: applies the login fix to your game scripts, enables the RPCS3
   patch the server needs and sets RPCS3's network options. The host uses `127.0.0.1`.
3. **Friends**: each friend installs the toolkit, does the one-time setup, and runs
   *Set up this PC for online play* with **your** IP address (shown on the page). Over the internet,
   forward TCP ports **10060, 10071 and 10075** to the host and use its public IP.
   Everyone needs a free **RPCN** account (RPCS3 → Configuration → RPCN).
4. **Publish to MyBuzz** on any pack puts its questions on your server as online quizzes.

The RPCS3 patches that *Set up this PC for online play* adds are also in the toolkit as a file of
their own, `rpcs3_patches\buzz_toolkit_patches.yml`, if you'd rather add them yourself: open RPCS3's
**Manage → Game Patches** window, drag the file onto it, choose **Import**, then tick the patches
for Buzz! Quiz World. They contain only our
own changes to the game code, no game data:

* **Online: logged in when connected to the server**: lets the menus go online with the toolkit's
  server, and lets the game carry on offline when the server isn't running.
* **60 FPS**: runs the game at 60 frames per second instead of 30 (optional).

What works online today: the MyBuzz menus (online quizzes, leaderboards, buddies). Live online
matches against remote players are not supported yet (see the roadmap).

## Question sources and licences

* **Open Trivia DB** and **OpenTriviaQA**: CC BY-SA 4.0. The pack's credits page is filled in
  automatically; keep it if you share the pack.
* **The Trivia API** (free tier): CC BY-NC 4.0, **non-commercial use only**.
* Your own questions and pictures: share only what you have the right to share.

## Known issues

* **Real PS3 consoles** (HEN / CFW) are untested; packs are confirmed on RPCS3 (PKG install via
  *File → Install Packages/Raps/Edats* and *Copy straight into RPCS3*).
* **Online:** live online matches against remote players are not supported (MyBuzz quizzes,
  leaderboards and buddies are).
* **Host voice in languages other than English** is cloned from a short sample (no training
  yet), so it is less close to the real host than the English trained voice.

## Licence

Buzz Toolkit is released under the [MIT licence](LICENSE). The licence covers the toolkit's own code
and documentation only; it grants no rights to Buzz! Quiz World or any other game content, which
belongs to its owners and is not included. Third-party parts keep their own licences; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Disclaimer

**Use at your own risk.** Buzz Toolkit is provided **as is**, without warranty of any kind,
express or implied, including fitness for a particular purpose. You use it entirely at your own
risk. The author is not responsible for any damage, data loss, corrupted saves or game
installs, account problems or any other issue arising from its use or misuse, including errors
in the toolkit itself. The toolkit changes files in your RPCS3 installation and keeps backups
of what it changes, but you should keep your own backups too.

**Fan project.** This is an unofficial, non-commercial fan project. It is not affiliated with,
endorsed, sponsored or approved by Sony Interactive Entertainment, Relentless Software or any
other rights holder. "Buzz!", "PlayStation" and "PS3" are trademarks of their respective owners
and are used here only to describe what the toolkit works with.

**Your own copy only.** You need your own legally obtained copy of Buzz! Quiz World. The toolkit
contains no game files, keys or recordings; it reads what it needs from your copy, on your
machine. The game update is downloaded from Sony's own servers, not from this project. Don't use
the toolkit to share or distribute game content, and only share packs made from questions and
pictures you have the right to share.
