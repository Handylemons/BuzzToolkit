# Buzz Toolkit 0.1.5

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

### Installing on a real PS3 (untested)

Packs are confirmed on RPCS3 only. They are built the same way as community-made DLC for modified
consoles, so they should install on a PS3 running **HEN** or **custom firmware (CFW)**. They
**cannot** install on an unmodified PS3: it only accepts packages signed by Sony.

You need the disc the pack was made for. Discs that share a download folder can share packs:

| Disc | Pack languages | Download folder on the PS3 |
|---|---|---|
| BCES00644 | GBR, FRA, DEU, ITA, NLD | `/dev_hdd0/game/BCES00098` |
| BCES00645 | GBR, ESP, PRT | `/dev_hdd0/game/BCES00098` |
| BCES00647 | RUS, POL, GRC, CRO, CZE | `/dev_hdd0/game/BCES00195` |

1. **Make the pack in the language your game is showing.** The game only lists a pack that has a
   file for the language it is running in. (In RPCS3, BCES00647 always runs in Russian; how it
   chooses its language on a console has not been confirmed. If a Polish, Greek, Croatian or Czech
   pack doesn't appear, note which language the game's menus are in.)
2. **Check the pack number** isn't one of your official packs (see Pack numbers above). The app
   can only see what is installed in RPCS3, not on your console.
3. Copy the `.pkg` from the pack's `output` folder to the **root of a FAT32 USB stick**.
4. On HEN, **enable HEN first** (every time the console starts). Then install it from the XMB
   under **Game → Package Manager → Install Package Files** (on CFW: **Game → Install Package
   Files**).
5. Start the game and open the pack list.

The game patches in this toolkit (60 FPS, online) are for RPCS3 only. Packs don't need them.

#### Troubleshooting on a console

Nobody has tried this on a real console yet, so this is a list of what *could* go wrong, from
the most likely to the least.

