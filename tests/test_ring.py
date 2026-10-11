import unittest

from backend.ring import RingState


class RingTests(unittest.TestCase):
    def setUp(self):
        self.ring = RingState()

    def choose(self, index):
        self.ring.action("focus", value=index)
        return self.ring.action("select")

    def test_fixed_slots_and_clockwise_wrap(self):
        self.assertEqual(len(self.ring.slots()), 8)
        self.assertEqual(self.ring.slots()[4]["label"], "Back")
        self.assertEqual(self.ring.slots()[6]["label"], "More")
        self.assertFalse(self.ring.slots()[7]["enabled"])  # Spell was removed from the wheel
        self.assertNotIn("spell", [s["action"] for s in self.ring.slots()])
        self.assertEqual(self.ring.action("left")["selected"], 6)
        self.assertEqual(self.ring.action("right")["selected"], 0)

    def test_more_never_repeats_and_exhausts(self):
        seen = set()
        for page in range(3):
            phrases = {s["value"] for s in self.ring.slots() if s["action"] == "phrase"}
            self.assertFalse(seen & phrases)
            seen |= phrases
            if page < 2:
                self.choose(6)
        self.assertEqual(len(seen), 15)
        self.assertFalse(self.ring.slots()[6]["enabled"])
        self.ring.action("focus", value=5)
        self.assertEqual(self.ring.action("right")["selected"], 0)  # empty slot 7 is skipped

    def test_confirmation_is_explicit_and_shared(self):
        self.ring.action("right")
        self.assertEqual(self.ring.snapshot()["confirmed"], "")
        state = self.ring.action("select")
        self.assertEqual(state["confirmed"], "Thank you for being here with me.")
        self.assertEqual(state["selection_id"], 1)
        self.assertEqual(state["history"][0]["text"], state["confirmed"])

    def test_home_back_opens_needs_with_moment(self):
        state = self.choose(4)
        self.assertEqual(state["screen"], "needs")
        self.assertEqual(state["confirmed"], "Give me a moment.")
        self.assertEqual(self.ring.slots()[4]["label"], "Back")
        self.assertEqual(self.choose(4)["screen"], "home")

    def test_spelling_groups_word_completion_delete_and_speak(self):
        self.ring.open_spelling()
        for letter in "WA":
            while True:
                index = next(i for i, s in enumerate(self.ring.slots()) if s["action"] == "letters" and letter in s["value"])
                item = self.ring.slots()[index]
                self.choose(index)
                if len(item["value"]) == 1:
                    break
        self.assertEqual(self.ring.draft, "wa")
        self.assertEqual(self.ring.slots()[2]["value"], "water")
        self.choose(2)
        self.assertEqual(self.ring.draft, "water ")
        self.choose(6)
        self.assertEqual(self.ring.draft, "water")
        state = self.choose(7)
        self.assertEqual(state["confirmed"], "water")
        self.assertEqual(self.choose(4)["screen"], "home")

    def test_back_rewinds_letter_group_and_contact_resets_pages(self):
        self.ring.open_spelling(); self.choose(0)
        self.assertEqual(self.ring.letters, "ABCDEFGHIJKLM")
        self.choose(4)
        self.assertEqual(self.ring.letters, "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        self.assertEqual(self.ring.screen, "spell")
        state = self.ring.action("contact", value="kat")
        self.assertEqual(state["screen"], "home")
        self.assertEqual(state["page"], 0)

    def test_invalid_input_does_not_mutate(self):
        initial = self.ring.snapshot()
        for action, value in (("unknown", None), ("focus", -1), ("focus", True), ("contact", "unknown")):
            with self.assertRaises(ValueError):
                self.ring.action(action, value=value)
            self.assertEqual(self.ring.snapshot(), initial)
