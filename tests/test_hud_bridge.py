import json
import os
import tempfile
import unittest

from backend.events import Action
from backend.hud_bridge import HUD, action_to_commands, load_phrases, parse_selected


class FakeConnection:
    def __init__(self):
        self.written = b""

    def write(self, data):
        self.written += data

    def flush(self):
        pass


class FakeSpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


class HudBridgeTests(unittest.TestCase):
    def test_action_mapping(self):
        self.assertEqual(action_to_commands(Action.NEXT), ["n"])
        self.assertEqual(action_to_commands(Action.PREV), ["p"])
        self.assertEqual(action_to_commands(Action.SELECT), ["s"])
        self.assertEqual(action_to_commands(Action.BACK), ["H:4", "s"])

    def test_parse_selected(self):
        self.assertEqual(parse_selected("SELECTED:2:Listen"), (2, "Listen"))
        self.assertEqual(parse_selected("SELECTED:0:Dr Lee"), (0, "Dr Lee"))
        self.assertIsNone(parse_selected("Ready. Try: O:Food"))
        self.assertIsNone(parse_selected("SELECTED:x:Food"))

    def test_events_become_commands(self):
        connection = FakeConnection()
        hud = HUD(connection, {}, FakeSpeaker())
        hud.set_options(["Hello", "Thanks"])
        hud.handle_event(Action.NEXT)
        hud.handle_event(Action.BACK)
        self.assertEqual(connection.written, b"O:Hello,Thanks\nn\nH:4\ns\n")

    def test_selection_speaks_phrase_but_not_back(self):
        speaker = FakeSpeaker()
        hud = HUD(FakeConnection(), {"Food": "I would like something to eat."}, speaker)
        hud.handle_line("SELECTED:0:Food")
        hud.handle_line("SELECTED:5:Unknown")
        hud.handle_line("SELECTED:4:Back")
        self.assertEqual(speaker.spoken, ["I would like something to eat.", "Unknown"])

    def test_phrases_file(self):
        here = os.path.dirname(__file__)
        phrases = load_phrases(os.path.join(here, "..", "config", "hud_phrases.json"))
        self.assertEqual(phrases["Light"], "Could you adjust the lighting, please?")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "p.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"labels": {"Yes": "Yes."}}, stream)
            self.assertEqual(load_phrases(path), {"Yes": "Yes."})
            self.assertEqual(load_phrases(os.path.join(folder, "missing.json")), {})


if __name__ == "__main__":
    unittest.main()
