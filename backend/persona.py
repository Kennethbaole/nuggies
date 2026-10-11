"""Per-contact personality from the user's own past conversations.

A chat export between the user and one contact is reduced to a local profile:
how the user writes to that person (a short style note) and real exchanges
(they said -> the user replied). For each request the exchanges closest to what
was just heard are handed to the local model as examples, so replies sound like
the user talking to that particular person. Contacts without a profile use the
"default" profile when one exists, otherwise the curated phrases.

Profiles are private: config/persona.<contact>.local.json is Git-ignored, and
the only model that receives them runs on this device. Nothing is trained
here; training_rows() exports the same exchanges for fine-tuning later.

The Community page now personalizes with descriptive notes instead
(backend/community.py); these conversation profiles are used by the CLI tools
scripts.import_chat and scripts.try_suggest only.
Standard library only.
"""

import io
import json
import math
import re
import statistics
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSONA_DIR = ROOT / "config"
DEFAULT_ID = "default"
MAX_TURN_CHARS = 200     # Longer turns are stories or pasted text, not reply style.
MAX_PAIRS = 2000
MAX_OPENERS = 200
MAX_CHAT_BYTES = 8_000_000
EXAMPLE_COUNT = 4

# "[10/9/26, 9:41:22 PM] Name: text" and "10/9/26, 9:41 PM - Name: text" (WhatsApp exports).
STAMPED = re.compile(r"^‎?\[?\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4},? [^\]\-]{3,24}?(?:\]| -) (?P<rest>.*)$")
SPEAKER = re.compile(r"^(?P<name>[^:\n]{1,40}): ?(?P<text>.*)$")
SKIPPED = re.compile(r"omitted>?$|^<attached:|^‎|^https?://\S+$|^(?:image|video|audio|sticker|gif)$", re.IGNORECASE)
WORD = re.compile(r"[a-z0-9']+")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
COMMON = frozenset("a an and are as at be but do for i in is it me my of on or so that the this to we you your".split())


def chat_text(data):
    """Text of an uploaded export: a text file, or the chat inside a WhatsApp .zip."""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                chats = [item for item in archive.infolist() if item.filename.lower().endswith(".txt")]
                if not chats:
                    raise ValueError("No .txt chat file inside this zip")
                chat = max(chats, key=lambda item: item.file_size)
                if chat.file_size > MAX_CHAT_BYTES:
                    raise ValueError("The chat file is larger than 8 MB; export a shorter period")
                data = archive.read(chat)
        except zipfile.BadZipFile as error:
            raise ValueError("This zip file could not be opened") from error
    if not data or len(data) > MAX_CHAT_BYTES:
        raise ValueError("The chat file must be between 1 byte and 8 MB")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("The chat file must be plain UTF-8 text") from error


def speaker_counts(text):
    """Who appears in an export and how often, so the user can say which name is theirs."""
    counts = Counter(name for name, _ in parse_chat(text))
    return [dict(name=name, messages=count) for name, count in counts.most_common(12)]


