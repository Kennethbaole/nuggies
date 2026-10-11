"""Community: the people the user talks with, and a short note about each.

A member is a name and a relationship. Anything else (pronouns, nicknames, how
the user likes to speak with them, topics they share) goes in a plain-text
notes file the user uploads per member. The notes are given to the reply model
alongside the live conversation as background for wording and tone; nothing is
trained. Members without notes use the default speaking style.

Everything is kept in Git-ignored files under config/: members in
community.local.json (contacts.local.json from earlier versions is still read),
notes in notes.<member>.local.json. Standard library only.
"""

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
MAX_LOCAL_MEMBERS = 20
MAX_NOTES_CHARS = 2000   # A paragraph or two; small local models get slower with every token.
MAX_NOTES_BYTES = 32_000
RESERVED_IDS = frozenset({"default"})
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def notes_text(data):
    """Clean text of an uploaded notes file, or ValueError with a message for the page."""
    if not data.strip():
        raise ValueError("This file is empty")
    if len(data) > MAX_NOTES_BYTES or data[:2] == b"PK":
        raise ValueError(f"Notes must be a short .txt file (at most {MAX_NOTES_CHARS:,} characters)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Notes must be plain text saved as UTF-8") from error
    if "\x00" in text:
        raise ValueError("Notes must be plain text saved as UTF-8")
    text = CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not text:
        raise ValueError("This file is empty")
    if len(text) > MAX_NOTES_CHARS:
        raise ValueError(f"Notes can be at most {MAX_NOTES_CHARS:,} characters; this file has {len(text):,}. "
                         "Keep the details that matter most for how you speak with them.")
    return text


def notes_path(member_id, folder=None):
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", member_id or ""):
        raise ValueError("Member id must be lowercase letters, digits, - or _")
    return Path(folder or CONFIG_DIR) / f"notes.{member_id}.local.json"


class NotesStore:
    """Notes per member, loaded on demand and reloaded when a file changes."""

    def __init__(self, folder=None):
        self.folder = Path(folder or CONFIG_DIR)
        self.cache = {}

    def load(self, member_id):
        """{text, source, updated} for this member, or None."""
        try:
            path = notes_path(member_id, self.folder)
            stamp = path.stat().st_mtime_ns
        except (ValueError, OSError):
            return None
        cached = self.cache.get(member_id)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            notes = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(notes, dict) or not isinstance(notes.get("text"), str) or not notes["text"].strip():
            return None
        notes = dict(text=notes["text"], source=str(notes.get("source") or ""), updated=notes.get("updated"))
        self.cache[member_id] = (stamp, notes)
        return notes

    def text(self, member_id):
        notes = self.load(member_id)
        return notes["text"] if notes else ""

    def save(self, member_id, text, source=""):
        """Store notes (replacing any earlier ones); written via a temporary file so a crash keeps the old notes."""
        path = notes_path(member_id, self.folder)
        notes = dict(text=text, source=Path(str(source or "")).name[:80], updated=int(time.time()))
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(notes, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
        self.cache.pop(member_id, None)
        return notes

    def remove(self, member_id):
        path = notes_path(member_id, self.folder)
        self.cache.pop(member_id, None)
        if not path.is_file():
            raise ValueError("This member has no notes")
        path.unlink()


PROFILE_LIMITS = dict(relationship=30, gender=30, pronouns=20)
TONES = 6  # Profile colours; frontend/styles.css defines .avatar[data-tone="0".."5"].


def profile_fields(payload):
    """Validated profile edits: label, gender and pronouns (free text, may be blank
    except the label) and a colour index, or None for the automatic colour."""
    fields = {}
    for key, limit in PROFILE_LIMITS.items():
        value = payload.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} must be text")
        fields[key] = " ".join(value.split())[:limit]
    if not fields["relationship"]:
        raise ValueError("Choose a label, such as Friend or Family")
    tone = payload.get("tone")
    if tone is not None and (not isinstance(tone, int) or isinstance(tone, bool) or not 0 <= tone < TONES):
        raise ValueError("Unknown profile colour")
    fields["tone"] = tone
    return fields


def member_id_for(name, taken):
    """A stable lowercase id from a display name, unique among existing members."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "member"
    candidate, number = base, 2
    while candidate in taken or candidate in RESERVED_IDS:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


class MemberBook:
    """Members added on this device, kept in config/community.local.json (Git-ignored)."""

    def __init__(self, folder=None):
        folder = Path(folder or CONFIG_DIR)
        self.path = folder / "community.local.json"
        self.legacy_path = folder / "contacts.local.json"  # Written by the earlier People page.
        # Edits to any member, including the defaults in config/phrases.json, which stay untouched.
        self.profiles_path = folder / "profiles.local.json"

    def load_profiles(self):
        try:
            profiles = json.loads(self.profiles_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(profiles, dict):
            return {}
        valid = {}
        for member_id, fields in profiles.items():
            try:
                valid[member_id] = profile_fields(fields if isinstance(fields, dict) else {})
            except ValueError:
                continue
        return valid

    def apply_profiles(self, members):
        """Members with their saved edits applied (new dicts; the input is not changed)."""
        profiles = self.load_profiles()
        return [dict(member, **profiles.get(member["id"], {})) for member in members]

    def save_profile(self, member_id, fields):
        profiles = self.load_profiles()
        profiles[member_id] = fields
        temporary = self.profiles_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(profiles, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.profiles_path)

    def load(self):
        path = self.path if self.path.exists() else self.legacy_path
        try:
            members = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(members, list):
            return []
        keys = ("id", "name", "relationship", "initials")
        return [{key: member[key] for key in keys} for member in members
                if isinstance(member, dict) and all(isinstance(member.get(key), str) for key in keys)]

    def add(self, name, relationship, existing):
        """Validate and store a new member; existing is every member already shown."""
        name = " ".join(str(name or "").split())[:40]
        relationship = " ".join(str(relationship or "").split())[:30] or "Friend"
        if not name:
            raise ValueError("Enter a name")
        if name.lower() in {member["name"].lower() for member in existing}:
            raise ValueError("Someone with this name is already in your community")
        local = self.load()
        if len(local) >= MAX_LOCAL_MEMBERS:
            raise ValueError("Your community list is full")
        initials = "".join(word[0] for word in name.split()[:2]).upper() if " " in name else name[:2].upper()
        member = dict(id=member_id_for(name, {member["id"] for member in existing}), name=name,
                      relationship=relationship, initials=initials)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(local + [member], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return member
