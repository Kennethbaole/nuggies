import base64
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from backend.app import Application
from backend.persona import (
    ContactBook, PersonaStore, chat_text, build_persona, parse_chat, persona_context, save_persona, similar_pairs, style_note, training_rows,
)
from backend.suggestions import OllamaSuggestions, context_text

PLAIN = """Bella: are you coming to dinner tonight?
Isa: yesss wouldnt miss it
Isa: what time
Bella: 7 at moms
Isa: ok perfect
Bella: can you bring the dessert: the lemon one
with the crust
Isa: on it 🍋
Bella: how was the doctor today?
Isa: long but fine, tell you later
Bella: love you
Isa: love u more
"""

WHATSAPP = """[10/9/26, 9:41:22 PM] Bella: Messages and calls are end-to-end encrypted.
[10/9/26, 9:41:30 PM] Bella: are you awake?
[10/9/26, 9:42:02 PM] Isa: barely lol
[10/9/26, 9:42:10 PM] Bella: ‎image omitted
[10/9/26, 9:43:00 PM] Isa: omg cute
10/9/26, 9:44 PM - Bella: goodnight
10/9/26, 9:44 PM - Isa: night night
10/9/26, 9:45 PM - Bella added Kenny
"""


def persona(text=PLAIN):
    return build_persona(text, "Isa", "bella", "chat.txt")


class ParseTests(unittest.TestCase):
    def test_plain_lines_keep_colons_and_continuations_inside_a_message(self):
        messages = parse_chat(PLAIN)
        self.assertEqual({name for name, _ in messages}, {"Bella", "Isa"})
        self.assertIn(("Bella", "can you bring the dessert: the lemon one with the crust"), messages)

    def test_whatsapp_exports_skip_media_and_system_lines(self):
        messages = parse_chat(WHATSAPP)
        self.assertEqual([body for name, body in messages if name == "Isa"], ["barely lol", "omg cute", "night night"])
        self.assertNotIn("Bella added Kenny", " ".join(body for _, body in messages))
        self.assertFalse(any("omitted" in body for _, body in messages))


class BuildTests(unittest.TestCase):
    def test_pairs_what_they_said_with_the_users_reply(self):
        built = persona()
        self.assertIn(dict(them="are you coming to dinner tonight?", me="yesss wouldnt miss it what time"), built["pairs"])
        self.assertIn(dict(them="love you", me="love u more"), built["pairs"])
        self.assertEqual(built["contact_id"], "bella")

    def test_unknown_user_name_lists_the_names_found(self):
        with self.assertRaisesRegex(ValueError, "Bella, Isa"):
            build_persona(PLAIN, "Isabella", "bella")

    def test_style_note_reports_only_measured_habits(self):
        note = style_note(["ok perfect", "on it", "love u more", "yesss", "long but fine", "what time"])
        self.assertIn("lowercase", note)
        self.assertIn("rarely ends with punctuation", note)
        self.assertEqual(style_note(["Hi."]), "")


class RetrievalTests(unittest.TestCase):
    def test_closest_exchange_comes_first(self):
        chosen = similar_pairs(persona(), "Are we still on for dinner?")
        self.assertEqual(chosen[0]["me"], "yesss wouldnt miss it what time")

    def test_context_tops_up_with_recent_exchanges(self):
        context = persona_context(persona(), "completely unrelated zebra", count=3)
        self.assertEqual([pair["me"] for pair in context["examples"]],
                         ["love u more", "long but fine, tell you later", "on it 🍋"])

    def test_training_rows_are_chat_format(self):
        row = training_rows(persona(), "Bella")[0]
        self.assertEqual([m["role"] for m in row["messages"]], ["system", "user", "assistant"])
        self.assertEqual(row["messages"][2]["content"], "yesss wouldnt miss it what time")


class StoreTests(unittest.TestCase):
    def test_contact_profile_then_default_then_none(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PersonaStore(folder)
            self.assertIsNone(store.context("bella", "hi"))
            self.assertIsNone(store.summary("bella"))
            save_persona(dict(persona(), contact_id="default"), folder)
            self.assertEqual(store.summary("kenny")["profile"], "default")
            save_persona(persona(), folder)
            self.assertEqual(store.summary("bella"), dict(profile="bella", exchanges=5))
            self.assertTrue(store.context("bella", "dinner?")["examples"])

    def test_never_overwrites_without_replace_and_rejects_path_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            save_persona(persona(), folder)
            with self.assertRaises(FileExistsError):
                save_persona(persona(), folder)
            save_persona(persona(), folder, replace=True)
            with self.assertRaises(ValueError):
                save_persona(dict(persona(), contact_id="../evil"), folder)
            self.assertIsNone(PersonaStore(folder).load("../evil"))

    def test_damaged_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "persona.bella.local.json").write_text("{not json")
            self.assertIsNone(PersonaStore(folder).context("bella", "hi"))


