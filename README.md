<p align="center">
  <img src="assets/logo/roots-icon-128.png" width="96" alt="RootsVoice logo">
</p>

<h1 align="center">RootsVoice</h1>

<p align="center">
  <b>Voice-controlled scripture for VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP and FreeShow.</b><br>
  Speak a Bible reference - it appears on screen.
</p>

<p align="center">
  <a href="../../releases/latest"><img src="https://img.shields.io/badge/download-Windows%20installer-1E7A46" alt="Download"></a>
  <img src="https://img.shields.io/badge/version-2.2.3-1E7A46" alt="Version 2.2.3">
  <img src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-555" alt="Windows 10 | 11">
</p>

---

RootsVoice listens to the preacher, picks out Bible references ("turn to John chapter three verse sixteen") and shows them in your projection software - [VideoPsalm](https://www.videopsalm.com/), [BibleShow](https://bibleshow.net/), EasyWorship, ProPresenter, OpenLP, [FreeShow](https://freeshow.app/) or any program with a box for typing a reference - automatically with **RootsAuto**, or after the operator confirms. Ordinary preaching is ignored, speech is turned into text **on the computer itself**, and it keeps learning the way your preacher speaks.

Made by **nightfellas**.

<!-- Add screenshots here once you have them, e.g. ![Live screen](docs/images/live.png) -->

## Contents

- [Features](#features)
- [Install](#install)
- [Quick start](#quick-start)
- [Supported projection software](#supported-projection-software)
- [Voice commands](#voice-commands)
- [Moving through scripture](#moving-through-scripture)
- [Training](#training)
- [Run from source](#run-from-source)
- [Build the installer](#build-the-installer)
- [Project layout](#project-layout)
- [Privacy](#privacy)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing) · [Licence](#licence)

## Features

| | |
|---|---|
| **RootsAuto** | Autopilot: references and commands go on screen the moment the speaker pauses. |
| **Works with your software** | VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP, FreeShow (API) and any program with a reference box. *Detect* finds the one that's open. |
| **Understands real speech** | Spoken numbers, "First Peter" / "1st Peter" / "II Peter", ranges ("verses 3 to 5"), chapter-only references, one-chapter books ("Jude 3"). |
| **Scripture-only filter** | Unrelated preaching is ignored; impossible references ("John 35", "Psalm 151") are never shown. A misheard book is never replaced by the previous one - it asks *Did you mean...?* |
| **Any microphone** | *Find active microphone* shows which input hears sound; formats a mic refuses are converted; silence and unplugging are noticed and it reconnects by itself. Missing or broken drivers and Windows privacy blocks are spotted, with buttons to fix them. |
| **Sound-alikes** | "John 3 *this* 16" is read as verse 16; "Romans *ate* 28" as Romans 8:28 - only inside references, never in normal speech. |
| **Step through verses** | Voice ("Roots next"), on-screen verse buttons, system-wide keyboard shortcuts, or a presentation clicker. |
| **Learns your preacher** | Listen & correct, practice prompts, live learning and sermon import teach it misheard names and commands. |
| **Suggestions** | One-click next / previous verse, whole chapter, next chapter, and "Did you mean...?" for near misses. |
| **Easy on the operator** | Light and night mode, fold-out settings that fit small screens, Help built in, one-click **Check setup**. |
| **Offline & private** | Runs entirely on the PC after a one-time speech-model download (or none, with the full installer). |

## Install

1. Download **`RootsVoice-Setup-2.2.3.exe`** from the [latest release](../../releases/latest).
2. Double-click it and follow the wizard. Choose **Recommended** to include the speech model so it works offline straight away.
3. Open RootsVoice → **?** (Help) → **Check setup**.

No Python or anything else needs installing. If Windows shows *"Windows protected your PC"*, click **More info → Run anyway** (the installer is not yet code-signed - see [docs/BUILDING.md](docs/BUILDING.md#code-signing)).

## Quick start

1. Open your projection software. In RootsVoice, **Settings → Projection software → Detect** (first time only).
2. In RootsVoice, press **Start listening**.
3. Speak a reference: *"Turn to John chapter 3 verse 16."*
4. **RootsAuto on** - it appears on screen immediately. **RootsAuto off** - press **Send**.

A full operator guide, including a service-day checklist, is in [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Supported projection software

| Program | How RootsVoice sends the verse | Setup |
|---|---|---|
| VideoPsalm | Opens its search with `Ctrl+F` and types the reference | None |
| BibleShow | Presses `F5` (its reference shortcut) and types the reference | None |
| EasyWorship | Clicks the Scriptures reference box and types | *Point to it* once |
| ProPresenter | Clicks the Bible panel's reference box and types | *Point to it* once |
| OpenLP | Clicks the Bibles quick-search box and types | *Point to it* once |
| FreeShow | Sends `start_scripture` through FreeShow's API - nothing is typed | Turn on FreeShow's API (Settings → Connections) |
| Any other program | Clicks a box you point to (or uses its search shortcut) and types | Window title + *Point to it* |

*Point to it*: open the program's Bible panel, press **Point to it** in RootsVoice and hold the mouse over the box where a reference is typed for 5 seconds. It's measured from the program's window corner, so it keeps working if the window moves. Press **Send a test verse** to check. The profiles other than VideoPsalm and BibleShow are new in 2.2 and were built from each program's documentation - check yours with *Send a test verse*, and [report](../../issues/new/choose) anything that needs changing.

## Voice commands

| Say | What happens |
|---|---|
| "John chapter 3 verse 16" | Show John 3:16 |
| "Psalm 23" | Show the chapter (no verse spoken) |
| "Verse 5" · "Roots 5" | Verse 5 of the current chapter |
| "Chapter 4" · "Chapter 4 verse 2" | Another chapter of the same book |
| "Next verse" · "Roots next" | One verse forward |
| "Previous verse" · "Roots back" | One verse back |
| "Next chapter" · "Previous chapter" | Change chapter |
| "Clear the screen" | Blank the screen (set the program's blank key in Settings; FreeShow needs none) |

Optional safety: **Settings → Moving through scripture → Say "Roots" first** makes short commands need the word *Roots*, so "the next verse says..." in a sermon never moves the screen.

## Moving through scripture

Most projection programs have no voice-friendly next / previous verse keys, so RootsVoice keeps track of the current reference, works out the new one and sends it.

| Way | How |
|---|---|
| Voice | "Roots next", "Roots back", "Roots 18" |
| Click | ‹ › arrows and the verse numbers under the current verse |
| Keyboard (from any window) | see below |
| Presentation clicker | Settings → *Presentation clicker*: its forward / back buttons step verses |
| Undo | **Back** button or `Ctrl+Alt+B` |

| Shortcut | Action |
|---|---|
| `Ctrl+Alt+→` / `Ctrl+Alt+←` | Next / previous verse |
| `Ctrl+Alt+↓` / `Ctrl+Alt+↑` | Next / previous chapter |
| `Ctrl+Alt+B` | Back to the last reference |
| `Ctrl+Alt+A` | RootsAuto on / off |
| `Ctrl+Alt+L` | Start / stop listening |
| `Page Down` / `Page Up` | Next / previous verse (clicker mode only) |

## Training

Everything learned is used immediately by the Live screen and RootsAuto. Open the **Training** tab:

- **Listen & correct** *(quickest)* - say something, fix any wrong words in the text it heard, press *Save correction*. It learns misheard book names ("for street pita" → 1 Peter), commands ("neck's verse" → next verse) and sound-alikes ("this" → verse).
- **Practice prompts** - read about 15 editable prompts aloud, then *Finish session* (you can stop early; a new session starts each time).
- **Import sermon recordings** - finds misheard book names in past sermons; you approve each one.
- **Re-learn everything** - re-checks every saved recording, e.g. after switching to a more accurate model.
- **Learned words** - see and remove anything it learned.

## Run from source

**Easiest:** download the code (or `git clone` it), then double-click **`setup_rootsvoice.bat`**. It installs Python 3.11 if needed, creates RootsVoice's own environment (`.venv`), installs every component from `requirements.txt` (including the faster-whisper speech engine and, if missing, Microsoft's Visual C++ runtime), checks that they really load, downloads the speech model and puts a **RootsVoice** shortcut on the desktop. Afterwards start it from that shortcut or `RootsVoice.bat`.

If RootsVoice is started with a Python that lacks something, it says so at startup and offers **Install now** (also under Help → *Install missing components*).

By hand (Windows 10/11, Python 3.10-3.12):

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python rootsvoice.py --check-deps
python rootsvoice.py
```

Handy command-line checks:

```bat
python rootsvoice.py --test "john three sixteen|next verse|roots 18"
python rootsvoice.py --scan "open habakuk two four"
python rootsvoice.py --download-model base.en build\models
python rootsvoice.py --check-deps      # is everything installed and working?
python rootsvoice.py --install         # install whatever is missing
```

## Build the installer

**On GitHub (no Windows PC needed):** push a version tag and the *Build installer* workflow produces `RootsVoice-Setup-<version>.exe` and attaches it to a GitHub Release:

```bash
git tag v2.2.3
git push origin v2.2.3
```

**On a Windows PC:** double-click `build_installer.bat`. It installs Python, the libraries, the speech model and Inno Setup if needed, then writes `dist\RootsVoice-Setup-2.2.3.exe`.

Details, code signing and releasing a new version: [docs/BUILDING.md](docs/BUILDING.md).

## Project layout

```
rootsvoice.py              the whole app (speech, parsing, learning, window)
requirements.txt           libraries RootsVoice uses
setup_rootsvoice.bat       one-click setup to run from source (Python, components, model, shortcut)
RootsVoice.bat             starts RootsVoice with its own environment
build_installer.bat        one-click Windows build of the installer
installer/
  RootsVoice.iss           installer wizard (Inno Setup) - publisher nightfellas
  version_info.txt         publisher and version shown in RootsVoice.exe properties
assets/
  roots.ico                app icon
  wizard-*.bmp             installer artwork
  logo/                    Roots logo files
docs/
  USER_GUIDE.md            for operators: setup, service-day checklist, training
  BUILDING.md              for maintainers: building, signing, releasing
tests/
  test_logic.py            references, commands, learning, engine, training
  test_gui.py              drives the full window on a stand-in toolkit
  faketk/                  the stand-in for tkinter used by test_gui.py
.github/                   automatic tests, installer builds, issue templates
```

`rootsvoice.py` is organised top to bottom: settings → Bible books and reference parsing → sound-alikes → scripture filter and learning → speech models → projection software (VideoPsalm, BibleShow, FreeShow…) → setup check → keyboard shortcuts → microphones and listening engine → training data → look and feel → Training screen → main window.

## Privacy

- Speech is converted to text **on the computer** with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Nothing said is sent over the internet.
- The only download is the speech model, once (none if the installer includes it).
- Training recordings and settings stay in `%APPDATA%\RootsVoice` (or next to `rootsvoice.py` when run from source) and are excluded from Git by `.gitignore`.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Missing package" / faster-whisper | Help → **Install missing components**, or double-click `setup_rootsvoice.bat`. |
| Stuck on "Downloading" | First use needs internet. Settings → Listening → Download on a good connection; it resumes if interrupted. |
| "... window not found" | Open the program, or Settings → Projection software → **Detect**. |
| Verse typed in the wrong place | Open the program's Bible panel, then **Point to it** again. |
| Program comes to the front but nothing is typed | It's running as administrator, so Windows blocks typing into it - run RootsVoice as administrator too. |
| "Didn't catch the book name" | Pick from *Did you mean*, or teach it in Training → Listen & correct. |
| "Microphone needs attention" | Use its buttons: *Look for driver updates* (Windows Update → Optional updates), *Open Device Manager*, or the microphone privacy settings. |
| Mic level bar doesn't move | Settings → Listening → **Find active microphone**. A feed from the sound desk works best. |
| "No sound from the microphone for 20 seconds" | Check mute switches and cables; it reconnects by itself when an unplugged mic comes back. |
| Wrong verse shown | Press **Back** (`Ctrl+Alt+B`), then teach it in Training → Listen & correct. |
| Falling behind the speaker | Choose a smaller *Accuracy* model. |
| Window too big / small | Settings → Display → Size. |
| `Ctrl+Alt+arrows` rotate the screen | The graphics driver uses them - turn its hotkeys off, or turn RootsVoice's shortcuts off. |

Still stuck? [Open an issue](../../issues/new/choose) and include the Activity log (Live screen → Activity).

## Contributing

Bug reports, ideas and pull requests are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md). Run the tests before sending changes:

```bash
python tests/test_logic.py
python tests/test_gui.py
```

## Licence

Copyright © 2026 nightfellas. All rights reserved - see [LICENSE](LICENSE).

RootsVoice uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT), OpenAI's Whisper models (MIT), [sounddevice](https://github.com/spatialaudio/python-sounddevice) (MIT), [PyAutoGUI](https://github.com/asweigart/pyautogui) (BSD-3) and [PyGetWindow](https://github.com/asweigart/PyGetWindow) (BSD-3). VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP and FreeShow are separate products by their own publishers and are not affiliated with RootsVoice.
