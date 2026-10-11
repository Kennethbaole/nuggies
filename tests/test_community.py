import base64
import json
import tempfile
import unittest
from pathlib import Path

from backend.app import Application
from backend.community import MemberBook, NotesStore, notes_text
from backend.suggestions import (
    NOTES_REMINDER, REPLY_KINDS, OllamaSuggestions, SuggestionResult, SuggestionUnavailable, context_text, copied_phrase, format_timing,
)

MAYA = ("Maya is my younger sister. She uses she/her pronouns. I call her May. We're close, and I usually "
        "speak casually with her. Keep my replies short, warm, and sometimes playful. Light teasing is fine, "
        "but avoid overly sentimental wording. We often talk about food and movies.")


def encoded(text):
    return base64.b64encode(text.encode() if isinstance(text, str) else text).decode()


class NotesFileTests(unittest.TestCase):
    def test_cleans_line_endings_spaces_and_blank_runs(self):
        raw = "﻿Maya   is my sister.\r\n\r\n\r\n\r\nShe likes  films.\x07\r\n"
        self.assertEqual(notes_text(raw.encode()), "Maya is my sister.\n\nShe likes films.")

    def test_rejects_unusable_files(self):
        for data in (b"", b"  \n ", b"PK\x03\x04zip", b"\xff\xfe\x00b\x00", b"x" * 40_000, b"word " * 500):
            with self.assertRaises(ValueError):
                notes_text(data)


class NotesStoreTests(unittest.TestCase):
    def test_save_replace_remove_and_reject_path_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            store = NotesStore(folder)
            self.assertIsNone(store.load("maya"))
            store.save("maya", MAYA, "../private/maya.txt")
            self.assertEqual((store.text("maya"), store.load("maya")["source"]), (MAYA, "maya.txt"))
            store.save("maya", "Short and kind.", "new.txt")
            self.assertEqual(store.text("maya"), "Short and kind.")
            store.remove("maya")
            self.assertEqual(store.text("maya"), "")
            with self.assertRaises(ValueError):
                store.remove("maya")
            with self.assertRaises(ValueError):
                store.save("../evil", MAYA)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), [])

    def test_damaged_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "notes.maya.local.json").write_text("{not json")
            self.assertIsNone(NotesStore(folder).load("maya"))