def parse_chat(text):
    """Return [(sender, message)] from a chat export; unlabeled lines continue the previous message."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # In undated "Name: text" files a message may itself contain a colon, so only
    # prefixes that recur across the file count as speakers.
    labels = Counter(match.group("name").strip() for match in map(SPEAKER.match, lines) if match)
    speakers = {name for name, count in labels.items() if count >= max(2, sum(labels.values()) // 20)}
    messages = []
    for line in lines:
        stamped = STAMPED.match(line)
        match = SPEAKER.match(stamped.group("rest") if stamped else line)
        if match and (stamped or match.group("name").strip() in speakers):
            messages.append((match.group("name").strip(), match.group("text").strip()))
        elif stamped:
            continue  # A dated system notice such as "Messages are end-to-end encrypted".
        elif messages:
            name, body = messages[-1]
            messages[-1] = (name, f"{body} {line}".strip())
    return [(name, body) for name, body in messages if body and not SKIPPED.search(body)]


def turns(messages):
    """Merge consecutive messages from one sender into a single turn."""
    merged = []
    for name, body in messages:
        if merged and merged[-1][0] == name:
            merged[-1] = (name, f"{merged[-1][1]} {body}")
        else:
            merged.append((name, body))
    return merged


def style_note(replies):
    """Describe measurable habits only; an empty note is better than a guess."""
    if len(replies) < 5:
        return ""
    words = statistics.median(len(text.split()) for text in replies)
    share = lambda test: sum(1 for text in replies if test(text)) / len(replies)
    notes = [f"usually about {round(words)} words"]
    if share(lambda text: text[:1].islower()) > 0.6:
        notes.append("mostly starts in lowercase")
    if share(lambda text: text[-1:] in ".!?") < 0.3:
        notes.append("rarely ends with punctuation")
    if share(lambda text: "!" in text) > 0.3:
        notes.append("often uses exclamation marks")
    if share(lambda text: bool(EMOJI.search(text))) > 0.2:
        notes.append("often uses emoji")
    return ", ".join(notes)


def build_persona(text, me, contact_id, source=""):
    """Reduce a chat export to the profile stored for one contact."""
    messages = parse_chat(text)
    senders = {name for name, _ in messages}
    if me not in senders:
        found = ", ".join(sorted(senders)) or "none"
        raise ValueError(f'No messages from "{me}" in this file; names found: {found}')
    pairs, openers, previous = [], [], None
    for name, body in turns(messages):
        if name == me and len(body) <= MAX_TURN_CHARS:
            if previous and len(previous) <= MAX_TURN_CHARS:
                pairs.append(dict(them=previous, me=body))
            else:
                openers.append(body)
        previous = None if name == me else body
    replies = [pair["me"] for pair in pairs] + openers
    if not replies:
        raise ValueError(f'"{me}" has no usable messages in this file')
    return dict(contact_id=contact_id, me=me, source=source, note=style_note(replies),
                pairs=pairs[-MAX_PAIRS:], openers=openers[-MAX_OPENERS:])


def tokens(text):
    return {word for word in WORD.findall(text.lower()) if word not in COMMON}


def similar_pairs(persona, heard_text, count=EXAMPLE_COUNT):
    """Past exchanges whose prompt shares the rarest words with what was heard."""
    pairs = persona.get("pairs", [])
    heard = tokens(heard_text or "")
    if not heard or not pairs:
        return []
    keyed = [tokens(pair["them"]) for pair in pairs]
    seen = Counter(word for words in keyed for word in words)
    scored = []
    for index, words in enumerate(keyed):
        shared = heard & words
        if shared:
            weight = sum(math.log(1 + len(pairs) / seen[word]) for word in shared)
            scored.append((weight / math.sqrt(len(words)), index))
    chosen, used = [], set()
    for _, index in sorted(scored, key=lambda item: (-item[0], -item[1])):  # Ties: newest first.
        reply = pairs[index]["me"].lower()
        if reply not in used:
            used.add(reply)
            chosen.append(pairs[index])
        if len(chosen) == count:
            break
    return chosen


def persona_context(persona, heard_text, count=EXAMPLE_COUNT):
    """What the model is shown: the style note plus the closest exchanges, topped up with recent ones."""
    examples = similar_pairs(persona, heard_text, count)
    used = {pair["me"].lower() for pair in examples}
    for pair in reversed(persona.get("pairs", [])):
        if len(examples) == count:
            break
        if pair["me"].lower() not in used:
            used.add(pair["me"].lower())
            examples.append(pair)
    return dict(note=persona.get("note", ""), examples=examples)


def training_rows(persona, contact_name, system_prompt=""):
    """Chat-format rows (one per exchange) for fine-tuning a model on this contact later."""
    system = system_prompt or f"You are replying to {contact_name} exactly as the user would."
    return [dict(messages=[dict(role="system", content=system), dict(role="user", content=pair["them"]),
                           dict(role="assistant", content=pair["me"])]) for pair in persona.get("pairs", [])]


def persona_path(contact_id, folder=None):
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", contact_id or ""):
        raise ValueError("Contact id must be lowercase letters, digits, - or _")
    return Path(folder or PERSONA_DIR) / f"persona.{contact_id}.local.json"


def save_persona(persona, folder=None, replace=False):
    path = persona_path(persona["contact_id"], folder)
    with path.open("w" if replace else "x", encoding="utf-8") as stream:
        json.dump(persona, stream, indent=1, ensure_ascii=False)
        stream.write("\n")
    return path


class PersonaStore:
    """Loads profiles on demand and reloads one when its file changes."""

    def __init__(self, folder=None):
        self.folder = Path(folder or PERSONA_DIR)
        self.cache = {}

    def load(self, contact_id):
        try:
            path = persona_path(contact_id, self.folder)
            stamp = path.stat().st_mtime_ns
        except (ValueError, OSError):
            return None
        cached = self.cache.get(contact_id)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            persona = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(persona, dict) or not isinstance(persona.get("pairs"), list):
            return None
        self.cache[contact_id] = (stamp, persona)
        return persona

    def context(self, contact_id, heard_text):
        """Profile for this contact, else the default one, else None (curated phrases apply)."""
        persona = self.load(contact_id) or self.load(DEFAULT_ID)
        return persona_context(persona, heard_text) if persona else None

    def describe(self, contact_id):
        """This contact's own profile for the contacts page (no default fallback)."""
        persona = self.load(contact_id)
        if persona is None:
            return None
        return dict(exchanges=len(persona["pairs"]), note=persona.get("note", ""),
                    me=persona.get("me", ""), source=persona.get("source", ""))

    def remove(self, contact_id):
        """Delete the derived profile; the original export is never touched."""
        path = persona_path(contact_id, self.folder)
        self.cache.pop(contact_id, None)
        if not path.is_file():
            raise ValueError("This contact has no profile")
        path.unlink()

    def summary(self, contact_id):
        """For the interface: which profile applies and how much it knows."""
        for name in (contact_id, DEFAULT_ID):
            persona = self.load(name)
            if persona:
                return dict(profile=name, exchanges=len(persona["pairs"]))
        return None

