"""
RootsVoice - speak a Bible reference, show it in your projection software.

Listens to a microphone, picks out Bible references and voice commands, and shows them in
VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP, FreeShow or any program with a
reference box. Each new reference REPLACES whatever was there before. If a book name is
misheard, nothing is shown - RootsVoice asks "Did you mean ...?" instead of guessing.
Ordinary preaching is ignored: only scripture-related speech is acted on or shown.

What it understands
    "turn to John chapter three verse sixteen"  -> John 3:16
    "Psalm twenty three"                         -> Psalm 23      (no verse spoken = chapter only)
    "First Peter two nine" / "1st Peter 2:9"     -> 1 Peter 2:9
    "Jude three"                                 -> Jude 1:3      (one-chapter books)
    "verse five"                                 -> same book and chapter, verse 5
    "chapter four" / "chapter four verse two"    -> same book, chapter 4 (verse 2)
    "next verse" / "previous verse"              -> one verse forward / back
    "next chapter" / "previous chapter"          -> one chapter forward / back
    "clear the screen"                           -> presses your Clear key (set in Settings)
    Impossible references ("John 35", "Psalm 151") are ignored as mishearings.

RootsAuto (Live tab)
    Autopilot: references and commands go on screen the moment the speaker stops,
    with no confirmation. Click the green bar to pause it. "Back" undoes a wrong jump.
    Optional safety: Settings > "Short commands need 'Roots' first" ("Roots, next verse").

Suggestions
    One-click next verse / previous / whole chapter / next chapter, and "Did you mean...?"
    when a book name was misheard. Picking a "Did you mean" also teaches that spelling.

Voice Training tab
    C. Listen & correct -> say anything, edit the text it heard, Save correction. It learns
       misheard book names AND misheard commands ("neck's verse" -> "next verse").
    B. Practice prompts -> read ~15 editable prompts aloud; Finish session any time.
    A. Import recordings -> finds misheard book names in sermons; you approve them.
    Re-learn from everything -> re-checks every saved recording with the current model.
    Everything learned is used immediately by the Live tab and RootsAuto.

Live learning mode (Live tab)
    Tick the box, click the line it got wrong, type what it should have been, press
    "Learn & send".

Look
    Light and night mode (moon / sun button, top right). The Roots logo turns white on green in
    light mode and black on green in night mode. Uses Windows' own icon font, nothing to install.

Install (Windows):
    pip install faster-whisper sounddevice numpy pyautogui pygetwindow

Run:
    python rootsvoice.py                                  # opens the GUI
    python rootsvoice.py --test "john 3 16|next verse"    # parser test
    python rootsvoice.py --scan "open habakuk two four"   # near-miss test
"""
import collections
import difflib
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import wave

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows: avoids symlink problems
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")         # fail instead of hanging forever

# --------------------------------------------------------------------------
# PATHS AND DEFAULT SETTINGS (editable in the Settings tab)
# --------------------------------------------------------------------------
FROZEN = bool(getattr(sys, "frozen", False))          # True when running as the installed RootsVoice.exe
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
# Settings, training and downloaded models must be writable: next to the script when run from source,
# in %APPDATA%\RootsVoice when installed (Program Files is read-only for normal users).
BASE_DIR = (os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "RootsVoice") if FROZEN
            else APP_DIR)
os.makedirs(BASE_DIR, exist_ok=True)
BUNDLED_MODELS_DIR = os.path.join(APP_DIR, "models")    # a model shipped with the installer (read-only)
SETTINGS_FILE = os.path.join(BASE_DIR, "rootsvoice_settings.json")
ALIASES_FILE = os.path.join(BASE_DIR, "rootsvoice_aliases.json")   # learned book spellings
REPLACEMENTS_FILE = os.path.join(BASE_DIR, "rootsvoice_replacements.json")  # learned command phrases
SOUNDALIKES_FILE = os.path.join(BASE_DIR, "rootsvoice_soundalikes.json")    # learned: {"this": "verse"}
TRAINING_DIR = os.path.join(BASE_DIR, "rootsvoice_training")        # recorded samples
MODELS_DIR = os.path.join(BASE_DIR, "rootsvoice_models")            # downloaded speech models

DEFAULTS = {
    "target": "videopsalm",         # projection software: see TARGETS
    "window_title": "VideoPsalm",   # text that appears in the program's window title
    "focus": "hotkey",              # how to reach its reference box: "hotkey" or "click" (a spot you point to)
    "search_hotkey": "ctrl+f",      # the shortcut that opens its search / reference box
    "click_x": None,                # where the reference box is, from the window's top-left corner
    "click_y": None,
    "api_port": 5506,               # FreeShow's API port
    "api_key": "",                  # FreeShow's API key, if one is set
    "targets": {},                  # saved settings for each program you have used
    "after_keys": "enter",          # comma-separated keys pressed after typing, e.g. "enter,enter"
    "separator": ":",               # between chapter and verse
    "model": "base.en",             # tiny.en / base.en / small.en / medium.en
    "mic": "",                      # input device name; empty = system default
    "mode": "manual",               # "manual" = operator confirms, "auto" = send after a delay
    "auto_delay": 3,                # seconds before auto-send
    "always_on_top": True,
    "live_learning": False,         # show the "fix what it heard" panel on the Live tab
    "roots_auto": False,            # RootsAuto: act on voice instantly, no confirmation
    "next_key": "",                 # the program's own next-verse key; blank = type the reference
    "prev_key": "",                 # key for previous verse; blank = type the reference
    "clear_key": "",                # the program's blank-screen key; blank = voice clear is off
    "wake_word": False,             # short commands ("next verse") need "Roots" first
    "show_all_speech": False,       # log everything, not just scripture-related speech
    "theme": "light",               # "light" or "dark" (night mode)
    "size": "auto",                 # window size: auto, compact, normal, large
    "global_keys": True,            # Ctrl+Alt shortcuts that work while the projection software is in front
    "clicker": False,               # presentation clicker: Page Down / Page Up = next / previous verse
}
APP_VERSION = "2.2.3"
APP_PUBLISHER = "nightfellas"
SAMPLE_RATE = 16000
REPEAT_WINDOW = 20      # seconds in which the same reference is ignored
HISTORY_SIZE = 8

# --------------------------------------------------------------------------
# BIBLE BOOKS
# --------------------------------------------------------------------------
# Numbered books: every way a speaker (or the transcriber) might say or write the number.
# 'one'/'two'/'three' never need listing - they are converted to digits before matching.
_PREFIXES = {
    1: ["1", "first", "1st"],
    2: ["2", "second", "2nd", "ii"],
    3: ["3", "third", "3rd", "iii"],
}
PREFIX_NUM = {p: n for n, ps in _PREFIXES.items() for p in ps}


def _num(n, *bases):
    return [f"{p} {b}" for p in _PREFIXES[n] for b in bases]


BOOKS = {
    "Genesis": ["genesis"], "Exodus": ["exodus"], "Leviticus": ["leviticus"],
    "Numbers": ["numbers"], "Deuteronomy": ["deuteronomy"], "Joshua": ["joshua"],
    "Judges": ["judges"], "Ruth": ["ruth"],
    "1 Samuel": _num(1, "samuel"), "2 Samuel": _num(2, "samuel"),
    "1 Kings": _num(1, "kings"), "2 Kings": _num(2, "kings"),
    "1 Chronicles": _num(1, "chronicles"), "2 Chronicles": _num(2, "chronicles"),
    "Ezra": ["ezra"], "Nehemiah": ["nehemiah"], "Esther": ["esther"], "Job": ["job"],
    "Psalm": ["psalms", "psalm"], "Proverbs": ["proverbs"],
    "Ecclesiastes": ["ecclesiastes"], "Song of Solomon": ["song of solomon", "song of songs"],
    "Isaiah": ["isaiah"], "Jeremiah": ["jeremiah"], "Lamentations": ["lamentations"],
    "Ezekiel": ["ezekiel"], "Daniel": ["daniel"], "Hosea": ["hosea"], "Joel": ["joel"],
    "Amos": ["amos"], "Obadiah": ["obadiah"], "Jonah": ["jonah"], "Micah": ["micah"],
    "Nahum": ["nahum"], "Habakkuk": ["habakkuk"], "Zephaniah": ["zephaniah"],
    "Haggai": ["haggai"], "Zechariah": ["zechariah"], "Malachi": ["malachi"],
    "Matthew": ["matthew"], "Mark": ["mark"], "Luke": ["luke"], "John": ["john"],
    "Acts": ["acts"], "Romans": ["romans"],
    "1 Corinthians": _num(1, "corinthians", "corinthian"),
    "2 Corinthians": _num(2, "corinthians", "corinthian"),
    "Galatians": ["galatians"], "Ephesians": ["ephesians"], "Philippians": ["philippians"],
    "Colossians": ["colossians"],
    "1 Thessalonians": _num(1, "thessalonians", "thessalonian"),
    "2 Thessalonians": _num(2, "thessalonians", "thessalonian"),
    "1 Timothy": _num(1, "timothy"), "2 Timothy": _num(2, "timothy"),
    "Titus": ["titus"], "Philemon": ["philemon"], "Hebrews": ["hebrews"], "James": ["james"],
    "1 Peter": _num(1, "peter"), "2 Peter": _num(2, "peter"),
    "1 John": _num(1, "john"), "2 John": _num(2, "john"), "3 John": _num(3, "john"),
    "Jude": ["jude"], "Revelation": ["revelations", "revelation"],
}

# base word ("peter", "habakkuk") -> books it can belong to; used for near-miss matching
BASE_TO_BOOKS = {}
for _book, _names in BOOKS.items():
    for _a in _names:
        _w = _a.split()
        if len(_w) == 1 or _w[0] in PREFIX_NUM:
            BASE_TO_BOOKS.setdefault(_w[-1], set()).add(_book)

_RANGE = r"(?:\s*(?:to|through|thru|-)\s*(?P<{}>\d{{1,3}}))?"
# Chapters in each book, in BOOKS order - used to reject impossible references (e.g. "John 35").
CHAPTERS = dict(zip(BOOKS, [
    50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42, 150, 31, 12, 8, 66, 52,
    5, 48, 12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4,
    28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1, 1, 22]))
MAX_VERSE = 176  # Psalm 119 is the longest chapter

# Voice commands. Kept to whole phrases so normal preaching doesn't trigger them.
_WAKE = r"(?:roots|routes|root|ruts)"
NEXT_RE = re.compile(rf"\b(?:(?:next|following) verse|{_WAKE} (?:next|forward))\b")
PREV_RE = re.compile(rf"\b(?:previous verse|verse before|go back a verse|back one verse|{_WAKE} (?:back|previous))\b")
WAKE_NUM_RE = re.compile(rf"\b{_WAKE} (\d{{1,3}})\b")   # "Roots 18" = verse 18
NEXT_CH_RE = re.compile(r"\bnext chapter\b")
PREV_CH_RE = re.compile(r"\bprevious chapter\b")
CLEAR_RE = re.compile(r"\b(?:clear|blank) (?:the )?screen\b")
WAKE_RE = re.compile(r"\b(?:roots|routes|root|ruts)\b")
COMMAND_RES = (NEXT_RE, PREV_RE, NEXT_CH_RE, PREV_CH_RE, CLEAR_RE)
_STOP_WORDS = {"chapter", "verse", "verses", "next", "previous"}

UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}

ALIAS_TO_BOOK = {}
KNOWN_WORDS = set()
MAIN_RE = None


def load_custom_aliases():
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k).lower().strip(): v for k, v in data.items() if v in BOOKS and str(k).strip()}


def compile_patterns():
    """(Re)build the book-name lookup and the main regex. Called again whenever
    learned spellings change."""
    global ALIAS_TO_BOOK, KNOWN_WORDS, BOOK_END_WORDS, SCRIPTURE_WORDS, MAIN_RE
    aliases = {a: book for book, names in BOOKS.items() for a in names}
    aliases.update(load_custom_aliases())
    ALIAS_TO_BOOK = aliases
    KNOWN_WORDS = {w for a in aliases for w in a.split()}
    BOOK_END_WORDS = {a.split()[-1] for a in aliases}       # "peter" in "first peter"
    SCRIPTURE_WORDS = (KNOWN_WORDS | set(PREFIX_NUM) | set(UNITS) | set(TENS) | _REFERENCE_WORDS)
    alias_re = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    # One pass, left to right: a full reference (book + chapter [+ verse]) or a bare
    # "verse N" that borrows the book/chapter from context.
    MAIN_RE = re.compile(
        rf"\b(?P<book>{alias_re})\s+(?:chapter\s+)?(?P<ch>\d{{1,3}})"
        rf"(?:\s*(?:verses?|:|colon)?\s*(?P<v1>\d{{1,3}}){_RANGE.format('v2')})?"
        rf"|\bchapter\s+(?P<bc>\d{{1,3}})(?:\s*(?:verses?|:|colon)\s*(?P<bcv1>\d{{1,3}}){_RANGE.format('bcv2')})?"
        rf"|\bverses?\s+(?P<bv1>\d{{1,3}}){_RANGE.format('bv2')}"
    )
    _compile_replacements()
    _load_soundalikes()


# ---- sound-alikes: ordinary words heard in place of the words references are made of ----
# Only swapped where a reference word MUST be (e.g. between the chapter and the verse number),
# so "this is good" is untouched but "John 3 this 16" becomes "John 3 verse 16".
_REFERENCE_WORDS = {"chapter", "verse", "verses", "to", "through", "thru", "and", "colon",
                    "next", "previous", "following", "hundred"}
SOUNDALIKES = {
    "verse": ["this", "is", "these", "vers", "vs", "worse", "was", "vas", "fears", "fierce",
              "purse", "nurse", "birth", "voice", "base", "bus"],
    "chapter": ["chapta", "chaptor", "chapters", "captor", "capture", "chatter", "shatter", "chap",
                "cheaper", "chopper", "japter", "shafter"],
}
NUMBER_SOUNDALIKES = {"won": "1", "too": "2", "tree": "3", "free": "3", "for": "4", "fore": "4",
                      "fife": "5", "sex": "6", "sick": "6", "ate": "8", "nein": "9", "tin": "10"}
LEARNED_SOUNDS = {}
BOOK_END_WORDS = set()
SCRIPTURE_WORDS = set()
_COMMON = {"to", "the", "and", "of", "a", "an", "is", "it", "in", "on", "at", "i", "we", "you", "he",
           "she", "they", "that", "this", "these", "was", "for", "so", "be", "has", "have", "are"}


