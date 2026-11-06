# Changelog

All notable changes to RootsVoice. The newest version is at the top.

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