class MemberBookTests(unittest.TestCase):
    def test_reads_members_added_by_the_earlier_people_page(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = [dict(id="kenny", name="Kenny", relationship="Friend", initials="KE")]
            Path(folder, "contacts.local.json").write_text(json.dumps(legacy))
            book = MemberBook(folder)
            self.assertEqual(book.load(), legacy)
            book.add("Maya", "Sister", legacy)
            self.assertEqual([m["id"] for m in MemberBook(folder).load()], ["kenny", "maya"])

    def test_null_file_is_an_empty_list(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "community.local.json").write_text("null")
            self.assertEqual(MemberBook(folder).load(), [])


class PromptTests(unittest.TestCase):
    CONTACT = dict(name="Maya", relationship="Sister")

    def test_notes_guide_tone_without_being_forced_or_taken_as_feelings(self):
        text = context_text(self.CONTACT, [], [], "Pizza tonight?", ["Hi, it is good to see you."], notes=MAYA)
        self.assertIn(f"<notes>\n{MAYA}\n</notes>", text)
        self.assertIn("Never bring up their topics unless Maya just mentioned", text)
        self.assertIn("not what the user wants or feels right now", text)
        self.assertNotIn("good to see you", text)  # Notes replace the generic style examples.

    def test_without_notes_the_default_style_applies(self):
        text = context_text(self.CONTACT, [], [], "Pizza tonight?", ["Hi, it is good to see you."])
        self.assertIn("good to see you", text)
        self.assertNotIn("<notes>", text)

    def test_both_modes_send_the_notes(self):
        for mode in ("single", "parallel"):
            calls = []
            reply = json.dumps({"suggestions": [{"text": "yes please"}]}) if mode == "single" else "yes please"
            local = OllamaSuggestions(mode=mode, transport=lambda *args: calls.append(args) or {"message": {"content": reply}})
            local.model = "qwen3:4b"
            local.suggest(contact=self.CONTACT, heard_text="Pizza tonight?", notes=MAYA)
            self.assertTrue(all("I call her May" in call[2]["messages"][1]["content"] for call in calls))


SAMPLES = "omg no way\n\nI lowkey just like happy music so im wit you\n\nthat class is lowkey so mid lol"


class CopyGuardTests(unittest.TestCase):
    CONTACT = dict(name="Kat", relationship="Friend")

    def test_flags_copied_runs_but_not_everyday_phrasing_or_what_was_said(self):
        self.assertEqual(copied_phrase("i lowkey just like happy music too", SAMPLES), "lowkey just like happy")
        self.assertEqual(copied_phrase("I'm down, what movie tho", SAMPLES), "")
        self.assertEqual(copied_phrase("so im wit you on that", "so im wit you"), "")  # Only everyday words.
        self.assertEqual(copied_phrase("that class is lowkey hard", SAMPLES, "how is that class is lowkey going"), "")
        self.assertEqual(copied_phrase("anything", ""), "")

    def test_notes_rules_and_reminder_come_with_the_notes(self):
        text = context_text(self.CONTACT, [], [], "wanna watch a movie later?", [], notes=SAMPLES)
        self.assertIn("Never reuse a sentence or phrase", text)
        self.assertIn(NOTES_REMINDER, text)
        self.assertGreater(text.index("CURRENT INCOMING TURN"), text.index(NOTES_REMINDER))
        self.assertNotIn(NOTES_REMINDER, context_text(self.CONTACT, [], [], "hi", []))

    def parallel(self, first, retry, calls=None):
        """Parallel suggester whose answer depends on the reply kind asked for, not on thread order."""
        def transport(url, headers, body, timeout):
            content = body["messages"][1]["content"]
            if calls is not None:
                calls.append(content)
            kind = next(index for index, kind in enumerate(REPLY_KINDS) if f"Write {kind}." in content)
            return {"message": {"content": retry if "earlier try copied" in content else first[kind]}}
        local = OllamaSuggestions(mode="parallel", transport=transport)
        local.model = "qwen3:1.7b"
        return local

    FIRST = ["yess what movie", "i lowkey just like happy music so im wit you", "which one were u thinking",
             "u good tho", "only if we get snacks"]

    def test_parallel_retries_a_copied_reply_once_then_drops_it(self):
        calls = []
        result = self.parallel(self.FIRST, "I lowkey just like happy music", calls).suggest(
            contact=self.CONTACT, heard_text="wanna watch a movie later?", notes=SAMPLES)
        retries = [content for content in calls if "earlier try copied" in content]
        self.assertEqual((len(calls), len(retries)), (6, 1))
        self.assertIn('copied "lowkey just like happy"', retries[0])
        self.assertEqual([s["text"] for s in result.suggestions],
                         ["yess what movie", "which one were u thinking", "u good tho", "only if we get snacks"])
        self.assertEqual(result.timing["copies_retried"], 1)
        self.assertIn("1 copied from notes", format_timing(result.timing))

    def test_parallel_keeps_a_fixed_retry_and_single_mode_drops_copies(self):
        result = self.parallel(self.FIRST, "nah not tonight").suggest(heard_text="movie later?", notes=SAMPLES)
        self.assertEqual([s["text"] for s in result.suggestions][1], "nah not tonight")
        reply = json.dumps({"suggestions": [{"text": "yess"}, {"text": "I lowkey just like happy music"}]})
        single = OllamaSuggestions(mode="single", transport=lambda *args: {"message": {"content": reply}})
        single.model = "qwen3:1.7b"
        result = single.suggest(heard_text="movie later?", notes=SAMPLES)
        self.assertEqual(([s["text"] for s in result.suggestions], result.timing["copies_dropped"]), (["yess"], 1))


class FakeSuggester:
    available = True

    def __init__(self):
        self.calls = []

    def suggest(self, **kwargs):
        self.calls.append(kwargs)
        return SuggestionResult(kwargs["heard_text"], [dict(id="ai-1", label="Yes", text="Yes, pizza!")], "fake", 12)


class CommunityPageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = Application()
        self.app.notes = NotesStore(folder.name)
        self.app.member_book = MemberBook(folder.name)
        self.app.suggester = FakeSuggester()
        self.first = self.app.ring.config["contacts"][0]["id"]

    def send(self, action, **extra):
        return self.app.community_command(dict(session_id=self.app.session_id, action=action, **extra))

    def notes_of(self, community, member_id):
        return next(m for m in community["members"] if m["id"] == member_id)["notes"]

    def test_upload_show_replace_and_remove_notes(self):
        self.assertIsNone(self.notes_of(self.app.community(), self.first))
        community = self.send("save_notes", member_id=self.first, filename="maya.txt", file_b64=encoded(MAYA))
        self.assertEqual(self.notes_of(community, self.first)["text"], MAYA)
        self.assertTrue(self.app.state()["has_notes"])
        community = self.send("save_notes", member_id=self.first, filename="v2.txt", file_b64=encoded("Short."))
        self.assertEqual(self.notes_of(community, self.first)["source"], "v2.txt")
        self.assertIsNone(self.notes_of(self.send("remove_notes", member_id=self.first), self.first))
        self.assertFalse(self.app.state()["has_notes"])

    def test_live_suggestions_use_the_selected_members_notes(self):
        self.send("save_notes", member_id=self.first, file_b64=encoded(MAYA))
        self.app.suggest(dict(session_id=self.app.session_id, heard_text="Pizza tonight?"))
        self.assertEqual(self.app.suggester.calls[-1]["notes"], MAYA)
        other = self.app.ring.config["contacts"][1]["id"]
        self.app.ring.action("contact", value=other)
        self.app.last_suggest = 0
        self.app.suggest(dict(session_id=self.app.session_id, heard_text="Pizza tonight?"))
        self.assertEqual(self.app.suggester.calls[-1]["notes"], "")

    def test_preview_generates_without_touching_the_ring(self):
        self.send("save_notes", member_id=self.first, file_b64=encoded(MAYA))
        before = (self.app.ring.revision, list(self.app.ring.history), self.app.ring.slots())
        preview = self.send("preview", member_id=self.first, heard="Pizza tonight?")
        self.assertEqual((preview["suggestions"], preview["used_notes"]), (["Yes, pizza!"], True))
        self.assertEqual(self.app.suggester.calls[-1]["notes"], MAYA)
        self.assertEqual(self.app.suggester.calls[-1]["contact"]["id"], self.first)
        self.assertEqual(before, (self.app.ring.revision, list(self.app.ring.history), self.app.ring.slots()))
        self.app.suggester.available = False
        with self.assertRaises(SuggestionUnavailable):
            self.send("preview", member_id=self.first, heard="Pizza tonight?")

    def test_edit_profile_reaches_companion_prompt_and_survives_restart(self):
        community = self.send("update_member", member_id=self.first, relationship=" Best   friend ",
                              gender="Woman", pronouns="she/her", tone=4)
        edited = community["members"][0]
        self.assertEqual((edited["relationship"], edited["gender"], edited["pronouns"], edited["tone"]),
                         ("Best friend", "Woman", "she/her", 4))
        self.assertEqual(self.app.state()["contacts"][0]["pronouns"], "she/her")
        self.app.suggest(dict(session_id=self.app.session_id, heard_text="Pizza tonight?"))
        self.assertIn("(Best friend, Woman, pronouns she/her)",
                      context_text(self.app.suggester.calls[-1]["contact"], [], [], "hi", []))
        restarted = MemberBook(self.app.member_book.path.parent).apply_profiles([dict(id=self.first, name="X",
                                                                                      relationship="Family", initials="X")])
        self.assertEqual((restarted[0]["relationship"], restarted[0]["tone"]), ("Best friend", 4))
        cleared = self.send("update_member", member_id=self.first, relationship="Family", gender="", pronouns="", tone=None)
        self.assertEqual((cleared["members"][0]["gender"], cleared["members"][0]["tone"]), ("", None))
        for bad in (dict(relationship=" "), dict(relationship="Friend", tone=6), dict(relationship="Friend", tone=True),
                    dict(relationship="Friend", pronouns=5), dict(member_id="nobody", relationship="Friend")):
            with self.assertRaises(ValueError):
                self.send("update_member", **{"member_id": self.first, **bad})

    def test_added_members_are_selectable_and_validation(self):
        community = self.send("add_member", name="  Maya   Lopez ", relationship="Sister")
        added = community["members"][-1]
        self.assertEqual((added["id"], added["name"], added["initials"], added["notes"]),
                         ("maya-lopez", "Maya Lopez", "ML", None))
        self.assertEqual(self.app.ring.action("contact", value="maya-lopez")["contact"], "maya-lopez")
        for bad in (dict(action="add_member", name="maya lopez"), dict(action="add_member", name="  "),
                    dict(action="save_notes", member_id="nobody", file_b64=encoded(MAYA)),
                    dict(action="save_notes", member_id=self.first, file_b64="***"),
                    dict(action="save_notes", member_id=self.first, file_b64=encoded(b"\x00\x01binary")),
                    dict(action="remove_notes", member_id=self.first),
                    dict(action="preview", member_id=self.first, heard=" "),
                    dict(action="explode", member_id=self.first)):
            with self.assertRaises(ValueError):
                self.app.community_command(dict(session_id=self.app.session_id, **bad))
        with self.assertRaises(ValueError):
            self.app.community_command(dict(session_id="other", action="add_member", name="Zed"))


if __name__ == "__main__":
    unittest.main()