def _load_soundalikes():
    global LEARNED_SOUNDS
    try:
        with open(SOUNDALIKES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    LEARNED_SOUNDS = {str(k).lower().strip(): str(v).lower().strip() for k, v in data.items() if str(k).strip()}


def add_soundalike(word, target):
    word, target = word.lower().strip(), target.lower().strip()
    if not word or word == target or LEARNED_SOUNDS.get(word) == target:
        return False
    data = dict(LEARNED_SOUNDS)
    data[word] = target
    with open(SOUNDALIKES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _load_soundalikes()
    return True


_SOUND_FOLD = [("tch", "S"), ("ch", "S"), ("sh", "S"), ("th", "B"), ("ph", "B"), ("ck", "K"), ("qu", "K")]
_SOUND_CLASS = {**dict.fromkeys("bpfvw", "B"), **dict.fromkeys("dt", "D"), **dict.fromkeys("szcx", "S"),
                **dict.fromkeys("gkq", "K"), **dict.fromkeys("mn", "N"), **dict.fromkeys("lr", "R"),
                **dict.fromkeys("jy", "J")}


def sound_key(word):
    """Rough 'how it sounds' skeleton: consonant groups that accents commonly swap
    (th/v/f/b, d/t, s/z, ...) are folded together and vowels dropped. 'this' and 'verse'
    both start with the same group and end in an s-sound."""
    w = word.lower()
    for a, b in _SOUND_FOLD:
        w = w.replace(a, b)
    key = "".join(_SOUND_CLASS.get(ch, ch if ch.isupper() else "") for ch in w)
    return re.sub(r"(.)\1+", r"\1", key)


def sounds_like(word, target, cutoff=0.75):
    a, b = sound_key(word), sound_key(target)
    return bool(a and b) and difflib.SequenceMatcher(None, a, b).ratio() >= cutoff


def _slot_word(word, wanted):
    """Is `word` (heard where `wanted` belongs) really `wanted`? Learned first, then the
    built-in list, then a sound comparison."""
    if LEARNED_SOUNDS.get(word) == wanted or word in SOUNDALIKES.get(wanted, ()):
        return True
    return sounds_like(word, wanted)


def fit_scripture_slots(toks):
    """Swap words that can't be part of a reference for the similar-sounding word that can,
    but only in the positions where a reference word has to be."""
    out = list(toks)
    for i, w in enumerate(out):
        if not w.isalpha():
            continue
        prev = out[i - 1] if i > 0 else ""
        nxt = out[i + 1] if i + 1 < len(out) else ""
        # a number word after a book name / 'chapter' / 'verse': "Romans ate 28" -> "Romans 8 28"
        if prev in BOOK_END_WORDS | {"chapter", "verse", "verses"} and (nxt.isdigit() or nxt in ("verse", "chapter", ":")):
            num = LEARNED_SOUNDS.get(w) if (LEARNED_SOUNDS.get(w) or "").isdigit() else NUMBER_SOUNDALIKES.get(w)
            if num and w not in SCRIPTURE_WORDS:
                out[i] = num
                continue
        if w in SCRIPTURE_WORDS or not nxt.isdigit():
            continue
        before_prev = out[i - 2] if i > 1 else ""
        if (prev.isdigit() and before_prev in BOOK_END_WORDS | {"chapter"}
                and _slot_word(w, "verse")):                         # "John 3 this 16"
            out[i] = "verse"
        elif prev in BOOK_END_WORDS and _slot_word(w, "chapter"):  # "John cheaper 3"
            out[i] = "chapter"
        elif w not in _COMMON and LEARNED_SOUNDS.get(w) in ("verse", "chapter"):
            out[i] = LEARNED_SOUNDS[w]                             # learned, uncommon word: "worse 5"
    return out


# ---- learned command phrases, e.g. {"neck's verse": "next verse"} ----
REPL = {}
REPL_RE = None


def load_replacements():
    try:
        with open(REPLACEMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {str(k).lower().strip(): str(v).lower().strip() for k, v in data.items() if str(k).strip()}


def _compile_replacements():
    global REPL, REPL_RE
    REPL = load_replacements()
    keys = sorted(REPL, key=len, reverse=True)
    REPL_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b") if keys else None


def apply_replacements(text):
    return REPL_RE.sub(lambda m: REPL[m.group(1)], text) if REPL_RE else text


def add_replacement(heard, correct):
    heard, correct = heard.lower().strip(), correct.lower().strip()
    if not heard or heard == correct or REPL.get(heard) == correct:
        return False
    data = load_replacements()
    data[heard] = correct
    with open(REPLACEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _compile_replacements()
    return True


def remove_learned(phrase):
    """Forget one learned spelling, command phrase or sound-alike."""
    for path in (ALIASES_FILE, REPLACEMENTS_FILE, SOUNDALIKES_FILE):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if phrase in data:
            del data[phrase]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    compile_patterns()


compile_patterns()


def add_aliases(new):
    """Save learned spellings ({'habakuk': 'Habakkuk'}) and apply them. Returns how many were new."""
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    added = 0
    for k, v in new.items():
        k = str(k).lower().strip()
        if k and v in BOOKS and k not in ALIAS_TO_BOOK and cur.get(k) != v:
            cur[k] = v
            added += 1
    if added:
        with open(ALIASES_FILE, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2, ensure_ascii=False)
        compile_patterns()
    return added


def clear_aliases():
    """Forget everything learned (book spellings, command phrases and sound-alikes)."""
    for path in (ALIASES_FILE, REPLACEMENTS_FILE, SOUNDALIKES_FILE):
        try:
            os.remove(path)
        except OSError:
            pass
    compile_patterns()


# --------------------------------------------------------------------------
# NUMBERS AND REFERENCES
# --------------------------------------------------------------------------


def normalize(text):
    """Tidy transcriber quirks before matching."""
    t = text.lower().replace("\u2013", "-").replace("\u2014", "-")      # en/em dash -> hyphen
    t = re.sub(r"['\u2019]", " ", t)                                       # neck's -> neck s
    t = re.sub(r"\b(\d{1,3})\s?(?:st|nd|rd|th)\b", r"\1", t)             # 1st / 2 nd -> 1 / 2
    t = re.sub(r"(?<=[a-z])-(?=[a-z0-9])|(?<=\d)-(?=[a-z])", " ", t)      # first-peter, 1-peter, twenty-three
    t = re.sub(r"(?<=\d)\.(?=\d)", ":", t)                                # 3.16 -> 3:16
    return t


def words_to_digits(text):
    """Convert spoken numbers ('three sixteen', 'one hundred nineteen') to digits, and swap
    sound-alike words that sit where a reference word must be."""
    return " ".join(fit_scripture_slots(_digit_tokens(text)))


def explain_soundalikes(text):
    """[(heard word, scripture word)] for every sound-alike swap made in `text`."""
    raw = _digit_tokens(text)
    return [(a, b) for a, b in zip(raw, fit_scripture_slots(raw)) if a != b]


def _digit_tokens(text):
    tokens = re.findall(r"[a-z0-9]+|:|-", apply_replacements(normalize(text)))
    out, i = [], 0
    while i < len(tokens):
        if tokens[i] in UNITS or tokens[i] in TENS:
            val, i = _read_number(tokens, i)
            out.append(str(val))
        else:
            out.append(tokens[i])
            i += 1
    return out


def _read_number(tokens, i):
    t = tokens[i]
    val = UNITS.get(t, TENS.get(t))
    i += 1
    if t in TENS and i < len(tokens) and tokens[i] in UNITS and 1 <= UNITS[tokens[i]] <= 9:
        val += UNITS[tokens[i]]
        i += 1
    if i < len(tokens) and tokens[i] == "hundred":
        val *= 100
        i += 1
        if i < len(tokens) and tokens[i] == "and":
            i += 1
        if i < len(tokens) and (tokens[i] in UNITS or tokens[i] in TENS):
            rest, i = _read_number(tokens, i)
            val += rest
    return val, i


def format_ref(book, ch, v1=None, v2=None, sep=":"):
    """Chapter only when no verse was given; otherwise include the verse (and range)."""
    ref = f"{book} {ch}"
    if v1:
        ref += f"{sep}{v1}"
        if v2 and v2 > v1:
            ref += f"-{v2}"
    return ref


def _int(x):
    return int(x) if x else None


class RefTracker:
    """Turns transcribed speech into a reference string and remembers the last
    book/chapter/verse so 'verse 5', 'chapter 4', 'next verse' etc. work.
    After parse(): .action says what happened ('ref', 'verse', 'chapter', 'next', 'prev',
    'next_ch', 'prev_ch' or None) and .clear is True if 'clear the screen' was heard."""

    def __init__(self, separator=":"):
        self.separator = separator
        self.require_wake = False
        self.reset()

    def reset(self):
        self.book = self.ch = self.v1 = self.v2 = None
        self.action = None
        self.clear = False
        self.unclear = False    # True when a book name was heard but not recognised

    def format(self):
        return format_ref(self.book, self.ch, self.v1, self.v2, self.separator)

    def _set(self, book, ch, v1=None, v2=None, spoken=False):
        """Apply a reference only if it exists in the Bible. Returns True if applied."""
        chapters = CHAPTERS.get(book, 150)
        if spoken and chapters == 1 and v1 is None and ch > 1:   # "Jude 3" means Jude 1:3
            ch, v1 = 1, ch
        if not (1 <= ch <= chapters):
            return False
        if v1 is not None and not 1 <= v1 <= MAX_VERSE:
            return False
        if v2 is not None and not (v1 and v1 < v2 <= MAX_VERSE):
            v2 = None
        self.book, self.ch, self.v1, self.v2 = book, ch, v1, v2
        return True

    def parse(self, text, fresh_text=None):
        """`text` may start with the tail of the previous phrase (so a reference split
        across two phrases is still caught). Only matches reaching into `fresh_text`
        are acted on, so nothing from earlier speech is ever applied twice."""
        self.action, self.clear, self.unclear = None, False, False
        if fresh_text is None or not text.endswith(fresh_text):
            tail, fresh = "", text
        else:
            tail, fresh = text[: len(text) - len(fresh_text)], fresh_text
        tail_d, fresh_d = words_to_digits(tail), words_to_digits(fresh)
        combined = f"{tail_d} {fresh_d}" if tail_d else fresh_d
        start = len(tail_d) + 1 if tail_d else 0
        woke = not self.require_wake or bool(WAKE_RE.search(combined))

        found = None
        for m in MAIN_RE.finditer(combined):
            if m.end() <= start:
                continue  # entirely in the previous phrase: already handled
            if m.group("book"):
                if self._set(ALIAS_TO_BOOK[m.group("book")], int(m.group("ch")), _int(m.group("v1")),
                             _int(m.group("v2")), spoken=True):
                    found, self.action = self.format(), "ref"
            elif not (self.book and woke):
                continue
            elif book_was_misheard(combined, m.start()):
                # "Turn to Habakook chapter 2": the book wasn't recognised. Never fall back to the
                # previous book (that is how Psalm used to appear) - ask instead.
                self.unclear = True
                continue
            elif m.group("bc"):
                if self._set(self.book, int(m.group("bc")), _int(m.group("bcv1")), _int(m.group("bcv2"))):
                    found, self.action = self.format(), "chapter"
            elif self._set(self.book, self.ch, int(m.group("bv1")), _int(m.group("bv2"))):
                found, self.action = self.format(), "verse"

        if self.book and woke:
            for _ in NEXT_RE.finditer(fresh_d):
                if self._set(self.book, self.ch, ((self.v2 or self.v1) or 0) + 1):
                    found, self.action = self.format(), "next"
            for _ in PREV_RE.finditer(fresh_d):
                if self._set(self.book, self.ch, max(1, (self.v1 or 2) - 1)):
                    found, self.action = self.format(), "prev"
            for _ in NEXT_CH_RE.finditer(fresh_d):
                if self._set(self.book, self.ch + 1):
                    found, self.action = self.format(), "next_ch"
            for _ in PREV_CH_RE.finditer(fresh_d):
                if self._set(self.book, self.ch - 1):
                    found, self.action = self.format(), "prev_ch"
        if self.book:
            for m in WAKE_NUM_RE.finditer(fresh_d):
                if self._set(self.book, self.ch, int(m.group(1))):
                    found, self.action = self.format(), "verse"
        if woke and CLEAR_RE.search(fresh_d):
            self.clear = True
        return found

    def step(self, kind, n=None):
        """Move from the current reference: 'next', 'prev', 'next_ch', 'prev_ch' or 'verse' (n).
        Returns the new reference, or None if there is nowhere to go."""
        if not (self.book and self.ch):
            return None
        before = self.format()
        moves = {
            "next": lambda: self._set(self.book, self.ch, ((self.v2 or self.v1) or 0) + 1),
            "prev": lambda: self._set(self.book, self.ch, max(1, (self.v1 or 2) - 1)),
            "next_ch": lambda: self._set(self.book, self.ch + 1),
            "prev_ch": lambda: self._set(self.book, self.ch - 1),
            "verse": lambda: self._set(self.book, self.ch, n),
        }
        if kind not in moves or not moves[kind]() or self.format() == before:
            return None
        self.action = kind
        return self.format()

    # --- predictions (do not change the context) ---
    def peek_next(self):
        if not (self.book and self.ch):
            return None
        v = ((self.v2 or self.v1) or 0) + 1
        return format_ref(self.book, self.ch, v, None, self.separator) if v <= MAX_VERSE else None

    def peek_prev(self):
        if not (self.book and self.ch and self.v1 and self.v1 > 1):
            return None
        return format_ref(self.book, self.ch, self.v1 - 1, None, self.separator)

    def peek_chapter(self):
        if not (self.book and self.ch and self.v1):
            return None
        return format_ref(self.book, self.ch)

    def peek_next_chapter(self):
        if not (self.book and self.ch and self.ch < CHAPTERS.get(self.book, 0)):
            return None
        return format_ref(self.book, self.ch + 1)


def find_reference(text):
    """Stateless helper: one phrase in, reference string (or None) out."""
    return RefTracker().parse(text)


# --------------------------------------------------------------------------
# SUGGESTIONS
# --------------------------------------------------------------------------
def _book_for(base_word, num):
    for b in sorted(BASE_TO_BOOKS.get(base_word, ())):
        head = b.split()[0]
        if (num is None and not head.isdigit()) or (num is not None and head == str(num)):
            return b
    return None


# Words that can sit just before "chapter 4" / "verse 4" without being a book name.
_CONTEXT_WORDS = {
    "to", "the", "and", "in", "now", "then", "so", "our", "of", "from", "into", "at", "on", "onto", "see", "read",
    "look", "go", "back", "same", "this", "that", "its", "it", "is", "also", "again", "with", "or", "let", "lets",
    "us", "please", "turn", "open", "we", "you", "i", "a", "an", "are", "was", "were", "has", "have", "there",
    "here", "say", "says", "said", "verse", "verses", "chapter", "next", "previous", "following", "roots",
    "amen", "okay", "ok", "yes", "right", "well", "book", "bible", "reading", "where", "which", "what", "as",
    "for", "by", "but", "if", "when", "till", "until", "start", "starting", "begin", "beginning", "down",
    "up", "continue", "continuing", "jump", "onward", "onwards", "same", "very", "first", "second", "third",
    "last", "end", "his", "her", "my", "your", "their", "all", "out", "about", "over", "through", "verse's",
}


def book_was_misheard(text, pos):
    """True when the word just before position `pos` of the (already normalised) text looks like
    a book name that wasn't recognised - 'turn to habakook chapter 2', 'open zefanaya 3 verse 17'.
    'chapter 2' / 'verse 17' must then NOT be applied to whatever book was used before."""
    before = text[:pos].split()
    if len(before) >= 2 and before[-1].isdigit():   # "zefanaya 3 verse 17"
        before = before[:-1]
        if before and before[-1] == "chapter":
            before = before[:-1]
    if not before:
        return False
    w = before[-1]
    if not w.isalpha() or len(w) < 3:
        return False
    return w not in SCRIPTURE_WORDS and w not in _CONTEXT_WORDS


def guess_books(word, num=None, n=3):
    """Books a misheard word probably meant, best first. Compares spelling and how it sounds,
    so 'habakook' -> Habakkuk, 'zefanaya' -> Zephaniah, 'lamentasions' -> Lamentations."""
    word = word.lower()
    wkey = sound_key(word)
    scored = {}
    for base in BASE_TO_BOOKS:
        spell = difflib.SequenceMatcher(None, word, base).ratio()
        bkey = sound_key(base)
        sound = (difflib.SequenceMatcher(None, wkey, bkey).ratio()
                 if len(wkey) >= 3 and len(bkey) >= 3 and word[:1] == base[:1] else 0.0)
        score = max(spell, 0.9 * sound)
        if score < 0.7:
            continue
        book = _book_for(base, num)
        # "Thessalonians" said without First/Second: offer both books
        candidates = [book] if book else (sorted(BASE_TO_BOOKS[base]) if num is None else [])
        for i, b in enumerate(candidates):
            s = score - 0.01 * i
            if s > scored.get(b, 0):
                scored[b] = s
    return [b for b, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:n]


def scan_near_misses(text, guesses=1):
    """Find 'almost' book names followed by a chapter number, e.g. 'habakuk 2 4' or
    'first pita 2 9'. Returns [{'phrase','book','ch','v'}] - up to `guesses` books per phrase."""
    toks = words_to_digits(text).split()
    out = []
    for i, w in enumerate(toks):
        if not w.isalpha() or len(w) < 4 or w in KNOWN_WORDS or w in _STOP_WORDS:
            continue
        j = i + 1
        if j < len(toks) and toks[j] == "chapter":
            j += 1
        if j >= len(toks) or not toks[j].isdigit():
            continue
        num, phrase = None, w
        if i > 0 and toks[i - 1] in PREFIX_NUM:
            num, phrase = PREFIX_NUM[toks[i - 1]], f"{toks[i - 1]} {w}"
        books = guess_books(w, num, n=guesses)
        if not books:
            continue
        k = j + 1
        if k < len(toks) and toks[k] in ("verse", "verses", ":"):
            k += 1
        verse = int(toks[k]) if k < len(toks) and toks[k].isdigit() else None
        for book in books:
            out.append({"phrase": phrase, "book": book, "ch": int(toks[j]), "v": verse, "pos": i})
    return out


def spoken_name(book):
    """'1 Peter' -> 'First Peter' (how a preacher would say it)."""
    ordinals = {"1": "First", "2": "Second", "3": "Third"}
    head, _, rest = book.partition(" ")
    return f"{ordinals[head]} {rest}" if head in ordinals else book


def book_completions(text, n=4):
    """Book names that start with what the operator has typed (for the manual box)."""
    t = normalize(text).strip()
    if not t or re.search(r"[a-z]+\s+\d", t):  # empty, or a book is already followed by a number
        return []
    out = []
    for book, names in BOOKS.items():
        candidates = [book.lower(), spoken_name(book).lower()] + names
        if any(c.startswith(t) for c in candidates) and book not in out:
            out.append(book)
        if len(out) >= n:
            break
    return out


def build_suggestions(tracker, near_misses=(), predict=True, limit=4):
    """One-click options: 'Did you mean...' for misheard books, then next/previous/chapter."""
    sep = tracker.separator
    out, seen = [], set()

    def add(label, ref, learn=None):
        if ref and ref not in seen:
            seen.add(ref)
            out.append({"label": label, "action": "send", "ref": ref, "learn": learn})

    near_misses = list(near_misses)
    last = max((m.get("pos", 0) for m in near_misses), default=0)
    for m in [m for m in near_misses if m.get("pos", 0) == last][:3]:
        if not 1 <= m["ch"] <= CHAPTERS.get(m["book"], 150):
            continue
        ref = format_ref(m["book"], m["ch"], m["v"], None, sep)
        add(f"Did you mean {ref}?", ref, (m["phrase"], m["book"]))
    if predict:
        add(f"Next: {tracker.peek_next()}", tracker.peek_next())
        add(f"Previous: {tracker.peek_prev()}", tracker.peek_prev())
        add(f"Whole chapter: {tracker.peek_chapter()}", tracker.peek_chapter())
        add(f"Next chapter: {tracker.peek_next_chapter()}", tracker.peek_next_chapter())
    return out[:limit]


# --------------------------------------------------------------------------
# SCRIPTURE FILTER - keep only speech that looks like a reference or a command
# --------------------------------------------------------------------------
_FILLER = {"to", "the", "turn", "open", "and", "of", "now", "for", "our", "your", "a", "an",
           "is", "it", "in", "on", "at", "i", "we", "you", "he", "she", "they", "that", "this"}


def scripture_snippet(text, width=4):
    """Return just the scripture-related part of `text` (book + numbers, commands), or None
    if nothing in it relates to scripture. Unrelated preaching is ignored."""
    toks = words_to_digits(text).split()
    if not toks:
        return None
    joined, offsets, pos = " ".join(toks), [], 0
    for t in toks:
        offsets.append(pos)
        pos += len(t) + 1
    hits = set()
    book_words = KNOWN_WORDS - set(PREFIX_NUM) - _FILLER
    for i, w in enumerate(toks):
        nxt = toks[i + 1: i + 4]
        if w in book_words and any(x.isdigit() for x in nxt):
            hits.add(i)
        elif w in ("verse", "verses", "chapter") and nxt[:1] and nxt[0].isdigit():
            hits.update({i, i + 1})
        elif w.isdigit() and nxt[:1] and nxt[0].isdigit():
            hits.update({i, i + 1})
        elif WAKE_RE.fullmatch(w):
            hits.add(i)
    for rx in COMMAND_RES:
        for m in rx.finditer(joined):
            hits.update(i for i, o in enumerate(offsets) if m.start() <= o < m.end())
    if not hits:
        return joined if scan_near_misses(text) else None
    keep = sorted({j for i in hits for j in range(max(0, i - width), min(len(toks), i + width + 1))})
    out, prev = [], None
    for j in keep:
        if prev is not None and j != prev + 1:
            out.append("\u2026")
        out.append(toks[j])
        prev = j
    return " ".join(out)


_COMMAND_VOCAB = {"next", "following", "previous", "verse", "chapter", "clear", "blank", "screen",
                  "roots", "go", "back", "a", "one", "the", "before"}
_COMMAND_KEYS = {"next", "previous", "verse", "chapter", "clear", "blank", "roots"}


def learn_from_correction(heard, corrected):
    """Compare what was heard with the corrected text and work out what to learn.
    Returns [("book", heard_phrase, Book)] / [("phrase", heard_phrase, correct_phrase)].
    Number-only differences are never learned (they change from verse to verse)."""
    h = words_to_digits(heard).split()
    c = words_to_digits(corrected).split()
    out = []
    sm = difflib.SequenceMatcher(None, h, c, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        hs, cs = h[i1:i2], c[j1:j2]
        before = h[i1 - 1] if i1 > 0 else ""
        after = h[i2] if i2 < len(h) else ""
        if len(hs) == 1 and len(cs) == 1 and hs[0].isalpha() and hs[0] not in SCRIPTURE_WORDS:
            # "this" heard where "verse" was said: learn it, but only for use inside references
            if cs[0] in ("verse", "chapter") and after.isdigit():
                out.append(("sound", hs[0], cs[0]))
                continue
            if cs[0].isdigit() and before in BOOK_END_WORDS | {"chapter", "verse", "verses"}:
                out.append(("sound", hs[0], cs[0]))   # "Romans ate 28" -> 8
                continue
        if len(hs) > 4 or any(x.isdigit() for x in hs + cs):
            continue
        candidates = [(hs, cs)]
        if i1 > 0 and j1 > 0 and h[i1 - 1] == c[j1 - 1] and h[i1 - 1] in PREFIX_NUM:
            candidates.insert(0, ([h[i1 - 1]] + hs, [c[j1 - 1]] + cs))  # keep "first" with "pita"
        for hh, cc in candidates:
            book = ALIAS_TO_BOOK.get(" ".join(cc))
            phrase = " ".join(hh)
            if book and phrase not in ALIAS_TO_BOOK and not all(x in _FILLER for x in hh):
                out.append(("book", phrase, book))
                break
        else:
            if (set(cs) <= _COMMAND_VOCAB and set(cs) & _COMMAND_KEYS
                    and all(x.isalpha() and x not in UNITS and x not in TENS for x in hs)
                    and not all(x in _FILLER for x in hs)):
                out.append(("phrase", " ".join(hs), " ".join(cs)))
    return out


def apply_learned(items):
    """Save what learn_from_correction found. Returns human-readable lines."""
    lines = []
    for kind, phrase, target in items:
        if kind == "book" and add_aliases({phrase: target}):
            lines.append(f"'{phrase}' = {target}")
        elif kind == "phrase" and add_replacement(phrase, target):
            lines.append(f"'{phrase}' = '{target}'")
        elif kind == "sound" and add_soundalike(phrase, target):
            lines.append(f"'{phrase}' = '{target}' inside references")
    return lines


def learned_items():
    """Everything learned so far, for the 'Learned words' window."""
    items = [(k, v) for k, v in sorted(load_custom_aliases().items())]
    items += [(k, f"'{v}'") for k, v in sorted(load_replacements().items())]
    items += [(k, f"'{v}' (inside references)") for k, v in sorted(LEARNED_SOUNDS.items())]
    return items


# --------------------------------------------------------------------------
# SETTINGS
# --------------------------------------------------------------------------
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return upgrade_settings(s)


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------------------
# SPEECH MODELS: visible download progress, stall detection, offline folder
# --------------------------------------------------------------------------
MODEL_MB = {"tiny.en": 75, "base.en": 145, "small.en": 485, "medium.en": 1500}
POLL_SECONDS = 1.0      # how often download progress is checked
STALL_SECONDS = 90      # no new data for this long = download considered stuck


class Cancelled(Exception):
    pass


def _model_complete(p):
    need = ("model.bin", "config.json", "tokenizer.json")
    has_vocab = any(os.path.isfile(os.path.join(p, v)) for v in ("vocabulary.json", "vocabulary.txt"))
    return has_vocab and all(os.path.isfile(os.path.join(p, f)) for f in need)


def model_path(name):
    """The installer's copy if it has this model, otherwise the user's download folder."""
    bundled = os.path.join(BUNDLED_MODELS_DIR, name)
    return bundled if _model_complete(bundled) else os.path.join(MODELS_DIR, name)


def model_ready(name):
    return _model_complete(model_path(name))


def _dir_size(path):
    total = 0
    for root_, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root_, f))
            except OSError:
                pass
    return total


def _download_files(name, dest):
    from faster_whisper.utils import download_model
    download_model(name, output_dir=dest)


_downloads = {}  # name -> (thread, errors) so two requests share one download


def ensure_model(name, status=None, cancel=None):
    """Return a folder with a complete local copy of the model, downloading it
    (with progress) if needed. Raises RuntimeError with advice if it stalls."""
    status = status or (lambda m: None)
    dest = model_path(name)
    if model_ready(name):
        return dest
    os.makedirs(dest, exist_ok=True)

    entry = _downloads.get(name)
    if not entry or not entry[0].is_alive():
        errors = []

        def run():
            try:
                _download_files(name, dest)
            except Exception as e:
                errors.append(e)

        th = threading.Thread(target=run, daemon=True)
        entry = (th, errors)
        _downloads[name] = entry
        th.start()
    th, errors = entry

    total = MODEL_MB.get(name, 0)
    start = time.time()
    last_size, last_change = -1, time.time()
    while th.is_alive():
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        th.join(POLL_SECONDS)
        size = _dir_size(dest)
        status(f"Downloading {name}: {size / 1e6:.0f} of ~{total} MB  ({int(time.time() - start)}s)")
        if size != last_size:
            last_size, last_change = size, time.time()
        elif time.time() - last_change > STALL_SECONDS:
            raise RuntimeError(
                f"Download of '{name}' stalled (no data for {STALL_SECONDS}s). Check the internet "
                f"connection and press Start again - it resumes where it stopped. Offline option: "
                f"copy the files of 'Systran/faster-whisper-{name}' from huggingface.co into {dest}")
    if errors:
        raise RuntimeError(f"Download of '{name}' failed: {errors[0]}")
    if not model_ready(name):
        raise RuntimeError(f"Download of '{name}' finished but files are incomplete. Press Start to retry.")
    return dest


def _timed(status, label, fn):
    """Run fn() while showing '<label> 12s' so a slow step never looks frozen."""
    done = threading.Event()

    def tick():
        t0 = time.time()
        while not done.wait(1):
            status(f"{label} {int(time.time() - t0)}s")

    threading.Thread(target=tick, daemon=True).start()
    try:
        return fn()
    finally:
        done.set()


_MODEL_CACHE = {}


def get_model(name, status=None, cancel=None):
    """Load a speech model: own folder first, then any older cache, then download."""
    status = status or (lambda m: None)
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    ok, msg = check_speech_engine()
    if not ok:
        raise RuntimeError(msg)
    from faster_whisper import WhisperModel

    model, src = None, None
    if model_ready(name):
        src = model_path(name)
    else:
        try:  # model already in the Hugging Face cache from an earlier run?
            model = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True)
        except Exception:
            src = ensure_model(name, status, cancel)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if model is None:
        model = _timed(status, f"Loading '{name}' into memory",
                       lambda: WhisperModel(src, device="cpu", compute_type="int8"))
    _MODEL_CACHE[name] = model
    return model


# Giving Whisper a hint with the book names noticeably improves recognition.
WHISPER_PROMPT = ("Bible references: " + ", ".join(BOOKS)
                  + ". First Peter, Second Peter, First Corinthians, Third John. John 3:16. Psalm 23. Verse 5.")


def read_wav(path):
    """Read a plain 16-bit PCM .wav ourselves (no extra decoder needed) as 16 kHz mono float32.
    Returns None if the file is not that kind of wav."""
    import numpy as np
    try:
        with wave.open(path, "rb") as w:
            if w.getsampwidth() != 2:
                return None
            ch, rate, frames = w.getnchannels(), w.getframerate(), w.readframes(w.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    audio = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
    if ch > 1:
        audio = audio[: len(audio) // ch * ch].reshape(-1, ch).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = int(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
    return audio


def load_audio(path):
    """File -> 16 kHz mono float32. Plain wavs (all training samples) are read directly;
    mp3/m4a/etc. need the 'av' decoder that comes with faster-whisper."""
    audio = read_wav(path)
    if audio is not None:
        return audio
    try:
        try:
            from faster_whisper.audio import decode_audio
        except ImportError:
            from faster_whisper import decode_audio
        return decode_audio(path, sampling_rate=SAMPLE_RATE)
    except TypeError as e:
        if "metadata_errors" in str(e):
            raise RuntimeError(
                "Your 'av' (PyAV) package is too old for this version of faster-whisper, so it can't "
                "open this file. Fix: run  pip install --upgrade av faster-whisper  and restart RootsVoice. "
                "(Plain .wav files don't need it.)")
        raise


def transcribe(model, audio, on_segment=None, cancel=None):
    """audio = numpy array (16 kHz mono float32) or a file path."""
    if isinstance(audio, str):
        audio = load_audio(audio)
    segments, info = model.transcribe(
        audio, language="en", vad_filter=True,
        initial_prompt=WHISPER_PROMPT, condition_on_previous_text=False)
    parts = []
    for s in segments:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if getattr(s, "no_speech_prob", 0) > 0.6 and getattr(s, "avg_logprob", 0) < -0.8:
            continue  # probably noise or music, not speech
        parts.append(s.text)
        if on_segment:
            on_segment(s.end, info.duration)
    text = " ".join(parts).strip()
    return "" if text.lower().startswith("bible references:") else text  # Whisper echoing the hint


def find_device(sd, name):
    if name:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["name"] == name:
                return i
    return None


ACTIVE_LEVEL = 0.01          # average loudness above which an input is "hearing sound"
_VIRTUAL_INPUTS = ("sound mapper", "primary sound capture")


# ---- Recording with Windows' own winmm.dll, used when the 'sounddevice' library isn't installed ----
_MM_ERRORS = {1: "an unspecified Windows audio error", 2: "that microphone isn't available (unplugged?)",
              4: "it is already in use by another program", 6: "no driver is installed for it",
              7: "Windows ran out of memory", 32: "it doesn't support this recording format"}


def mm_error_text(code):
    return _MM_ERRORS.get(int(code), f"Windows audio error {code}")


class AudioUnavailable(Exception):
    """No way to record: neither the sounddevice library nor Windows' own recording works."""


class WinMMSound:
    """The parts of the 'sounddevice' library RootsVoice uses (query_devices, InputStream), built on
    Windows' own winmm.dll - so recording works even when sounddevice isn't installed. `dll` lets
    the tests use a simulated driver."""
    WAVE_MAPPER = 0xFFFFFFFF
    DRVM_MAPPER_PREFERRED_GET = 0x2015

    def __init__(self, dll=None):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes
        self.mm = dll if dll is not None else ctypes.windll.winmm

        class WAVEINCAPSW(ctypes.Structure):
            _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                        ("szPname", wintypes.WCHAR * 32), ("dwFormats", wintypes.DWORD),
                        ("wChannels", wintypes.WORD), ("wReserved1", wintypes.WORD)]

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                        ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                        ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]

        class WAVEHDR(ctypes.Structure):
            _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                        ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                        ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD), ("lpNext", ctypes.c_void_p),
                        ("reserved", ctypes.c_size_t)]

        self.CAPS, self.FMT, self.HDR = WAVEINCAPSW, WAVEFORMATEX, WAVEHDR
        if dll is None:      # the real DLL: declare argument types (64-bit handles and pointers)
            P, m, U = ctypes.POINTER, self.mm, wintypes.UINT
            m.waveInGetNumDevs.restype = U
            m.waveInGetDevCapsW.argtypes = (ctypes.c_size_t, P(WAVEINCAPSW), U)
            m.waveInOpen.argtypes = (P(ctypes.c_void_p), U, P(WAVEFORMATEX), ctypes.c_size_t, ctypes.c_size_t,
                                     wintypes.DWORD)
            for fn in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
                getattr(m, fn).argtypes = (ctypes.c_void_p, P(WAVEHDR), U)
            for fn in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
                getattr(m, fn).argtypes = (ctypes.c_void_p,)
            m.waveInMessage.argtypes = (ctypes.c_void_p, U, ctypes.c_size_t, ctypes.c_size_t)
            for fn in ("waveInGetDevCapsW", "waveInOpen", "waveInPrepareHeader", "waveInUnprepareHeader",
                       "waveInAddBuffer", "waveInStart", "waveInStop", "waveInReset", "waveInClose", "waveInMessage"):
                getattr(m, fn).restype = U
        self.mm.waveInGetNumDevs()   # fails here if Windows audio isn't usable at all

    def _caps(self, dev_id):
        caps = self.CAPS()
        return caps if self.mm.waveInGetDevCapsW(dev_id, self.ct.pointer(caps), self.ct.sizeof(caps)) == 0 else None

    def preferred(self):
        """The id of Windows' default recording device, or None."""
        dev, flags = self.ct.c_uint32(0), self.ct.c_uint32(0)
        r = self.mm.waveInMessage(self.WAVE_MAPPER, self.DRVM_MAPPER_PREFERRED_GET,
                                  self.ct.addressof(dev), self.ct.addressof(flags))
        return int(dev.value) if r == 0 else None

    def query_devices(self, device=None, kind=None):
        devs = []
        for i in range(int(self.mm.waveInGetNumDevs())):
            caps = self._caps(i)          # list position = Windows device id, so keep a slot even on errors
            devs.append({"name": caps.szPname if caps else f"Input {i + 1}",
                         "max_input_channels": max(1, int(caps.wChannels)) if caps else 0,
                         "default_samplerate": 48000})
        if device is None and kind is None:
            return devs
        if device is None:
            pref = self.preferred()
            if pref is not None and 0 <= pref < len(devs):
                return devs[pref]
            return {"name": devs[0]["name"] if devs else "", "max_input_channels": 1, "default_samplerate": 48000}
        return devs[int(device)]

    def InputStream(self, samplerate, channels, dtype="float32", blocksize=None, device=None, callback=None):
        return WinMMStream(self, self.WAVE_MAPPER if device is None else int(device), int(samplerate), int(channels),
                           int(blocksize or samplerate // 10), callback)

    def _terminate(self):
        pass

    def _initialize(self):
        pass


class WinMMStream:
    """A recording from winmm.dll: a ring of buffers that Windows fills; a thread hands each full one on."""
    WHDR_DONE = 1

    def __init__(self, snd, dev_id, rate, channels, blocksize, callback, nbuf=6):
        ct = snd.ct
        self.snd, self.mm, self.cb, self.ch = snd, snd.mm, callback, channels
        fmt = snd.FMT(1, channels, rate, rate * 2 * channels, 2 * channels, 16, 0)     # 16-bit PCM
        self.h = ct.c_void_p()
        r = self.mm.waveInOpen(ct.pointer(self.h), dev_id, ct.pointer(fmt), 0, 0, 0)
        if r:
            raise OSError(f"Windows couldn't open the microphone: {mm_error_text(r)}")
        nbytes = blocksize * 2 * channels
        self.bufs, self.hdrs = [], []
        for _ in range(nbuf):
            buf = ct.create_string_buffer(nbytes)
            hdr = snd.HDR()
            hdr.lpData, hdr.dwBufferLength = ct.cast(buf, ct.c_void_p), nbytes
            self.mm.waveInPrepareHeader(self.h, ct.pointer(hdr), ct.sizeof(hdr))
            self.mm.waveInAddBuffer(self.h, ct.pointer(hdr), ct.sizeof(hdr))
            self.bufs.append(buf)
            self.hdrs.append(hdr)
        self.running, self.closed, self.thread, self.next = False, False, None, 0

    def start(self):
        r = self.mm.waveInStart(self.h)
        if r:
            self.close()
            raise OSError(f"Windows couldn't start recording: {mm_error_text(r)}")
        self.running = True
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self):
        import numpy as np
        ct = self.snd.ct
        while self.running:
            hdr = self.hdrs[self.next]
            if not hdr.dwFlags & self.WHDR_DONE:
                time.sleep(0.01)
                continue
            n = int(hdr.dwBytesRecorded)
            if n and self.cb:
                audio = np.frombuffer(ct.string_at(self.bufs[self.next], n), dtype="<i2").astype("float32") / 32768.0
                self.cb(audio.reshape(-1, self.ch), len(audio) // self.ch, None, None)
            hdr.dwFlags &= ~self.WHDR_DONE
            if self.running:
                self.mm.waveInAddBuffer(self.h, ct.pointer(hdr), ct.sizeof(hdr))
            self.next = (self.next + 1) % len(self.hdrs)

    def stop(self):
        self.running = False
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(1)
        if not self.closed:
            self.mm.waveInReset(self.h)

    def close(self):
        if self.closed:
            return
        self.running = False
        self.mm.waveInReset(self.h)
        for hdr in self.hdrs:
            self.mm.waveInUnprepareHeader(self.h, self.snd.ct.pointer(hdr), self.snd.ct.sizeof(hdr))
        self.mm.waveInClose(self.h)
        self.closed = True


_winmm_cache = []


def winmm_sound():
    """Windows' own recording, or None when not on Windows."""
    if not _winmm_cache:
        try:
            _winmm_cache.append(WinMMSound())
        except Exception:
            _winmm_cache.append(None)
    return _winmm_cache[0]


def audio_module():
    """The 'sounddevice' library if it is installed and works, otherwise Windows' own recording.
    Raises AudioUnavailable with a message that says how to fix it."""
    try:
        import sounddevice as sd
        return sd
    except (ImportError, OSError) as e:
        nat = winmm_sound()
        if nat is not None:
            return nat
        if isinstance(e, ImportError):
            raise AudioUnavailable(missing_package("sounddevice"))
        raise AudioUnavailable(f"The microphone system could not start: {e}")


def default_input_name(sd):
    """The name of Windows' default microphone, or ''."""
    try:
        return str(dict(sd.query_devices(kind="input")).get("name") or "")
    except Exception:
        return ""


# ---- Microphone health: driver problems, no microphone, Windows privacy blocking ----
WIN_LINKS = {
    "updates": ("Look for driver updates", "ms-settings:windowsupdate-optionalupdates"),
    "devices": ("Open Device Manager", "devmgmt.msc"),
    "privacy": ("Open microphone privacy settings", "ms-settings:privacy-microphone"),
    "sound": ("Open Sound settings", "ms-settings:sound"),
}
DRIVER_PROBLEMS = {
    1: "isn't set up correctly", 3: "has a damaged driver", 10: "can't start", 12: "has a resource conflict",
    14: "needs the computer to restart", 18: "needs its driver reinstalled", 19: "has a settings problem",
    21: "is being removed", 22: "is turned off (disabled)", 28: "has no driver installed",
    31: "isn't working properly", 32: "has its driver turned off", 37: "has a driver that failed to load",
    39: "has a missing or damaged driver", 43: "was stopped because it reported a problem",
    48: "has a blocked driver", 52: "has a driver Windows can't verify",
}


def microphone_access_blocked():
    """True when Windows privacy settings stop desktop programs from using the microphone."""
    try:
        import winreg
    except ImportError:
        return False
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, base), (winreg.HKEY_CURRENT_USER, base),
                      (winreg.HKEY_CURRENT_USER, base + r"\NonPackaged")):
        try:
            with winreg.OpenKey(hive, key) as k:
                if str(winreg.QueryValueEx(k, "Value")[0]).lower() == "deny":
                    return True
        except OSError:
            continue
    return False


def parse_driver_problems(text):
    """[(device name, problem, code)] from PowerShell's JSON list of devices with a problem code."""
    try:
        data = json.loads(text) if text and text.strip() else []
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            code = int(d.get("ConfigManagerErrorCode") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if code in (0, 24, 45):        # fine, or simply not plugged in right now
            continue
        out.append((d.get("Name") or "A sound device", DRIVER_PROBLEMS.get(code, f"has a problem (code {code})"), code))
    return out


def audio_driver_problems(timeout=12):
    """Sound devices Windows reports a driver problem with (asks Windows via PowerShell)."""
    if os.name != "nt":
        return []
    import subprocess
    ps = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 -and "
          "$_.PNPClass -in @('MEDIA','AudioEndpoint','AudioProcessingObject') } | "
          "Select-Object Name, ConfigManagerErrorCode | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                capture_output=True, text=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return []
    return parse_driver_problems(result.stdout)


def microphone_health(mic_count=None, problems=None, blocked=None):
    """Things stopping the microphone that the person can fix, each with buttons:
    [{'title', 'detail', 'actions': [(label, windows link)]}]."""
    issues = []
    if blocked is None:
        blocked = microphone_access_blocked()
    if blocked:
        issues.append({"title": "Windows is blocking the microphone",
                       "detail": "Turn on 'Microphone access' and 'Let desktop apps access your microphone' "
                                 "in Windows privacy settings.",
                       "actions": [WIN_LINKS["privacy"]]})
    for name, problem, code in (audio_driver_problems() if problems is None else problems):
        if code == 22:
            issues.append({"title": f"'{name}' {problem}", "detail": "Turn it back on in Device Manager "
                           "(right-click it \u203a Enable device).", "actions": [WIN_LINKS["devices"]]})
        else:
            issues.append({"title": f"'{name}' {problem}",
                           "detail": "Install or update its driver: look in Windows Update \u203a Optional updates "
                                     "\u203a Driver updates, or download it from the maker's website.",
                           "actions": [WIN_LINKS["updates"], WIN_LINKS["devices"]]})
    if mic_count is None:
        try:
            mic_count = len(list_microphones(audio_module()))
        except Exception:
            mic_count = None
    if mic_count == 0:
        issues.append({"title": "No microphone found",
                       "detail": "Plug one in. If it is plugged in, Windows may be missing its driver - look for "
                                 "driver updates, or download the driver from the maker's website.",
                       "actions": [WIN_LINKS["sound"], WIN_LINKS["updates"], WIN_LINKS["devices"]]})
    return issues


def open_windows_link(target):
    """Open a Windows settings page or tool, e.g. 'ms-settings:sound'. Returns True if it opened."""
    try:
        os.startfile(target)
        return True
    except Exception:
        return False


def list_microphones(sd, include_virtual=False):
    """Input devices as (index, name, info), one per name. Windows lists the same microphone once per
    sound system; the first listing is the most compatible, so later duplicates are skipped."""
    out, seen = [], set()
    for i, d in enumerate(sd.query_devices()):
        name = d["name"]
        if d.get("max_input_channels", 0) <= 0 or name in seen:
            continue
        if not include_virtual and any(v in name.lower() for v in _VIRTUAL_INPUTS):
            continue
        seen.add(name)
        out.append((i, name, d))
    return out


def _to_16k_mono(rate, deliver):
    """Microphone callback that turns any rate / channel count into the 16 kHz mono the speech model needs."""
    import numpy as np

    def callback(indata, frames, t, status):
        x = np.asarray(indata, dtype="float32")
        x = x.mean(axis=1) if x.ndim > 1 and x.shape[1] > 1 else x.reshape(-1)
        if rate != SAMPLE_RATE and len(x):
            n = max(1, int(round(len(x) * SAMPLE_RATE / rate)))
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype("float32")
        deliver(x.copy())

    return callback


def open_microphone(sd, device, deliver, block_seconds=0.1):
    """Open a microphone in a format it accepts and pass 16 kHz mono audio to deliver(array).
    Many microphones and USB interfaces refuse 16 kHz or a single channel, so several formats
    are tried and the sound is converted. Returns (stream, info); raises if nothing works."""
    try:
        dev = dict(sd.query_devices(device) if device is not None else sd.query_devices(kind="input"))
    except Exception:
        dev = {}
    native = int(dev.get("default_samplerate") or 48000)
    maxch = max(1, int(dev.get("max_input_channels") or 1))
    tries = []
    for rate, ch in ((SAMPLE_RATE, 1), (native, 1), (native, min(2, maxch)), (48000, 1), (44100, 1),
                     (48000, min(2, maxch)), (44100, min(2, maxch))):
        if (rate, ch) not in tries:
            tries.append((rate, ch))
    last = None
    for rate, ch in tries:
        stream = None
        try:
            stream = sd.InputStream(samplerate=rate, channels=ch, dtype="float32",
                                    blocksize=int(rate * block_seconds), device=device,
                                    callback=_to_16k_mono(rate, deliver))
            stream.start()
            return stream, {"rate": rate, "channels": ch, "name": dev.get("name", "")}
        except Exception as e:
            last = e
            try:
                stream.close()
            except Exception:
                pass
    raise last or RuntimeError("the microphone did not accept any audio format")


def measure_microphone(sd, device, seconds=0.8):
    """Listen for a moment. Returns (average loudness, info); raises if it can't be opened."""
    import numpy as np
    chunks = []
    stream, info = open_microphone(sd, device, chunks.append)
    time.sleep(seconds)
    try:
        stream.stop()
        stream.close()
    except Exception:
        pass
    audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype="float32")
    info["samples"] = len(audio)
    return (float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0.0), info


def scan_microphones(seconds=0.8, progress=None, cancel=None):
    """Listen to every input in turn. Returns [{'name', 'ok', 'level', 'rate', 'note', 'loopback'}]."""
    sd = audio_module()
    mics = list_microphones(sd)
    results = []
    for n, (idx, name, d) in enumerate(mics, 1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(n, len(mics), name)
        loopback = any(w in name.lower() for w in ("stereo mix", "what u hear", "loopback", "wave out"))
        entry = {"name": name, "ok": False, "level": 0.0, "rate": None, "note": "", "loopback": loopback}
        try:
            level, info = measure_microphone(sd, idx, seconds)
            entry["rate"] = info["rate"]
            if not info["samples"]:
                entry["note"] = "Opened, but no sound arrived"
            else:
                entry["ok"], entry["level"] = True, level
                entry["note"] = "Hearing sound" if level > ACTIVE_LEVEL else "Works, but quiet right now"
            if info["rate"] != SAMPLE_RATE:
                entry["note"] += f" \u00b7 {info['rate'] // 1000} kHz, converted"
        except Exception as e:
            entry["note"] = "Can't be used: " + (str(e).splitlines() or ["unknown error"])[0][:70]
        if loopback:
            entry["note"] += " \u00b7 the computer's own sound, not a microphone"
        results.append(entry)
    return results


def best_microphone(results):
    """The input hearing the most sound (never 'Stereo Mix'-style loopback), or None if all are quiet."""
    ok = [r for r in results if r["ok"] and not r["loopback"]]
    if not ok:
        return None
    best = max(ok, key=lambda r: r["level"])
    return best if best["level"] > ACTIVE_LEVEL else None


# --------------------------------------------------------------------------
# PROJECTION SOFTWARE - VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP, FreeShow, others
# --------------------------------------------------------------------------
# kind "keys": RootsVoice brings the program to the front, opens its reference box (with a shortcut,
#              or by clicking a spot you showed it once), clears it and types the reference.
# kind "freeshow": FreeShow's own API - nothing is typed.
TARGETS = {
    "videopsalm": {"name": "VideoPsalm", "kind": "keys",
                   "note": "VideoPsalm's search opens with Ctrl+F - nothing else to set up.",
                   "defaults": {"window_title": "VideoPsalm", "focus": "hotkey", "search_hotkey": "ctrl+f",
                                "after_keys": "enter"}},
    "bibleshow": {"name": "BibleShow", "kind": "keys",
                  "note": "BibleShow's reference box opens with F5 - RootsVoice presses F5, types the reference "
                          "(e.g. John 3:16) and presses Enter. Nothing else to set up.",
                  "defaults": {"window_title": "BibleShow", "focus": "hotkey", "search_hotkey": "f5",
                               "after_keys": "enter"}},
    "easyworship": {"name": "EasyWorship", "kind": "keys",
                    "note": "Open the Scriptures tab, then press 'Point to it' and hold the mouse over its "
                            "reference box.",
                    "defaults": {"window_title": "EasyWorship", "focus": "click", "after_keys": "enter"}},
    "propresenter": {"name": "ProPresenter", "kind": "keys",
                     "note": "Open the Bible panel, then press 'Point to it' and hold the mouse over its "
                             "reference box. ProPresenter's clear keys (F1-F6) can be used as the Clear key.",
                     "defaults": {"window_title": "ProPresenter", "focus": "click", "after_keys": "enter"}},
    "openlp": {"name": "OpenLP", "kind": "keys",
               "note": "Open the Bibles tab (Quick search), then press 'Point to it' and hold the mouse over "
                       "the search box.",
               "defaults": {"window_title": "OpenLP", "focus": "click", "after_keys": "enter"}},
    "freeshow": {"name": "FreeShow", "kind": "freeshow",
                 "note": "Uses FreeShow's own API - turn it on in FreeShow › Settings › Connections. "
                         "Nothing is typed, so FreeShow can stay in the background.",
                 "defaults": {"window_title": "FreeShow", "api_port": 5506, "api_key": ""}},
    "custom": {"name": "Other program", "kind": "keys",
               "note": "Works with any program that has a box for typing a Bible reference. Type part of its "
                       "window title, then press 'Point to it' (or set its search shortcut).",
               "defaults": {"window_title": "", "focus": "click", "after_keys": "enter"}},
}
TARGET_FIELDS = ("window_title", "focus", "search_hotkey", "after_keys", "next_key", "prev_key", "clear_key",
                 "click_x", "click_y", "api_port", "api_key")
_TARGET_BLANK = {"window_title": "", "focus": "click", "search_hotkey": "", "after_keys": "enter", "next_key": "",
                 "prev_key": "", "clear_key": "", "click_x": None, "click_y": None, "api_port": 5506, "api_key": ""}


def target_id(settings):
    tid = settings.get("target") or "videopsalm"
    return tid if tid in TARGETS else "custom"


def target_profile(settings):
    return TARGETS[target_id(settings)]


def target_values(tid, saved=None):
    """Settings for one program: its defaults, overlaid with what you changed for it."""
    defaults = TARGETS.get(tid, TARGETS["custom"])["defaults"]
    vals = dict(_TARGET_BLANK)
    vals.update(defaults)
    saved = {k: v for k, v in (saved or {}).items() if k in TARGET_FIELDS}
    if _never_pointed(defaults, saved):
        saved.pop("focus", None)
        saved.pop("search_hotkey", None)
    vals.update(saved)
    return vals


def _never_pointed(defaults, saved):
    """True for settings saved while a program still needed pointing, when it now has a known shortcut
    and the box was never pointed to (BibleShow before 2.2.1)."""
    return (defaults.get("focus") == "hotkey" and saved.get("focus") == "click"
            and saved.get("click_x") is None)


def upgrade_settings(s):
    """Bring settings saved by an older RootsVoice up to date."""
    tid = target_id(s)
    defaults = TARGETS[tid]["defaults"]
    if _never_pointed(defaults, s):
        s["focus"], s["search_hotkey"] = defaults["focus"], defaults["search_hotkey"]
    return s


def target_name(settings):
    if target_id(settings) == "custom":
        return (settings.get("window_title") or "").strip() or "your projection software"
    return target_profile(settings)["name"]


# ---- Typing, clicking and window control with Windows' own functions (no extra packages) ----
# pyautogui / pygetwindow are only used where Windows' functions aren't available.
_EXTENDED_KEYS = {"up", "down", "left", "right", "home", "end", "pageup", "pagedown", "insert", "delete", "win"}
_VK_NAMES = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
}
_KEY_ALIASES = {"pgup": "pageup", "pgdn": "pagedown", "del": "delete", "return": "enter", "escape": "esc",
                "control": "ctrl"}


