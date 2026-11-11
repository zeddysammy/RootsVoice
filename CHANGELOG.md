# Changelog

All notable changes to RootsVoice. The newest version is at the top.

## [2.2.3] - 2026-11-11

### Fixed
- **"Missing faster-whisper".** RootsVoice now checks its components at startup. If the speech engine (or anything else) is missing, it offers **Install now**, installs it into the Python it is running with (showing progress), and restarts. Also under Help → *Install missing components*.
- Install problems are explained in plain words: no internet, a Python version the speech engine isn't built for, missing package installer, permissions (retried for the current user), full disk, and Microsoft's Visual C++ runtime (with its download link).

### Added
- **`setup_rootsvoice.bat`**: one double-click installs Python 3.11 (if needed), RootsVoice's own environment, every component, the Visual C++ runtime if the speech engine needs it, the speech model, and a desktop shortcut - then starts RootsVoice. **`RootsVoice.bat`** starts it afterwards.
- `--check-deps`, `--install` and `--make-shortcut` commands; Check setup lists the components.

## [2.2.2] - 2026-11-11

### Fixed
- **"Couldn't find the sounddevice module".** When the sounddevice library isn't installed (or won't load), RootsVoice now records with Windows' own sound system (winmm), so listening, training and Find active microphone all work without it.

### Added
- **Microphone list shows Windows' default by name** - "Windows default (Microphone Array ...)" first, then every microphone. A saved microphone that is unplugged is marked "(not connected)", and a refresh button picks up newly plugged ones.
- **Driver notices:** RootsVoice asks Windows which sound devices have driver problems (no driver, damaged, disabled...) and shows "Microphone needs attention" with buttons to *Look for driver updates* (Windows Update → Optional updates), *Open Device Manager* or *Open Sound settings*. It also spots Windows privacy settings blocking the microphone. Shown when the microphone fails to open, when Find active microphone hears nothing, and in Check setup.
- Check setup runs in the background, so the window no longer freezes while it checks.

## [2.2.1] - 2026-11-11

### Fixed
- **"Missing package: pyautogui" with BibleShow.** On Windows, RootsVoice now types, presses keys, clicks and finds windows with Windows' own functions, so pyautogui and pygetwindow are no longer needed there (they remain a fallback elsewhere). If a library is ever missing, the message says exactly how to fix it.
- Typing uses real characters, so references come out right with any keyboard layout (":" used to depend on the layout).
- Bringing the projection program to the front works even when Windows normally refuses it.
- **BibleShow uses F5** to open its reference box - no pointing needed. Settings saved by 2.2 are switched to F5 automatically (unless you had pointed to a box).

### Added
- Troubleshooting tip: a program running as administrator can't be typed into unless RootsVoice runs as administrator too.

## [2.2] - 2026-11-11

### Added
- **More projection software:** BibleShow, EasyWorship, ProPresenter, OpenLP, FreeShow and "Other program", alongside VideoPsalm. Settings → *Projection software* has a program list, **Detect** (finds the open one), and **Send a test verse**. Each program's settings are remembered separately.
- **Point to it:** for programs without a search shortcut, hold the mouse over the reference box once; RootsVoice clicks there (measured from the window corner, so moving the window is fine).
- **FreeShow** is controlled through its own API (`start_scripture`, `clear_all`) - nothing is typed.
- **Find active microphone** (Settings → Listening): listens to every input, shows which one hears sound and picks the most active; "Stereo Mix"-style loopback is never chosen.
- Help sections for *Projection software* and *Microphones*.

### Fixed
- **A misheard book no longer shows the previous book (often Psalm).** "Turn to *Habakook* chapter 2 verse 4" used to put Psalm 2:4 on screen after a Psalm; now nothing is sent and *Did you mean Habakkuk 2:4?* is offered. Picking it teaches the spelling.
- Better *Did you mean* guesses, by spelling and by sound (e.g. "Zefanaya" → Zephaniah, "Thesalonians" → 1 or 2 Thessalonians), and only for chapters that exist.
- **Microphone compatibility:** inputs that refuse 16 kHz or a single channel (many USB interfaces) are opened in a format they accept and converted.
- A saved microphone that is unplugged falls back to the default with a warning; if sound stops while listening, RootsVoice reconnects by itself; 20 seconds of silence brings a "check it isn't muted" warning.
- *Check setup* now really listens to the chosen microphone and checks the chosen projection software.

## [2.1] - 2026-11-06

### Added
- **Windows installer** (`RootsVoice-Setup-2.1.exe`) with a branded wizard, publisher *nightfellas*: install for one user or all users, optional bundled speech model, desktop shortcut, start with Windows, clean uninstall.
- `build_installer.bat` builds the installer on any Windows PC, fetching Python, libraries, the speech model and Inno Setup automatically.
- GitHub workflows: tests on every change, installer built and attached to a release for every version tag.
- **Moving through scripture in RootsAuto** without VideoPsalm hotkeys: verse stepper on the Live screen, system-wide shortcuts (`Ctrl+Alt+arrows`, `B`, `A`, `L`), presentation-clicker mode, voice commands "Roots next / back / 18".
- **Help** (quick start, commands, shortcuts, RootsAuto, training tips, troubleshooting) and **About** (version, publisher, privacy, data folder).
- **Check setup** button: confirms microphone, speech model, VideoPsalm and typing are ready.
- Size setting (Auto, Compact, Normal, Large); Auto picks Compact on laptop screens.

### Changed
- Window fits small screens: docks at the right edge, much smaller minimum size, text rewraps to the window width.
- Settings and Help use fold-out sections; keys and countdown use dropdowns.
- When installed, settings, training and models live in `%APPDATA%\RootsVoice` so they survive upgrades; a speech model shipped with the installer is used automatically.

### Fixed
- If the microphone system cannot start, an error is shown instead of hanging on "Starting...".

## [2.0] - 2026-11-06

### Added
- New minimalist design with light and **night mode**, clean icons, rounded cards, status pill and microphone level meter.
- Roots logo in the header and taskbar: white on green in light mode, black on green in night mode.
- **Sound-alikes**: ordinary words heard where a reference word must be are swapped for the scripture word they sound like ("John 3 *this* 16" → verse 16), learned from corrections, never applied to normal speech.

## [1.x] - earlier development

- **RootsAuto** autopilot: references and commands sent instantly; Back and Clear; scripture-only filter; chapter checking against all 66 books; one-chapter books; "chapter 4", "next/previous chapter", "clear the screen"; optional "Roots" wake word.
- Pause-based listening (no gaps, faster response).
- Training: practice prompts (15, editable), finish-anytime sessions, Listen & correct, live learning, sermon import, re-learn from everything, learned-words manager.
- Suggestions: next/previous verse, whole chapter, "Did you mean...?".
- Speech-model download with progress, stall detection and offline option.
- VideoPsalm control (Ctrl+F search, each reference replaces the last), verse included when spoken, numbered books (1st / First / I Peter).