class PromptTests(unittest.TestCase):
    CONTACT = dict(name="Bella", relationship="Family")

    def context(self):
        return persona_context(persona(), "dinner tonight?")

    def test_persona_replaces_the_generic_examples(self):
        text = context_text(self.CONTACT, [], [], "dinner tonight?", ["Hi, it is good to see you."], self.context())
        self.assertIn("How the user writes to Bella", text)
        self.assertIn('"are you coming to dinner tonight?" -> "yesss wouldnt miss it what time"', text)
        self.assertNotIn("good to see you", text)

    def test_local_model_gets_the_persona(self):
        calls = []
        local = OllamaSuggestions(transport=lambda *args: calls.append(args) or {"message": {"content": json.dumps(
            {"suggestions": [{"label": "Yes", "text": "yesss im in"}]})}})
        local.model = "qwen3:4b"
        local.suggest(contact=self.CONTACT, heard_text="dinner tonight?", persona=self.context())
        self.assertIn("wouldnt miss it", calls[0][2]["messages"][1]["content"])


class AppTests(unittest.TestCase):
    def test_app_passes_the_current_contacts_persona_and_reports_it(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Application()
            app.personas = PersonaStore(folder)
            contact = app.ring.contact
            self.assertIsNone(app.state()["persona"])
            save_persona(dict(persona(), contact_id=contact), folder)
            self.assertEqual(app.state()["persona"], dict(profile=contact, exchanges=5))
            seen = {}

            class Suggester:
                available = True

                def suggest(self, **kwargs):
                    seen.update(kwargs)
                    raise ValueError("stop here")

            app.suggester = Suggester()
            with self.assertRaises(ValueError):
                app.suggest(dict(session_id=app.session_id, heard_text="dinner tonight?"))
            self.assertEqual(seen["persona"]["examples"][0]["me"], "yesss wouldnt miss it what time")


def encoded(data):
    return base64.b64encode(data).decode()


def zipped(name="_chat.txt", text=PLAIN):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("photo.jpg", b"not text")
        archive.writestr(name, text)
    return buffer.getvalue()


class UploadTests(unittest.TestCase):
    def test_reads_text_and_whatsapp_zip(self):
        self.assertEqual(chat_text(PLAIN.encode()), PLAIN)
        self.assertEqual(chat_text(zipped()), PLAIN)

    def test_rejects_unusable_files(self):
        for data in (b"", b"PK not really a zip", zipped("notes.md"), b"\xff\xfe\x00binary", b"x" * 8_000_001):
            with self.assertRaises(ValueError):
                chat_text(data)


class ContactsPageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = Application()
        self.app.personas = PersonaStore(folder.name)
        self.app.contact_book = ContactBook(folder.name)
        self.first = self.app.ring.config["contacts"][0]["id"]

    def send(self, action, **extra):
        return self.app.persona_command(dict(session_id=self.app.session_id, action=action, **extra))

    def test_inspect_then_save_then_preview_then_remove(self):
        names = self.send("inspect", file_b64=encoded(zipped()))["names"]
        self.assertEqual(names, [dict(name="Isa", messages=6), dict(name="Bella", messages=5)])
        people = self.send("save", contact_id=self.first, me="Isa", file_b64=encoded(PLAIN.encode()),
                           filename="../secret/chat.txt")
        profile = people["contacts"][0]["profile"]
        self.assertEqual((profile["exchanges"], profile["me"], profile["source"]), (5, "Isa", "chat.txt"))
        preview = self.send("preview", contact_id=self.first, heard="dinner tonight?")
        self.assertEqual(preview["context"]["examples"][0]["me"], "yesss wouldnt miss it what time")
        self.assertIsNone(self.send("remove", contact_id=self.first)["contacts"][0]["profile"])
        with self.assertRaises(ValueError):
            self.send("remove", contact_id=self.first)

    def test_default_profile_and_validation(self):
        self.assertIsNone(self.app.people()["default"])
        people = self.send("save", contact_id="default", me="Isa", file_b64=encoded(PLAIN.encode()))
        self.assertEqual(people["default"]["exchanges"], 5)
        for bad in (dict(action="save", contact_id="nobody", me="Isa", file_b64=encoded(PLAIN.encode())),
                    dict(action="save", contact_id=self.first, me="Stranger", file_b64=encoded(PLAIN.encode())),
                    dict(action="save", contact_id=self.first, me="Isa", file_b64="***"),
                    dict(action="inspect", file_b64=encoded(b"no speakers here")),
                    dict(action="preview", contact_id=self.first, heard=" "),
                    dict(action="explode", contact_id=self.first)):
            with self.assertRaises(ValueError):
                self.app.persona_command(dict(session_id=self.app.session_id, **bad))
        with self.assertRaises(ValueError):
            self.app.persona_command(dict(session_id="other", action="remove", contact_id=self.first))

    def test_added_contacts_are_selectable_and_survive_restart(self):
        before = len(self.app.ring.config["contacts"])
        people = self.send("add_contact", name="  Maya   Lopez ", relationship="Sister")
        added = people["contacts"][-1]
        self.assertEqual((added["id"], added["name"], added["initials"]), ("maya-lopez", "Maya Lopez", "ML"))
        self.assertEqual(self.app.ring.action("contact", value="maya-lopez")["contact"], "maya-lopez")
        self.assertEqual([c["id"] for c in ContactBook(self.app.contact_book.path.parent).load()], ["maya-lopez"])
        with self.assertRaises(ValueError):
            self.send("add_contact", name="maya lopez")
        with self.assertRaises(ValueError):
            self.send("add_contact", name="   ")
        self.assertEqual(len(self.app.ring.config["contacts"]), before + 1)


if __name__ == "__main__":
    unittest.main()