def key_code(name):
    """Windows key code for a key name: 'f5', 'enter', 'ctrl', 'a', '7', 'pagedown' ... Raises ValueError."""
    k = name.strip().lower()
    if k in _VK_NAMES:
        return _VK_NAMES[k]
    if len(k) == 1 and ("a" <= k <= "z" or "0" <= k <= "9"):
        return ord(k.upper())
    if k.startswith("f") and k[1:].isdigit() and 1 <= int(k[1:]) <= 24:
        return 0x6F + int(k[1:])
    raise ValueError(f"Unknown key '{name}'")


class NativeWindows:
    """Windows' own SendInput / window functions. Types text as real characters, so it works
    with any keyboard layout (pyautogui's typing breaks ':' on some layouts)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.user32, self.kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self.INPUT, self.U, self.KEYBDINPUT, self.MOUSEINPUT = INPUT, _U, KEYBDINPUT, MOUSEINPUT
        u = self.user32
        u.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        u.SendInput.restype = wintypes.UINT
        for fn in ("IsIconic", "IsWindowVisible", "SetForegroundWindow", "BringWindowToTop"):
            getattr(u, fn).argtypes = (wintypes.HWND,)
        u.GetForegroundWindow.restype = wintypes.HWND
        u.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        u.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        u.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        u.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)

    # ---- keyboard and mouse
    def _send(self, *inputs):
        arr = (self.INPUT * len(inputs))(*inputs)
        if self.user32.SendInput(len(inputs), arr, self.ct.sizeof(self.INPUT)) != len(inputs):
            raise OSError("Windows blocked the key presses (is the program running as administrator?)")

    def _key(self, vk=0, scan=0, flags=0):
        return self.INPUT(type=1, u=self.U(ki=self.KEYBDINPUT(vk, scan, flags, 0, 0)))

    def hotkey(self, *names):
        """Press keys together, e.g. hotkey('ctrl', 'a') or hotkey('f5')."""
        codes = [(key_code(n), 1 if _KEY_ALIASES.get(n.lower(), n.lower()) in _EXTENDED_KEYS else 0)
                 for n in names]
        downs = [self._key(vk, 0, ext) for vk, ext in codes]
        ups = [self._key(vk, 0, ext | 2) for vk, ext in reversed(codes)]
        self._send(*(downs + ups))

    def press(self, name):
        self.hotkey(name)

    def typewrite(self, text, interval=0.0):
        """Type text as characters (KEYEVENTF_UNICODE) - independent of the keyboard layout."""
        for ch in text:
            code = ord(ch)
            self._send(self._key(0, code, 4), self._key(0, code, 4 | 2))
            if interval:
                time.sleep(interval)

    def click(self, x, y):
        self.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        mi = lambda flags: self.INPUT(type=0, u=self.U(mi=self.MOUSEINPUT(0, 0, 0, flags, 0, 0)))
        self._send(mi(0x0002), mi(0x0004))            # left button down, up

    def position(self):
        pt = self.wt.POINT()
        self.user32.GetCursorPos(self.ct.byref(pt))
        return pt.x, pt.y

    # ---- windows
    def windows(self):
        """Visible top-level windows that have a title."""
        found = []
        u = self.user32

        @self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)
        def each(hwnd, _):
            if u.IsWindowVisible(hwnd):
                n = u.GetWindowTextLengthW(hwnd)
                if n:
                    buf = self.ct.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(hwnd, buf, n + 1)
                    if buf.value.strip():
                        found.append(NativeWindow(self, hwnd, buf.value))
            return True

        u.EnumWindows(each, 0)
        return found


class NativeWindow:
    """One window, with the same handful of properties RootsVoice used from pygetwindow."""

    def __init__(self, nat, hwnd, title):
        self.nat, self.hwnd, self.title = nat, hwnd, title

    def _rect(self):
        r = self.nat.wt.RECT()
        self.nat.user32.GetWindowRect(self.hwnd, self.nat.ct.byref(r))
        return r

    left = property(lambda self: self._rect().left)
    top = property(lambda self: self._rect().top)
    width = property(lambda self: self._rect().right - self._rect().left)
    height = property(lambda self: self._rect().bottom - self._rect().top)
    isMinimized = property(lambda self: bool(self.nat.user32.IsIconic(self.hwnd)))

    def restore(self):
        self.nat.user32.ShowWindow(self.hwnd, 9)        # SW_RESTORE

    def activate(self):
        """Bring to the front. Windows only lets the program the user last used do this, so a quick
        Alt tap (and, if needed, sharing the input queue) is used - the usual, harmless workaround."""
        u = self.nat.user32
        if u.GetForegroundWindow() == self.hwnd:
            return
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(self.hwnd)
        if u.GetForegroundWindow() != self.hwnd:
            fg_thread = u.GetWindowThreadProcessId(u.GetForegroundWindow(), None)
            me = self.nat.kernel32.GetCurrentThreadId()
            u.AttachThreadInput(me, fg_thread, True)
            u.BringWindowToTop(self.hwnd)
            u.SetForegroundWindow(self.hwnd)
            u.AttachThreadInput(me, fg_thread, False)
        if u.GetForegroundWindow() != self.hwnd:
            raise OSError("Windows would not switch to it - click it once, then try again")


_native_cache = []


def native_windows():
    """NativeWindows on Windows, otherwise None."""
    if not _native_cache:
        try:
            _native_cache.append(NativeWindows())
        except Exception:
            _native_cache.append(None)
    return _native_cache[0]


def missing_package(name):
    """A message that says how to fix a missing library."""
    if FROZEN:
        return f"Part of RootsVoice is missing ({name}). Please reinstall RootsVoice with the latest installer."
    return (f"Missing package: {name}. RootsVoice can install it for you (Help \u203a Install missing components), "
            f'or run:  "{sys.executable}" -m pip install {name}')


# --------------------------------------------------------------------------
# COMPONENTS - the libraries RootsVoice needs, and installing them from inside the app
# --------------------------------------------------------------------------
WINDOWS = os.name == "nt"
COMPONENTS = [   # import name, pip name, what it does, required (the rest have a built-in Windows fallback)
    ("faster_whisper", "faster-whisper", "the speech engine that turns speech into text", True),
    ("numpy", "numpy", "sound processing", True),
    ("sounddevice", "sounddevice", "microphone access (Windows has a built-in fallback)", not WINDOWS),
    ("pyautogui", "pyautogui", "typing into the projection software (Windows has a built-in fallback)", not WINDOWS),
    ("pygetwindow", "pygetwindow", "finding the projection software (Windows has a built-in fallback)", not WINDOWS),
]
VC_RUNTIME_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VC_RUNTIME_MSG = ("The speech engine needs Microsoft's Visual C++ runtime, which is missing on this computer. "
                  f"Download and install it from {VC_RUNTIME_URL} , then restart RootsVoice.")


def has_module(name):
    """Is this library installed? (Quick check - it isn't loaded.)"""
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        import importlib.util
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_dependencies(include_optional=True):
    """[(pip name, what it does, required)] for components that aren't installed."""
    return [(pip, why, req) for mod, pip, why, req in COMPONENTS
            if (req or include_optional) and not has_module(mod)]


def needs_install():
    return any(req for _, _, req in missing_dependencies())


def python_version_note():
    """A warning when this Python is outside the versions the speech engine is built for, else ''."""
    v = sys.version_info[:2]
    if (3, 9) <= v <= (3, 13):
        return ""
    return (f"This computer runs Python {v[0]}.{v[1]}. The speech engine is built for Python 3.9 - 3.13; if "
            "installing fails, double-click setup_rootsvoice.bat in the RootsVoice folder - it installs Python 3.11 "
            "and everything else for you.")


def check_speech_engine():
    """Really load the speech engine. Returns (True, 'ready') or (False, what to do)."""
    try:
        import faster_whisper  # noqa: F401
        return True, "ready"
    except ImportError as e:
        if "dll load failed" in str(e).lower():
            return False, VC_RUNTIME_MSG
        name = (getattr(e, "name", None) or "faster_whisper").split(".")[0]
        return False, missing_package("faster-whisper" if name == "faster_whisper" else name.replace("_", "-"))
    except OSError as e:          # a DLL inside the engine couldn't be loaded
        return False, VC_RUNTIME_MSG if "dll" in str(e).lower() or WINDOWS else f"The speech engine couldn't load: {e}"


def _stream_command(cmd, log):
    """Run a command, passing each line of its output to log(). Returns (exit code, all output)."""
    import subprocess
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return 1, str(e)
    lines = []
    for line in p.stdout:
        lines.append(line)
        log(line.rstrip())
    return p.wait(), "".join(lines)


def explain_pip_failure(out):
    """Turn pip's output into one plain sentence about what to do."""
    low = out.lower()
    if any(k in low for k in ("failed to establish a new connection", "could not fetch url", "name resolution",
                              "getaddrinfo failed", "network is unreachable", "connection timed out",
                              "read timed out", "connection aborted", "proxyerror")):
        return "No internet connection - connect to the internet and try again (it's only needed once)."
    if "no matching distribution" in low or "could not find a version that satisfies" in low:
        v = sys.version_info
        return (f"The speech engine isn't available for Python {v[0]}.{v[1]}. Double-click setup_rootsvoice.bat "
                "in the RootsVoice folder - it installs Python 3.11 and everything else for you.")
    if "microsoft visual c++" in low or "subprocess-exited-with-error" in low or "failed building wheel" in low:
        return ("A component couldn't be built on this computer. Double-click setup_rootsvoice.bat - it uses "
                "Python 3.11, which has ready-made versions of everything.")
    if "no space left" in low or "not enough space" in low:
        return "The disk is full - free up about 1 GB and try again."
    if "permission" in low or "access is denied" in low:
        return "Windows refused the install. Run setup_rootsvoice.bat, or start RootsVoice as administrator once."
    last = [line.strip() for line in out.splitlines() if line.strip()][-1:]
    return "Installing failed: " + (last[0][:200] if last else "unknown error")


def install_packages(packages, log=print, run=None):
    """Install libraries with pip into the Python that is running RootsVoice. Returns (ok, message)."""
    if FROZEN:
        return False, "This is the installed RootsVoice - please reinstall it with the latest Setup file."
    if not packages:
        return True, "Everything is already installed."
    run = run or _stream_command
    py = sys.executable
    if py.lower().endswith("pythonw.exe") and os.path.exists(py[:-5] + ".exe"):
        py = py[:-5] + ".exe"                       # the console version shows pip's messages
    code, out = run([py, "-m", "pip", "--version"], log)
    if code != 0:
        log("Setting up pip (the package installer)...")
        code, out = run([py, "-m", "ensurepip", "--upgrade"], log)
        if code != 0:
            return False, ("This Python has no package installer (pip). Double-click setup_rootsvoice.bat - "
                           "it installs Python 3.11 with everything RootsVoice needs.")
    cmd = [py, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *packages]
    code, out = run(cmd, log)
    if code != 0 and ("permission" in out.lower() or "access is denied" in out.lower()):
        log("Trying again for this Windows user only...")
        code, out = run(cmd + ["--user"], log)
    if code == 0:
        return True, "Installed " + ", ".join(packages) + ". Restart RootsVoice to start using them."
    return False, explain_pip_failure(out)


def make_desktop_shortcut():
    """Put a 'RootsVoice' shortcut (with the Roots icon) on the desktop. Returns (ok, message)."""
    if not WINDOWS:
        return False, "Desktop shortcuts are made on Windows only."
    import subprocess
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    target = sys.executable if FROZEN else (pyw if os.path.exists(pyw) else sys.executable)
    env = dict(os.environ, RV_TARGET=target, RV_ARGS="" if FROZEN else f'"{os.path.abspath(__file__)}"',
               RV_DIR=APP_DIR, RV_ICON=os.path.join(APP_DIR, "assets", "roots.ico"))
    # paths travel in environment variables, so spaces or quotes in folder names can't break the command
    ps = ("$d=[Environment]::GetFolderPath('Desktop');"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'RootsVoice.lnk'));"
          "$s.TargetPath=$env:RV_TARGET;$s.Arguments=$env:RV_ARGS;$s.WorkingDirectory=$env:RV_DIR;"
          "if(Test-Path $env:RV_ICON){$s.IconLocation=$env:RV_ICON};"
          "$s.Description='RootsVoice - voice-controlled scripture';$s.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return False, f"Couldn't make the shortcut: {e}"
    return (r.returncode == 0,
            "Desktop shortcut made." if r.returncode == 0 else f"Couldn't make the shortcut: {r.stderr.strip()[:150]}")


def component_lines():
    """[(ok, message)] for Check setup and --check-deps."""
    out = []
    for mod, pip, why, req in COMPONENTS:
        if mod == "faster_whisper":
            ok, msg = check_speech_engine()
            out.append((ok, f"Speech engine (faster-whisper): {'installed' if ok else msg}"))
        elif has_module(mod):
            out.append((True, f"{pip}: installed"))
        elif req:
            out.append((False, f"{pip} ({why}): missing - Help \u203a Install missing components"))
        else:
            out.append((True, f"{pip}: not installed - using Windows' built-in version"))
    return out


def input_backend():
    """(keyboard-and-mouse object, None) or (None, error message)."""
    nat = native_windows()
    if nat is not None:
        return nat, None
    try:
        import pyautogui
        return pyautogui, None
    except ImportError:
        return None, missing_package("pyautogui")


def window_titles_and_finder():
    """(list of windows, None) or (None, error message). Each window has .title, .left, .top ..."""
    nat = native_windows()
    if nat is not None:
        return nat.windows(), None
    try:
        import pygetwindow as gw
    except ImportError:
        return None, missing_package("pygetwindow")
    return gw, None


_send_lock = threading.Lock()  # sends never overlap, so keystrokes can't interleave


def _keys(spec):
    """'ctrl+f' -> ['ctrl', 'f']"""
    return [k.strip().lower() for k in spec.split("+") if k.strip()]


def find_target_window(settings):
    """The projection program's window. Returns (window, None) or (None, error message)."""
    title = (settings.get("window_title") or "").strip()
    if not title:
        return None, "Type part of the program's window title in Settings › Projection software."
    source, err = window_titles_and_finder()
    if err:
        return None, err
    if isinstance(source, list):          # Windows' own window list
        wins = [w for w in source if title.lower() in w.title.lower()]
    else:                                 # pygetwindow
        wins = source.getWindowsWithTitle(title)
    wins = [w for w in wins if w.title.strip() and "RootsVoice" not in w.title]
    if not wins:
        return None, f"{target_name(settings)} window not found (looking for '{title}'). Is it open?"
    return wins[0], None


def _focus_target(settings):
    """Bring the projection program to the front. Returns (keyboard, window, None) or (None, None, error)."""
    inp, err = input_backend()
    if err:
        return None, None, err
    win, err = find_target_window(settings)
    if err:
        return None, None, err
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
    except Exception as e:
        return None, None, f"Could not bring {target_name(settings)} to the front: {e}"
    time.sleep(0.3)
    return inp, win, None


def send_reference(ref, settings):
    """Show `ref` in the chosen projection software. Each new reference replaces the last.
    Returns (ok, message)."""
    if target_profile(settings)["kind"] == "freeshow":
        return freeshow_call(settings, "start_scripture", {"reference": ref}, f"Sent {ref}")
    if settings.get("focus") == "click" and (settings.get("click_x") is None or settings.get("click_y") is None):
        return False, (f"Show RootsVoice where {target_name(settings)}'s reference box is: "
                       "Settings › Projection software › Point to it.")
    with _send_lock:
        keys, win, err = _focus_target(settings)
        if err:
            return False, err
        try:
            if settings.get("focus") == "click":
                keys.click(win.left + int(settings["click_x"]), win.top + int(settings["click_y"]))
                time.sleep(0.15)
            else:
                keys.hotkey(*_keys(settings.get("search_hotkey") or "ctrl+f"))
                time.sleep(0.25)
            keys.hotkey("ctrl", "a")      # select whatever was there before...
            time.sleep(0.08)
            keys.press("backspace")       # ...and delete it, so the new reference overwrites it
            time.sleep(0.08)
            keys.typewrite(ref, interval=0.015)
            time.sleep(0.15)
            for key in [k.strip() for k in (settings.get("after_keys") or "").split(",") if k.strip()]:
                keys.hotkey(*_keys(key))
                time.sleep(0.15)
        except Exception as e:
            return False, f"Couldn't type into {target_name(settings)}: {e}"
    return True, f"Sent {ref}"


def press_in_target(keys, settings, label, api_action=None):
    """Press a key or combo in the projection program, e.g. 'down' or 'f2'.
    FreeShow is told through its API instead (`api_action`). Returns (ok, message)."""
    if target_profile(settings)["kind"] == "freeshow":
        if api_action:
            return freeshow_call(settings, api_action, None, label)
        return False, "FreeShow is controlled through its API - no keys are needed."
    with _send_lock:
        inp, win, err = _focus_target(settings)
        if err:
            return False, err
        try:
            for key in [k.strip() for k in keys.split(",") if k.strip()]:
                inp.hotkey(*_keys(key))
                time.sleep(0.1)
        except Exception as e:
            return False, f"Couldn't press '{keys}' in {target_name(settings)}: {e}"
    return True, label


send_to_videopsalm, press_in_videopsalm = send_reference, press_in_target   # names used by RootsVoice 2.1


def freeshow_call(settings, action, data=None, label="Done"):
    """Send one action to FreeShow's API (REST), e.g. start_scripture {"reference": "John 3:16"}."""
    import urllib.error
    import urllib.parse
    import urllib.request
    try:
        port = int(settings.get("api_port") or 5506)
    except (TypeError, ValueError):
        port = 5506
    key = (settings.get("api_key") or "").strip()
    payload = {"action": action}
    payload.update(data or {})
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = f"http://127.0.0.1:{port}"
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=3).close()
        return True, label
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "FreeShow refused the request - check the API key in Settings › Projection software."
        if e.code in (404, 405):      # other FreeShow versions take the action in the address instead
            query = {"action": action, "data": json.dumps(data or {})}
            if key:
                query["auth"] = key
            try:
                urllib.request.urlopen(f"{url}/?{urllib.parse.urlencode(query)}", timeout=3).close()
                return True, label
            except Exception as e2:
                return False, f"FreeShow did not accept the request ({e2})."
        return False, f"FreeShow replied with error {e.code}."
    except OSError:
        return False, (f"Can't reach FreeShow on port {port}. Open FreeShow and turn on its API "
                       "(Settings › Connections).")


def detect_open_programs():
    """Supported programs that are open right now, e.g. ['bibleshow']."""
    source, err = window_titles_and_finder()
    if err:
        return []
    try:
        raw = [w.title for w in source] if isinstance(source, list) else source.getAllTitles()
        titles = [t.lower() for t in raw if t.strip() and "rootsvoice" not in t.lower()]
    except Exception:
        return []
    found = []
    for tid, t in TARGETS.items():
        word = (t["defaults"].get("window_title") or "").lower()
        if word and any(word in title for title in titles):
            found.append(tid)
    return found


def pointer_offset(settings):
    """Where the mouse is, measured from the projection program's top-left corner.
    Returns ((x, y), None) or (None, error message)."""
    inp, err = input_backend()
    if err:
        return None, err
    win, err = find_target_window(settings)
    if err:
        return None, err
    pos = inp.position()
    x, y = int(pos[0]) - int(win.left), int(pos[1]) - int(win.top)
    if not (0 <= x < int(win.width) and 0 <= y < int(win.height)):
        return None, f"The mouse wasn't over {target_name(settings)}'s window - try again."
    return (x, y), None


# --------------------------------------------------------------------------
# SETUP CHECK - one click to confirm the computer is ready for a service
# --------------------------------------------------------------------------
def setup_check(settings):
    """[(ok, message)] for components, the microphone, speech model, projection software and typing."""
    out = [line for line in component_lines() if not line[0] or "Speech engine" in line[1]]
    try:
        sd = audio_module()
        mics = list_microphones(sd)
        wanted = settings.get("mic") or ""
        label = wanted or "default microphone"
        if not mics:
            out.append((False, "Microphone: none found - plug one in"))
        elif settings.get("_listening"):
            out.append((True, f"Microphone '{label}': in use - RootsVoice is listening"))
        else:
            device = find_device(sd, wanted)
            if wanted and device is None:
                out.append((False, f"Microphone '{wanted}' isn't connected - the default is used instead"))
                label = "default microphone"
            try:
                level, info = measure_microphone(sd, device, 1.0)
                if level > ACTIVE_LEVEL:
                    out.append((True, f"Microphone '{label}': hearing sound"))
                else:
                    out.append((False, f"Microphone '{label}': works, but heard nothing - speak while checking, "
                                       "or use Settings \u203a Listening \u203a Find active microphone"))
            except Exception as e:
                out.append((False, f"Microphone '{label}' can't be opened ({str(e).splitlines()[0][:60]})"))
    except AudioUnavailable as e:
        out.append((False, f"Microphone: {e}"))
    except Exception as e:
        out.append((False, f"Microphone system could not start ({e})"))
    name = settings["model"]
    ready = model_ready(name)
    out.append((ready, f"Speech model '{name}': ready" if ready else
                f"Speech model '{name}': downloads the first time you press Start (needs internet once)"))
    name = target_name(settings)
    if target_profile(settings)["kind"] == "freeshow":
        ok, msg = freeshow_call(settings, "get_shows", None, "reachable")
        reachable = ok or "refused" in msg or "error" in msg or "accept" in msg
        out.append((reachable, f"{name}: API reachable on port {settings.get('api_port') or 5506}" if reachable
                    else f"{name}: {msg}"))
        return out
    win, err = find_target_window(settings)
    out.append((win is not None, f"{name}: open and found" if win is not None else f"{name}: {err}"))
    if settings.get("focus") == "click" and settings.get("click_x") is None:
        out.append((False, f"{name}: show RootsVoice the reference box (Settings › Projection software › "
                           "Point to it)"))
    inp, err = input_backend()
    if err:
        out.append((False, f"Typing into {name}: {err}"))
    else:
        out.append((True, f"Typing into {name}: ready" + (" (built into Windows)" if native_windows() else "")))
    return out


# --------------------------------------------------------------------------
# SYSTEM-WIDE SHORTCUTS - work even while the projection software is the window in front
# --------------------------------------------------------------------------
_CTRL_ALT = 0x0002 | 0x0001
HOTKEYS = [   # id, modifiers, Windows key code, action, label
    (1, _CTRL_ALT, 0x27, "next", "Ctrl+Alt+Right"),
    (2, _CTRL_ALT, 0x25, "prev", "Ctrl+Alt+Left"),
    (3, _CTRL_ALT, 0x28, "next_ch", "Ctrl+Alt+Down"),
    (4, _CTRL_ALT, 0x26, "prev_ch", "Ctrl+Alt+Up"),
    (5, _CTRL_ALT, 0x42, "back", "Ctrl+Alt+B"),
    (6, _CTRL_ALT, 0x41, "auto", "Ctrl+Alt+A"),
    (7, _CTRL_ALT, 0x4C, "listen", "Ctrl+Alt+L"),
]
CLICKER_KEYS = [   # a presentation clicker sends Page Down / Page Up
    (20, 0, 0x22, "next", "Page Down"),
    (21, 0, 0x21, "prev", "Page Up"),
]
ACTION_NAMES = {"next": "Next verse", "prev": "Previous verse", "next_ch": "Next chapter",
                "prev_ch": "Previous chapter", "back": "Back to the last reference",
                "auto": "Turn RootsAuto on/off", "listen": "Start / stop listening"}


class GlobalHotkeys(threading.Thread):
    """Registers shortcuts with Windows itself (RegisterHotKey), so they work whichever
    window is in front. on_fire(action) is called for each press."""

    def __init__(self, bindings, on_fire, on_status):
        super().__init__(daemon=True)
        self.bindings, self.on_fire, self.on_status = bindings, on_fire, on_status
        self.thread_id = None

    def run(self):
        try:
            import ctypes
            import ctypes.wintypes as wt
            user32 = ctypes.windll.user32
            self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        except Exception:
            self.on_status("Keyboard shortcuts work on Windows only.")
            return
        actions, failed = {}, []
        for hid, mods, vk, action, label in self.bindings:
            if user32.RegisterHotKey(None, hid, mods | 0x4000, vk):   # 0x4000 = ignore auto-repeat
                actions[hid] = action
            else:
                failed.append(label)
        if failed:
            self.on_status("Another program already uses: " + ", ".join(failed))
        if actions:
            self.on_status("Shortcuts ready: " + ", ".join(b[4] for b in self.bindings if b[0] in actions))
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312 and msg.wParam in actions:     # WM_HOTKEY
                self.on_fire(actions[msg.wParam])
        for hid in actions:
            user32.UnregisterHotKey(None, hid)

    def stop(self):
        try:
            import ctypes
            if self.thread_id:
                ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)   # WM_QUIT
        except Exception:
            pass


# --------------------------------------------------------------------------
# LISTENING ENGINE (background thread)
# --------------------------------------------------------------------------
class Endpointer:
    """Cuts a continuous microphone stream into phrases at natural pauses, so a short
    command like 'next verse' is acted on as soon as the speaker stops, and words are
    never chopped in half. Silence is skipped entirely."""
    FRAME = 0.1  # seconds

    def __init__(self, rate=SAMPLE_RATE, end_silence=0.5, max_len=8.0, min_speech=0.3):
        import numpy as np
        self.np = np
        self.n = int(rate * self.FRAME)
        self.end_frames = max(1, round(end_silence / self.FRAME))
        self.max_frames = round(max_len / self.FRAME)
        self.min_frames = max(1, round(min_speech / self.FRAME))
        self.buf = np.zeros(0, dtype="float32")
        self.pre = collections.deque(maxlen=3)  # a little audio from before the speech started
        self.utt, self.speech, self.silent = [], 0, 0
        self.noise, self.level = 0.002, 0.0

    def feed(self, audio):
        np = self.np
        self.buf = np.concatenate([self.buf, np.asarray(audio, dtype="float32").ravel()])
        out = []
        while len(self.buf) >= self.n:
            frame, self.buf = self.buf[: self.n], self.buf[self.n:]
            phrase = self._frame(frame)
            if phrase is not None:
                out.append(phrase)
        return out

    def _frame(self, f):
        np = self.np
        rms = float(np.sqrt(np.mean(f * f))) + 1e-9
        self.level = rms
        loud = rms > max(self.noise * 3.0, 0.004)
        # background-noise estimate: follows quiet quickly, rises slowly
        self.noise = 0.8 * self.noise + 0.2 * rms if rms < self.noise else 0.995 * self.noise + 0.005 * rms
        if not self.utt:
            if loud:
                self.utt, self.speech, self.silent = list(self.pre) + [f], 1, 0
                self.pre.clear()
            else:
                self.pre.append(f)
            return None
        self.utt.append(f)
        if loud:
            self.speech, self.silent = self.speech + 1, 0
        else:
            self.silent += 1
        if self.silent >= self.end_frames or len(self.utt) >= self.max_frames:
            audio, keep = np.concatenate(self.utt), self.speech >= self.min_frames
            self.utt, self.speech, self.silent = [], 0, 0
            return audio if keep else None
        return None


class Engine(threading.Thread):
    """Listens continuously, transcribes each phrase, and posts events to `events`:
       ("progress", text) | ("status", text) | ("text", combined, fresh, audio)
       ("level", rms) | ("warn", text) | ("error", text)"""

    def __init__(self, events, model_name, mic_name):
        super().__init__(daemon=True)
        self.events = events
        self.model_name = model_name
        self.mic_name = mic_name
        self.stop_flag = threading.Event()
        self.failed = False

    def _fail(self, msg):
        self.failed = True
        self.events.put(("error", msg))

    def run(self):
        try:
            sd = audio_module()
        except AudioUnavailable as e:
            return self._fail(str(e))
        ok, msg = check_speech_engine()
        if not ok:
            return self._fail(msg)

        try:
            model = get_model(self.model_name, lambda m: self.events.put(("progress", m)), self.stop_flag)
        except Cancelled:
            self.events.put(("status", "Stopped"))
            return
        except Exception as e:
            return self._fail(f"Could not load model '{self.model_name}': {e}")
        if self.stop_flag.is_set():
            self.events.put(("status", "Stopped"))
            return

        raw = queue.Queue()  # the microphone keeps filling this while a phrase is being transcribed
        device = find_device(sd, self.mic_name)
        if self.mic_name and device is None:
            self.events.put(("warn", f"'{self.mic_name}' isn't connected - using the default microphone."))
        try:
            stream, info = open_microphone(sd, device, raw.put)
        except Exception as e:
            return self._fail(f"Could not open the microphone: {e}")
        if info["rate"] != SAMPLE_RATE or info["channels"] != 1:
            self.events.put(("log", f"Microphone opened at {info['rate']} Hz, {info['channels']} channel(s) "
                                    "- converted automatically"))

        ep = Endpointer()
        self.events.put(("status", "Listening"))
        prev_tail, last_heard, last_level = "", time.time(), 0.0
        last_block = last_sound = time.time()
        silence_warned = False
        try:
            while not self.stop_flag.is_set():
                try:
                    block = raw.get(timeout=0.2)
                except queue.Empty:
                    if time.time() - last_block > 3:          # unplugged, or the sound system stopped
                        self.events.put(("warn", "The microphone stopped sending sound - reconnecting\u2026"))
                        try:
                            stream.stop()
                            stream.close()
                        except Exception:
                            pass
                        try:
                            sd._terminate()                   # refresh the list so a re-plugged mic is found
                            sd._initialize()
                        except Exception:
                            pass
                        try:
                            stream, info = open_microphone(sd, find_device(sd, self.mic_name), raw.put)
                            self.events.put(("log", "Microphone reconnected"))
                        except Exception:
                            pass
                        last_block = time.time()
                    continue
                last_block = time.time()
                if raw.qsize() > 300:  # more than 30 s behind: this computer is too slow for the model
                    while not raw.empty():
                        raw.get_nowait()
                    ep = Endpointer()
                    self.events.put(("warn", "Falling behind the speaker - choose a smaller Accuracy model in Settings."))
                    continue
                for phrase in ep.feed(block):
                    text = transcribe(model, phrase)
                    if self.stop_flag.is_set():
                        break
                    if text:
                        # the tail of the previous phrase is passed along so a reference split
                        # across two phrases is still caught
                        self.events.put(("text", (prev_tail + " " + text).strip(), text, phrase))
                        prev_tail, last_heard = " ".join(text.split()[-6:]), time.time()
                if time.time() - last_heard > 15:
                    prev_tail = ""  # long pause: start fresh
                if time.time() - last_level > 0.25:
                    self.events.put(("level", ep.level))
                    last_level = time.time()
                if ep.level > 0.004:
                    last_sound, silence_warned = time.time(), False
                elif time.time() - last_sound > 20 and not silence_warned:
                    silence_warned = True
                    self.events.put(("warn", "No sound from the microphone for 20 seconds - check it isn't muted, "
                                             "or use Settings \u203a Listening \u203a Find active microphone."))
        except Exception as e:
            self._fail(f"Audio/transcription error: {e}")
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if not self.failed:
            self.events.put(("status", "Stopped"))


# --------------------------------------------------------------------------
# VOICE TRAINING
# --------------------------------------------------------------------------
PROMPTS_FILE = os.path.join(BASE_DIR, "rootsvoice_prompts.json")      # your editable practice list
SAMPLES_INDEX = os.path.join(TRAINING_DIR, "samples.json")            # the CURRENT session
CORRECTIONS_INDEX = os.path.join(TRAINING_DIR, "corrections.json")    # live-learning corrections

# The books speech recognition most often gets wrong. Edit the list in the Voice Training tab.
DEFAULT_PROMPTS = [
    "Turn to First Corinthians chapter 13 verse 4.",
    "Turn to Second Corinthians chapter 5 verse 17.",
    "Turn to First Thessalonians chapter 5 verse 16.",
    "Turn to Second Timothy chapter 3 verse 16.",
    "Turn to First Peter chapter 2 verse 9.",
    "Turn to Second Peter chapter 3 verse 9.",
    "Turn to First John chapter 1 verse 9.",
    "Turn to Habakkuk chapter 2 verse 4.",
    "Turn to Zephaniah chapter 3 verse 17.",
    "Turn to Philippians chapter 4 verse 13.",
    "Turn to Ecclesiastes chapter 3 verse 1.",
    "Turn to Deuteronomy chapter 31 verse 6.",
    "Psalm twenty three.",
    "Verse five.",
    "Next verse.",
]


def load_prompt_lines():
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            lines = [str(x).strip() for x in json.load(f) if str(x).strip()]
    except (OSError, ValueError, TypeError):
        lines = []
    return lines or list(DEFAULT_PROMPTS)


def save_prompt_lines(lines):
    clean = []
    for line in lines:
        line = line.strip()
        if line and line not in clean:
            clean.append(line)
    if clean:
        try:
            with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    return clean


def prompt_info(text):
    """Work out what the parser should produce when this prompt is read aloud."""
    t = RefTracker(":")
    ref = t.parse(text)
    return {"text": text, "book": t.book if ref else None, "ch": t.ch if ref else None, "ref": ref}


def training_prompts():
    return [prompt_info(line) for line in load_prompt_lines()]


