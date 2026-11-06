# Contributing to RootsVoice

Thanks for helping. RootsVoice is used live in church services, so the priorities are: **never show the wrong verse**, never freeze, and keep it simple for operators.

## Getting set up

```bat
git clone https://github.com/<your-account>/rootsvoice.git
cd rootsvoice
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python rootsvoice.py
```

The tests need only `numpy` and run on any operating system:

```bash
python tests/test_logic.py
python tests/test_gui.py
```

Both must print `ALL PASS`. They also run automatically on every push and pull request.

## Making a change

1. Create a branch: `git checkout -b fix/short-description`.
2. Keep changes focused - one fix or feature per pull request.
3. Add or update a check in `tests/` for anything the parser, learning or window does differently.
4. Update `README.md` / `docs/` if operators will notice the change, and add a line under a new heading at the top of `CHANGELOG.md`.
5. Open a pull request and fill in the template.

## Code guidelines

- Everything lives in `rootsvoice.py`, in clearly marked sections (see *Project layout* in the README). Put new code in the section it belongs to.
- Python 3.10+; 4-space indents; lines up to 120 characters.
- Plain-English names and comments - the people maintaining this may not be full-time programmers.
- Messages shown to operators are short, calm and say what to do next.
- Anything slow (speech model, recording, sending keys) runs off the window thread and reports back through the event queue; the window must never freeze.
- New colours go into **both** themes in `THEMES`; widgets register with `ui.register` / `ui.themed` so night mode keeps working.
- Never commit personal data: settings, training recordings and models are in `.gitignore` - keep it that way.

## Releasing a new version

1. Update the version in **four** places:
   - `APP_VERSION` in `rootsvoice.py`
   - `#define MyAppVersion` in `installer/RootsVoice.iss`
   - `filevers`, `prodvers`, `FileVersion`, `ProductVersion` in `installer/version_info.txt`
   - the file name in the final message of `build_installer.bat`
2. Move the notes in `CHANGELOG.md` under the new version and date.
3. Commit, then tag and push:
   ```bash
   git tag v2.2
   git push origin main v2.2
   ```
4. The *Build installer* workflow builds `RootsVoice-Setup-2.2.exe` and attaches it to a GitHub Release. Check the release notes and publish.

## Reporting bugs

Use **Issues → New issue → Bug report**. The most useful things to include: what was said, what RootsVoice showed, the Activity log from the Live screen, the Accuracy model, and the RootsVoice and Windows versions.
