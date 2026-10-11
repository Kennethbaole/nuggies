"""Authoritative wheel state, shared by companion UI, HUD and input adapters."""

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config" / "phrases.json"
PHRASE_SLOTS = (0, 1, 2, 3, 5)  # Slot 4 is always the bottom Back position.


class RingState:
    def __init__(self, config=None):
        self.config = config or json.loads(CONFIG.read_text())
        self.contact = self.config["contacts"][0]["id"]
        self.cardinal_layout = False
        self.screen = "home"
        self.selected = 0
        self.pages = {"home": 0, "needs": 0}
        self.draft = ""
        self.letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        self.letter_stack = []
        self.return_screen = "home"
        self.confirmed = ""
        self.selection_id = 0
        self.revision = 0
        self.last_source = "keyboard"
        self.history = []
        self.suggested = None  # Model replies replacing the Home phrase pool, if any.
        self.suggestions_provider = "curated-demo"
        self.heard = ""
        self.shown = []  # Recently offered suggestion texts, so refreshes don't repeat.

    def set_suggestions(self, items, heard="", provider="ollama"):
        """Replace the Home pool with previewed replies; nothing is spoken."""
        self.suggested = list(items)
        self.suggestions_provider = provider
        self.heard = heard
        self.shown = (self.shown + [item["text"] for item in items])[-30:]
        self.pages["home"] = 0
        if self.screen == "home":
            self.selected = 0
        self.revision += 1

    def show_heard(self, heard):
        """Show what was heard without changing the phrases (no reply model configured)."""
        self.heard = heard
        self.revision += 1

    def clear_suggestions(self):
        self.suggested, self.heard = None, ""
        self.suggestions_provider = "curated-demo"
        self.pages["home"] = 0
        if self.screen == "home":
            self.selected = 0
        self.revision += 1

    def _slot(self, label, action, text="", enabled=True, value=""):
        return dict(label=label, action=action, text=text, enabled=enabled, value=value)

    def completions(self):
        prefix = self.draft.lower().split(" ")[-1]
        words = [w for w in self.config["words"] if prefix and w.startswith(prefix) and w != prefix]
        if not self.draft or not prefix:
            words = self.config["completions"][:2]
        return words[:2]

    def slots(self):
        slots = [self._slot("—", "none", enabled=False) for _ in range(8)]
        slots[4] = self._slot("Back", "back")
        if self.screen == "spell":
            midpoint = (len(self.letters) + 1) // 2
            for index, group in enumerate((self.letters[:midpoint], self.letters[midpoint:])):
                label = group if len(group) <= 1 else f"{group[0]}–{group[-1]}"
                slots[index] = self._slot(label or "—", "letters", value=group, enabled=bool(group))
            for index, word in zip((2, 3), self.completions()):
                slots[index] = self._slot(word.split()[0].capitalize(), "complete", word, value=word)
            slots[5] = self._slot("Space", "space")
            slots[6] = self._slot("Delete", "delete", enabled=bool(self.draft))
            slots[7] = self._slot("Speak", "speak", self.draft, enabled=bool(self.draft.strip()))
        else:
            pool = (self.suggested or self.config["phrases"]) if self.screen == "home" else self.config["needs"]
            page = self.pages[self.screen]
            page_size = 2 if self.cardinal_layout else 5
            # Eye control: replies sit on left/right, the reliably detected axis; More/Back use up/down.
            phrase_slots = (6, 2) if self.cardinal_layout else PHRASE_SLOTS
            for index, phrase in zip(phrase_slots, pool[page * page_size:page * page_size + page_size]):
                slots[index] = self._slot(phrase["label"], "phrase", phrase["text"], value=phrase["id"])
            slots[0 if self.cardinal_layout else 6] = self._slot("More", "more", enabled=(page + 1) * page_size < len(pool))
            # Spelling is no longer offered from the wheel; slot 7 stays empty.
        return slots

    def open_spelling(self):
        """Spelling screen entry. No wheel slot offers it now; kept for a later return."""
        self.return_screen = self.screen
        self.screen, self.selected = "spell", 0
        self.letters, self.letter_stack = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", []
        self.revision += 1

    def snapshot(self):
        slots = self.slots()
        return dict(schema_version=1, revision=self.revision, screen=self.screen,
                    contact=self.contact, contacts=self.config["contacts"], selected=self.selected,
                    slots=slots, preview=slots[self.selected]["text"], confirmed=self.confirmed,
                    selection_id=self.selection_id, draft=self.draft, page=self.pages.get(self.screen, 0),
                    source=self.last_source, suggestions_provider=self.suggestions_provider,
                    heard=self.heard, history=list(self.history))

    def confirm(self, text):
        text = text.strip()
        if not text:
            return
        self.confirmed = text
        self.selection_id += 1
        self.history.insert(0, dict(id=self.selection_id, text=text))
        self.history = self.history[:12]

    def action(self, action, source="keyboard", value=None):
        if action not in {"left", "right", "select", "back", "contact", "reset", "focus"}:
            raise ValueError("Unknown ring action")
        if action == "contact" and value not in {c["id"] for c in self.config["contacts"]}:
            raise ValueError("Unknown contact")
        if action == "focus" and (type(value) is not int or not 0 <= value < 8):
            raise ValueError("Slot must be 0–7")
        self.last_source = source
        if action in ("left", "right"):
            step = 1 if action == "right" else -1
            for _ in range(8):
                self.selected = (self.selected + step) % 8
                if self.slots()[self.selected]["enabled"]:
                    break
        elif action == "focus":
            if self.slots()[value]["enabled"]:
                self.selected = value
        elif action == "contact":
            self.contact = value
            self.suggested, self.heard = None, ""  # A new conversation partner changes the context.
            self.suggestions_provider = "curated-demo"
            self.screen, self.selected = "home", 0
            self.pages = {"home": 0, "needs": 0}
            self.letters, self.letter_stack = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", []
        elif action == "reset":
            self.screen, self.selected = "home", 0
            self.pages = {"home": 0, "needs": 0}
            self.draft = ""
            self.letters, self.letter_stack = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", []
        else:
            item = self._slot("Back", "back") if action == "back" else self.slots()[self.selected]
            if item["enabled"]:
                operation = item["action"]
                if operation == "phrase":
                    self.confirm(item["text"])
                elif operation == "more":
                    self.pages[self.screen] += 1  # No previously shown phrases in this context.
                    self.selected = 0
                elif operation == "spell":
                    self.open_spelling()
                elif operation == "back":
                    if self.screen == "spell" and self.letter_stack:
                        self.letters = self.letter_stack.pop()
                    elif self.screen == "spell":
                        self.screen = self.return_screen
                    elif self.screen == "home":
                        self.screen = "needs"
                        self.confirm("Give me a moment.")
                    else:
                        self.screen = "home"
                    self.selected = 0
                elif operation == "letters":
                    if len(item["value"]) == 1:
                        self.draft = (self.draft + item["value"].lower())[:280]
                        self.letters, self.letter_stack = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", []
                    else:
                        self.letter_stack.append(self.letters)
                        self.letters = item["value"]
                    self.selected = 0
                elif operation == "space":
                    self.draft = (self.draft.rstrip() + " ")[:280]
                elif operation == "delete":
                    self.draft = self.draft[:-1]
                elif operation == "complete":
                    word = item["value"]
                    if " " in word:
                        self.draft = word[:280]
                    else:
                        prefix = self.draft.rsplit(" ", 1)[0] + " " if " " in self.draft else ""
                        self.draft = (prefix + word + " ")[:280]
                    self.letters, self.letter_stack = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", []
                elif operation == "speak":
                    self.confirm(self.draft)
        self.revision += 1
        return self.snapshot()