def default_prompt_for(book, ch=None, v=None):
    ch = ch or min(CHAPTERS.get(book, 12), (len(book) * 3) % 12 + 1)
    v = v or (len(book) * 5) % 20 + 1
    return f"Turn to {spoken_name(book)} chapter {ch} verse {v}."


def add_prompt_for_book(book, ch=None, v=None):
    """Add a practice prompt for a book that was misheard (skipped if one exists). True if added."""
    lines = load_prompt_lines()
    if any(prompt_info(line)["book"] == book for line in lines):
        return False
    save_prompt_lines(lines + [default_prompt_for(book, ch, v)])
    return True


_COMMON_WORDS = {"to", "the", "turn", "open", "and", "of", "now", "for", "our", "your", "chapter", "verse"}


def learn_phrase(heard, book, ch):
    """The transcriber's spelling of `book`, found just before the chapter number, e.g.
    heard 'turn to first pita chapter 2 verse 9' for 1 Peter 2 -> 'first pita'."""
    parts = book.split()
    if len(parts) > 1 and not parts[0].isdigit():  # e.g. Song of Solomon: skip
        return None
    toks = words_to_digits(heard).split()
    for j, tok in enumerate(toks):
        if tok != str(ch) or j == 0:
            continue
        i = j - 1
        if toks[i] == "chapter":
            i -= 1
        if i < 0 or not toks[i].isalpha() or len(toks[i]) < 3 or toks[i] in KNOWN_WORDS or toks[i] in _COMMON_WORDS:
            continue
        phrase = toks[i]
        if parts[0].isdigit():  # numbered book: the number must have been heard correctly
            if i == 0 or PREFIX_NUM.get(toks[i - 1]) != int(parts[0]):
                continue
            phrase = f"{toks[i - 1]} {phrase}"
        return phrase
    return None