**Where's my pack?** Each pack ends up as one file:
`<download folder>/USRDIR/PACKnnnn/<LANG>PACKnnnn.EDAT`, for example
`/dev_hdd0/game/BCES00195/USRDIR/PACK0097/CZEPACK0097.EDAT`. Checking whether that file exists
(webMAN MOD's file manager, or FTP) tells you which half failed: the install, or the game loading
the pack.

| What you see | Likely cause | What to try |
|---|---|---|
| The `.pkg` isn't offered for install | Unmodified firmware; HEN not enabled since the console started; the USB stick isn't FAT32; the file isn't in the stick's root | Enable HEN, or use a CFW console. Reformat the stick as FAT32 and put the `.pkg` in its root. |
| The install stops with an error | The console's installer rejects the package. Our packages copy the layout of Sony's own Buzz packs but can't carry Sony's signature, so on a console this is the part most likely to fail. | Skip the package and copy the `.EDAT` by FTP (see below). |
| It installs, but the pack isn't in the game's list | The language doesn't match: the pack has a file for one language and the game runs in another | Make the pack in the language the game's menus are in (step 1). |
| | Wrong disc: the pack went into the other download folder (`BCES00098` holds packs for 644/645, `BCES00195` for 647) | Check the table above, then rebuild the pack in a language from your disc. |
| | The `.EDAT` was renamed, or copied into the wrong `PACKnnnn` folder | Use the exact file name and folder from the `output` folder. Its encryption is tied to the name. |
| | The console rejects the pack file itself. Toolkit packs use the "free" licence type, which needs no licence file. Their signatures are placeholders, as with other community-made packs. RPCS3 accepts them; a console might not. | Report it (see below). Nothing on the console side fixes this. |
| An official pack disappeared, or shows our questions | Same pack number as an official pack: installing replaced it | Give the pack another number and reinstall the official pack. |
| The pack plays, but the host is silent | Built without a voice for that language (Generate says *built without audio*). Not a console problem. | Make a voice for that language (see Host voice) and generate again. |

**Copying the `.EDAT` by FTP instead of installing the `.pkg`:** with webMAN MOD or multiMAN
running, connect an FTP client to the console and copy the `.EDAT` from the pack's `output`
folder into `<download folder>/USRDIR/PACKnnnn/`. Create the `PACKnnnn` folder if needed, and
don't rename the file. The download folder itself must already exist with its `PARAM.SFO`. It
does if you have ever installed an official pack, or this pack's `.pkg`. Otherwise the game
can't find any packs there.

Please report what you see: console model, firmware with HEN or CFW name and version, disc ID, the
game's language, the step that failed, and any error code shown (for example `8002xxxx`).

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
  the default. For another language, add `--lang` with the disc's code and name the voice after
  it, e.g. `--lang CZE --name buzz_host_CZE` (codes: ESP, PRT, FRA, DEU, ITA, NLD, POL, RUS, GRC,
  CZE, CRO). Use a separate scratch folder per language.

**Languages.** Every pack language on the three discs can be voiced: English, Spanish,
Portuguese, French, German, Italian, Dutch, Polish, Russian and Greek directly, plus Czech and
Croatian (below). Each language needs its own voice, made from that language's host on your disc.
A language with no voice on your PC builds without audio, and Generate says so.

**Czech and Croatian** are not among the voice engine's own languages. The toolkit speaks them
through its Polish voice, after respelling the text the way a Polish reader would pronounce it
and writing numbers out as Czech or Croatian words. With only the quick sample this sounds
foreign, so **train these two voices**. Training uses 1,500 delivery steps for them
automatically, so it takes about 2 hours rather than 1.

Times measured on an RTX 3060 (12 GB). Faster cards are quicker; CPU-only training is not practical.

### How accurate is it?

Every generated line is checked with speech recognition, which compares what it hears against the
question text. A line with too many wrong words is made again, up to four times, and the best take
is kept. Czech and Croatian lines often use all four takes, so voicing those packs takes longer.

Our measurements, on disc questions the voices never trained on (12 per language, 24 for English). *Similarity* is how close the
voice sounds to the real host (1.0 = identical). *Misheard* is the share of words the recogniser
got wrong, which is a rough measure of pronunciation. Even the real host isn't at 0%.

| Language | Similarity, trained (real host) | Misheard, quick sample | Misheard, trained | Misheard, real host |
|---|---|---|---|---|
| English | 0.964 (not measured) | 13.9% | 13.5% | not measured |
| Czech | 0.982 (0.983) | 55.4% | 27.3% | 15.5% |
| Croatian | 0.980 (0.987) | 46.8% | 19.6% | 20.5% |

A trained Croatian voice is about as clear as the real host. A trained Czech voice sounds very like
the host, but a native speaker will still notice some words. Other languages use the engine's own
pronunciation and haven't been measured yet.

### Fixing words that come out wrong

The voice reads the question as written, so these help in every language:

* **Abbreviations** (`e.g.`, `km`, `např.`, `tzv.`) are not expanded. Write them out.
* **Ordinals and Roman numerals** (`1.`, `Karel IV.`, `Henry VIII`) are read as plain numbers or
  letters. Write them as words (`Karel Čtvrtý`).
* **Plain numbers** are fine. Czech and Croatian numbers, decimals (`3,5`) and percentages are
  written out for you. In other languages, write a number as words if it sounds wrong.
* **Foreign names** are read with the pack language's rules. Spell them the way they should sound
  (see below).

For words that keep coming out wrong, add them to the pack's `pack.json` (in
`content\projects\<pack>\`), inside `"voice"`. Close the app before editing it.

```json
"voice": {
  "pronounce": {"Shakespeare": "Šejkspír", "USA": "ú es á"},
  "say": {"KDO NAPSAL HAMLETA?": "Kdo napsal Hamleta?"}
}
```

* `pronounce` swaps single words for a spelling that sounds right, in the **pack's own language**.
  For Czech and Croatian, write it in Czech or Croatian spelling, not Polish; the respelling is
  applied afterwards.
* `say` replaces the spoken text of a whole question. The key must match the question exactly as it
  appears on screen, in capitals.
* Only lines whose text changed are made again on the next Generate. The rest come from the cache.

### Training a voice further

Training runs in stages and skips any stage that has already finished, so running the same command
again does nothing new. To train the delivery longer while reusing the decoded disc lines and the
trained voice, add `--retrain-t3` and a step count:

`tools\clone_venv\Scripts\python -m voice_trainer.run --disc "<extracted game folder>" --work <same scratch folder> --lang CZE --name buzz_host_CZE_long --retrain-t3 --t3-steps 3000`

* **Use a new `--name`** so your current voice stays as it is. The run ends by printing similarity
  and misheard figures. Compare them with the previous run, then pick the voice that sounds better.
* The previous delivery training is kept in your scratch folder as `models\t3_lora.prev`.
* **Expect small gains.** In our tests Czech stopped improving after about 1,000 steps, and
  Croatian after about 1,500. More steps mostly cost time. A wrong word is usually quicker to fix
  with `pronounce` than with more training.
* To start completely afresh, delete the scratch folder.

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

## Big Button buzzers

You can play with **Xbox 360 Big Button pads** (the wireless controllers from *Scene It?*)
instead of Buzz! buzzers or a keyboard. Each pad has the same five buttons as a buzzer. Up to four
pads work, one per player.

### What you need

* **The Big Button IR receiver**, the small USB receiver the pads came with (USB ID `045E:02A0`),
  plus the pads with batteries. The pads talk to it by infrared, so keep it in view of the players.
* **The WinUSB driver for the receiver.** Windows has no driver of its own for it. Install one
  once with [Zadig](https://zadig.akeo.ie/):
  1. Plug the receiver in and run Zadig.
  2. **Options → List All Devices**, then pick the entry whose USB ID is `045E 02A0`. Don't pick an
     *Xbox 360 Wireless Receiver*, which is a different device.
  3. Choose **WinUSB** as the driver and press **Install Driver** (or **Replace Driver**).

  To undo this later, uninstall the device in Windows Device Manager.
* **Buzz! started once in RPCS3**, so RPCS3 has a controller profile for the game.
* **Run `Install.bat` again** if you updated from an older toolkit. It adds the USB library the
  buzzers need.

### Switching them on

In the app, open **Big Button buzzers** (under *Online server*) and switch **Big Button buzzers
on**. The page checks the receiver, its driver and RPCS3's profile, and tells you what's missing.
Once it's on, every press shows on the page, for example `pad 2 big   down -> Q`. That's a quick
way to check each pad works and which player it is.

Then start (or go back to) the game in RPCS3 and **keep the RPCS3 window in front**. Switch off
on the same page when you're done: that stops the buzzers and puts your previous RPCS3 controller
settings back. **Switch off before closing the app**, or the buzzers keep running in the
background. If that happens, open the page again and switch on and then off: the app takes over
from the leftover buzzers and stops them.

### How a press reaches the game

1. The IR receiver passes every pad's presses to the PC over USB.
2. The toolkit's bridge (`buzz_bigbutton.py`) turns each pad's buttons into key presses. Each pad
   has its own keys:

   | Pad | Big button | X | B | A | Y | Start | Back |
   |---|---|---|---|---|---|---|---|
   | 1 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
   | 2 | Q | W | E | R | T | Y | U |
   | 3 | A | S | D | F | G | H | J |
   | 4 | Z | X | C | V | B | N | M |

   The d-pad is the arrow keys on every pad.
3. When you switch on, the toolkit sets RPCS3 players 1-4 to the keyboard with those keys, in the
   game's own controller profile. It also sets RPCS3's Buzz! emulation to *1 controller* (four
   buzzers). Your previous settings are backed up first.
4. RPCS3 hands players 1-4 to the game as buzzers 1-4:

   | Pad button | Buzzer button |
   |---|---|
   | Big button | Red buzzer |
   | X (blue) | Blue |
   | B (red) | Orange |
   | A (green) | Green |
   | Y (yellow) | Yellow |
   | Start, Back, d-pad | Menus |

The pads only report a button while it's held, never its release, so the bridge counts a button
as released 0.3 s after its last report. A quick tap still registers, but don't expect two
presses within a third of a second to count as two.

### If it doesn't work

| What you see | What to try |
|---|---|
| *Receiver not found* | Plug it in (try another USB port), then wait a few seconds for the page to update. |
| *Needs the WinUSB driver* | Install it with Zadig (above). Pick the `045E 02A0` entry, not another Xbox device. |
| *Can't open the receiver* in the log | Another program is using it. Close other copies of the toolkit or the bridge, switch off and on again, or reinstall the driver. |
| Presses show on the page but nothing happens in the game | Click the RPCS3 game window: RPCS3 only reads the keyboard while it has focus. Also check you're in a part of the game that takes buzzer input. |
| A pad shows up as the wrong player | Each pad reports its own number, and pad N is always player N. Check the number on the page when you press a button. |
| Keys like `1` or `Q` appear in other windows | The buzzers type keys wherever you are. Switch them off before using the PC for anything else. |
| Your normal controller stopped working in RPCS3 | The buzzers are still on. Switching off restores your previous settings. |

## Question sources and licences

* **Open Trivia DB** and **OpenTriviaQA**: CC BY-SA 4.0. The pack's credits page is filled in
  automatically; keep it if you share the pack.
* **The Trivia API** (free tier): CC BY-NC 4.0, **non-commercial use only**.
* Your own questions and pictures: share only what you have the right to share.

## Known issues

* **Real PS3 consoles** (HEN / CFW) are untested; packs are confirmed on RPCS3 (PKG install via
  *File → Install Packages/Raps/Edats* and *Copy straight into RPCS3*). See *Installing on a real
  PS3* for the steps and what to report. Unmodified consoles can't install them.
* **Big Button buzzers** are tested up to RPCS3: receiver, driver check, key presses and the RPCS3
  mapping and restore. A full four-pad game hasn't been played through yet.
* **Online:** live online matches against remote players are not supported (MyBuzz quizzes,
  leaderboards and buddies are).
* **Host voice from the quick sample** is less close to the real host than a trained voice. In
  Czech and Croatian it also has a Polish accent; training reduces it a lot, but some Czech words
  can still sound slightly off (see Host voice).

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