def load_samples():
    try:
        with open(SAMPLES_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_samples(index):
    os.makedirs(TRAINING_DIR, exist_ok=True)
    with open(SAMPLES_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def write_wav(path, audio, rate=SAMPLE_RATE):
    import numpy as np
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def archive_session():
    """Close the current session: move its recordings into archive/<timestamp>/ (kept for later
    use) so the next session starts empty. Returns the archive folder, or None if nothing to move."""
    if not load_samples():
        return None
    base = os.path.join(TRAINING_DIR, "archive", time.strftime("session_%Y%m%d_%H%M%S"))
    dest, n = base, 1
    while os.path.exists(dest):  # never merge into an earlier session
        n += 1
        dest = f"{base}_{n}"
    os.makedirs(dest)
    folder = os.path.join(TRAINING_DIR, "samples")
    if os.path.isdir(folder):
        shutil.move(folder, os.path.join(dest, "samples"))
    if os.path.isfile(SAMPLES_INDEX):
        shutil.move(SAMPLES_INDEX, os.path.join(dest, "samples.json"))
    return dest


def count_sessions():
    try:
        return len(os.listdir(os.path.join(TRAINING_DIR, "archive")))
    except OSError:
        return 0


def save_correction(audio, heard, correct, kind="ref"):
    """Keep the audio + what it heard + what it should have been, for re-learning and for later
    model fine-tuning. kind 'ref' = correct is a reference, 'text' = correct is the full sentence."""
    rel = f"corrections/{int(time.time() * 1000)}.wav"
    write_wav(os.path.join(TRAINING_DIR, rel), audio)
    try:
        with open(CORRECTIONS_INDEX, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError):
        index = []
    index.append({"file": rel, "heard": heard, "correct": correct, "kind": kind})
    with open(CORRECTIONS_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


# Roots logo (from the church's artwork), embedded so RootsVoice stays a single file.
LOGO_PNG = {
    "emblem_white_32": (
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAFSElEQVR42q2XfczWVRnHP+e+eXhAITCFECaDFpKiKJmzTVpO"
        "QIqsptME355M22xrrrWW6bSZL8C0rfFPVKugVFyaa/mKGTlfyHzDHIKSpKhYsIyFIQI+z/Ppn++PHW4fAtKz3Tv3uX7Xua7r"
        "fK+3c+D/HGrJPEqdXtMOZLTeh/KWOgx4EJgd2uADNaK1nwpbHYJbpZQ+YCFwHLCllGIpZWcpRbWttvigRy1YnaJuVfvUH6kj"
        "1NnqQR385f0oHBQhF6pjQusK/aYo71dfVI9V16kb1F+rn6gRPGAXqO1SSm+gngE8oZ4JWErpBfqq/ZOBcaWUycA5wGvAfepS"
        "dXgppV9t75cBaonyPvVL6k+B3wLjgTuBJ9VvA6uBm4F/ZOskdQ5wBfAycDLwEWCtekLktfcZ3Q1TIN6s9qiD1fWBvBnb1YfU"
        "Reqj6nfVv+fbbyqZl6u71FkNsv/T55l/Fb+Orb6dHuE71J3uOW5VV1Trk3KY7uy9IPRpe42J6uTz1VfVoVXQNd++Uynp7UDE"
        "rHeqE6osGJz/V6r/VIe9J60rBdNzwvEd9NJhxL8qpf1RvCPrx6KgVcnvyvxkYmpPVzQWqavVb1Yp2FIPavK5Kr9D1FPVezqQ"
        "2K6eGN6u8LUq+ccEoYm7XVGd7PPJ4XalfKa6uDKoqGPVWfF7M95Vn6h6QhNLP1Y/3RgU2gr1h7v5KgN+p16X/43/L4mCiyu0"
        "ZqmbQr9LXah+prPoVPHy2Qq1op6fjNqNKGq3+remegWFi9WrkkLmNI2xh6lfTra8oY6rAvZg9d7s2aZ+PbIaw45IDE2oY+Bo"
        "9aVsbhiviZAN6r/zv6eCd27lgqmVn68P7dX0ClO4dveSIDCrNmCmuqajIA1P1Ko+n/kXFc/KBKDqLRX9YfXNKiseDMKt6nBr"
        "1a/UBoxTzw20QyrGoeoV6u3qkvh/mnp/lffN7071KPWL6t1Z9wxQb7rUM9RJAE1aTQJWAIOBbcAuoCsN583wDQX6gW6gF5ga"
        "egE2AuuAw4G3o+sdoA2MBgYBOyOvnfWFpZTHB4X5LWAEMA/YFEUCHwKOBI4B1kTAeOAS4C/AscDW8A0HbgN2hO8/+b2TuTu8"
        "bWB5eBikllLKZnUT0F9KWaXeALyYU00BZgNfADYD04AlwErg1hi6EJgfoW8Ax0fh94FVwFeBl0opy9WP58Brm3bclMSngHMT"
        "5euj+JG45NnA/A3gLmARcCPwOjAK2AIsBg4BHojCG4Crgd8DhwIlsdUDrCulbFPbdSE6Vd2SIDlRfSbzEeqfMv9SvVZ9IUF2"
        "R/b8ISm2QX1OfVo9OnIfVZc1nVXdqJ7fVMJSVS/j56XAT4JAL3Ae8LNAfArwCrCrlPJJdTtwe/auAz4cNz0fpC7PZaYH+Dlw"
        "GrAgcfTuQN1wTirfyOri+bmc/AX1e0nHk9TzUtFWh/e+nPav6RdHphjNyfdhqQ3zBryYVEbcoa7M/xMidK66OG76mjoxUM9L"
        "MbpKPSVl+SL1KXWGeoh6VGQ9pt6711tR0/NTfNarS0MfHWSWZz1RfSUKFuRatky9TJ0cox9Sv6WOzp7b0msOHuCNsecDpFK6"
        "Id2uqB9VxwT6P6s35sK6NbecswL36VEwvaqkD0T5qH1d0TuNGKH+MZtnhjZWPVQdn+b1A3W5+jH15LrDqWerr+f78P1SPtBD"
        "IlBuTvM5J4Ydp56WlO2ueEerl6qrEg+X7utxUvb1+s1bb2SK0FkpKhuTjm+FfQwwATgsj5JlwJJSyttNipdSPCADOl5IfdV6"
        "CvCp1ImRkbElveHxUsr6ve0daPwXwSgZAeX4WF4AAAAASUVORK5CYII="
    ),
    "emblem_white_48": (
        "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAJIElEQVR42tWae7BWVRnGn3UuoIDcHAgR5KIRKKANF0nRgOIq"
        "TuSIoCiJhGhFGjU2KqUZOJLZZcQhR5PMyrLGGtSsnEyoTFERTFNMRgK5BITGRQTOd3790bPsdbsPl8Phj/bMnm/vvdZe6708"
        "73V/0hE8gCr/tgU6+To15R5VR5L4lFI90EvSEkn9j/SeR0LyJwDr+O9xWhz7f9BAraR7JXWRVJHUzEPVQHVTQ6kxBFbv7zkw"
        "3JLf699RZXMPl5lGayClVAGq4ua+Bmgr6SZJ+JSkwUACpgAjgVYppYpPGhJIU0s9+bcDcG5BkilIf5SlXgHqfP2kx573/U7g"
        "Z4V1UlPbSEMqbw+8BXwHaBHGm1srFxk6+4B6n3VAX6CLtfCAGQR4ATjvQPBsUswDT3rzF4ELbbR57Dz+d9SZEYAbCmscDVwG"
        "bPT4Q0DPJmciQKMDsADoA3w9wANgJTAb6AUcD9wNbArjFWCx1/kEsBj4HtAVOAaYF6A1MULzsDAffPpEYJs3+ZiZwNKtBEL3"
        "AEuBOcAFZvRNj/0IONHXa4AtwFqglfcYAqzy+PU5bjSKiQLx87MhAv3C+MMFJqJGMjM/BS4H/g7M8n12r3ts8Alo5nXbG0oA"
        "3/CzmsYQn2Fztxf7VmCoxr8nA7s9Xh9+i8xsAKYD1wWGAV5tYM8q4MeeM+eQmQgLLfAiXy7ZJP9eaGnuDUzEIxO7HXgnGDbA"
        "b4quM0MGqPE42UMdlGEHwj7rl2/JEihiMWjihmCoGU71Ba0UmaoHbi+TbtB0e2C1bajrAeNEeLG3pfRokfiCtFKIDXODtMuO"
        "yFDWwNiC0FKJID/qub88YDIYGHjC7qzzoWSQwADgLnuS9cAbJdLPudEfLZiq/ayXNXyP3xnaIJQCx+d48lVF9Rqf3crcWgkM"
        "Btud1oUza2gjcFJBaMlROpXYQ1fbz+MNCjQs9Iy9RvOwQGZuKPCHhmwi4PZqr1F2PAOcXDRY3/8eGFSgJ++9yO+f8j4mwuRT"
        "PenaggprvdlNHv9kYKIqSPx+Qyce24HngF8AF+eUIxCfbetyz7/SY7WFRPF0j9/4Po0HQufZg3QpU5V9cz2wA5gRA57Th9ts"
        "O5iRa4HJwJiitgPhzYCvGWL1WXglGXCtobcyMl6c9AKwvMTnT7GBzip4kXtNQPRMPYEbgWHAd83Qg5Zks0KE7wr8pbDmSEt7"
        "UmA203Gf53R6V8CB+PaW/vwQSLJmrgbeNkR2WVJ7vNiioOpo8H8LMPp+cLnJZ6tQG1R8brcX2wdMDzDNdFzp+cPetY/A3QAT"
        "NqUE3ycGd/gvp9Axyg4Maq4JtpRd5rNFJoEZQfIvm/ishR1AxxIkjCjSWCUpY+l4X6/JWnFbpDqltFrSPM9rL2m3pKck1Uiq"
        "l9TfzNamlOokTcqVp8c/DIxLKVUkZcid5nJzidc5WlL279eklDZ7b4JJvOk1u5QZ8CgbSe8Sg8uqnx9S55cDfseG+WMNt2I6"
        "sSW7SM+7Ffin02qCdj8fEVDQQFevMzvPSUByUd1KUg9JWyW9LWmXpVn08ydJGiNpoKQ3JK2TdJ+kYyVdIem6PDVot873tZKu"
        "cbtFki6SdKak1ZKel/RISmnnfiJzM0knSNqcUtoOpGQ1VYCzJf3K/ZtaSdsk7ZC012fFcHhL0k53NGr8vEfovD0nqaekdoGR"
        "eknLDL0Rfv5nSZsl7fP6dYZnazNe4zPT09wQq5E0J6V0H1BTE9oeW7zpq5JWSGrrF46S1NILN5fULUi3uTd4RdJ8SS9LujQQ"
        "nxmoljRA0t2Sbpc0TtJoSaeagVqf+wI9dRbgNgttt6TjJPX12PtiwDEuTn5ygITtA44L44HO9u2dgM8ArxvLvwWeDlXZEwHn"
        "TwFTnVO1BT7o9xPQGmi5n72vsE0NeE9SF5hY7hq1mV3iOY6mQ5wbtQbOcJX2jueuKKQOdzmmrA8GfJtP3I7J0Xqr52xwrtM9"
        "9FQnOzMYn4OlGwF7gNbvSb+DJ/q2F8yZ4llefJP7ODnPWeeQnon4klPe9X7vi8HH19u7dXCk3+Jifxyw0Gn1Ls9f5qidmwfz"
        "ct/JLZg3SzPSko5admX9HcQ6OQpvBaY5ii62K20BtLNkBllbe1wLvBQ0MwIY4+tt1mzOuY4FLrWg3gEm+P5m4DjDa6TfnVWW"
        "zKXA5ZacMIUm1YvAZuBEP5vqxXpY3a9bC2c5ilbcsMrl4L+BO/3uHYUo/RDQLvSdlnu9y0KXWxZYHdC1tCYoZKQAHzHmp3mT"
        "0R4/1+MX24i3AL8LidZe47af71cA3/R1T2tvnw1yuol6LbRrBhlyK4K0+xqKPz+YgqazvdHSMNbZar7ZvaAhfv5YyF2WGsu5"
        "lzM3tFTaAI/6+hjXB0tCDrbJjN/gZ5Mddfv4/sHCR5LqA3UkbvELk8JYh2D9/Y3/9Zbgp6yxXXazLe2hNlpyw+1F/uqa4gGv"
        "/4UgoBW2nY/nRnFITQDuPWBrJRQnrYF/BO+RtTPOWMStw5nAs35nfTD+Rcb+TM9dWnASq9xPqgPO8Fg3w+pWQy3Zeay18+h0"
        "UO33Eo/0iO9bGf8LgftD3Jjtxe/xswl+72zgEvv8HQFaj9shdAfudEI3N3uk0KavblRjq8DEV7zAwjA23hAZ77F+MdGztO7w"
        "/Z9s5LndPtzMnu8gOdMSvt7NsTZh7x/kWNCY1mJMYRdmJoKnSsA1hX7pLBO7DTjTKUJuaA0ygTuA80NxM9hMVsePg4H4hY1u"
        "swd7SO7jY/znSqlvmHuJxy9w5+J0t0hyW/0eP3vNEJoY3u0F9AgpRM6bFhxWe72kxf7V4BYnFAqeC0K/pgfwCrDExf0OG3xL"
        "33f294XmhWbAVAe82EyuOuzPsQUmxoYP178GTi/5hpaNuKNhNgP4kMeOKvlUNTp8rloVCvaqJv2WHGyifYisWNLTQibZBzjH"
        "16c00L3rDVwVMtnddhgtDvX7WDpUJlyYywR/TtKnJbXxlJckPS1ppYuRDS54Okrq5EJ+oKTunr9G0kJJP0wpbSru0eQMhMSv"
        "KjDSUtJQSeMlDZPUK/ytoHjsMpOPSXpY0rKUUn2Qen2hC9H0DBRyp6pi4e/M8nhLPPvuiqSNktamlLaXJJGVQyU8H/8Beq98"
        "F76m+I8AAAAASUVORK5CYII="
    ),
    "emblem_white_64": (
        "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"
        "QmCC"
    ),
    "emblem_black_32": (
        "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"
        "l478ondPN/4bUN9Qw7UZoGcAAAAASUVORK5CYII="
    ),
    "emblem_black_48": (
        "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"
        "IP8L2X0rZuG5HEkAAAAASUVORK5CYII="
    ),
    "emblem_black_64": (
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAaD0lEQVR42uV7eZhcVZ32+/7ure6ue6u7uqu6SQLpqu4QUQIi"
        "EnYVkG00LgRRQFxA3EYdRGTmYxyZEWdGx3EUdMYFHRFB2XH54BFEQAQkIDvIEjCGVCWQhKSqU91dVd1d9573+6Oqm0rTCUFQ"
        "53umnqef3s495/z297dc4C//8Wa+L0HHn/tw+x9AfJwczO4b5rLXBdWBTOvv/HNdwP9LEx/k+5aRuEoOU7Upf/R/iwY0JT+c"
        "2Z/klSADEE8jXB//b2AAAbiehT0ZOl4GWAhJhLrQ+POp/l+SAQZAkfkfN+MiOE21mBLA6+tsY5LX+uL/LwywHdiPAJpqTp4o"
        "QSA8CADQ2+1sfmuda62LAai1r/+nYMbL6QRdGyPc9piQyme/JnJ3SJr2BzRLxs4dDODJrqH+N3jCMiG+DfDvrxU2bWjb02v9"
        "rP8pGkAACBf1vbpz4cDi1uXmkhYBCLl0rxPeD8ja1rSI4ZsBiDH28Tq8s8y8nwPu0SCfvTrIZ04JF83bqU0rXhbz8F4mj65E"
        "T7DM83iR19N5d1SZKMyxvwFQqjccBvExgIk2xhACAezcmfS+H1uiaIg8SSS42HxbQtpyxNF7OtJBxk8ln4zG6pX28/+SDEgA"
        "UGdf2EPikwTfk0iH1tsR3ler1SbbTI0AXKKnax5oH24zP077BjMGzvjkxNrSTVNb6tc1KvXvJ/pSP1EcPyOh38wW07dDSJ2U"
        "SAeJRu9O96JSabwUJngv1ZtPq6SfDicldwrJHjO+cSqhYxPdybFGT/ZJjI5OtUyD1tsZGu0MENZ6dpoBIkkAaFTqV2AxOlFG"
        "o7GltrFRqd/WqNS/7fV0PUJhZ5q3hMYjE5p4U2dP58qp0Yk1f6w5ey9BcxwABMN9H+roCZfUiptXJNLBcSR3htQgOZ/GYxNo"
        "vKOjN+y0dGJjXJkciSuTWzrSwSJAr6BZF0A+xwgaAK8R9H4PxfGJ5MLsfp19wTkd6eDjnb1BtVYs/7RRqV/Y0ZvcIKe96Xmv"
        "EvieRG/SNSr122YJZscd2It0eATgwuHevSDvS/TszWq4NdViaVGQy/6tefyynOKZvUkjATk3JuBuAj8XvFsYRxHII2D4G5ot"
        "lpMDQUjrq4VyvivXt7/neTfBOQfg1zR7i3P6cVdCp5ZXlUeTu2QW0udXzXg8CLhYV9TG8WGUSmM7EIn+qCgwzSyXGsz+NZzd"
        "Qc/erMitgvHvAUDCJS5WpbUvARgk12QIu83sCJqdS7oH4NsPZQhj6P1y8T8DJEhKLOFQwAO/QSApsA5hZzVjBeVEAIn60+V1"
        "tULpBDl3hmI1zLMTghA3BPmB+S3i7eXUgOl1DHKZb5hnHxMAOfcdm5o6e3z9+OaWU4vCXPaL9PgZOUWzcIa2iuUkaIRiVUR9"
        "0Zz+AM8udc6dQ9gaGi5taZLXWvdQtVh6bWsftgskyPctA+xC82wnRe5BJ7ylvrb0zI5oAl8E8X6Qy1xsvneinKtKOq1WKF84"
        "yycwnUunI/PvBzgENQnYDnByAHx6BsTuKjn9N8hYxGUk+luhMaLRd7HOqxVLZ04zehaYi5KD2X3NdA3NWyAX39M1ziNKpdL4"
        "1jjjxZvADKeniXexe5bgW1rEe23wVgBQKVZGIJwKqQFuNzxNw1spdhE8excMnwD0VSN3ahHfMiMQ4MoZMLX1JwLg19eW7nUx"
        "lju5EXrefvUQ39sRGr0d8fbBUPY887wPudiVHNwxtUL5N63Lz05fBcBrVOqr/d7koySPaWMit8Nkg+RotjvI+S2IPGN2IEjh"
        "641KffU2vLwD4Eej9bV+b7CSTseZx738nmStUan/Zns4wXvBgsVQ5mSjfUlODYgn1ovlX82hhrOZ4EeV+qOJnmDAfDsYkmtL"
        "aratbcLsdS1GaDw296/RlonKNrTgOSZsqT+eSAcTNB4F4g1+b/KmaEt97baY4G0P5KRz6WEH72rSAij+P7Vi+eIXIH4rJjR2"
        "qd/kTyZ7jDyIRoNmHKHaLsO5TG6aKBop6bf1wsjXtkP8bA28w08nX2ee7YYYr2707vQjVCrxi/EBBKAI3rnmWVZxfG21MHLu"
        "tFbswB4CEOExTNUKpU85xcvktAIEafSmv0DaDjCSpL61jbNsjvUCIJNOVxyPmWcHBBp7z7ZCI7ep+rnet9Lzr4VU9uLG/qNr"
        "R//wYgDGbOAEAKnBgdc7iw8luFsTNmBXAgdvw0c0aEzIuWurhfLyWSn3DpXcwnzmy/S8v1MUP9mV5L6lJ54fFWxOW1qCDsL7"
        "R5KQ03kt4r25LtCV7zuolRBtS4LT6bE3vnbTb2qF8heqhdLJEG4isXAOwl0r9CWc0yNMdHxwlslMfzqSg9l9t6c5kp3n4vhZ"
        "+rZbva7j5/JDNldqG4z3H02P+yt26xKIv9kuxfbnkoPZfT3ZpRgY6GxDf3N9omnTSQ5n9g/y2V/S4w8BDrUxKZ6Bzh59J3cL"
        "xKPHV23YNMv2DYD1LepL0nRpRz6z+xy0OABWK25eD+FHLQX74FxCnMuGQOhUGOGACyrFysgcoccAwKjjmLChIKmTWhs/XxPy"
        "+a4gPzA/yPW/NchnLzfH2814lGI1IMUgbcYnAJD0qCL3ydqa8tG14ub1s8xuulboJiP7qPneK3zxLduhhXT6gZybILFfcjD7"
        "2tla4M8iyqVz6UUR8SZFrurkXTyH533ud+J1chKhf+/O9T0yVhxZ0Y4KAShp46+mww/o2xIIaGYGatBrFkQUuwcd+GsjnjC5"
        "h8dSI/fiMUy1V5BnldoaYT57EoB/RfPsXWf5G7VpAavrRn6XymXuQsI7jFH8VwDubWeqzZZqg4nD6FkS0k2TxWdXz6H+0zUA"
        "T0AaAkH2OvIXyaG+j7ahQgFA/anSPV5sx7jYfUPSREveCTndoFhHwnMnk/xtHOvaseLIihbx3ixiPAAuszjTE+Sy54K8ZMbk"
        "OFM9bszhJ6wZS3FTS7ePnh3J7HlFTeloEHDG62d5ZwOArqH+Q1K5zDsBxASKzRKGGiC7PXrnB0PZS7FgQdB+mdF1m1bVCqXT"
        "XKRDJV3v5E6OJ+OPwnhcM6vkZfS0V+tyfju0bp0bB7n+fSYaXGEez2ghRQcAFNYBiMOhvuO7cn0Hz2UOBO+QkyC8JsgPDLQl"
        "VDMLm1IeGEgROFCRi8zcirkAiwkpeXZVmM98SuKtrf8nIDg5RWZ8d9gx9dMWE9phsFdfV767uqa0jI7rvC7vfpIfA5hS5CZB"
        "/5kW4bOdrQsX9u1J6gYz7qFYjdZ+vpwmY+NDwVDmc4R3hUfrmJ26A4Cv6CHIbTBjmor33MqPtT/QmcY8EDkAG6vVjtWzYqYA"
        "IKHG44g1Cdp5pD4t5+oCSq0Sl9e0bzs6TEx9tg18TJuN3xSazqYxo9hNAnAwdtLFA7M0rvl9CTpgdgGN/XJqwJAAVG05zIYJ"
        "XzfaOU4qsXPykVl4QQBYKVa2CPwDjBBsaCuBtv/iNaLdaEZJv8fGjbU5nIpVipWnBNwOQgAXAOyC9IiEEpo1Pco5B+jUdC7d"
        "N6vuF2MpfIDz5SAQCQCOBATu066aM9IfyxwK4/5yikEmIN0DYH0zYjIFIN8yhf87/uT45jkwvwEQgdXNW7id2gW6FQPgOABD"
        "TOL320hemhZP/SOkyZmc3rgXhBslVUD6rQA0v4HEcNtzPgAFm/uPNMMrW3ZsAEwSCHxo3rx5YYthz2EKYncSDoQn6UYABtpi"
        "AILQAAnn9Gzsu89vL1cQMNrcm/O2iQNkTE3H422ksTEAqxfKd8WxOwVATNIn2EfiYAAXAW4lSIMwRcWTAIgl8AE0BgYGUpC+"
        "1Cp+PufkBEfjK8a7om/NAKP8dCmdMUiDwy8g+aAthRQBMPpMQG69kzt2YvVIcY6I1SY5V6LRM2D+trJB+d1h0uiSgK5rbJl4"
        "dBYAYRvD/Gh04uHO7vA2mXYDOEjP0gAOkMMtBJIgJqou+GeMjjawCXFyYWaXRicuN48HqZkee7OxBY17++muxd0DyZvrT9Wr"
        "ANDRk+wFdITIzZbwjyAEkiZhFMClkeKTJ4tbfoelSDQNY6ZH2X5nl+hNJiEGcryhUandP3Pm7F5hOp9OuUbouc7I9+PJqUrH"
        "QA2rVk1uL/MIF/btSY+7SVwqIiWHm2F6tl4o39W1a98gI3ubCX9Pj4NyWxU72vlfg+jRt04Xu4cpfNmizl+MPfNMKcgP7E25"
        "42VIUipAeKSa5G/xRGnsj2jeRnNlg83sabDveHp2kXOYAOEI1AWUIY0QnADVgDgFwmkGTGgKYglQRMJBiAV0EAgBDgs4wHxL"
        "A4KL3EoA/SSzs/N+EBNwulHksPm2Fxwg554WcBeApymMQS6i58k5Fzf3RwZgE81SCQle00fQp+SDSAjsJBAI6Dai3zl+p1bc"
        "/PlpmrfuDpNlgV2kugCCBEjs0jRFbsW2raoY5BwZBZp+zgly7k459xOYLSVwTKveN1s6SZIHSvwn13A9JD5Gs0U0HMfp5S33"
        "5MlaR2ju3F5bl5lm0Iw936v77Y9E8Ff7Lp4CJELvhbReYFKCwcy3JpdDAmlBXQI75VyX53mS5EPwBCQBdQGcMNgKMz0sJ0/g"
        "Zwme2DzNTYLseO7OqkEMRMwj9J+OOJ30Do4R5xjjcEiDAB2EGIRB6mhRF7eguGsiXk0SqAAsi64sh3EQMQhBdi5hr3IuXtfO"
        "r60YMMnJsi9/Az3LRVG8YWLtyB0vZFgDAwOpWtIdA3IeoAdrdbsbmzaNA0DXrn2D1uApIM80YxoAnNNvQP7ciC/KIYLRl8O9"
        "IGDkIZI6PPJ856IzQJ4H2UWt+QCEi8KdqnH/KIqFiRfb0QpzmRQkc85+306zv1XxsVDZgnx2JcicZ97+AO5sNkP69wL0HjPc"
        "Nl61m6cJBIBN6dhSU5gQeCgMXw2DeEz5zAMQexlzLyYIRQ4SIOjHtbB0Ujie+RrMiNZfQbzSwR0LZ98zcomcqxPYxTzvfDh3"
        "fpjLFltBeH6g8Qrzmd8C+JVL4Kr6qvI6AOhZ2JOZMm93n/YaJ2UN+PF4sfwkAKUGBw6CuUEXa4uX8J7YCibPCokRhHtBHCW5"
        "/abha624+f7kYO9CyS4JQzelZOYXAB8EsA+n9CqR/YDLNIMKu814CEDIuacU6XYA74bTA7Vi6YTU/PkZ19k4ERJAJCBEZpwn"
        "Z3sb9E4B95P05XClGvGNNH1Q5P5mDFt6OwDaWxXFu1jD1ge5vjHADo+g9xrYKeAukeeP95d+j2EAtyIW4n1pHuHiB6tPPbu5"
        "HTDZbNclc7fBiSTf0IKyUfdw/2407ygAT8LpNpJ1AB8w306E2d6ANkr4NqSf0Qjn3BOI4+OrhdJuglbSmKDcmQBidUz9ixn7"
        "4DTZSmFNgqNw2nih/LicvgVjAsS7RSXG15QPryVK2cjFB7sYH5HTxYrcGnr2WhouI+0aEMeA9EikSN5Zj5M34D40cGsLxxBH"
        "tVDBTdOpPLZRklZqQapfiY7f0bP5cO648UL5p5g3L+j2al1jz4yVACDI972J9C4AtIHgp8fXbL4V2Wx32M2HACWiuHHY5NrR"
        "PyQHs/t6CbvHRe7rtWLpU2G+/wxQXwFpcrqa0OtALmixP2oY9/BjjIF6iOQAATjnbqHpO50+ry+vKo9Oq3vDT7zLpH8COUDh"
        "U+NTHT9IJSaXybiMTteNF8s/BoDOwYFFvsUPAkw608H1p8p3t9cEZmuA12x08joY5YQTAAgbN9bHnhkrBfm+ZUE+c495/vWS"
        "nqqaO3x8zeZbASAMdTE9DgvuQ9PEm8ebXexubBKfPRPEuSQNTr8VdBnIAQixnFbS6PvOvb5W3Lye0kmA6s302t5Iz798ssG1"
        "YT77L1iCjtF1o+X6mtJ3CBwJ4GkYvxl0TF0c+bq7uqZ06nixfPV0EuSbez89LwXogXqm/MBWk2rb6QtcglgE8eaOXfpfAUBh"
        "PnsYwLMITil2IzGi92L1SAUAwnz2TEv4y10j+nptzcgNyXzmHebxVwTuBnhWMJS9jORXQEBOD8Hz307gVWwmTjHJKyEIwvsA"
        "WLVYvknCBfTowbnPqeF+ACCgb2eH45krsGQgBQDjhfLjLtIJcooILPecFYLBzNHTTi6dT/dCOLml3z/EfWjMbgbNZkAMgNVi"
        "6XZJK8zzun1PHwcgF+v3tUL5UELXwemEyUJlTZAfmB/mM2eA/IqL4gtqxZEzwl169zLySkhlSVtI3W/kiYIiSA9yquPI6uqN"
        "z0L4KwmCsQPCrbHThZbwDwvz2XMAwMldDoKO2LlaLH1A4P4uco9awlseVOPru/OZA5HPd9XXle+G9H1JVyrWyTB+MLM40wNA"
        "Dfkfpmd5xfF6WOLy2dLfbmMkmcu8y/O8K+XcKKEDxwvlxwF09CzsSY2uGy0n85l3GPE+iBnB/q1W2PQLABbks1eY8Z1yrk6z"
        "pHO6ilInPXu7Yh1RLZZ+1TM4sGts7j4AaRoRO3dcvYs3hpO4np69zjXiD9VccGlotTLImmB71AqbNnTm00M+/B/Ts30UO8Hp"
        "P6o7DZ/dN7I6mIr5gWqh/DUsXJgEgMCbTBPx/fS8BS6Oz64Vyl/YRmdrG4nDEnQEueydqUUDCnKZn26VPS5GZzjYtwfy+a7p"
        "B4J835vCof7Hw6F+BbnMaDiUVat6iyCf3RDmsiumw26Qz3w2NdyvIJfZkBruV5jLXggA6Vy6LxzKrgiHsmPJfObAMJd9KrVo"
        "QGE+c+3MWQsWBGE+893W8493DvbsOnPrpUjMzC3mM/+dWjSgMJd9qmdhT2ZbHept9wYfwxQZfUbOxTR7eyqfecdMWWsVJqtr"
        "Rx5FoTCVymWOC/PZHxi96yEQTu8lMS7h6mqhdGk4lPk3M84TotMARN2L+l9B2t/KaRWBC5sFFryta2h+vlKsjLgYnySZIvhl"
        "AHCRO49mbw00di4AYP36ehXlT8q5a0kb8+j/vNWdMqSaqL85McJTWljjs6PrRssvdnhqRtphLvOtphSy65K7ZBZOM64zlx4O"
        "85lrgnz2kXC4X0Gu/xYAFuazb0wN96t7KPvKcLBvj3CoX2Eu+wUA6FvUlw5z2RWpXQeUzGeODfKZU1LD/WpKs/8SAEA22x3m"
        "M/elhvoV5LPNsDuUPS9sasoR05dr2TmC/MDeYS5z5PR9e+f35sN85unUon4Fg31XvdAYwAsNSFgq23V7FONt5nFXUHs3dqlf"
        "jk2IOlJhitIdoF0LueW+s+WTye6JhO+ugkNlvFA6x/rSIaXYWfztaMtEhd3hP1nCTlIUf7lWKP9XRzr5EZD7yelG87k80d2V"
        "bGwoX5foTfYD6qKQTvR2PWqJjisRx6eDOLkjHRzs9wWjY6vLDwNgo1Lb0BqcABYsCLxO9zN6tocirYFNHNeoNKrbG5OxF2hN"
        "Y2T1SAWK3q/YVc2zw4Nq5vsAUH+6vK66buQRUQeAOnl03aZVQefUSebbXoJuBoDJwsY1ks6dWLOlEOT6l5rhdEXxPdVC+TOZ"
        "xZkeAYezmRH8l2J3LX3vrOTC7H7WOfVdUP/piE8Atmx81YZNkkYE3SJipQGfC4f6TpipGjfp8MLE5GU073WKNEEXn1wr1Db8"
        "ER3tubUkmc8uD/PZRstpXdBWYZl50SnIZc8Kh7LjTcwA4F3NZ1P57MfDfGY8NdyvcDBzOgAGQ5mTw6Fp9c+ehQULgnAouz4c"
        "6n+8pzl0DQB+uLBvz6YpZu8Mc5mVM1Wo5uC0P+38glz28tTwgMJ8NgoH+47f0UHQHZmliwF49ULpZ5L7uCTQs1ODfPZKzJuX"
        "BDCFxejEUiRILGbMN1cLpV8DIO5c2BEOZa9nwvsmxCucc6sFjDQruvx0c4BSoulTWL++Drnv0viq2He/C3LZ9wGIqutGHgFg"
        "hD4I4PEg3/9aAKiu3rgJQJSanxoIS9lrzOMJcs4J+kh17ciV25hh+qNHZZsjL5WJexPpZBHCMjPumfDdGzvTwR1TT9U3IkQi"
        "EYd3VddufrR1uAt6E/9uvr1PDfeFarF0Zkc6OBrmndvZF5wJ8gQ4rQHRB9AS6fAhD3pE0rsB+wcCZ/u9yTujSv0ZAJyq1J/t"
        "6Oq5xXVFU9HIxOjMbIKf+Il5PEhOkxBOrRXLF+3gGM+LnhSNAHi1QvlC5/BOOW2i2UEOuD2Zz/41VmGy1c5OABAWLkwSqGNK"
        "h1SLpbOxGL75PJ2Kz4fHcxDr86BuoDGG8JAhHhkrjqyAeBsd7osYHUJg95n23FIkqhs3Pjvxh5G1WIzOIJ/5Bw+8yTxboljr"
        "FLtjqsXSj2bS+j/RrPAMUkzlM7s74Dtm3hsEQU43OrnPTxRnqkjtTYoOAFPhcOYo0vuli92ttULpsDCfuQbgQ05gItU4d/Sx"
        "0XKQH5hvcL3jhdLK9kHI6cNT+exyEWeRPLDZXtf1EaJPTBYrT70YpPfyvGixFIlULnN2mM9UW1ghDob6L0kN9R86x3ovzGVO"
        "Sw33K7lL5oAWZrio1dG1VjN1bpNcgo5UPrs8yGV/GQ71K7VoQEE+uzEcypz2Uiff+RLfF2iOzOf7Xwvq7yicQN9MsYOE35C8"
        "GoxuqSa3rMRjmErlM7tL3LlaLN3cBDi9r6lpyxMo4Pk1vgULgi5/Yh/P7CgBx5rx1TBCkatKuihm/B+Thcqa2YNYf04GoK3z"
        "0pz/GcocQOFvCB5L30IIUOwE6WGADwC6D+DjNEaQe9bBG3Fe1OFNoYe+l42lPkp7gdyT0D6g7UqPgABFbi0MP6LTj8aL5cfa"
        "zfElv/CEl+/lKwcA3Tv37+YSblnzJSi9np4XbPV6lBMkOQiNZlGUHSQJm244EHAOLnYbAdxC2jVePHVDC9O3vyfk8DJIEH+C"
        "9xBnLta1qC/HmEtNXCrTrhAXUlgoKpxZLziSdQEFQmtEPkrqfk5MPdAaxcfLTTj+xG9pW5tpzMbgTOfT6cg6O7fyko2Jxui6"
        "0ZE51j9vIv3l/Pw/Mp59ln+YIogAAAAASUVORK5CYII="
    ),
    "icon_light_32": (
        "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"
        "Xpeb6vp3mFM8jWgyTtqyeGbfK7xzpIaa5k/49ORRSvMn8sM53+F0tJeP2xqIJRPkBrP4076/Mzm3kCWl11PX3sCtf34Qv+5j"
        "f1M9k3MLGZ99CW817CPgHtoFgxIowO10cfR0G/MvnUl+Zi6Pv/X0QB2MpT8Z5dGFP+JkuItk2uTh6if53ZKfsnHvVjI9QcZk"
        "jMSyLR55bQNPLq3Esi027N5Ka+9J1iy+nw9aPuEfB3YR9PiHdIEcmhnPtuKj25/ijhmLKMrOp623gxnjS5hWMIVtdTvY/UUt"
        "f9z1HCuuWcqOhn+y6PJrealuJ7OKSnFqTm4pvZ47tzxCPGXQ0HGM6yZexaTc8fx+57NkeoPYtnXez2gwkChAd7ho6T5B0krx"
        "uyU/ZVvd2zR0HEN3unBqDja++wL3zv0ucdOg/cwpxmfnkRMcwV/3V1Pb9hm3T7+RmJlg7ZtPs+CyOTx5ayXff/YR2s+cwu3U"
        "UUPzvtIy5havGs6CT/fyXuPHZPlCrFn8AFtqXqO5+wT/bDrI3bO/Q9HIPA62H+HB+XfxRWcriVSS3GA2z3+0nfrjR9j+2fv8"
        "cHYFf7jlZ9zz/KO831hHyBvAUvZ5mU8UVJZHEcI3PBdqUtId7ePOmYt5cN6dbKl5nS0fvIZSiu5YH3/+3iqOdR3ndKSXlw/s"
        "xK976Qh3UZidx8ML7qYwO4+fvLiGuvbDjPBmkB5GPUKAUjGR/4vyXdKlXavMtD08GTukRnesj4k543io/C4m5ozjw5ZPae45"
        "QcSIc6SzGTOdJujxMWV0MbOLppKXmcP2Q+/z5O7/JpkyCbh95x+ulCVcDmmb1rsib2X5DQ639qZt2mlQ2vCA6pAacdMgbia4"
        "bMwEFlw2m5IxEwh5g+gOJ5qUmOk0bb0d7GmsZdfnNXT29xDyBtGExB5OOygQlnRJR9qwFnyt0exsPBfEzSQxM44mJD7di0tz"
        "olDETYOEaaBJjYDbi1NzYg2/9cVGMyoqtPCfXn8jWDY2R+qOq9CkuNCcoJTCqTnw6148Lh3J2dspFC6Hc3BdDOTKCw6nToeQ"
        "DinshLm5bc3Z4VSjoQGqqmT4sb+8kTG7+CMl1CgUIxHCdc4oOATI//m4EGIwXp27fuHxnAiCvVj8R9vjb6+jqkqyaZP6X0SQ"
        "iZA8v18HAAAAAElFTkSuQmCC"
    ),
    "icon_light_128": (
        "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"
    ),
    "icon_dark_32": (
        "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"
    ),
    "icon_dark_128": (
        "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"
    ),
}


# --------------------------------------------------------------------------
# LOOK AND FEEL - light and night themes, rounded widgets, icons
# --------------------------------------------------------------------------
THEMES = {
    "light": dict(
        bg="#F4F5F3", surface="#FFFFFF", surface2="#F7F8F6", seg="#E7E9E5", seg_on="#FFFFFF",
        border="#E1E4DF", line="#EEF0EC", field_border="#D7DBD5", text="#1A1C1A", muted="#5A615B",
        subtle="#4F5650", accent="#1E7A46", accent_hover="#186A3C", on_accent="#FFFFFF",
        accent_soft="#E4F2EA", accent_soft_text="#155C34", chip_border="#CFE3D7",
        dark_btn="#1A1C1A", dark_btn_hover="#333733", on_dark_btn="#FFFFFF",
        warn_soft="#FFF6E5", warn_text="#7A4A00", rec_soft="#FDF0EE", rec_border="#F0C9C4",
        rec_text="#A3261A", rec_dot="#C8372A", switch_off="#C9CEC7", knob="#FFFFFF",
        meter_off="#CDD2CC", hover="#EEF0EC", select="#E4F2EA", disabled="#A7ADA6"),
    "dark": dict(
        bg="#111312", surface="#1A1D1B", surface2="#222624", seg="#1A1D1B", seg_on="#2A2F2C",
        border="#2A2F2C", line="#242826", field_border="#2F3531", text="#E8EBE9", muted="#A9B1AC",
        subtle="#A9B1AC", accent="#3FBF78", accent_hover="#52CB88", on_accent="#0B1F13",
        accent_soft="#1C3326", accent_soft_text="#8BE0AF", chip_border="#2D5A3F",
        dark_btn="#E8EBE9", dark_btn_hover="#FFFFFF", on_dark_btn="#111312",
        warn_soft="#3A2E14", warn_text="#F2C879", rec_soft="#3A1E1B", rec_border="#5A2B26",
        rec_text="#F4A79E", rec_dot="#E5564A", switch_off="#3A403C", knob="#C9CFCB",
        meter_off="#343A36", hover="#262A28", select="#1C3326", disabled="#5E6661"),
}

# Windows' own icon font (Segoe Fluent Icons on Windows 11, Segoe MDL2 Assets on Windows 10).
# Second value: what to show where neither font exists ("" = no icon).
ICONS = {
    "mic": (0xE720, ""), "stop": (0xE71A, "■"), "settings": (0xE713, ""), "training": (0xE7BE, ""),
    "bolt": (0xE945, ""), "send": (0xE724, "→"), "close": (0xE711, "✕"), "undo": (0xE7A7, "↶"),
    "monitor": (0xE7F4, ""), "search": (0xE721, ""), "down": (0xE70D, "˅"), "up": (0xE70E, "˄"),
    "left": (0xE76B, "‹"), "right": (0xE76C, "›"), "arrow_r": (0xE72A, "→"),
    "arrow_l": (0xE72B, "←"), "check": (0xE8FB, "✓"), "upload": (0xE898, ""),
    "refresh": (0xE72C, "↻"), "list": (0xE8FD, ""), "edit": (0xE70F, ""), "moon": (0xE708, "☾"),
    "sun": (0xE706, "☀"), "download": (0xE896, ""), "spark": (0xE945, ""),
    "help": (0xE897, "?"), "info": (0xE946, "i"), "folder": (0xE8B7, ""), "keyboard": (0xE92E, ""),
}


def enable_sharp_text():
    """Windows: draw text at the screen's real resolution instead of a blurry stretched copy."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class UI:
    """Shared theme, fonts and screen scaling. Every widget registers a restyle function,
    so switching between light and night mode repaints everything at once."""

    ZOOMS = {"compact": 0.8, "normal": 0.9, "large": 1.0}

    def __init__(self, tk, ttk, root, theme="light", size="auto"):
        import tkinter.font as tkfont
        self.tk, self.ttk, self.root, self.tkfont = tk, ttk, root, tkfont
        self.name = theme if theme in THEMES else "light"
        self.c = THEMES[self.name]
        self.callbacks = []
        self.buttons = {}          # text -> Button (handy for keyboard shortcuts and tests)
        self.wraps = []            # (label, preferred wrap width) - rewrapped when the window changes size
        try:
            dpi = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
        except Exception:
            dpi = 1.0
        try:
            self.screen_h = int(root.winfo_screenheight())
            self.screen_w = int(root.winfo_screenwidth())
        except Exception:
            self.screen_h, self.screen_w = 1080, 1920
        if size not in self.ZOOMS:   # auto: smaller on laptop-sized screens
            size = "compact" if self.screen_h / dpi < 860 else "normal"
        self.size_name, self.zoom = size, self.ZOOMS[size]
        self.dpi, self.scale = dpi, dpi * self.zoom
        try:
            fams = set(tkfont.families(root))
        except Exception:
            fams = set()
        pick = lambda names, default: next((f for f in names if f in fams), default)
        self.family = pick(("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Arial"), "TkDefaultFont")
        self.display = pick(("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"), self.family)
        self.icon_family = pick(("Segoe Fluent Icons", "Segoe MDL2 Assets"), None)
        self.mono = pick(("Cascadia Mono", "Consolas", "Menlo", "Courier New"), "TkFixedFont")
        self._fonts = {}
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.register(self._style_ttk)

    # ---- sizes and fonts
    def px(self, n):
        return int(round(n * self.scale))

    def font(self, size=10, weight="normal", display=False, mono=False, icon=False):
        fam = self.icon_family if icon else self.mono if mono else self.display if display else self.family
        size = max(7, int(round(size * self.zoom)))
        key = (fam, size, weight)
        if key not in self._fonts:
            try:
                self._fonts[key] = self.tkfont.Font(root=self.root, family=fam, size=size, weight=weight)
            except Exception:
                self._fonts[key] = (fam, size, weight)
        return self._fonts[key]

    def measure(self, text, font):
        try:
            return int(font.measure(text))
        except Exception:
            return len(text) * self.px(7)

    def icon(self, name):
        code, fallback = ICONS.get(name, (0, ""))
        return chr(code) if (self.icon_family and code) else fallback

    # ---- theming
    def register(self, fn):
        self.callbacks.append(fn)
        try:
            fn()
        except self.tk.TclError:
            pass
        return fn

    def set_theme(self, name):
        self.name = name if name in THEMES else "light"
        self.c = THEMES[self.name]
        alive = []
        for fn in self.callbacks:
            try:
                fn()
                alive.append(fn)
            except self.tk.TclError:
                pass  # widget was destroyed
        self.callbacks = alive

    def themed(self, widget, **opts):
        """Keep widget options tied to theme colours, e.g. themed(lbl, bg="surface", fg="muted")."""
        widget._roots_spec = dict(opts)
        self.register(lambda: widget.configure(**{k: self.c[v] for k, v in widget._roots_spec.items()}))
        return widget

    def retheme(self, widget, **opts):
        widget._roots_spec.update(opts)
        widget.configure(**{k: self.c[v] for k, v in opts.items()})

    def _style_ttk(self):
        c, s = self.c, self.style
        s.configure("TCombobox", fieldbackground=c["surface"], background=c["surface2"], foreground=c["text"],
                    arrowcolor=c["muted"], bordercolor=c["field_border"], lightcolor=c["surface"],
                    darkcolor=c["surface"], selectbackground=c["surface"], selectforeground=c["text"],
                    padding=self.px(6))
        s.map("TCombobox", fieldbackground=[("readonly", c["surface"])], foreground=[("readonly", c["text"])],
              bordercolor=[("focus", c["accent"])], arrowcolor=[("active", c["text"])])
        s.configure("Roots.Horizontal.TProgressbar", troughcolor=c["seg"], background=c["accent"],
                    bordercolor=c["seg"], lightcolor=c["accent"], darkcolor=c["accent"], thickness=self.px(6))
        for opt, tok in (("background", "surface"), ("foreground", "text"),
                         ("selectBackground", "select"), ("selectForeground", "text")):
            self.root.option_add(f"*TCombobox*Listbox.{opt}", c[tok])

    # ---- simple themed widgets
    def frame(self, parent, bg="surface"):
        return self.themed(self.tk.Frame(parent, bd=0, highlightthickness=0), bg=bg)

    def label(self, parent, text="", textvariable=None, size=10, weight="normal", fg="text", bg="surface",
              wrap=0, display=False, mono=False, icon=False, anchor="w", justify="left"):
        w = self.tk.Label(parent, text=text, bd=0, padx=0, pady=0, anchor=anchor, justify=justify,
                          font=self.font(size, weight, display, mono, icon))
        if textvariable is not None:
            w.configure(textvariable=textvariable)
        if wrap:
            w.configure(wraplength=self.px(wrap))
            self.wraps.append((w, wrap))
        return self.themed(w, bg=bg, fg=fg)

    def fit_wraps(self, avail):
        """Rewrap text to the window width so nothing is cut off on narrow screens."""
        keep = []
        for w, pref in self.wraps:
            try:
                w.configure(wraplength=max(self.px(120), min(self.px(pref), avail)))
                keep.append((w, pref))
            except self.tk.TclError:
                pass
        self.wraps = keep

    def listbox(self, parent, height=4, bg="surface"):
        w = self.tk.Listbox(parent, height=height, bd=0, highlightthickness=0, activestyle="none",
                            exportselection=False, font=self.font(10), selectborderwidth=0)
        return self.themed(w, bg=bg, fg="text", selectbackground="select", selectforeground="text")

    def text(self, parent, height=6, bg="surface", mono=True):
        w = self.tk.Text(parent, height=height, bd=0, highlightthickness=0, wrap="word",
                         font=self.font(9, mono=mono), padx=self.px(8), pady=self.px(6))
        return self.themed(w, bg=bg, fg="text", insertbackground="text", selectbackground="select")


class _Wrapped:
    """Lets our canvas-drawn widgets be packed/gridded like normal tk widgets."""
    w = None

    def pack(self, **kw):
        self.w.pack(**kw)
        return self

    def grid(self, **kw):
        self.w.grid(**kw)
        return self

    def place(self, **kw):
        self.w.place(**kw)
        return self

    def __getattr__(self, name):
        return getattr(self.w, name)


class Card(_Wrapped):
    """A rounded panel. Put children in `.body`."""

    def __init__(self, ui, parent, fill="surface", border="border", outer="bg", radius=12, pad=14,
                 padx=None, pady=None):
        self.ui, self.fill, self.border, self.outer, self.r = ui, fill, border, outer, radius
        self.padx = ui.px(pad if padx is None else padx)
        self.pady = ui.px(pad if pady is None else pady)
        self.w = ui.tk.Canvas(parent, highlightthickness=0, bd=0, height=ui.px(24))
        self.body = ui.tk.Frame(self.w, bd=0, highlightthickness=0)
        self.win = self.w.create_window(self.padx, self.pady, window=self.body, anchor="nw")
        self.w.bind("<Configure>", self._redraw, add="+")
        self.body.bind("<Configure>", self._fit, add="+")
        ui.register(self.restyle)

    def _fit(self, event=None):
        h = int(self.body.winfo_reqheight()) + 2 * self.pady
        try:
            cur = int(float(self.w.cget("height")))
        except (ValueError, TypeError):
            cur = -1
        if cur != h:
            self.w.configure(height=h)

    def _redraw(self, event=None):
        w, h = int(self.w.winfo_width()), int(self.w.winfo_height())
        if w < 4 or h < 4:
            return
        self.w.itemconfigure(self.win, width=max(1, w - 2 * self.padx))
        self.w.delete("shape")
        c = self.ui.c
        round_rect(self.w, 1, 1, w - 1, h - 1, self.ui.px(self.r), fill=c[self.fill],
                   outline=c[self.border] if self.border else c[self.fill], width=1, tags="shape")
        self.w.tag_lower("shape")

    def restyle(self):
        self.w.configure(bg=self.ui.c[self.outer])
        self.body.configure(bg=self.ui.c[self.fill])
        self._redraw()

    def set_look(self, fill=None, border=None):
        if fill:
            self.fill = fill
            self.body.configure(bg=self.ui.c[fill])
        if border:
            self.border = border
        self._redraw()


class Button(_Wrapped):
    """Rounded button with an optional icon. configure(text=, icon=, state=, command=, kind=)."""
    KINDS = {   # fill, text, border, hover fill
        "primary": ("accent", "on_accent", None, "accent_hover"),
        "secondary": ("surface2", "text", "border", "hover"),
        "ghost": (None, "subtle", "border", "hover"),
        "dark": ("dark_btn", "on_dark_btn", None, "dark_btn_hover"),
        "chip": ("surface", "text", "border", "hover"),
        "chip_accent": ("accent_soft", "accent_soft_text", "chip_border", "select"),
        "record": ("rec_soft", "rec_text", "rec_border", "rec_soft"),
        "seg_on": ("seg_on", "text", None, "seg_on"),
        "seg_off": ("seg", "subtle", None, "hover"),
        "section": ("surface", "text", "border", "hover"),
    }

    def __init__(self, ui, parent, text="", icon=None, kind="secondary", command=None, height=44, radius=10,
                 size=10, weight="normal", outer="surface", width=None, dot=False, icon_after=False, align="center"):
        self.ui, self.text, self.icon_name, self.kind, self.command = ui, text, icon, kind, command
        self.align = align
        self.h, self.r, self.outer, self.dot, self.icon_after = ui.px(height), radius, outer, dot, icon_after
        self.state, self.hover = "normal", False
        self.fnt = ui.font(size, weight)
        self.ifnt = ui.font(size + 1, icon=True) if ui.icon_family else self.fnt
        self.w = ui.tk.Canvas(parent, highlightthickness=0, bd=0, height=self.h, cursor="hand2", takefocus=1)
        self.fixed_width = ui.px(width) if width else None
        self.w.configure(width=self.fixed_width or self.natural_width())
        for seq, fn in (("<Configure>", self._draw), ("<Enter>", lambda e: self._hover(True)),
                        ("<Leave>", lambda e: self._hover(False)), ("<ButtonRelease-1>", self._click),
                        ("<Return>", self._click), ("<space>", self._click)):
            self.w.bind(seq, fn, add="+")
        if text:
            ui.buttons[text] = self
        ui.register(self._draw)

    def natural_width(self):
        ui, gap = self.ui, self.ui.px(7)
        if not self.text:
            return self.h          # icon-only buttons are square
        icon = ui.icon(self.icon_name) if self.icon_name else ""
        w = ui.measure(self.text, self.fnt)
        if icon:
            w += ui.measure(icon, self.ifnt) + gap
        if self.dot:
            w += ui.px(10) + gap
        return w + 2 * ui.px(14)

    def _hover(self, on):
        self.hover = on
        self._draw()

    def _click(self, event=None):
        if self.state != "disabled" and self.command:
            self.command()

    def invoke(self):
        self._click()

    def configure(self, **kw):
        for key in ("text", "icon", "state", "command", "kind"):
            if key in kw:
                setattr(self, {"icon": "icon_name"}.get(key, key), kw.pop(key))
        if kw:
            self.w.configure(**kw)
        if not self.fixed_width:
            self.w.configure(width=self.natural_width())
        self._draw()

    config = configure

    def cget(self, key):
        return {"text": self.text, "state": self.state}.get(key) if key in ("text", "state") else self.w.cget(key)

    def _draw(self, event=None):
        ui, c = self.ui, self.ui.c
        w, h = int(self.w.winfo_width()), int(self.w.winfo_height())
        if w < 4:
            w = self.fixed_width or self.natural_width()
        if h < 4:
            h = self.h
        fill_t, text_t, border_t, hover_t = self.KINDS.get(self.kind, self.KINDS["secondary"])
        outer = c[self.outer]
        fill = c[fill_t] if fill_t else outer
        if self.hover and self.state != "disabled" and hover_t:
            fill = c[hover_t]
        fg = c[text_t] if self.state != "disabled" else c["disabled"]
        if self.state == "disabled" and self.kind in ("primary", "dark"):
            fill, fg = c["seg"], c["disabled"]
        self.w.configure(bg=outer)
        self.w.delete("all")
        round_rect(self.w, 1, 1, w - 1, h - 1, ui.px(self.r), fill=fill,
                   outline=c[border_t] if border_t else fill, width=1)
        icon = ui.icon(self.icon_name) if self.icon_name else ""
        gap = ui.px(7)
        parts = []
        if self.dot:
            parts.append(("dot", ui.px(10)))
        if icon and not self.icon_after:
            parts.append(("icon", ui.measure(icon, self.ifnt)))
        if self.text:
            parts.append(("text", ui.measure(self.text, self.fnt)))
        if icon and self.icon_after:
            parts.append(("icon", ui.measure(icon, self.ifnt)))
        if self.align == "split":       # title on the left, icon on the right (fold-out headers)
            y = h / 2
            self.w.create_text(ui.px(16), y, text=self.text, font=self.fnt, fill=fg, anchor="w")
            if icon:
                self.w.create_text(w - ui.px(16), y, text=icon, font=self.ifnt, fill=c["muted"], anchor="e")
            return
        total = sum(p[1] for p in parts) + gap * max(0, len(parts) - 1)
        x, y = (w - total) / 2, h / 2
        for kind, width in parts:
            if kind == "dot":
                r = width / 2
                self.w.create_oval(x, y - r, x + width, y + r, fill=c["rec_dot"], outline="")
            elif kind == "icon":
                self.w.create_text(x, y, text=icon, font=self.ifnt, fill=fg, anchor="w")
            else:
                self.w.create_text(x, y, text=self.text, font=self.fnt, fill=fg, anchor="w")
            x += width + gap


class Switch(_Wrapped):
    """On/off switch bound to a BooleanVar."""

    def __init__(self, ui, parent, variable, command=None, outer="surface"):
        self.ui, self.var, self.command, self.outer = ui, variable, command, outer
        self.w = ui.tk.Canvas(parent, width=ui.px(46), height=ui.px(26), highlightthickness=0, bd=0,
                              cursor="hand2", takefocus=1)
        self.w.bind("<ButtonRelease-1>", self.toggle, add="+")
        self.w.bind("<space>", self.toggle, add="+")
        try:
            variable.trace_add("write", lambda *a: self._draw())
        except Exception:
            pass
        ui.register(self._draw)

    def toggle(self, event=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self, *args):
        ui, c, on = self.ui, self.ui.c, bool(self.var.get())
        w, h = ui.px(46), ui.px(26)
        self.w.configure(bg=c[self.outer])
        self.w.delete("all")
        round_rect(self.w, 0, 0, w, h, h / 2, fill=c["accent"] if on else c["switch_off"], outline="")
        k, m = ui.px(20), ui.px(3)
        x = w - k - m if on else m
        self.w.create_oval(x, m, x + k, m + k, fill=c["on_accent"] if on else c["knob"], outline="")


class Pill(_Wrapped):
    """Small rounded status badge with a coloured dot."""
    TONES = {"live": ("accent_soft", "accent_soft_text", "accent"), "idle": ("seg", "subtle", "muted"),
             "busy": ("warn_soft", "warn_text", "warn_text"), "error": ("rec_soft", "rec_text", "rec_dot")}

    def __init__(self, ui, parent, outer="bg", max_chars=34):
        self.ui, self.outer, self.max_chars = ui, outer, max_chars
        self.text, self.tone = "Stopped", "idle"
        self.fnt = ui.font(9, "bold")
        self.w = ui.tk.Canvas(parent, highlightthickness=0, bd=0, height=ui.px(26))
        ui.register(self._draw)

    def set(self, text, tone=None):
        self.text = text if len(text) <= self.max_chars else text[: self.max_chars - 1] + "…"
        self.tone = tone or self.tone
        self._draw()

    def _draw(self):
        ui, c = self.ui, self.ui.c
        bg_t, fg_t, dot_t = self.TONES.get(self.tone, self.TONES["idle"])
        pad, dot = ui.px(10), ui.px(7)
        w = ui.measure(self.text, self.fnt) + 2 * pad + dot + ui.px(6)
        h = ui.px(26)
        self.w.configure(width=w, bg=c[self.outer])
        self.w.delete("all")
        round_rect(self.w, 0, 0, w, h, h / 2, fill=c[bg_t], outline="")
        self.w.create_oval(pad, (h - dot) / 2, pad + dot, (h + dot) / 2, fill=c[dot_t], outline="")
        self.w.create_text(pad + dot + ui.px(6), h / 2, text=self.text, font=self.fnt, fill=c[fg_t], anchor="w")


class LevelMeter(_Wrapped):
    """Five-bar microphone level indicator."""

    def __init__(self, ui, parent, outer="surface"):
        self.ui, self.outer, self.level = ui, outer, 0.0
        self.w = ui.tk.Canvas(parent, width=ui.px(56), height=ui.px(28), highlightthickness=0, bd=0)
        ui.register(self._draw)

    def set(self, level):
        self.level = max(0.0, min(1.0, float(level)))
        self._draw()

    def _draw(self):
        ui, c = self.ui, self.ui.c
        self.w.configure(bg=c[self.outer])
        self.w.delete("all")
        bw, gap, h = ui.px(6), ui.px(4), ui.px(28)
        shape = (0.3, 0.6, 1.0, 0.55, 0.28)
        lit = round(self.level * 5)
        for i, f in enumerate(shape):
            bh = max(ui.px(5), h * f)
            x = i * (bw + gap)
            round_rect(self.w, x, h - bh, x + bw, h, bw / 2, fill=c["accent"] if i < lit else c["meter_off"], outline="")


class InputBox(Card):
    """Rounded text field with an optional icon and placeholder. The tk Entry is `.entry`."""

    def __init__(self, ui, parent, variable, placeholder="", icon=None, outer="bg", size=11, height=46):
        super().__init__(ui, parent, fill="surface", border="field_border", outer=outer, radius=11,
                         padx=12, pady=max(6, (height - 26) // 2))
        self.var = variable
        if icon and ui.icon(icon):
            ui.label(self.body, text=ui.icon(icon), icon=bool(ui.icon_family), size=11, fg="muted").pack(
                side="left", padx=(0, ui.px(8)))
        self.entry = ui.tk.Entry(self.body, textvariable=variable, bd=0, highlightthickness=0,
                                 font=ui.font(size), relief="flat")
        ui.themed(self.entry, bg="surface", fg="text", insertbackground="text",
                  selectbackground="select", selectforeground="text", disabledbackground="surface")
        self.entry.pack(side="left", fill="x", expand=True)
        self.ph = ui.label(self.body, text=placeholder, size=size, fg="muted") if placeholder else None
        if self.ph:
            self.ph.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: (self.set_look(border="accent"), self._placeholder()), add="+")
        self.entry.bind("<FocusOut>", lambda e: (self.set_look(border="field_border"), self._placeholder()), add="+")
        try:
            variable.trace_add("write", lambda *a: self._placeholder())
        except Exception:
            pass
        self._placeholder()

    def _placeholder(self):
        if not self.ph:
            return
        if self.var.get():
            self.ph.place_forget()
        else:
            self.ph.place(in_=self.entry, x=0, rely=0.5, anchor="w")

    def bind(self, seq, fn, add="+"):
        return self.entry.bind(seq, fn, add=add)


class Flow(_Wrapped):
    """Lays children out left to right, wrapping onto new lines (for suggestion chips)."""

    def __init__(self, ui, parent, bg="bg", gap=8):
        self.ui, self.gap, self.items = ui, ui.px(gap), []
        self.w = ui.frame(parent, bg=bg)
        self.w.configure(height=1)
        self.w.bind("<Configure>", lambda e: self.relayout(), add="+")

    def clear(self):
        for it in self.items:
            it.destroy()
        self.items = []
        self.relayout()

    def add(self, widget):
        self.items.append(widget)
        self.relayout()

    def relayout(self):
        avail = max(int(self.w.winfo_width()), self.ui.px(200))
        x = y = row_h = 0
        for it in self.items:
            iw, ih = int(float(it.cget("width"))), int(float(it.cget("height")))
            if x and x + iw > avail:
                x, y = 0, y + row_h + self.gap
                row_h = 0
            it.place(x=x, y=y)
            x += iw + self.gap
            row_h = max(row_h, ih)
        self.w.configure(height=max(1, y + row_h))


class ScrollPage(_Wrapped):
    """A page that scrolls with the mouse wheel when it is taller than the window."""

    def __init__(self, ui, parent, bg="bg", pad=22):
        self.ui = ui
        self.w = ui.tk.Canvas(parent, highlightthickness=0, bd=0)
        ui.themed(self.w, bg=bg)
        self.body = ui.frame(self.w, bg=bg)
        self.pad = ui.px(pad)
        self.win = self.w.create_window(self.pad, ui.px(4), window=self.body, anchor="nw")
        self.w.bind("<Configure>", self._resize, add="+")
        self.body.bind("<Configure>", self._region, add="+")
        self.w.bind("<Enter>", lambda e: self.w.bind_all("<MouseWheel>", self._wheel), add="+")
        self.w.bind("<Leave>", lambda e: self.w.unbind_all("<MouseWheel>"), add="+")

    def _resize(self, event=None):
        width = int(self.w.winfo_width())
        self.w.itemconfigure(self.win, width=max(1, width - 2 * self.pad))
        self.ui.fit_wraps(width - 2 * self.pad - self.ui.px(56))
        self._region()

    def _region(self, event=None):
        h = int(self.body.winfo_reqheight()) + self.ui.px(24)
        self.w.configure(scrollregion=(0, 0, int(self.w.winfo_width()), h))

    def _wheel(self, event):
        if int(self.body.winfo_reqheight()) + self.ui.px(24) > int(self.w.winfo_height()):
            self.w.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")


class Section(_Wrapped):
    """A fold-out panel: click the header to show or hide what is inside. Sections in the same
    group work like an accordion - opening one closes the others, so everything fits small screens."""

    def __init__(self, ui, parent, title, subtitle=None, open_=False, group=None):
        self.ui, self.group, self.is_open = ui, group, False
        self.w = ui.frame(parent, bg="bg")
        self.head = Button(ui, self.w, text=title, icon="down", icon_after=True, kind="section", outer="bg",
                           height=46, radius=11, size=10, weight="bold", align="split", command=self.toggle)
        self.head.pack(fill="x")
        self.card = Card(ui, self.w, pad=16)
        self.body = self.card.body
        if subtitle:
            ui.label(self.body, text=subtitle, size=9, fg="muted", wrap=440).pack(anchor="w", pady=(0, ui.px(6)))
        if group is not None:
            group.append(self)
        if open_:
            self.open()

    def open(self):
        for other in (self.group or []):
            if other is not self and other.is_open:
                other.close()
        self.card.pack(fill="x", pady=(self.ui.px(6), 0))
        self.is_open = True
        self.head.configure(icon="up")

    def close(self):
        self.card.pack_forget()
        self.is_open = False
        self.head.configure(icon="down")

    def toggle(self):
        self.close() if self.is_open else self.open()


def logo_image(ui, kind):
    """PhotoImage of the embedded Roots logo. kind: 'emblem' (follows the theme) or 'icon'."""
    if kind == "emblem":
        size = 32 if ui.scale < 1.25 else 48 if ui.scale < 1.75 else 64
        key = f"emblem_{'white' if ui.name == 'light' else 'black'}_{size}"
    else:
        key = kind
    try:
        return ui.tk.PhotoImage(master=ui.root, data="".join(LOGO_PNG[key]))
    except Exception:
        return None


class LogoBadge(_Wrapped):
    """Green rounded square with the Roots emblem: white in light mode, black in night mode."""

    def __init__(self, ui, parent, outer="bg", size=40):
        self.ui, self.outer, self.size = ui, outer, ui.px(size)
        self.w = ui.tk.Canvas(parent, width=self.size, height=self.size, highlightthickness=0, bd=0)
        self.img = None
        ui.register(self._draw)

    def _draw(self):
        ui, c, s = self.ui, self.ui.c, self.size
        self.w.configure(bg=c[self.outer])
        self.w.delete("all")
        round_rect(self.w, 0, 0, s, s, ui.px(10), fill=c["accent"], outline="")
        self.img = logo_image(ui, "emblem")
        if self.img is not None:
            self.w.create_image(s / 2, s / 2, image=self.img)


def section_title(ui, parent, text, bg="bg"):
    return ui.label(parent, text=text, size=9, weight="bold", fg="subtle", bg=bg)


def setting_row(ui, parent, title, hint=None, bg="surface"):
    """A settings line: title (and hint) on the left, a control on the right. Returns the right frame."""
    row = ui.frame(parent, bg=bg)
    row.pack(fill="x", pady=ui.px(6))
    left = ui.frame(row, bg=bg)
    left.pack(side="left", fill="x", expand=True)
    ui.label(left, text=title, size=10, weight="bold", bg=bg).pack(anchor="w")
    if hint:
        ui.label(left, text=hint, size=9, fg="muted", bg=bg, wrap=230).pack(anchor="w")
    right = ui.frame(row, bg=bg)
    right.pack(side="right", padx=(ui.px(12), 0))
    return right


def themed_dialog(ui, title):
    win = ui.tk.Toplevel(ui.root)
    win.title(title)
    win.transient(ui.root)
    ui.themed(win, bg="bg")
    body = ui.frame(win, bg="bg")
    body.pack(fill="both", expand=True, padx=ui.px(18), pady=ui.px(16))
    return win, body


class TrainingTab:
    """Voice Training screen. Heavy work runs in a background thread and reports back
    through its own queue, so the window never freezes."""

    def __init__(self, ui, parent, root, get_settings, is_listening, log, filedialog, messagebox):
        self.ui, self.root = ui, root
        self.tk = ui.tk
        self.get_settings, self.is_listening, self.log = get_settings, is_listening, log
        self.filedialog, self.messagebox = filedialog, messagebox
        self.prompts = training_prompts()
        self.samples = load_samples()
        self.idx = 0
        self.capture = None          # None, "record" (practice prompt) or "listen" (listen & correct)
        self.stream = None
        self.frames = []
        self.t0 = 0.0
        self.busy = False
        self.finish_pending = False
        self.heard_audio = None
        self.heard_text = ""
        self.cancel = threading.Event()
        self.tq = queue.Queue()
        self._build(parent)
        self._goto_first_unrecorded()
        self.refresh()
        self.root.after(200, self._poll)

    @property
    def recording(self):
        return self.capture is not None

    # ---------------- layout ----------------
    def _build(self, parent):
        ui, tk, px = self.ui, self.tk, self.ui.px
        gap = px(14)

        # ---- Listen & correct
        lc = Card(ui, parent, pad=16).pack(fill="x", pady=(0, gap))
        b = lc.body
        top = ui.frame(b)
        top.pack(fill="x")
        txt = ui.frame(top)
        txt.pack(side="left", fill="x", expand=True)
        ui.label(txt, text="Listen & correct", size=12, weight="bold").pack(anchor="w")
        ui.label(txt, text="Say anything, then fix the words it got wrong", size=9, fg="muted").pack(anchor="w")
        self.listen_btn = Button(ui, top, text="Listen", icon="mic", kind="primary", height=40, radius=20,
                                 weight="bold", command=self.toggle_listen).pack(side="right")
        self.listen_var = tk.StringVar(value="Press Listen, say a reference or command, then press Stop.")
        ui.label(b, textvariable=self.listen_var, size=9, fg="muted", wrap=440).pack(anchor="w", pady=(px(8), px(4)))
        ui.label(b, text="What it heard (edit if wrong)", size=9, weight="bold", fg="subtle").pack(anchor="w")
        self.heard_var = tk.StringVar()
        self.heard_box = InputBox(ui, b, self.heard_var, outer="surface", size=12).pack(fill="x", pady=(px(6), px(8)))
        self.heard_entry = self.heard_box.entry
        self.heard_box.bind("<KeyRelease>", self._update_detect)
        self.heard_box.bind("<Return>", lambda e: self.save_correction_click())
        info = ui.frame(b)
        info.pack(fill="x")
        self.sound_var = tk.StringVar(value="")
        self.sound_chip = ui.label(info, textvariable=self.sound_var, size=9, fg="warn_text", bg="warn_soft")
        self.sound_chip.configure(padx=px(8), pady=px(4))
        self.detect_var = tk.StringVar(value="")
        self.detect_lbl = ui.label(info, textvariable=self.detect_var, size=9, weight="bold", fg="accent_soft_text")
        self.detect_lbl.pack(side="left")
        row = ui.frame(b)
        row.pack(fill="x", pady=(px(10), 0))
        row.columnconfigure(0, weight=2)
        row.columnconfigure(1, weight=1)
        self.save_corr_btn = Button(ui, row, text="Save correction", kind="dark", weight="bold",
                                    command=self.save_correction_click).grid(row=0, column=0, sticky="ew", padx=(0, px(8)))
        self.right_btn = Button(ui, row, text="It was right", kind="secondary",
                                command=self.mark_right).grid(row=0, column=1, sticky="ew")
        self.save_corr_btn.configure(state="disabled")
        self.right_btn.configure(state="disabled")

        # ---- Practice prompts
        pc = Card(ui, parent, pad=16).pack(fill="x", pady=(0, gap))
        b = pc.body
        top = ui.frame(b)
        top.pack(fill="x")
        ui.label(top, text="Practice prompts", size=12, weight="bold").pack(side="left")
        self.edit_btn = Button(ui, top, text="Edit", icon="edit", kind="secondary", height=30, radius=8, size=9,
                               command=self.edit_prompts).pack(side="right")
        self.prompt_var = tk.StringVar()
        ui.label(b, textvariable=self.prompt_var, size=13, weight="bold", wrap=440).pack(anchor="w", pady=(px(8), px(6)))
        prog = ui.frame(b)
        prog.pack(fill="x")
        self.progress = ui.ttk.Progressbar(prog, maximum=len(self.prompts), style="Roots.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, px(10)))
        self.count_var = tk.StringVar()
        ui.label(prog, textvariable=self.count_var, size=9, fg="muted").pack(side="right")
        nav = ui.frame(b)
        nav.pack(fill="x", pady=(px(10), 0))
        self.prev_btn = Button(ui, nav, icon="left", kind="secondary", command=lambda: self._step(-1)).pack(side="left")
        self.next_btn = Button(ui, nav, icon="right", kind="secondary", command=lambda: self._step(1)).pack(side="right")
        self.rec_btn = Button(ui, nav, text="Record", kind="record", dot=True, weight="bold",
                              command=self.toggle_record).pack(side="left", fill="x", expand=True, padx=px(8))
        self.rec_var = tk.StringVar(value="")
        ui.label(b, textvariable=self.rec_var, size=9, fg="rec_text").pack(anchor="w", pady=(px(4), 0))
        self.finish_btn = Button(ui, b, text="Finish session", kind="ghost", height=40,
                                 command=self.finish_session).pack(fill="x", pady=(px(4), 0))

        # ---- Import
        self.import_btn = Button(ui, parent, text="Import sermon recordings", icon="upload", kind="ghost",
                                 outer="bg", height=46, radius=12, command=self.import_recordings).pack(fill="x")
        ui.label(parent, text=".wav .mp3 .m4a .flac · you approve what it finds", size=9, fg="muted",
                 bg="bg").pack(anchor="w", pady=(px(4), gap))

        # ---- Stats
        stats = ui.frame(parent, bg="bg")
        stats.pack(fill="x", pady=(0, gap))
        self.stat_vars = {}
        for i, (key, title) in enumerate((("corr", "Corrections"), ("learned", "Words learned"), ("sessions", "Sessions"))):
            stats.columnconfigure(i, weight=1, uniform="stats")
            card = Card(ui, stats, pad=12).grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(8), 0))
            var = tk.StringVar(value="0")
            self.stat_vars[key] = var
            ui.label(card.body, textvariable=var, size=16, weight="bold", display=True).pack(anchor="w")
            ui.label(card.body, text=title, size=9, fg="muted").pack(anchor="w")

        # ---- Status + tools
        self.status_var = tk.StringVar()
        ui.label(parent, textvariable=self.status_var, size=9, fg="muted", bg="bg", wrap=460).pack(anchor="w")
        self.work_var = tk.StringVar(value="")
        ui.label(parent, textvariable=self.work_var, size=10, weight="bold", fg="text", bg="bg",
                 wrap=460).pack(anchor="w", pady=(px(2), px(8)))
        tools = ui.frame(parent, bg="bg")
        tools.pack(fill="x")
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)
        self.relearn_btn = Button(ui, tools, text="Re-learn everything", icon="refresh", kind="secondary",
                                  outer="bg", height=42, command=self.relearn).grid(row=0, column=0, sticky="ew", padx=(0, px(8)))
        self.words_btn = Button(ui, tools, text="Learned words", icon="list", kind="secondary", outer="bg",
                                height=42, command=self.manage_words).grid(row=0, column=1, sticky="ew")
        self.cancel_btn = Button(ui, parent, text="Cancel", icon="close", kind="ghost", outer="bg", height=38,
                                 command=self.cancel.set)
        self.busy_widgets = [self.import_btn, self.finish_btn, self.edit_btn, self.relearn_btn,
                             self.words_btn, self.listen_btn, self.rec_btn]
        self.capture_locked = [self.prev_btn, self.next_btn, self.finish_btn, self.import_btn,
                               self.edit_btn, self.relearn_btn, self.words_btn]

    # ---------------- state helpers ----------------
    def _recorded(self):
        return [p for p in self.prompts if p["text"] in self.samples]

    def _corrections_count(self):
        try:
            with open(CORRECTIONS_INDEX, "r", encoding="utf-8") as f:
                return len(json.load(f))
        except (OSError, ValueError):
            return 0

    def refresh(self):
        p = self.prompts[self.idx]
        self.prompt_var.set(p["text"])
        n = len(self._recorded())
        self.count_var.set(f"{n} of {len(self.prompts)}" + ("  ·  this one ✓" if p["text"] in self.samples else ""))
        self.progress["value"] = n
        self.stat_vars["corr"].set(str(self._corrections_count()))
        self.stat_vars["learned"].set(str(len(learned_items())))
        self.stat_vars["sessions"].set(str(count_sessions()))
        self.status_var.set(f"Prompt {self.idx + 1} of {len(self.prompts)}  ·  "
                            f"model: {self.get_settings()['model']}")

    def _step(self, delta):
        if self.recording:
            return
        self.idx = (self.idx + delta) % len(self.prompts)
        self.refresh()

    def _goto_first_unrecorded(self):
        for i, p in enumerate(self.prompts):
            if p["text"] not in self.samples:
                self.idx = i
                return

    def _set_busy(self, busy, text=""):
        self.busy = busy
        for w in self.busy_widgets:
            w.configure(state="disabled" if busy else "normal")
        if busy:
            self.cancel_btn.pack(fill="x", pady=(self.ui.px(8), 0))
        else:
            self.cancel_btn.pack_forget()
        if not busy and not self.heard_text:
            self.save_corr_btn.configure(state="disabled")
            self.right_btn.configure(state="disabled")
        if text:
            self.work_var.set(text)

    # ---------------- microphone ----------------
    def _open_mic(self):
        if self.is_listening():
            self.messagebox.showinfo("RootsVoice", "Stop listening on the Live tab first - the microphone is in use.")
            return False
        try:
            sd = audio_module()
        except AudioUnavailable as e:
            self.messagebox.showerror("RootsVoice", str(e))
            return False
        self.frames = []
        try:
            self.stream, _info = open_microphone(sd, find_device(sd, self.get_settings()["mic"]), self.frames.append)
        except Exception as e:
            self.messagebox.showerror("RootsVoice", f"Could not open the microphone: {e}")
            return False
        self.t0 = time.time()
        return True

    def _close_mic(self):
        import numpy as np
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        return np.concatenate(self.frames).flatten() if self.frames else np.zeros(0, dtype="float32")

    def _lock(self, locked, keep):
        for w in self.capture_locked + [self.listen_btn, self.rec_btn]:
            if w is not keep:
                w.configure(state="disabled" if locked else "normal")

    def _tick(self):
        if self.capture:
            msg = f"● Recording {time.time() - self.t0:0.1f}s – press Stop when done"
            (self.rec_var if self.capture == "record" else self.listen_var).set(msg)
            self.root.after(200, self._tick)

    # ---------------- B. practice prompts ----------------
    def toggle_record(self):
        if self.capture == "record":
            return self._stop_record()
        if self.capture or self.busy or not self._open_mic():
            return
        self.capture = "record"
        self.rec_btn.configure(text="Stop and save")
        self._lock(True, self.rec_btn)
        self._tick()

    def _stop_record(self):
        audio = self._close_mic()
        self.capture = None
        self.rec_btn.configure(text="Record")
        self.rec_var.set("")
        self._lock(False, None)
        if len(audio) < SAMPLE_RATE * 0.6:
            self.messagebox.showinfo("RootsVoice", "That recording was too short - please try again.")
            return
        prompt = self.prompts[self.idx]["text"]
        old = self.samples.get(prompt)
        rel = f"samples/{int(time.time() * 1000)}.wav"
        write_wav(os.path.join(TRAINING_DIR, rel), audio)
        if old:
            try:
                os.remove(os.path.join(TRAINING_DIR, old["file"]))
            except OSError:
                pass
        self.samples[prompt] = {"file": rel}
        save_samples(self.samples)
        self.log(f"Saved training sample {len(self._recorded())}")
        before = self.idx
        self._goto_first_unrecorded()
        if self.idx == before and prompt in self.samples:
            self.messagebox.showinfo("RootsVoice", "All prompts recorded. Press 'Finish session' to learn from them.")
        self.refresh()

    # ---------------- C. listen & correct ----------------
    def toggle_listen(self):
        if self.capture == "listen":
            audio = self._close_mic()
            self.capture = None
            self.listen_btn.configure(text="Listen", icon="mic")
            self._lock(False, None)
            if len(audio) < SAMPLE_RATE * 0.5:
                self.listen_var.set("Too short - press Listen and try again.")
                return
            self.cancel.clear()
            self._set_busy(True, "Working out what was said...")
            self.listen_var.set("Working out what was said...")
            self._run(lambda: self._listen_worker(audio))
            return
        if self.capture or self.busy or not self._open_mic():
            return
        self.capture = "listen"
        self.heard_text, self.heard_audio = "", None
        self.heard_var.set("")
        self._update_detect()
        self.listen_btn.configure(text="Stop", icon="stop")
        self._lock(True, self.listen_btn)
        self._tick()

    def _listen_worker(self, audio):
        model = get_model(self.get_settings()["model"], lambda m: self.tq.put(("progress", m)), self.cancel)
        self.tq.put(("heard", audio, transcribe(model, audio, cancel=self.cancel)))

    def _update_detect(self, event=None):
        text = self.heard_var.get()
        swaps = explain_soundalikes(text)
        if swaps:
            self.sound_var.set("  ".join(f"“{a}” sounds like “{b}” here" for a, b in swaps[:2]))
            self.sound_chip.pack(side="left", padx=(0, self.ui.px(10)), before=self.detect_lbl)
        else:
            self.sound_chip.pack_forget()
        if not text.strip():
            self.detect_var.set("")
            return
        t = RefTracker(self.get_settings()["separator"])
        ref = t.parse(text)
        if ref:
            self.detect_var.set(f"✓ Would show {ref}")
        elif t.clear:
            self.detect_var.set("✓ Would clear the screen")
        else:
            self.detect_var.set("No scripture reference in this text yet")

    def save_correction_click(self):
        if self.heard_audio is None or self.busy:
            return
        corrected = " ".join(self.heard_var.get().split())
        if not corrected:
            return
        heard = self.heard_text
        learned = apply_learned(learn_from_correction(heard, corrected)) if corrected != heard else []
        t = RefTracker(":")
        ref = t.parse(corrected)
        if ref and not learned and RefTracker(":").parse(heard) != ref:
            phrase = learn_phrase(heard, t.book, t.ch)  # fall back to the position-based method
            if phrase and add_aliases({phrase: t.book}):
                learned.append(f"'{phrase}' = {t.book}")
        try:
            save_correction(self.heard_audio, heard, corrected, kind="text")
        except Exception as e:
            self.log(f"(could not keep the audio: {e})")
        added = ref and t.book and add_prompt_for_book(t.book, t.ch, t.v1)
        if added:
            self.reload_prompts()
        for line in learned:
            self.log(f"Learned: {line}")
        if learned:
            msg = "Learned " + ", ".join(learned) + "."
        elif corrected == heard:
            msg = "Saved - it heard that correctly."
        else:
            msg = "Saved. Nothing new to learn (only numbers or ordinary words changed)."
        self.work_var.set(msg + (" Added to your practice prompts." if added else ""))
        self._reset_listen("Saved. Press Listen for the next one.")

    def mark_right(self):
        if self.heard_audio is None:
            return
        try:
            save_correction(self.heard_audio, self.heard_text, self.heard_text, kind="text")
        except Exception as e:
            self.log(f"(could not keep the audio: {e})")
        self.work_var.set("Saved as correct.")
        self._reset_listen("Saved. Press Listen for the next one.")

    def _reset_listen(self, message):
        self.heard_audio, self.heard_text = None, ""
        self.heard_var.set("")
        self._update_detect()
        self.listen_var.set(message)
        self.save_corr_btn.configure(state="disabled")
        self.right_btn.configure(state="disabled")
        self.refresh()

    # ---------------- finishing a session ----------------
    def finish_session(self):
        if self.busy or self.recording:
            return
        n, total = len(self._recorded()), len(self.prompts)
        if n == 0:
            self.messagebox.showinfo("RootsVoice", "Nothing recorded in this session yet.")
            return
        answer = self.messagebox.askyesnocancel(
            "Finish session",
            f"You recorded {n} of {total} prompts - you don't have to do them all.\n\n"
            "Learn from them now? A new session starts afterwards.\n\n"
            "Yes: learn now, then start a new session\n"
            "No: save without learning, then start a new session\n"
            "Cancel: keep recording")
        if answer is True:
            self.finish_pending = True
            self.cancel.clear()
            self._set_busy(True, "Preparing the speech model...")
            self._run(self._learn_worker)
        elif answer is False:
            self._new_session("Session saved without learning.")

    def _new_session(self, message):
        """Close the current session (its recordings are kept in the 'archive' folder) and start fresh."""
        archive_session()
        self.samples = {}
        save_samples(self.samples)
        self.idx = 0
        self.refresh()
        self.work_var.set(message + " A new session has started.")

    def _learn_worker(self):
        model = get_model(self.get_settings()["model"], lambda m: self.tq.put(("progress", m)), self.cancel)
        by_text = {p["text"]: p for p in self.prompts}
        aliases, ok, fixed, bad, total = {}, 0, 0, [], 0
        items = list(self.samples.items())
        for n, (text, entry) in enumerate(items, 1):
            p = by_text.get(text) or prompt_info(text)
            if not p["ref"]:
                continue
            self.tq.put(("progress", f"Checking sample {n} of {len(items)}..."))
            heard = transcribe(model, os.path.join(TRAINING_DIR, entry["file"]), cancel=self.cancel)
            total += 1
            if RefTracker(":").parse(heard) == p["ref"]:
                ok += 1
                continue
            phrase = learn_phrase(heard, p["book"], p["ch"])
            if phrase:
                aliases[phrase] = p["book"]
                fixed += 1
            else:
                bad.append((text, heard))
        self.tq.put(("learned", aliases, ok, fixed, bad, total))

    # ---------------- re-learn from everything ----------------
    def relearn(self):
        if self.busy or self.recording:
            return
        self.cancel.clear()
        self._set_busy(True, "Preparing the speech model...")
        self._run(self._relearn_worker)

    def _all_training_audio(self):
        """Every saved recording with what was really said: (path, kind, truth)."""
        jobs = []
        folders = [TRAINING_DIR]
        arch = os.path.join(TRAINING_DIR, "archive")
        if os.path.isdir(arch):
            folders += [os.path.join(arch, d) for d in sorted(os.listdir(arch))]
        for folder in folders:
            try:
                with open(os.path.join(folder, "samples.json"), "r", encoding="utf-8") as f:
                    index = json.load(f)
            except (OSError, ValueError):
                continue
            for text, entry in index.items():
                info = prompt_info(text)
                if info["ref"]:
                    jobs.append((os.path.join(folder, entry["file"]), "prompt", info))
        try:
            with open(CORRECTIONS_INDEX, "r", encoding="utf-8") as f:
                for c in json.load(f):
                    jobs.append((os.path.join(TRAINING_DIR, c["file"]), c.get("kind", "ref"), c["correct"]))
        except (OSError, ValueError, KeyError):
            pass
        return [j for j in jobs if os.path.isfile(j[0])]

    def _relearn_worker(self):
        jobs = self._all_training_audio()
        if not jobs:
            self.tq.put(("info", "Nothing saved yet - record some prompts or corrections first."))
            return
        model = get_model(self.get_settings()["model"], lambda m: self.tq.put(("progress", m)), self.cancel)
        found, ok = [], 0
        for i, (path, kind, truth) in enumerate(jobs, 1):
            self.tq.put(("progress", f"Re-checking recording {i} of {len(jobs)}..."))
            heard = transcribe(model, path, cancel=self.cancel)
            if kind == "text":
                if words_to_digits(heard).split() == words_to_digits(truth).split():
                    ok += 1
                else:
                    found += learn_from_correction(heard, truth)
                continue
            if kind == "prompt":
                book, ch, ref = truth["book"], truth["ch"], truth["ref"]
            else:
                t = RefTracker(":")
                ref = t.parse(truth)
                if not ref:
                    continue
                book, ch = t.book, t.ch
            if RefTracker(":").parse(heard) == ref:
                ok += 1
            else:
                phrase = learn_phrase(heard, book, ch)
                if phrase:
                    found.append(("book", phrase, book))
        self.tq.put(("relearned", found, ok, len(jobs)))

    # ---------------- A. import ----------------
    def import_recordings(self):
        if self.busy or self.recording:
            return
        paths = self.filedialog.askopenfilenames(
            title="Choose the preacher's recordings",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.aac"), ("All files", "*.*")])
        if not paths:
            return
        self.cancel.clear()
        self._set_busy(True, "Preparing the speech model...")
        self._run(lambda: self._import_worker(list(paths)))

    def _import_worker(self, paths):
        model = get_model(self.get_settings()["model"], lambda m: self.tq.put(("progress", m)), self.cancel)
        counts = {}
        for i, path in enumerate(paths, 1):
            name = os.path.basename(path)
            text = transcribe(
                model, path, cancel=self.cancel,
                on_segment=lambda end, dur, i=i, name=name: self.tq.put(
                    ("progress", f"File {i} of {len(paths)} ({name}): {end / 60:.0f} of {dur / 60:.0f} min")))
            for m in scan_near_misses(text):
                if 1 <= m["ch"] <= CHAPTERS.get(m["book"], 150):
                    key = (m["phrase"], m["book"])
                    counts[key] = counts.get(key, 0) + 1
        self.tq.put(("review", counts))

    # ---------------- learned words ----------------
    def manage_words(self):
        ui = self.ui
        win, body = themed_dialog(ui, "Learned words")
        ui.label(body, text="Learned words", size=13, weight="bold", bg="bg").pack(anchor="w")
        ui.label(body, text="What RootsVoice has learned. Select a wrong one and press Remove.", size=9,
                 fg="muted", bg="bg", wrap=420).pack(anchor="w", pady=(0, ui.px(10)))
        card = Card(ui, body, pad=6).pack(fill="both", expand=True)
        lb = ui.listbox(card.body, height=12)
        lb.configure(width=52)
        lb.pack(fill="both", expand=True)
        items = []

        def fill():
            items[:] = learned_items()
            lb.delete(0, "end")
            for heard, means in items:
                lb.insert("end", f"  “{heard}”  →  {means}")
            if not items:
                lb.insert("end", "  (nothing learned yet)")

        def remove():
            sel = lb.curselection()
            if sel and sel[0] < len(items):
                remove_learned(items[sel[0]][0])
                fill()
                self.refresh()

        def forget_all():
            if items and self.messagebox.askyesno("RootsVoice", "Forget everything learned?", parent=win):
                clear_aliases()
                fill()
                self.refresh()

        fill()
        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(ui.px(12), 0))
        Button(ui, row, text="Remove", kind="secondary", outer="bg", height=38, command=remove).pack(side="left")
        Button(ui, row, text="Forget all", kind="ghost", outer="bg", height=38,
               command=forget_all).pack(side="left", padx=ui.px(8))
        Button(ui, row, text="Close", kind="dark", outer="bg", height=38, command=win.destroy).pack(side="right")

    # ---------------- editable prompts ----------------
    def reload_prompts(self):
        self.prompts = training_prompts()
        self.progress.configure(maximum=len(self.prompts))
        self.idx = 0
        self._goto_first_unrecorded()
        self.refresh()

    def edit_prompts(self):
        if self.recording:
            return
        ui = self.ui
        win, body = themed_dialog(ui, "Edit practice prompts")
        ui.label(body, text="Practice prompts", size=13, weight="bold", bg="bg").pack(anchor="w")
        ui.label(body, bg="bg", fg="muted", size=9, wrap=460,
                 text="One prompt per line - what the preacher reads aloud. Put the books that get misheard "
                      "most; about 15 is plenty. Spell the book correctly, e.g. 'Turn to First Peter chapter 2 "
                      "verse 9.'").pack(anchor="w", pady=(0, ui.px(10)))
        card = Card(ui, body, pad=8).pack(fill="both", expand=True)
        box = ui.text(card.body, height=14, mono=False)
        box.configure(width=60, font=ui.font(10))
        box.pack(fill="both", expand=True)
        box.insert("1.0", "\n".join(p["text"] for p in self.prompts))
        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(ui.px(10), 0))
        book_var = self.tk.StringVar()
        ui.ttk.Combobox(row, textvariable=book_var, values=list(BOOKS), state="readonly", width=18).pack(side="left")

        def add_book():
            if book_var.get():
                has_text = bool(box.get("1.0", "end-1c").strip())
                box.insert("end-1c", ("\n" if has_text else "") + default_prompt_for(book_var.get()))

        def reset():
            box.delete("1.0", "end")
            box.insert("1.0", "\n".join(DEFAULT_PROMPTS))

        def save():
            lines = save_prompt_lines(box.get("1.0", "end").splitlines())
            if not lines:
                self.messagebox.showinfo("RootsVoice", "Add at least one prompt.")
                return
            self.reload_prompts()
            self.work_var.set(f"Saved {len(lines)} prompts.")
            win.destroy()

        Button(ui, row, text="Add book", kind="secondary", outer="bg", height=36, command=add_book).pack(
            side="left", padx=ui.px(8))
        Button(ui, row, text="Reset to default 15", kind="ghost", outer="bg", height=36, command=reset).pack(side="left")
        row2 = ui.frame(body, bg="bg")
        row2.pack(fill="x", pady=(ui.px(12), 0))
        Button(ui, row2, text="Save", kind="primary", outer="bg", height=40, weight="bold", command=save).pack(side="right")
        Button(ui, row2, text="Cancel", kind="ghost", outer="bg", height=40, command=win.destroy).pack(
            side="right", padx=ui.px(8))

    # ---------------- background plumbing ----------------
    def _run(self, fn):
        def go():
            try:
                fn()
            except Cancelled:
                self.tq.put(("info", "Cancelled."))
            except Exception as e:
                self.tq.put(("error", str(e)))
            finally:
                self.tq.put(("idle",))

        threading.Thread(target=go, daemon=True).start()

    def _poll(self):
        try:
            while True:
                ev = self.tq.get_nowait()
                kind = ev[0]
                if kind in ("progress", "info"):
                    self.work_var.set(ev[1])
                elif kind == "error":
                    self.work_var.set("Problem: " + ev[1])
                    self.messagebox.showerror("RootsVoice", ev[1])
                elif kind == "idle":
                    self.finish_pending = False  # learning failed or was cancelled: keep the session open
                    self._set_busy(False)
                    if self.listen_var.get().startswith("Working"):
                        self.listen_var.set("Press Listen, say a reference or command, then press Stop.")
                    self.refresh()
                elif kind == "heard":
                    self.heard_audio, self.heard_text = ev[1], ev[2]
                    self.heard_var.set(ev[2])
                    self._update_detect()
                    if ev[2]:
                        self.listen_var.set("Edit the text if it's wrong, then press Save correction.")
                    else:
                        self.listen_var.set("Heard nothing clear. Type what you said and press Save correction.")
                    self.save_corr_btn.configure(state="normal")
                    self.right_btn.configure(state="normal" if ev[2] else "disabled")
                    self.heard_entry.focus_set()
                elif kind == "learned":
                    self._show_learned(*ev[1:])
                    if self.finish_pending:
                        self.finish_pending = False
                        self._new_session("Session finished.")
                elif kind == "relearned":
                    self._show_relearned(*ev[1:])
                elif kind == "review":
                    self._show_review(ev[1])
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def _show_learned(self, aliases, ok, fixed, bad, total):
        added = add_aliases(aliases)
        for phrase, book in aliases.items():
            self.log(f"Learned: '{phrase}' = {book}")
        msg = (f"Checked {total} samples.\n\n"
               f"• Understood correctly: {ok}\n"
               f"• Fixed by learning new spellings: {fixed} ({added} new)\n"
               f"• Still not recognised: {len(bad)}")
        if bad:
            msg += "\n\nNot recognised, for example:\n" + "\n".join(
                f'  "{t}" heard as "{h or "(nothing)"}"' for t, h in bad[:3])
            msg += "\n\nTry Listen & correct with these, or a larger Accuracy model in Settings."
        self.work_var.set(f"Done: {ok} correct, {fixed} fixed, {len(bad)} not recognised.")
        self.messagebox.showinfo("Training result", msg)

    def _show_relearned(self, found, ok, total):
        lines = apply_learned(found)
        for line in lines:
            self.log(f"Learned: {line}")
        self.work_var.set(f"Re-checked {total} recordings: {ok} understood correctly, {len(lines)} new thing(s) learned.")
        self.messagebox.showinfo(
            "Re-learn result",
            f"Re-checked {total} saved recordings with the '{self.get_settings()['model']}' model.\n\n"
            f"• Understood correctly: {ok}\n• New things learned: {len(lines)}"
            + ("\n\n" + "\n".join(lines[:8]) if lines else ""))
        self.refresh()

    def _show_review(self, counts):
        if not counts:
            self.work_var.set("Finished. No misheard book names found.")
            self.messagebox.showinfo("RootsVoice", "No misheard book names were found in these recordings.")
            return
        ui = self.ui
        win, body = themed_dialog(ui, "Review what was found")
        ui.label(body, text="Misheard book names", size=13, weight="bold", bg="bg").pack(anchor="w")
        ui.label(body, bg="bg", fg="muted", size=9, wrap=420,
                 text="Switch on the ones that are right and RootsVoice will recognise them from now on."
                 ).pack(anchor="w", pady=(0, ui.px(10)))
        card = Card(ui, body, pad=12).pack(fill="x")
        picks = []
        for (phrase, book), n in sorted(counts.items(), key=lambda kv: -kv[1]):
            var = self.tk.BooleanVar(value=n >= 2)
            right = setting_row(ui, card.body, f"“{phrase}” → {book}", f"heard {n}×")
            Switch(ui, right, var).pack()
            picks.append((var, phrase, book))

        def add():
            chosen = {p: b for v, p, b in picks if v.get()}
            n = add_aliases(chosen)
            self.log(f"Learned {n} spelling(s) from recordings")
            self.work_var.set(f"Added {n} learned spelling(s).")
            self.refresh()
            win.destroy()

        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(ui.px(12), 0))
        Button(ui, row, text="Add selected", kind="primary", outer="bg", height=40, weight="bold",
               command=add).pack(side="right")
        Button(ui, row, text="Cancel", kind="ghost", outer="bg", height=40, command=win.destroy).pack(
            side="right", padx=ui.px(8))


# --------------------------------------------------------------------------
# MAIN WINDOW
# --------------------------------------------------------------------------
def run_gui():
    enable_sharp_text()
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog

    settings = load_settings()
    events = queue.Queue()
    tracker = RefTracker(settings["separator"])

    root = tk.Tk()
    root.title("RootsVoice")
    ui = UI(tk, ttk, root, settings.get("theme", "light"), settings.get("size", "auto"))
    px = ui.px
    gap = px(14)
    win_w = max(px(380), min(px(540), int(ui.screen_w * 0.42)))
    win_h = min(px(900), ui.screen_h - int(90 * ui.dpi))
    root.geometry(f"{win_w}x{win_h}+{max(0, ui.screen_w - win_w - int(24 * ui.dpi))}+{int(12 * ui.dpi)}")
    root.minsize(px(360), px(420))
    root.attributes("-topmost", bool(settings["always_on_top"]))
    ui.themed(root, bg="bg")

    window_icons = {}

    def set_window_icon():
        imgs = [i for i in (logo_image(ui, f"icon_{ui.name}_{s}") for s in (128, 32)) if i is not None]
        if imgs:
            window_icons["current"] = imgs   # keep a reference or Tk drops the image
            try:
                root.iconphoto(True, *imgs)
            except Exception:
                pass

    ui.register(set_window_icon)

    state = {"engine": None, "pending": None, "countdown_job": None, "showing": None,
             "last_ref": None, "last_time": 0.0, "training": None, "ignored": 0, "last_auto": 0.0}
    history = []   # [(reference, "HH:MM")], newest first

    # ---- variables
    auto_var = tk.BooleanVar(value=bool(settings["roots_auto"]))
    learn_var = tk.BooleanVar(value=bool(settings["live_learning"]))
    dark_var = tk.BooleanVar(value=ui.name == "dark")
    top_var = tk.BooleanVar(value=bool(settings["always_on_top"]))
    wake_var = tk.BooleanVar(value=bool(settings["wake_word"]))
    show_all_var = tk.BooleanVar(value=bool(settings["show_all_speech"]))
    mic_var = tk.StringVar(value=settings["mic"])
    model_var = tk.StringVar(value=settings["model"])
    mode_var = tk.StringVar(value=settings["mode"])
    delay_var = tk.IntVar(value=int(settings["auto_delay"]))
    title_var = tk.StringVar(value=settings["window_title"])
    current_target = {"id": target_id(settings)}
    saved_targets = dict(settings.get("targets") or {})
    target_var = tk.StringVar(value=TARGETS[current_target["id"]]["name"])
    focus_var = tk.StringVar(value=settings.get("focus") or "hotkey")
    pointer = {"x": settings.get("click_x"), "y": settings.get("click_y")}
    api_port_var = tk.StringVar(value=str(settings.get("api_port") or 5506))
    api_key_var = tk.StringVar(value=settings.get("api_key") or "")
    click_var = tk.StringVar()
    target_note = tk.StringVar()
    hotkey_var = tk.StringVar(value=settings["search_hotkey"])
    after_var = tk.StringVar(value=settings["after_keys"])
    sep_var = tk.StringVar(value="space" if settings["separator"] == " " else settings["separator"])
    next_key_var = tk.StringVar(value=settings["next_key"])
    prev_key_var = tk.StringVar(value=settings["prev_key"])
    clear_key_var = tk.StringVar(value=settings["clear_key"])
    ref_var = tk.StringVar(value="—")
    caption_var = tk.StringVar(value="READY")
    hint_var = tk.StringVar(value="Press Start listening, then speak a Bible reference.")
    manual_var = tk.StringVar()
    teach_var = tk.StringVar()
    model_hint = tk.StringVar()

    # ================= HEADER =================
    shell = ui.frame(root, bg="bg")
    shell.pack(fill="both", expand=True)
    head = ui.frame(shell, bg="bg")
    head.pack(fill="x", padx=px(22), pady=(px(18), px(12)))
    LogoBadge(ui, head).pack(side="left")
    ui.label(head, text="RootsVoice", size=14, weight="bold", display=True, bg="bg").pack(side="left", padx=(px(10), 0))
    theme_btn = Button(ui, head, icon="sun" if ui.name == "dark" else "moon", kind="secondary", outer="bg",
                       height=36, radius=9, command=lambda: apply_theme("light" if ui.name == "dark" else "dark"))
    theme_btn.pack(side="right")
    help_btn = Button(ui, head, icon="help", kind="secondary", outer="bg", height=36, radius=9,
                      command=lambda: show_page("help"))
    help_btn.pack(side="right", padx=(0, px(6)))
    pill = Pill(ui, head, max_chars=26).pack(side="right", padx=(0, px(8)))

    # ---- section switcher
    nav = Card(ui, shell, fill="seg", border=None, outer="bg", radius=11, pad=4)
    nav.pack(fill="x", padx=px(22), pady=(0, px(6)))
    holder = ui.frame(shell, bg="bg")
    holder.pack(fill="both", expand=True)
    pages = {k: ScrollPage(ui, holder) for k in ("live", "training", "settings", "help")}
    nav_btns = {}
    for i, (key, label, icon) in enumerate((("live", "Live", "mic"), ("training", "Training", "training"),
                                            ("settings", "Settings", "settings"))):
        nav.body.columnconfigure(i, weight=1, uniform="nav")
        nav_btns[key] = Button(ui, nav.body, text=label, icon=icon, kind="seg_off", outer="seg", height=34,
                               radius=8, command=lambda k=key: show_page(k)).grid(
            row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(4), 0))

    def show_page(key):
        for k, page in pages.items():
            page.pack_forget()
            if k in nav_btns:
                nav_btns[k].configure(kind="seg_on" if k == key else "seg_off")
        help_btn.configure(kind="primary" if key == "help" else "secondary")
        pages[key].pack(fill="both", expand=True, pady=(px(8), 0))

    # ================= LIVE =================
    lb = pages["live"].body

    hero = ui.frame(lb, bg="bg")
    hero.pack(fill="x", pady=(0, gap))
    start_btn = Button(ui, hero, text="Start listening", icon="mic", kind="primary", outer="bg", height=48,
                       radius=11, size=11, weight="bold", command=lambda: toggle())
    start_btn.pack(side="left", fill="x", expand=True)
    meter_card = Card(ui, hero, pad=0, padx=14, pady=12, radius=11)
    meter_card.pack(side="left", padx=(px(10), 0))
    meter_card.w.configure(width=px(84))
    meter = LevelMeter(ui, meter_card.body).pack()

    # RootsAuto
    auto_card = Card(ui, lb, pad=14).pack(fill="x", pady=(0, gap))
    ab = auto_card.body
    auto_icon = tk.Canvas(ab, width=px(38), height=px(38), highlightthickness=0, bd=0)
    auto_icon.pack(side="left")
    auto_txt = ui.frame(ab)
    auto_txt.pack(side="left", fill="x", expand=True, padx=(px(12), 0))
    ui.label(auto_txt, text="RootsAuto", size=11, weight="bold").pack(anchor="w")
    auto_sub = tk.StringVar()
    ui.label(auto_txt, textvariable=auto_sub, size=9, fg="muted").pack(anchor="w")
    Switch(ui, ab, auto_var, command=lambda: on_auto_toggle()).pack(side="right")

    def live_target_name():
        try:
            return target_name(current_settings())
        except NameError:          # still building the window
            return target_name(settings)

    def draw_auto():
        on = auto_var.get()
        c = ui.c
        auto_icon.configure(bg=c["surface"])
        auto_icon.delete("all")
        s = px(38)
        round_rect(auto_icon, 0, 0, s, s, px(10), fill=c["accent_soft"] if on else c["seg"], outline="")
        glyph = ui.icon("bolt") or "A"
        auto_icon.create_text(s / 2, s / 2, text=glyph, font=ui.font(12, icon=bool(ui.icon_family)),
                              fill=c["accent"] if on else c["muted"])
        auto_sub.set(f"Voice controls {live_target_name()} instantly" if on
                     else "Paused \u00b7 you confirm each verse")

    ui.register(draw_auto)

    # Now showing
    now = Card(ui, lb, pad=18, radius=14).pack(fill="x", pady=(0, gap))
    nb = now.body
    caption_lbl = ui.label(nb, textvariable=caption_var, size=8, weight="bold", fg="muted")
    caption_lbl.pack(anchor="w")
    ui.label(nb, textvariable=ref_var, size=24, weight="bold", display=True).pack(anchor="w")
    ui.label(nb, textvariable=hint_var, size=9, fg="muted", wrap=430).pack(anchor="w")
    stepper = ui.frame(nb)
    stepper.pack(fill="x", pady=(px(12), 0))
    Button(ui, stepper, icon="left", kind="secondary", height=36, radius=9,
           command=lambda: navigate("prev", source="button")).pack(side="left")
    Button(ui, stepper, icon="right", kind="secondary", height=36, radius=9,
           command=lambda: navigate("next", source="button")).pack(side="right")
    strip = ui.frame(stepper)
    strip.pack(side="left", fill="x", expand=True, padx=px(6))

    def render_strip():
        """Nearby verse numbers: click one to jump straight to it."""
        for child in strip.winfo_children():
            child.destroy()
        if not tracker.book:
            ui.label(strip, text="Verse buttons appear after the first reference", size=9, fg="muted",
                     anchor="center").pack(fill="x", pady=px(9))
            return
        cur = tracker.v1 or 0
        first = max(1, cur - 2) if cur else 1
        for i, v in enumerate(range(first, min(first + 5, MAX_VERSE + 1))):
            strip.columnconfigure(i, weight=1, uniform="verse")
            Button(ui, strip, text=str(v), kind="chip_accent" if v == cur else "chip", height=36, radius=9,
                   weight="bold" if v == cur else "normal",
                   command=lambda v=v: navigate("verse", v, source="button")).grid(
                row=0, column=i, sticky="ew", padx=px(2))

    actions = ui.frame(nb)
    actions.pack(fill="x", pady=(px(12), 0))
    send_btn = Button(ui, actions, text="Send", icon="send", kind="primary", weight="bold", command=lambda: send_pending())
    skip_btn = Button(ui, actions, text="Skip", icon="close", command=lambda: skip_pending())
    back_btn = Button(ui, actions, text="Back", icon="undo", command=lambda: go_back())
    clear_btn = Button(ui, actions, text="Clear", icon="monitor", command=lambda: do_clear())

    def layout_actions(pending):
        for b in (send_btn, skip_btn, back_btn, clear_btn):
            b.grid_forget()
        order = (send_btn, skip_btn, back_btn) if pending else (back_btn, skip_btn, clear_btn)
        weights = (2, 1, 1) if pending else (1, 1, 1)
        for i, (b, wt) in enumerate(zip(order, weights)):
            actions.columnconfigure(i, weight=wt, uniform="act")
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(8), 0))

    # Suggestions
    section_title(ui, lb, "Suggestions").pack(anchor="w", pady=(0, px(6)))
    sug_hint = ui.label(lb, text="Next verse, previous verse and chapter jumps appear here.", size=9,
                        fg="muted", bg="bg")
    flow = Flow(ui, lb, bg="bg")
    flow.pack(fill="x")
    sug_hint.pack(anchor="w")
    spacer = ui.frame(lb, bg="bg")
    spacer.configure(height=gap)
    spacer.pack(fill="x")

    # Manual entry
    man = ui.frame(lb, bg="bg")
    man.pack(fill="x", pady=(0, gap))
    send_typed_btn = Button(ui, man, icon="send", kind="dark", outer="bg", height=46, radius=11,
                            command=lambda: send_manual())
    send_typed_btn.pack(side="right")
    manual_box = InputBox(ui, man, manual_var, placeholder="Type a reference or command…", icon="search")
    manual_box.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
    manual_entry = manual_box.entry

    # Live learning (optional)
    learn_card = Card(ui, lb, pad=16)
    lcb = learn_card.body
    ui.label(lcb, text="Live learning", size=11, weight="bold").pack(anchor="w")
    ui.label(lcb, text="1. Click the line it got wrong   2. Type what it should be   3. Learn & send",
             size=9, fg="muted", wrap=430).pack(anchor="w", pady=(0, px(8)))
    recent_list = ui.listbox(lcb, height=4, bg="surface2")
    recent_list.pack(fill="x")
    trow = ui.frame(lcb)
    trow.pack(fill="x", pady=(px(8), 0))
    teach_btn = Button(ui, trow, text="Learn & send", kind="primary", weight="bold", command=lambda: learn_and_send())
    teach_btn.pack(side="right")
    teach_box = InputBox(ui, trow, teach_var, placeholder="It should be, e.g. First Peter 2:9", outer="surface",
                         size=10, height=44)
    teach_box.pack(side="left", fill="x", expand=True, padx=(0, px(8)))

    # Recent
    recent_card = Card(ui, lb, pad=0, padx=16, pady=12).pack(fill="x", pady=(0, gap))
    section_title(ui, recent_card.body, "Recent  ·  double-click to show again", bg="surface").pack(anchor="w")
    hist_rows = ui.frame(recent_card.body)
    hist_rows.pack(fill="x", pady=(px(4), 0))

    # Activity (collapsed)
    activity_btn = Button(ui, lb, text="Activity", icon="down", icon_after=True, kind="ghost", outer="bg",
                          height=42, radius=11, command=lambda: toggle_activity())
    activity_btn.pack(fill="x")
    log_card = Card(ui, lb, pad=6)
    log = ui.text(log_card.body, height=9)
    log.pack(fill="both", expand=True)
    log.configure(state="disabled")

    def toggle_activity():
        state["activity_open"] = not state.get("activity_open")
        if state["activity_open"]:
            log_card.pack(fill="x", pady=(px(8), 0))
            activity_btn.configure(icon="up")
        else:
            log_card.pack_forget()
            activity_btn.configure(icon="down")

    def update_activity_label():
        n = state["ignored"]
        activity_btn.configure(text="Activity" + (f"  ·  {n} unrelated phrase{'s' if n != 1 else ''} ignored" if n else ""))

    # ================= SETTINGS =================
    sb = pages["settings"].body
    settings_group = []
    keys_var = tk.BooleanVar(value=bool(settings.get("global_keys", True)))
    clicker_var = tk.BooleanVar(value=bool(settings.get("clicker", False)))
    size_var = tk.StringVar(value=settings.get("size", "auto").capitalize())

    def settings_section(title, subtitle=None, open_=False):
        sec = Section(ui, sb, title, subtitle, open_=open_, group=settings_group)
        sec.pack(fill="x", pady=(0, px(8)))
        return sec.body

    def field(parent, var, width=160):
        box = InputBox(ui, parent, var, outer="surface", size=10, height=36)
        box.w.configure(width=px(width))
        return box.pack()

    KEY_CHOICES = ["", "down", "up", "right", "left", "pagedown", "pageup", "space", "enter",
                   "ctrl+right", "ctrl+left", "b", "f8"]

    def key_dropdown(parent, var):
        box = ttk.Combobox(parent, textvariable=var, values=KEY_CHOICES, width=12)   # pick or type
        box.pack()
        return box

    mic_choice_var = tk.StringVar()
    mic_labels = {}          # what the dropdown shows -> the name that is saved ("" = Windows default)

    def refresh_mics(event=None):
        """Fill the dropdown: Windows' default microphone (by name) first, then every microphone."""
        try:
            sd = audio_module()
            names = [n for _, n, _ in list_microphones(sd)]
            default = default_input_name(sd)
        except Exception:
            names, default = [], ""
        mic_labels.clear()
        mic_labels[f"Windows default ({default})" if default else "Windows default"] = ""
        for n in names:
            mic_labels[n] = n
        saved = mic_var.get()
        if saved and saved not in names:
            mic_labels[f"{saved} (not connected)"] = saved
        mic_box.configure(values=list(mic_labels))
        mic_choice_var.set(next(label for label, name in mic_labels.items() if name == saved))
        mic_hint.set(f"{len(names)} microphone{'s' if len(names) != 1 else ''} found" if names else
                     "No microphones found - plug one in, then press refresh")

    def on_mic_pick(event=None):
        mic_var.set(mic_labels.get(mic_choice_var.get(), ""))
        save_settings(current_settings())

    def set_mic(name):
        mic_var.set(name)
        refresh_mics()

    c1 = settings_section("Listening", open_=True)
    mic_hint = tk.StringVar()
    r = setting_row(ui, c1, "Microphone", None)
    mic_box = ttk.Combobox(r, textvariable=mic_choice_var, state="readonly", width=24)
    mic_box.pack(side="left")
    mic_box.bind("<<ComboboxSelected>>", on_mic_pick)
    Button(ui, r, icon="refresh", kind="secondary", height=34, command=refresh_mics).pack(side="left", padx=(px(6), 0))
    ui.label(c1, textvariable=mic_hint, size=9, fg="muted").pack(anchor="w")
    refresh_mics()
    Button(ui, c1, text="Find active microphone", icon="mic", kind="secondary", height=38,
           command=lambda: find_active_mic()).pack(fill="x", pady=(px(2), px(6)))

    def issue_list(parent, issues):
        """Show each microphone problem with buttons that open the right Windows page."""
        for issue in issues:
            box = ui.frame(parent)
            box.pack(fill="x", pady=(0, px(10)))
            ui.label(box, text="\u26a0  " + issue["title"], size=10, weight="bold", fg="warn_text", wrap=400).pack(anchor="w")
            ui.label(box, text=issue["detail"], size=9, fg="muted", wrap=400).pack(anchor="w", pady=(px(2), px(4)))
            row = ui.frame(box)
            row.pack(fill="x")
            for label, target in issue["actions"]:
                Button(ui, row, text=label, kind="secondary", height=32, size=9,
                       command=lambda t=target: open_windows_link(t) or messagebox.showinfo(
                           "RootsVoice", "Open it from the Start menu: " + t)).pack(side="left", padx=(0, px(6)))

    def show_mic_notice(issues, intro="Something is stopping the microphone. Fix the items below, then try again."):
        win, body = themed_dialog(ui, "Microphone needs attention")
        ui.label(body, text="Microphone needs attention", size=13, weight="bold", bg="bg").pack(anchor="w")
        ui.label(body, text=intro, size=9, fg="muted", bg="bg", wrap=420).pack(anchor="w", pady=(0, px(10)))
        card = Card(ui, body, pad=14).pack(fill="x")
        issue_list(card.body, issues)
        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(px(12), 0))
        Button(ui, row, text="Close", kind="dark", outer="bg", height=38, command=win.destroy).pack(side="right")
        return win

    def check_mic_health_later():
        def worker():
            events.put(("mic_health", microphone_health()))
        threading.Thread(target=worker, daemon=True).start()

    def find_active_mic():
        if state["engine"]:
            messagebox.showinfo("RootsVoice", "Stop listening first - the microphone is in use.")
            return
        win, body = themed_dialog(ui, "Find active microphone")
        ui.label(body, text="Find active microphone", size=13, weight="bold", bg="bg").pack(anchor="w")
        ui.label(body, text="Speak, or have the sound desk play something, while RootsVoice listens to each "
                            "input for a moment.", size=9, fg="muted", bg="bg", wrap=420).pack(anchor="w")
        prog = tk.StringVar(value="Starting\u2026")
        ui.label(body, textvariable=prog, size=10, weight="bold", bg="bg", wrap=420).pack(anchor="w", pady=(px(10), 0))
        list_card = Card(ui, body, pad=12).pack(fill="x", pady=(px(8), 0))
        results_q = queue.Queue()
        stop_scan = threading.Event()

        def worker():
            try:
                found = scan_microphones(progress=lambda n, total, name: results_q.put(
                    ("progress", f"Listening to {n} of {total}: {name}")), cancel=stop_scan)
                issues = [] if best_microphone(found) else microphone_health(mic_count=len(found))
                results_q.put(("done", (found, issues)))
            except Exception as e:
                results_q.put(("error", str(e)))

        def poll():
            try:
                while True:
                    kind, val = results_q.get_nowait()
                    if kind == "progress":
                        prog.set(val)
                    elif kind == "error":
                        prog.set("Could not test the microphones: " + val)
                        return
                    elif kind == "done":
                        show(*val)
                        return
            except queue.Empty:
                pass
            if not stop_scan.is_set():
                root.after(150, poll)

        def show(found, issues=()):
            best = best_microphone(found)
            if issues:
                issue_list(list_card.body, issues)
            if not found:
                prog.set("No microphones found - plug one in and try again.")
            elif best:
                prog.set(f"Most active: {best['name']}")
            else:
                prog.set("None of the inputs heard any sound. Check cables, mute switches and the sound desk, "
                         "then try again.")
            for res in found:
                row = ui.frame(list_card.body)
                row.pack(fill="x", pady=px(4))
                LevelMeter(ui, row).pack(side="left").set(min(1.0, res["level"] * 10))
                txt = ui.frame(row)
                txt.pack(side="left", fill="x", expand=True, padx=(px(10), px(8)))
                ui.label(txt, text=res["name"], size=10, weight="bold", wrap=250).pack(anchor="w")
                ui.label(txt, text=res["note"], size=9, fg="muted", wrap=250).pack(anchor="w")
                if res["ok"]:
                    Button(ui, row, text="Use", kind="primary" if res is best else "secondary", height=32, size=9,
                           command=lambda n=res["name"]: use(n)).pack(side="right")

        def use(name):
            set_mic(name)
            save_settings(current_settings())
            write_log(f"Microphone: {name}")
            close()

        def close():
            stop_scan.set()
            win.destroy()

        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(px(12), 0))
        Button(ui, row, text="Test again", icon="refresh", kind="secondary", outer="bg", height=38,
               command=lambda: (close(), find_active_mic())).pack(side="left")
        Button(ui, row, text="Close", kind="dark", outer="bg", height=38, command=close).pack(side="right")
        threading.Thread(target=worker, daemon=True).start()
        poll()
    r = setting_row(ui, c1, "Accuracy", "Bigger hears better but needs a faster computer")
    model_box = ttk.Combobox(r, textvariable=model_var, state="readonly", values=list(MODEL_MB), width=10)
    model_box.pack(side="left")
    dl_btn = Button(ui, r, icon="download", kind="secondary", height=34, command=lambda: download_model_click())
    dl_btn.pack(side="left", padx=(px(6), 0))
    ui.label(c1, textvariable=model_hint, size=9, fg="muted", wrap=430).pack(anchor="w")

    c2 = settings_section("Moving through scripture",
                          "Most projection programs have no voice-friendly next / previous verse keys, so "
                          "RootsVoice works out the new reference and sends it for you. Choose how you want "
                          "to step:")
    Switch(ui, setting_row(ui, c2, "Keyboard shortcuts", "Ctrl+Alt+→ / ← for next / previous verse, "
                                                         "from any window. Full list in Help."),
           keys_var, command=lambda: (restart_hotkeys(), save_settings(current_settings()))).pack()
    Switch(ui, setting_row(ui, c2, "Presentation clicker", "Its forward / back buttons step verses "
                                                           "(takes over Page Down / Page Up)"),
           clicker_var, command=lambda: (restart_hotkeys(), save_settings(current_settings()))).pack()
    Switch(ui, setting_row(ui, c2, "Say \u201cRoots\u201d first", "Short voice commands need it, e.g. "
                                                              "\u201cRoots, next verse\u201d. Safer in a sermon."),
           wake_var).pack()

    c3 = settings_section("Projection software")
    r = setting_row(ui, c3, "Program", "Which program shows the verses")
    target_box = ttk.Combobox(r, textvariable=target_var, values=[t["name"] for t in TARGETS.values()],
                              state="readonly", width=14)
    target_box.pack(side="left")
    target_box.bind("<<ComboboxSelected>>", lambda e: switch_target_by_name(target_var.get()))
    Button(ui, r, text="Detect", icon="search", kind="secondary", height=34, size=9,
           command=lambda: detect_program()).pack(side="left", padx=(px(6), 0))
    ui.label(c3, textvariable=target_note, size=9, fg="muted", wrap=430).pack(anchor="w", pady=(0, px(4)))
    mode_holder = ui.frame(c3)
    mode_holder.pack(fill="x")
    keys_box, api_box = ui.frame(mode_holder), ui.frame(mode_holder)
    field(setting_row(ui, keys_box, "Window title", "Part of the program's title bar text"), title_var)
    r = setting_row(ui, keys_box, "Reach the reference box by", "Its shortcut key, or a spot you point to once")
    fseg = Card(ui, r, fill="seg", border=None, outer="surface", radius=9, pad=3).pack()
    focus_btns = {}
    for m, label in (("hotkey", "Shortcut"), ("click", "Pointing")):
        focus_btns[m] = Button(ui, fseg.body, text=label, kind="seg_off", outer="seg", height=30, radius=7,
                               size=9, command=lambda m=m: set_focus(m)).pack(side="left")
    focus_holder = ui.frame(keys_box)
    focus_holder.pack(fill="x")
    hotkey_row, click_row = ui.frame(focus_holder), ui.frame(focus_holder)
    field(setting_row(ui, hotkey_row, "Search shortcut", "e.g. ctrl+f"), hotkey_var)
    Button(ui, setting_row(ui, click_row, "Reference box", "Hold the mouse over it for 5 seconds"),
           text="Point to it", icon="edit", kind="secondary", height=34, size=9,
           command=lambda: point_to_box()).pack()
    ui.label(click_row, textvariable=click_var, size=9, fg="muted", wrap=430).pack(anchor="w")
    field(setting_row(ui, keys_box, "Keys after typing", "enter, or enter,enter to go live"), after_var)
    ttk.Combobox(setting_row(ui, keys_box, "Verse separator", "John 3:16, 3.16 or 3 16"), textvariable=sep_var,
                 values=[":", ".", "space"], state="readonly", width=7).pack()
    ui.label(keys_box, text="Only if the program has its own keys - leave blank and RootsVoice types the verse:",
             size=9, fg="muted", wrap=430).pack(anchor="w", pady=(px(8), 0))
    key_dropdown(setting_row(ui, keys_box, "Next verse key"), next_key_var)
    key_dropdown(setting_row(ui, keys_box, "Previous verse key"), prev_key_var)
    key_dropdown(setting_row(ui, keys_box, "Clear screen key", "Blank = Clear is off"), clear_key_var)
    field(setting_row(ui, api_box, "API port", "FreeShow › Settings › Connections"), api_port_var, 90)
    field(setting_row(ui, api_box, "API key", "Only if you set one in FreeShow"), api_key_var)
    Button(ui, c3, text="Send a test verse (John 3:16)", icon="send", kind="secondary", height=38,
           command=lambda: test_send()).pack(fill="x", pady=(px(10), 0))

    def profile_values():
        vals = {"window_title": title_var.get().strip(), "focus": focus_var.get(),
                "search_hotkey": hotkey_var.get().strip(), "after_keys": after_var.get().strip(),
                "next_key": next_key_var.get().strip(), "prev_key": prev_key_var.get().strip(),
                "clear_key": clear_key_var.get().strip(), "click_x": pointer["x"], "click_y": pointer["y"],
                "api_key": api_key_var.get().strip()}
        try:
            vals["api_port"] = int(api_port_var.get() or 5506)
        except ValueError:
            vals["api_port"] = 5506
        return vals

    def load_profile(tid):
        vals = target_values(tid, saved_targets.get(tid))
        title_var.set(vals["window_title"])
        focus_var.set(vals["focus"])
        hotkey_var.set(vals["search_hotkey"])
        after_var.set(vals["after_keys"])
        next_key_var.set(vals["next_key"])
        prev_key_var.set(vals["prev_key"])
        clear_key_var.set(vals["clear_key"])
        pointer["x"], pointer["y"] = vals["click_x"], vals["click_y"]
        api_port_var.set(str(vals["api_port"]))
        api_key_var.set(vals["api_key"])

    def apply_target_ui():
        t = TARGETS[current_target["id"]]
        target_var.set(t["name"])
        target_note.set(t["note"])
        keys_box.pack_forget()
        api_box.pack_forget()
        (api_box if t["kind"] == "freeshow" else keys_box).pack(fill="x")
        set_focus(focus_var.get())
        if pointer["x"] is None:
            click_var.set("Not set yet.")
        else:
            click_var.set(f"\u2713 Saved: {pointer['x']}, {pointer['y']} from the window's top-left corner.")
        draw_auto()

    def set_focus(m):
        focus_var.set(m)
        for k, b in focus_btns.items():
            b.configure(kind="seg_on" if k == m else "seg_off")
        hotkey_row.pack_forget()
        click_row.pack_forget()
        (click_row if m == "click" else hotkey_row).pack(fill="x")

    def switch_target(tid):
        if tid == current_target["id"]:
            apply_target_ui()
            return
        saved_targets[current_target["id"]] = profile_values()
        current_target["id"] = tid
        load_profile(tid)
        apply_target_ui()
        save_settings(current_settings())
        write_log(f"Projection software: {TARGETS[tid]['name']}")

    def switch_target_by_name(name):
        tid = next((k for k, t in TARGETS.items() if t["name"] == name), "custom")
        switch_target(tid)

    def detect_program():
        found = detect_open_programs()
        if not found:
            messagebox.showinfo("RootsVoice", "None of the supported programs is open right now.\n\n"
                                "Open your projection software and press Detect again, or choose it from the list.")
            return
        switch_target(found[0])
        others = ", ".join(TARGETS[t]["name"] for t in found[1:])
        messagebox.showinfo("RootsVoice", f"Found {TARGETS[found[0]]['name']} - RootsVoice will use it."
                            + (f"\n\nAlso open: {others}" if others else ""))

    def point_to_box():
        s = current_settings()
        win, err = find_target_window(s)
        if err:
            click_var.set(err)
            return
        try:
            win.activate()
        except Exception:
            pass
        countdown(5)

    def countdown(n):
        if n > 0:
            click_var.set(f"Hold the mouse over {target_name(current_settings())}'s reference box\u2026 {n}")
            root.after(1000, countdown, n - 1)
            return
        pos, err = pointer_offset(current_settings())
        if err:
            click_var.set(err)
            return
        pointer["x"], pointer["y"] = pos
        click_var.set(f"\u2713 Saved: {pos[0]}, {pos[1]} from the window's top-left corner.")
        save_settings(current_settings())
        write_log(f"Reference box set for {target_name(current_settings())}")

    def test_send():
        clear_pending("Sending a test verse...")
        do_send("John" + (" 3" + (current_settings()["separator"]) + "16"))

    c4 = settings_section("When RootsAuto is off")
    r = setting_row(ui, c4, "Sending", "Confirm each verse, or send after a countdown")
    seg = Card(ui, r, fill="seg", border=None, outer="surface", radius=9, pad=3).pack()
    mode_btns = {}

    def set_mode(m):
        mode_var.set(m)
        for k, b in mode_btns.items():
            b.configure(kind="seg_on" if k == m else "seg_off")

    for m, label in (("manual", "Confirm"), ("auto", "Countdown")):
        mode_btns[m] = Button(ui, seg.body, text=label, kind="seg_off", outer="seg", height=30, radius=7, size=9,
                              command=lambda m=m: set_mode(m)).pack(side="left")
    set_mode(mode_var.get())
    r = setting_row(ui, c4, "Countdown length", "Seconds before an unconfirmed verse is sent")
    ttk.Combobox(r, textvariable=delay_var, values=[str(i) for i in range(1, 16)], state="readonly",
                 width=4).pack()

    c5 = settings_section("Display")
    Switch(ui, setting_row(ui, c5, "Night mode", "Dark colours for a dim sanctuary"), dark_var,
           command=lambda: apply_theme("dark" if dark_var.get() else "light")).pack()
    size_box = ttk.Combobox(setting_row(ui, c5, "Size", f"Auto picks {ui.size_name.capitalize()} for this screen"),
                            textvariable=size_var, values=["Auto", "Compact", "Normal", "Large"],
                            state="readonly", width=9)
    size_box.pack()
    size_box.bind("<<ComboboxSelected>>", lambda e: on_size_change())
    Switch(ui, setting_row(ui, c5, "Keep on top", "Stay above your projection software"), top_var,
           command=lambda: root.attributes("-topmost", top_var.get())).pack()
    Switch(ui, setting_row(ui, c5, "Live learning panel", "Fix mishearings from the Live screen"), learn_var,
           command=lambda: toggle_learn_panel()).pack()
    Switch(ui, setting_row(ui, c5, "Show all speech", "Log everything, not just scripture"), show_all_var).pack()

    # ================= HELP & ABOUT =================
    hp = pages["help"].body
    help_group = []

    def help_section(title, open_=False):
        sec = Section(ui, hp, title, open_=open_, group=help_group)
        sec.pack(fill="x", pady=(0, px(8)))
        return sec.body

    def para(parent, text, fg="text"):
        ui.label(parent, text=text, size=10, fg=fg, wrap=440).pack(anchor="w", pady=(0, px(6)))

    def rows(parent, items):
        for key, desc in items:
            row = ui.frame(parent)
            row.pack(fill="x", pady=px(3))
            row.columnconfigure(1, weight=1)
            ui.label(row, text=key, size=10, weight="bold", wrap=190).grid(row=0, column=0, sticky="nw",
                                                                          padx=(0, px(12)))
            ui.label(row, text=desc, size=10, fg="muted", wrap=240).grid(row=0, column=1, sticky="nw")

    section_title(ui, hp, "HELP").pack(anchor="w", pady=(0, px(6)))
    b = help_section("Quick start", open_=True)
    rows(b, [("1", "Open your projection software, and pick it in Settings › Projection software "
                   "(or press Detect)."),
             ("2", "Press Start listening. The first time, the speech model downloads once (needs internet)."),
             ("3", "Speak a reference: “Turn to John chapter 3 verse 16”."),
             ("4", "RootsAuto on: it appears on screen straight away. RootsAuto off: press Send.")])

    def run_setup_check():
        set_status("Checking setup\u2026", "busy")
        s = dict(current_settings(), _listening=bool(state["engine"]))

        def worker():
            lines = setup_check(s)
            events.put(("setup_result", lines, microphone_health()))

        threading.Thread(target=worker, daemon=True).start()

    Button(ui, b, text="Check setup", icon="check", kind="primary", height=40, weight="bold",
           command=run_setup_check).pack(fill="x", pady=(px(8), 0))
    Button(ui, b, text="Install missing components", icon="download", kind="secondary", height=38,
           command=lambda: show_components_dialog()).pack(fill="x", pady=(px(6), 0))

    def show_components_dialog(missing=None):
        """Lists what is missing and installs it with one click, showing pip's progress."""
        missing = missing_dependencies() if missing is None else missing
        win, body = themed_dialog(ui, "Install components")
        required = [m for m in missing if m[2]]
        title = ("RootsVoice needs a few things" if required else
                 "Optional components" if missing else "Everything RootsVoice needs is installed")
        ui.label(body, text=title, size=13, weight="bold", bg="bg").pack(anchor="w")
        if FROZEN and missing:
            ui.label(body, text="Part of RootsVoice is missing. Please reinstall it with the latest Setup file.",
                     size=10, bg="bg", wrap=420).pack(anchor="w", pady=(px(6), 0))
        card = Card(ui, body, pad=12).pack(fill="x", pady=(px(8), 0))
        for pip, why, req in missing:
            ui.label(card.body, text=f"\u2022 {pip}" + ("" if req else "  (optional)"), size=10,
                     weight="bold").pack(anchor="w")
            ui.label(card.body, text=why, size=9, fg="muted", wrap=400).pack(anchor="w", pady=(0, px(4)))
        if not missing:
            ui.label(card.body, text="\u2713 Speech engine, sound and typing components are ready.", size=10,
                     fg="accent_soft_text").pack(anchor="w")
        note = python_version_note()
        status = tk.StringVar(value=(note + "\n\n" if note else "") + (
            "Needs internet once and takes a few minutes (about 150-300 MB)." if missing and not FROZEN else ""))
        ui.label(body, textvariable=status, size=9, fg="muted", bg="bg", wrap=420).pack(anchor="w", pady=(px(8), 0))
        log_card = Card(ui, body, pad=6)
        log_box = ui.text(log_card.body, height=8)
        log_box.pack(fill="both", expand=True)
        row = ui.frame(body, bg="bg")
        row.pack(fill="x", pady=(px(12), 0))
        q = queue.Queue()
        close_btn = Button(ui, row, text="Not now" if missing else "Close", kind="ghost", outer="bg", height=40,
                           command=win.destroy)
        close_btn.pack(side="right")
        install_btn = Button(ui, row, text="Install now", icon="download", kind="primary", outer="bg", height=40,
                             weight="bold", command=lambda: start())
        restart_btn = Button(ui, row, text="Restart RootsVoice", icon="refresh", kind="primary", outer="bg",
                             height=40, weight="bold", command=lambda: on_close(restart=True))
        if missing and not FROZEN:
            install_btn.pack(side="right", padx=(0, px(8)))

        def start():
            install_btn.configure(state="disabled")
            close_btn.configure(state="disabled")
            status.set("Installing\u2026 please keep RootsVoice open.")
            log_card.pack(fill="both", expand=True, pady=(px(8), 0), before=row)
            pkgs = [pip for pip, _, _ in missing]

            def worker():
                ok, msg = install_packages(pkgs, log=lambda line: q.put(("line", line)))
                q.put(("done", ok, msg))

            threading.Thread(target=worker, daemon=True).start()
            poll()

        def poll():
            try:
                while True:
                    item = q.get_nowait()
                    if item[0] == "line":
                        log_box.insert("end", item[1] + "\n")
                        log_box.see("end")
                    else:
                        _, ok, msg = item
                        status.set(msg)
                        write_log(msg)
                        close_btn.configure(state="normal", text="Close")
                        if ok:
                            install_btn.pack_forget()
                            restart_btn.pack(side="right", padx=(0, px(8)))
                        else:
                            install_btn.configure(state="normal", text="Try again")
                        return
            except queue.Empty:
                pass
            root.after(150, poll)

        return win
    rows(help_section("Voice commands"), [
        ("“John chapter 3 verse 16”", "Show that verse"),
        ("“Psalm 23”", "Show the chapter (no verse spoken)"),
        ("“Verse 5”  or  “Roots 5”", "Jump to verse 5 in this chapter"),
        ("“Chapter 4”", "Jump to chapter 4 in this book"),
        ("“Next verse”  or  “Roots next”", "One verse forward"),
        ("“Previous verse”  or  “Roots back”", "One verse back"),
        ("“Next chapter” / “Previous chapter”", "Change chapter"),
        ("“Clear the screen”", "Blank the screen (needs a Clear key in Settings, except FreeShow)")])
    b = help_section("Projection software")
    para(b, "Choose your program in Settings › Projection software, or press Detect while it is open. "
            "Then press Send a test verse.")
    rows(b, [("VideoPsalm", "Ready to go - RootsVoice uses its Ctrl+F search."),
             ("BibleShow", "Ready to go - RootsVoice presses F5 (BibleShow's reference shortcut), types the "
                           "reference and presses Enter."),
             ("EasyWorship, ProPresenter, OpenLP",
              "Open the program's Bible / scripture panel, press Point to it and hold the mouse over the box "
              "where you type a reference. RootsVoice clicks there each time."),
             ("FreeShow", "Turn on FreeShow's API (Settings › Connections). Nothing is typed, so FreeShow can "
                          "stay in the background."),
             ("Any other program", "Choose Other program, type part of its window title, then point to its "
                                   "reference box (or enter its search shortcut).")])
    para(b, "If the program's window moves, pointing still works. If its layout changes (another panel opened, "
            "a new version), press Point to it again.", fg="muted")
    b = help_section("Microphones")
    rows(b, [("Find active microphone", "Settings › Listening. Speak while it listens to every input, then "
                                        "press Use on the one that heard you."),
             ("Any microphone works", "Inputs that refuse RootsVoice's format (common with USB interfaces) are "
                                      "opened in a format they accept and converted automatically."),
             ("Unplugged?", "RootsVoice reconnects by itself when the microphone comes back."),
             ("Silent?", "After 20 seconds without sound, RootsVoice warns you to check mute switches."),
             ("Driver missing?", "RootsVoice asks Windows which sound devices have driver problems and offers "
                                 "Look for driver updates and Device Manager. Check setup shows them too."),
             ("Blocked by Windows?", "If Windows privacy settings block the microphone, RootsVoice says so and "
                                     "opens the right settings page."),
             ("No sounddevice library?", "RootsVoice records with Windows' own sound system instead - nothing to "
                                         "install."),
             ("Best sound", "A feed from the sound desk beats a room microphone.")])
    b = help_section("Moving through scripture in RootsAuto")
    para(b, "Most projection programs have no voice-friendly next / previous verse keys, so RootsVoice keeps "
            "track of where you are, works out the new reference and sends it. Use whichever suits you:")
    rows(b, [("Say it", "“Roots next”, “Roots back”, “Roots 18”"),
             ("Click", "The ‹ › arrows and verse numbers under the current verse"),
             ("Keyboard", "Ctrl+Alt+→ / ← from any window - your projection software can stay in front"),
             ("Clicker", "Turn on Presentation clicker in Settings: its forward / back buttons step verses"),
             ("Undo", "Back, or Ctrl+Alt+B, returns to the previous reference")])
    b = help_section("Keyboard shortcuts")
    para(b, "These work from any window while RootsVoice is open (Settings › Moving through scripture).",
         fg="muted")
    rows(b, [(lbl, ACTION_NAMES[act]) for _, _, _, act, lbl in HOTKEYS]
         + [(lbl + " (clicker)", ACTION_NAMES[act]) for _, _, _, act, lbl in CLICKER_KEYS])
    para(b, "If Ctrl+Alt+arrows turn the screen sideways, your graphics driver uses them: switch off its "
            "hotkeys in the graphics settings, or switch these shortcuts off.", fg="muted")
    b = help_section("RootsAuto")
    para(b, "With RootsAuto on, references and commands go on screen the moment the speaker pauses - no "
            "clicking. Ordinary preaching is ignored, impossible references such as “John 35” are "
            "never shown, and if a book name is misheard nothing is shown - pick from “Did you mean” "
            "instead. Turn it off (switch, or Ctrl+Alt+A) to check each verse before it goes on screen.")
    b = help_section("Training tips")
    rows(b, [("Listen & correct", "The quickest win. Say a reference, fix any wrong words, Save correction."),
             ("Practice prompts", "Read about 15 aloud, then Finish session. You can stop early."),
             ("Sound-alikes", "“John 3 this 16” is read as verse 16 automatically, and it learns "
                              "new ones from your corrections."),
             ("Re-learn", "After choosing a bigger Accuracy model, press Re-learn everything.")])
    rows(help_section("Troubleshooting"), [
        ("\u201cMissing package\u201d / faster-whisper", "Help \u203a Install missing components, or double-click "
                                                       "setup_rootsvoice.bat in the RootsVoice folder."),
        ("Stuck on Downloading", "First use needs internet. Press Download in Settings on a good connection; "
                                 "it resumes if interrupted."),
        ("Program not found", "Open your projection software, or check Settings › Projection software "
                              "(press Detect)."),
        ("Verse typed in the wrong place", "Open the program's Bible panel, then Point to it again."),
        ("Program comes to the front but nothing is typed", "It is probably running as administrator. Windows "
                                                            "then blocks other programs - run RootsVoice as "
                                                            "administrator too."),
        ("Mic bar doesn't move", "Settings › Listening › Find active microphone."),
        ("“Didn't catch the book name”", "Pick from Did you mean, or teach it in Training › "
                                                 "Listen & correct."),
        ("Wrong verse shown", "Press Back (Ctrl+Alt+B), then teach it in Training › Listen & correct."),
        ("Falling behind", "Choose a smaller Accuracy model in Settings."),
        ("Too big or small", "Settings › Display › Size.")])

    section_title(ui, hp, "ABOUT").pack(anchor="w", pady=(px(10), px(6)))
    about = Card(ui, hp, pad=18).pack(fill="x", pady=(0, gap))
    top = ui.frame(about.body)
    top.pack(fill="x")
    LogoBadge(ui, top, outer="surface", size=56).pack(side="left")
    name = ui.frame(top)
    name.pack(side="left", padx=(px(12), 0))
    ui.label(name, text="RootsVoice", size=15, weight="bold", display=True).pack(anchor="w")
    ui.label(name, text=f"Version {APP_VERSION}  ·  by {APP_PUBLISHER}", size=9, fg="muted").pack(anchor="w")
    para(about.body, "Voice-controlled scripture for VideoPsalm, BibleShow, EasyWorship, ProPresenter, OpenLP "
                     "and FreeShow. Speak a Bible reference and it appears on screen; step through verses by "
                     "voice, keyboard or clicker.")
    para(about.body, "Private by design: speech is turned into text on this computer and is never sent over "
                     "the internet. The only download is the speech model, once.", fg="muted")
    folder_row = ui.frame(about.body)
    folder_row.pack(fill="x", pady=(px(4), 0))
    ui.label(folder_row, text="Data folder: " + BASE_DIR, size=9, fg="muted", wrap=300).pack(side="left")

    def open_data_folder():
        try:
            os.startfile(BASE_DIR)
        except Exception:
            messagebox.showinfo("RootsVoice", "Your settings and training are kept in:\n" + BASE_DIR)

    Button(ui, folder_row, text="Open", icon="folder", kind="secondary", height=34, size=9,
           command=open_data_folder).pack(side="right")

    # ================= behaviour =================
    def current_settings():
        sep = " " if sep_var.get() == "space" else sep_var.get() or ":"
        try:
            delay = max(1, int(delay_var.get() or 3))
        except (ValueError, tk.TclError):
            delay = 3
        return {
            "window_title": title_var.get().strip() or DEFAULTS["window_title"],
            "search_hotkey": hotkey_var.get().strip() or DEFAULTS["search_hotkey"],
            "after_keys": after_var.get().strip(),
            "separator": sep,
            "model": model_var.get(),
            "mic": mic_var.get(),
            "mode": mode_var.get(),
            "auto_delay": delay,
            "always_on_top": bool(top_var.get()),
            "live_learning": bool(learn_var.get()),
            "roots_auto": bool(auto_var.get()),
            "next_key": next_key_var.get().strip(),
            "prev_key": prev_key_var.get().strip(),
            "clear_key": clear_key_var.get().strip(),
            "wake_word": bool(wake_var.get()),
            "show_all_speech": bool(show_all_var.get()),
            "theme": ui.name,
            "size": size_var.get().lower(),
            "global_keys": bool(keys_var.get()),
            "clicker": bool(clicker_var.get()),
            "target": current_target["id"],
            "focus": focus_var.get(),
            "click_x": pointer["x"],
            "click_y": pointer["y"],
            "api_port": profile_values()["api_port"],
            "api_key": api_key_var.get().strip(),
            "targets": {**saved_targets, current_target["id"]: profile_values()},
        }

    def apply_theme(name):
        ui.set_theme(name)
        theme_btn.configure(icon="sun" if name == "dark" else "moon")
        if dark_var.get() != (name == "dark"):
            dark_var.set(name == "dark")
        save_settings(current_settings())

    def set_status(text, tone=None):
        if tone is None:
            tone = ("live" if text.startswith("Listening") else "error" if text.startswith("Error")
                    else "idle" if text in ("Stopped", "Ready") else "busy")
        pill.set(text, tone)

    def write_log(msg):
        log.configure(state="normal")
        log.insert("end", time.strftime("%H:%M:%S  ") + msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    def toggle_learn_panel():
        if learn_var.get():
            learn_card.pack(fill="x", pady=(0, gap), before=recent_card.w)
            refresh_recent_list()
        else:
            learn_card.pack_forget()

    def on_auto_toggle():
        draw_auto()
        save_settings(current_settings())
        if auto_var.get():
            clear_pending("RootsAuto is on: references and commands are sent instantly.")
            write_log("RootsAuto ON")
        else:
            hint_var.set("RootsAuto paused: references wait for you to press Send.")
            write_log("RootsAuto OFF")

    # ---- model download / status
    def refresh_model_hint(event=None):
        name = model_var.get()
        if model_ready(name):
            model_hint.set(f"✓ {name} is ready on this computer.")
            dl_btn.configure(state="disabled")
        else:
            model_hint.set(f"{name} is not downloaded yet (about {MODEL_MB.get(name, '?')} MB, needs internet once). "
                           "Press Download, or just press Start listening and it downloads with progress shown.")
            dl_btn.configure(state="normal")

    def download_model_click():
        name = model_var.get()
        dl_btn.configure(state="disabled")

        def worker():
            try:
                ensure_model(name, lambda m: events.put(("progress", m)))
                events.put(("model_ready", name))
            except Exception as e:
                events.put(("error", str(e)))
                events.put(("model_ready", None))

        threading.Thread(target=worker, daemon=True).start()

    model_box.bind("<<ComboboxSelected>>", refresh_model_hint)
    refresh_model_hint()

    # ---- history
    def render_history():
        for child in hist_rows.winfo_children():
            child.destroy()
        if not history:
            ui.label(hist_rows, text="Nothing shown yet.", size=10, fg="muted").pack(anchor="w", pady=px(6))
            return
        for i, (ref, at) in enumerate(history[:5]):
            if i:
                line = ui.frame(hist_rows, bg="line")
                line.configure(height=1)
                line.pack(fill="x")
            row = ui.frame(hist_rows)
            row.pack(fill="x")
            a = ui.label(row, text=ref, size=10, weight="bold" if i == 0 else "normal")
            a.pack(side="left", pady=px(7))
            b = ui.label(row, text=at, size=9, fg="muted")
            b.pack(side="right")
            for w in (row, a, b):
                w.bind("<Double-Button-1>", lambda e, ref=ref: resend(ref))

    def add_history(ref):
        history[:] = [h for h in history if h[0] != ref]
        history.insert(0, (ref, time.strftime("%H:%M")))
        del history[HISTORY_SIZE:]
        render_history()

    def resend(ref):
        tracker.separator = current_settings()["separator"]
        tracker.parse(ref)
        write_log(f"Showing again: {ref}")
        clear_pending("Sending...")
        do_send(ref)
        show_suggestions(build_suggestions(tracker))

    def go_back():
        if len(history) < 2:
            hint_var.set("Nothing earlier to go back to yet.")
            return
        resend(history[1][0])

    # ---- suggestions
    def chip_for(s):
        label, kind, icon, after = s["label"], "chip", None, False
        if s["action"] == "fill":
            label = s["label"]
        elif label.startswith("Next: "):
            label, kind, icon, after = label[6:], "chip_accent", "arrow_r", True
        elif label.startswith("Previous: "):
            label, icon = label[10:], "arrow_l"
        elif label.startswith("Whole chapter: "):
            label = "Whole chapter"
        elif label.startswith("Next chapter: "):
            label = label[14:]
        elif label.startswith("Did you mean"):
            kind = "chip_accent"
        return Button(ui, flow.w, text=label, icon=icon, icon_after=after, kind=kind, outer="bg", height=34,
                      radius=17, size=10, command=lambda s=s: pick(s))

    def show_suggestions(items):
        render_strip()
        flow.clear()
        for s in items:
            flow.add(chip_for(s))
        if items:
            sug_hint.pack_forget()
        else:
            sug_hint.pack(anchor="w", after=flow.w)

    def pick(s):
        if s["action"] == "fill":
            manual_var.set(s["fill"])
            manual_entry.focus_set()
            manual_entry.icursor("end")
            return
        ref = s["ref"]
        if s.get("learn"):
            alias, book = s["learn"]
            if add_aliases({alias: book}):
                write_log(f"Learned: '{alias}' = {book}")
        tracker.separator = current_settings()["separator"]
        tracker.parse(ref)  # make this the new context for "next verse" etc.
        clear_pending("Sending...")
        do_send(ref)
        show_suggestions(build_suggestions(tracker))

    def on_manual_key(event=None):
        comps = book_completions(manual_var.get())
        if comps:
            show_suggestions([{"label": b, "action": "fill", "fill": b + " "} for b in comps])
        elif not manual_var.get().strip():
            show_suggestions(build_suggestions(tracker))

    manual_box.bind("<KeyRelease>", on_manual_key)
    manual_box.bind("<Return>", lambda e: send_manual())

    # ---- stepping through scripture (buttons, shortcuts, clicker)
    def navigate(kind, n=None, source=""):
        if not tracker.book:
            hint_var.set("Say or type a reference first, then step through it.")
            return
        tracker.separator = current_settings()["separator"]
        ref = tracker.step(kind, n)
        if not ref:
            hint_var.set("Can't go any further that way.")
            return
        s = current_settings()
        keys = s["next_key"] if kind == "next" else s["prev_key"] if kind == "prev" else ""
        state["last_ref"], state["last_time"] = ref, time.time()
        write_log(f"{ACTION_NAMES.get(kind, 'Verse')}{' (' + source + ')' if source else ''}: {ref}")
        clear_pending("Sending...")
        show_now("SENDING", ref)
        do_send(ref, keys)
        show_suggestions(build_suggestions(tracker))

    hotkeys = {"thread": None}

    def restart_hotkeys():
        if hotkeys["thread"]:
            hotkeys["thread"].stop()
            hotkeys["thread"] = None
        binds = (HOTKEYS if keys_var.get() else []) + (CLICKER_KEYS if clicker_var.get() else [])
        if binds:
            t = GlobalHotkeys(binds, lambda a: events.put(("hotkey", a)), lambda m: events.put(("hotkeys_status", m)))
            hotkeys["thread"] = t
            t.start()

    def on_size_change():
        save_settings(current_settings())
        if messagebox.askyesno("RootsVoice", "Restart RootsVoice now to use the new size?"):
            on_close(restart=True)

    # ---- the "now showing" card
    def show_now(caption, ref, pending=False):
        caption_var.set(caption)
        ref_var.set(ref or "—")
        now.set_look(border="accent" if pending else "border")
        ui.retheme(caption_lbl, fg="accent_soft_text" if pending else "muted")
        layout_actions(pending)

    def clear_pending(hint="Listening for the next reference or command..."):
        if state["countdown_job"]:
            root.after_cancel(state["countdown_job"])
            state["countdown_job"] = None
        state["pending"] = None
        if state["showing"]:
            show_now("NOW SHOWING", state["showing"])
        else:
            show_now("READY", None)
        hint_var.set(hint)
        send_btn.configure(state="disabled")
        skip_btn.configure(state="disabled")

    def do_send(ref, keys=""):
        """Show `ref` in the projection software: press `keys` if given (next/previous key), else type it."""
        s = current_settings()
        if target_profile(s)["kind"] == "freeshow":
            keys = ""            # FreeShow always gets the full reference

        def worker():
            if keys:
                ok, msg = press_in_target(keys, s, f"Sent {ref} (key '{keys}')")
            else:
                ok, msg = send_reference(ref, s)
            events.put(("sent", ref, msg) if ok else ("error", msg))

        threading.Thread(target=worker, daemon=True).start()

    def auto_send(ref, action):
        """RootsAuto: act at once, no confirmation."""
        s = current_settings()
        keys = s["next_key"] if action == "next" else s["prev_key"] if action == "prev" else ""
        clear_pending(f"RootsAuto sending {ref}...")
        show_now("SENDING", ref)
        state["last_auto"] = time.time()
        do_send(ref, keys)

    def do_clear(by_voice=False):
        s = current_settings()
        keys = s["clear_key"]
        if not keys and target_profile(s)["kind"] != "freeshow":
            msg = "Set a 'Clear screen key' in Settings to use Clear."
            hint_var.set(msg)
            if not by_voice:
                messagebox.showinfo("RootsVoice", msg)
            return

        def worker():
            ok, msg = press_in_target(keys, current_settings(), "Screen cleared", api_action="clear_all")
            events.put(("cleared", msg) if ok else ("error", msg))

        threading.Thread(target=worker, daemon=True).start()

    def send_pending():
        ref = state["pending"]
        if not ref:
            return
        clear_pending("Sending...")
        do_send(ref)

    def skip_pending():
        if state["pending"]:
            write_log(f"Skipped {state['pending']}")
        clear_pending()

    def tick(remaining):
        if not state["pending"]:
            return
        if remaining <= 0:
            send_pending()
            return
        hint_var.set(f"Sending in {remaining}s – press Skip to cancel")
        state["countdown_job"] = root.after(1000, tick, remaining - 1)

    def set_pending(ref):
        if state["countdown_job"]:
            root.after_cancel(state["countdown_job"])
            state["countdown_job"] = None
        state["pending"] = ref  # replaces any earlier pending reference
        show_now("READY TO SEND", ref, pending=True)
        send_btn.configure(state="normal")
        skip_btn.configure(state="normal")
        s = current_settings()
        if s["mode"] == "auto":
            tick(s["auto_delay"])
        else:
            hint_var.set(f"Heard just now \u2013 press Send to show it in {target_name(current_settings())}")

    def send_manual(event=None):
        text = manual_var.get().strip()
        if not text:
            return
        tracker.separator = current_settings()["separator"]
        ref = tracker.parse(text, text) or text
        manual_var.set("")
        write_log(f"Typed: {ref}")
        clear_pending("Sending...")
        do_send(ref)
        show_suggestions(build_suggestions(tracker))

    # ---- live learning: tell RootsVoice what was really said
    recent = []            # newest first: (heard text, text incl. previous tail, audio)
    teach = {"target": None}

    def refresh_recent_list():
        recent_list.delete(0, "end")
        for item in recent:
            recent_list.insert("end", "  " + item[0][:80])
        if recent:
            recent_list.selection_set(next((i for i, it in enumerate(recent) if it is teach["target"]), 0))

    def on_recent_pick(event=None):
        sel = recent_list.curselection()
        if sel and sel[0] < len(recent):
            teach["target"] = recent[sel[0]]

    recent_list.bind("<<ListboxSelect>>", on_recent_pick)

    def learn_and_send(event=None):
        if not recent:
            messagebox.showinfo("RootsVoice", "Nothing has been heard yet - press Start listening first.")
            return
        heard, combined, audio = next((it for it in recent if it is teach["target"]), recent[0])
        sep = current_settings()["separator"]
        wanted = teach_var.get().strip()
        t = RefTracker(sep)
        ref = t.parse(wanted, wanted)
        if not ref:
            messagebox.showinfo("RootsVoice", "Type the correct reference, for example "
                                              "'First Peter 2:9' or 'Habakkuk 2:4'.")
            return
        book, ch, verse = t.book, t.ch, t.v1
        heard_t = RefTracker(sep)
        heard_ref = heard_t.parse(combined)
        if heard_ref == ref:
            note = "It had already heard that correctly."
        elif heard_t.book == book:
            note = "It understood the book but misheard the numbers - nothing to learn about spelling."
        else:
            phrase = learn_phrase(combined, book, ch)
            if not phrase:  # couldn't work it out: ask which words were the book name
                answer = simpledialog.askstring(
                    "Teach RootsVoice",
                    f'It heard:\n"{heard}"\n\nWhich words did it hear instead of "{spoken_name(book)}"?\n'
                    "Type them exactly as shown above:", parent=root)
                phrase = " ".join(words_to_digits(answer or "").split())
            if not phrase:
                note = "Nothing learned (no words entered)."
            elif add_aliases({phrase: book}):
                note = f"Learned: '{phrase}' = {book}."
                write_log(note)
            else:
                note = f"'{phrase}' was already known."
        if audio is not None:
            try:
                save_correction(audio, heard, ref)
            except Exception as e:
                write_log(f"(could not keep the audio: {e})")
        if add_prompt_for_book(book, ch, verse):
            note += " Added to your practice prompts."
            if state["training"]:
                state["training"].reload_prompts()
        teach["target"] = None
        teach_var.set("")
        tracker.separator = sep
        tracker.parse(ref)
        clear_pending("Sending...")
        do_send(ref)
        show_suggestions(build_suggestions(tracker))
        hint_var.set(f"{note} Sent {ref}.")

    teach_box.bind("<Return>", learn_and_send)

    # ---- start / stop
    def start():
        s = current_settings()
        save_settings(s)
        tracker.reset()
        state["ignored"] = 0
        update_activity_label()
        eng = Engine(events, s["model"], s["mic"])
        state["engine"] = eng
        eng.start()
        start_btn.configure(text="Stop listening", icon="stop")
        set_status("Starting…", "busy")
        write_log("Starting...")

    def stop():
        eng = state["engine"]
        if eng:
            eng.stop_flag.set()
        state["engine"] = None
        start_btn.configure(text="Start listening", icon="mic")
        set_status("Stopped", "idle")
        meter.set(0)
        clear_pending("Stopped. Press Start listening to continue.")

    def toggle():
        stop() if state["engine"] else start()

    # ---- training screen
    state["training"] = TrainingTab(ui, pages["training"].body, root, current_settings,
                                    lambda: bool(state["engine"]), write_log, filedialog, messagebox)

    # ---- event pump (runs on the GUI thread, so it owns all state)
    def pump():
        try:
            while True:
                ev = events.get_nowait()
                kind = ev[0]
                if kind == "progress":
                    set_status(ev[1], "busy")
                elif kind == "status":
                    set_status(ev[1])
                    write_log(ev[1])
                elif kind == "model_ready":
                    refresh_model_hint()
                    if ev[1]:
                        set_status("Ready", "idle")
                        write_log(f"Model '{ev[1]}' is ready")
                elif kind == "level":
                    meter.set(ev[1] * 10)
                elif kind == "warn":
                    write_log("WARNING: " + ev[1])
                    hint_var.set(ev[1])
                elif kind == "log":
                    write_log(ev[1])
                elif kind == "setup_result":
                    lines, issues = ev[1], ev[2]
                    lines = lines + [(False, i["title"]) for i in issues
                                     if not any(i["title"] in m for _, m in lines)]
                    good = all(ok for ok, _ in lines)
                    set_status("Listening" if state["engine"] else "Stopped", "live" if state["engine"] else "idle")
                    messagebox.showinfo("Check setup", ("Everything is ready.\n\n" if good else
                                                        "Almost there - see the items marked \u2715.\n\n")
                                        + "\n".join(("\u2713  " if ok else "\u2715  ") + msg for ok, msg in lines))
                    if issues:
                        show_mic_notice(issues)
                elif kind == "mic_health":
                    if ev[1]:
                        show_mic_notice(ev[1])
                elif kind == "text":
                    s = current_settings()
                    combined, fresh = ev[1], ev[2]
                    snippet = scripture_snippet(fresh)
                    related = snippet or scripture_snippet(combined)
                    if s["show_all_speech"]:
                        write_log(f'Heard: "{fresh}"')
                    elif snippet:
                        write_log(f'Heard: "{snippet}"')
                    if not related:
                        state["ignored"] += 1  # unrelated preaching: ignored
                        update_activity_label()
                    else:
                        recent.insert(0, (related, combined, ev[3] if len(ev) > 3 else None))
                        del recent[8:]
                        if learn_var.get():
                            refresh_recent_list()
                    tracker.separator = s["separator"]
                    tracker.require_wake = s["wake_word"]
                    ref = tracker.parse(combined, fresh)
                    if tracker.clear:
                        if auto_var.get():
                            do_clear(by_voice=True)
                        else:
                            hint_var.set("Heard “clear the screen” – press Clear to do it.")
                    if ref:
                        now_t = time.time()
                        if (tracker.action not in ("next", "prev", "next_ch", "prev_ch")
                                and ref == state["last_ref"] and now_t - state["last_time"] < REPEAT_WINDOW):
                            continue
                        state["last_ref"], state["last_time"] = ref, now_t
                        if auto_var.get():
                            auto_send(ref, tracker.action)
                        else:
                            set_pending(ref)
                        show_suggestions(build_suggestions(tracker))
                    elif related or tracker.unclear:
                        near = scan_near_misses(combined, guesses=3)
                        if near:
                            hint_var.set("Didn't catch the book name \u2013 is it one of these?")
                            show_suggestions(build_suggestions(tracker, near, predict=False))
                        elif tracker.unclear:
                            hint_var.set("Didn't catch the book name \u2013 say it again, or type it below.")
                        if tracker.unclear:
                            write_log("Book name not recognised - nothing sent")
                elif kind == "cleared":
                    write_log(ev[1])
                    hint_var.set("Screen cleared.")
                elif kind == "hotkey":
                    action = ev[1]
                    if action in ("next", "prev", "next_ch", "prev_ch"):
                        navigate(action, source="shortcut")
                    elif action == "back":
                        go_back()
                    elif action == "auto":
                        auto_var.set(not auto_var.get())
                        on_auto_toggle()
                    elif action == "listen":
                        toggle()
                elif kind == "hotkeys_status":
                    write_log(ev[1])
                elif kind == "sent":
                    write_log(ev[2])
                    add_history(ev[1])
                    state["showing"] = ev[1]
                    state["last_ref"], state["last_time"] = ev[1], time.time()
                    if not state["pending"]:
                        show_now("NOW SHOWING", ev[1])
                        hint_var.set(("Shown by RootsAuto" if auto_var.get() else "Sent")
                                     + f" at {time.strftime('%H:%M')}")
                elif kind == "error":
                    write_log("ERROR: " + ev[1])
                    set_status("Error \u2013 see Activity", "error")
                    hint_var.set(ev[1][:160])
                    if "missing package" in ev[1].lower() and not FROZEN:
                        show_components_dialog()       # offer to install it right here
                    elif "microphone" in ev[1].lower() or "sounddevice" in ev[1].lower():
                        check_mic_health_later()      # driver missing? privacy? no mic? - say how to fix it
                    eng = state["engine"]
                    if eng is not None and eng.failed:
                        state["engine"] = None
                        start_btn.configure(text="Start listening", icon="mic")
        except queue.Empty:
            pass
        root.after(150, pump)

    def on_close(restart=False):
        save_settings(current_settings())
        if state["engine"]:
            state["engine"].stop_flag.set()
        if hotkeys["thread"]:
            hotkeys["thread"].stop()
        root.destroy()
        if restart:
            os.execv(sys.executable, [sys.executable] + (sys.argv[1:] if FROZEN else sys.argv))

    root.protocol("WM_DELETE_WINDOW", lambda: on_close())
    show_page("live")
    if needs_install():
        root.after(500, show_components_dialog)      # e.g. faster-whisper missing: offer to install it now
    apply_target_ui()
    restart_hotkeys()
    toggle_learn_panel()
    render_history()
    clear_pending("Press Start listening, then speak a Bible reference.")
    show_suggestions([])
    set_status("Stopped", "idle")
    pump()
    write_log(f"Ready. Open {target_name(current_settings())}, then press Start listening.")
    root.mainloop()


if __name__ == "__main__":
    if "--test" in sys.argv:
        t = RefTracker()
        for phrase in sys.argv[sys.argv.index("--test") + 1].split("|"):
            print(f"{phrase.strip()!r:55} -> {t.parse(phrase)}")
    elif "--scan" in sys.argv:
        print(scan_near_misses(sys.argv[sys.argv.index("--scan") + 1]))
    elif "--check-deps" in sys.argv:              # used by setup_rootsvoice.bat
        lines = component_lines()
        for ok, msg in lines:
            print(("  OK   " if ok else "  FIX  ") + msg)
        note = python_version_note()
        if note:
            print("  NOTE " + note)
        sys.exit(0 if all(ok for ok, _ in lines) else 1)
    elif "--make-shortcut" in sys.argv:           # used by setup_rootsvoice.bat
        ok, msg = make_desktop_shortcut()
        print(msg)
        sys.exit(0 if ok else 1)
    elif "--install" in sys.argv:                 # install whatever is missing
        ok, msg = install_packages([p for p, _, _ in missing_dependencies()], log=print)
        print(msg)
        sys.exit(0 if ok else 1)
    elif "--download-model" in sys.argv:          # used by build_installer.bat
        i = sys.argv.index("--download-model")
        name = sys.argv[i + 1] if len(sys.argv) > i + 1 else "base.en"
        if len(sys.argv) > i + 2:
            MODELS_DIR = os.path.abspath(sys.argv[i + 2])
        BUNDLED_MODELS_DIR = os.path.join(MODELS_DIR, "_none_")
        try:
            print("Model ready in", ensure_model(name, lambda m: print(m, flush=True)))
        except Exception as e:
            print("Model download failed:", e)
            sys.exit(1)
    else:
        run_gui()
