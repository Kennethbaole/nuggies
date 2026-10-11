import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from backend.app import Application, make_handler
from backend.hud_sync import (CENTER_LIMITS, MAX_LABEL, Mirror, SerialTarget, ascii_text, center_text,
                              fetch_state, frame_for, offline_frame, run, wrap_center)
from backend.ring import RingState


class FakeConnection:
    def __init__(self):
        self.written = b""

    def write(self, data):
        self.written += data

    def flush(self):
        pass

    def close(self):
        pass


class ListTarget:
    def __init__(self):
        self.frames = []

    def send(self, frame):
        self.frames.append(frame)


def fields(frame):
    assert frame.startswith("W:")
    parts = frame[2:].split("|")
    return int(parts[0]), parts[1:9], parts[9:]


class FrameTests(unittest.TestCase):
    def test_home_frame_matches_ring(self):
        state = RingState().snapshot()
        selected, labels, center = fields(frame_for(state))
        self.assertEqual(selected, 0)
        self.assertEqual(labels, [slot["label"] if slot["enabled"] else "" for slot in state["slots"]])
        self.assertEqual(labels[7], "")  # Spell was removed from the wheel
        self.assertEqual(labels[4], "Back")
        self.assertEqual(center, ["Ready", "", ""])

    def test_frame_always_has_twelve_ascii_fields(self):
        ring = RingState()
        ring.open_spelling()  # Spell: labels contain an en dash, slots 2/3 may be empty
        frame = frame_for(ring.snapshot())
        self.assertEqual(len(frame[2:].split("|")), 12)
        self.assertTrue(frame.isascii())
        _, labels, center = fields(frame)
        self.assertEqual(labels[0], "A-M")
        self.assertEqual(labels[6], "")  # Delete is disabled with an empty draft, so hidden
        self.assertEqual(center, ["Choose", "letters", ""])

    def test_disabled_slots_keep_their_position(self):
        state = RingState().snapshot()
        state["slots"][1]["enabled"] = False
        _, labels, _ = fields(frame_for(state))
        self.assertEqual(labels[1], "")
        self.assertEqual(labels[2], state["slots"][2]["label"])

    def test_labels_are_cut_to_firmware_length(self):
        state = RingState().snapshot()
        state["slots"][0]["label"] = "Could you help"
        state["slots"][1]["label"] = "a|b"
        _, labels, _ = fields(frame_for(state))
        self.assertEqual(labels[0], "Could you")
        self.assertLessEqual(max(map(len, labels)), MAX_LABEL)
        self.assertEqual(labels[1], "a/b")

    def test_no_highlight_while_eyes_drive_the_wheel(self):
        state = RingState().snapshot()
        state.update(wheel_test=True, wheel_message="Look center")
        selected, _, center = fields(frame_for(state))
        self.assertEqual(selected, -1)
        self.assertEqual(center[:2], ["Look", "center"])  # wraps inside the narrowed inner ellipse

    def test_highlight_dropped_when_selected_slot_is_hidden(self):
        state = RingState().snapshot()
        state["slots"][0]["enabled"] = False
        self.assertEqual(fields(frame_for(state))[0], -1)

    def test_confirmed_sentence_shows_in_centre(self):
        ring = RingState()
        ring.action("select")
        state = ring.snapshot()
        _, _, center = fields(frame_for(state))
        self.assertEqual(" ".join(center).split(), ascii_text(state["confirmed"]).split())

    def test_communication_centre_text_matches_browser_hud(self):
        ring = RingState()
        ring.cardinal_layout = True
        state = ring.snapshot()
        state.update(eog_communication=True, wheel_test=True, gaze_hover=dict(phase="ready"))
        self.assertEqual(center_text(state), "Choose a reply")
        state["gaze_hover"] = dict(phase="centering")
        self.assertEqual(center_text(state), "Look center")
        state.update(eog_choice_pending=True, eog_confirmation_ready=False)
        label = state["slots"][state["selected"]]["label"]
        self.assertEqual(center_text(state), f"{label}. Return center")
        _, labels, center = fields(frame_for(state))
        self.assertEqual([index for index, text in enumerate(labels) if text], [0, 2, 4, 6])
        self.assertFalse(center[0].startswith("!"))  # too early to blink: no alert yet
        state["eog_confirmation_ready"] = True
        self.assertEqual(center_text(state), f"{label}. Double blink")
        self.assertEqual(fields(frame_for(state))[2], ["!DOUBLE BLINK", label, ""])

    def test_reading_pause_shows_on_the_display(self):
        state = RingState().snapshot()
        state.update(eog_communication=True, wheel_test=True, eog_paused=True, gaze_hover=dict(phase="ready"))
        self.assertEqual(fields(frame_for(state))[2], ["Paused.", "Double", "blink"])

    def test_blink_alert_needs_communication_mode_and_a_pending_choice(self):
        state = RingState().snapshot()
        state.update(eog_confirmation_ready=True)
        self.assertFalse(fields(frame_for(state))[2][0].startswith("!"))
        state.update(eog_communication=True, wheel_test=True, eog_choice_pending=False)
        self.assertFalse(fields(frame_for(state))[2][0].startswith("!"))

    def test_wrap_fits_the_inner_ellipse(self):
        self.assertEqual(wrap_center(""), [])
        self.assertEqual(wrap_center("Ready"), ["Ready"])
        self.assertEqual(wrap_center("Hello. Double blink"), ["Hello.", "Double", "blink"])
        self.assertEqual(wrap_center("Choose a reply"), ["Choose a", "reply"])
        self.assertEqual(wrap_center("Paused. Double blink"), ["Paused.", "Double", "blink"])
        for text in ("Could I have some water, please?", "Supercalifragilistic word", "I love you.",
                     "Please listen, I want to say something to you right now"):
            lines = wrap_center(text)
            limits = CENTER_LIMITS[len(lines)]
            self.assertTrue(all(0 < len(line) <= limit for line, limit in zip(lines, limits)), (text, lines))
        self.assertTrue(wrap_center("Please listen, I want to say something to you right now")[-1].endswith(".."))

    def test_offline_frame_hides_the_wheel(self):
        selected, labels, center = fields(offline_frame())
        self.assertEqual((selected, labels), (-1, [""] * 8))
        self.assertEqual(" ".join(center).strip(), "Website offline")


class TransportTests(unittest.TestCase):
    def test_serial_target_writes_one_line(self):
        connection = FakeConnection()
        SerialTarget(connection).send("W:0|a")
        self.assertEqual(connection.written, b"W:0|a\n")

    def test_serial_target_survives_an_unplugged_cable(self):
        class Unplugged(FakeConnection):
            def write(self, data):
                raise OSError("Device not configured")

        replacement, attempts = FakeConnection(), []

        def reopen():
            attempts.append(1)
            if len(attempts) < 2:
                raise OSError("port not there yet")
            return replacement

        target = SerialTarget(Unplugged(), reopen)
        target.send("W:a")  # write fails: connection dropped, no exception
        self.assertIsNone(target.connection)
        target.send("W:a")  # port still missing
        self.assertIsNone(target.connection)
        target.send("W:a")  # reopened; board is rebooting, nothing written yet
        self.assertIs(target.connection, replacement)
        target.send("W:b")
        self.assertEqual(replacement.written, b"W:b\n")

    def test_serial_target_without_reopen_still_raises(self):
        class Unplugged(FakeConnection):
            def write(self, data):
                raise OSError("gone")

        with self.assertRaises(OSError):
            SerialTarget(Unplugged()).send("W:a")

    def test_reply_cut_off_midway_shows_offline_instead_of_crashing(self):
        import socket

        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)

        def serve():
            while True:
                try:
                    client, _ = server.accept()
                except OSError:
                    return
                client.recv(4096)
                client.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 5000\r\n\r\n{\"slots\":")
                client.close()

        threading.Thread(target=serve, daemon=True).start()
        target, stop = ListTarget(), threading.Event()
        worker = threading.Thread(target=run, args=(f"http://127.0.0.1:{server.getsockname()[1]}", "", [target], 0.02, stop), daemon=True)
        worker.start()
        deadline = time.monotonic() + 3
        while not target.frames and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
        self.assertTrue(worker.is_alive())
        stop.set()
        worker.join(2)
        self.assertEqual(target.frames[0], offline_frame())

    def test_mirror_sends_changes_and_heartbeats_only(self):
        target = ListTarget()
        mirror = Mirror([target], heartbeat_s=1.0)
        self.assertTrue(mirror.update("A", 10.0))
        self.assertFalse(mirror.update("A", 10.5))
        self.assertTrue(mirror.update("B", 10.6))
        self.assertTrue(mirror.update("B", 11.7))
        self.assertEqual(target.frames, ["A", "B", "B"])


class WebsiteTests(unittest.TestCase):
    """The real application and HTTP server, with the display replaced by a list."""

    def setUp(self):
        self.app = Application()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_frames_follow_website_actions(self):
        target, stop = ListTarget(), threading.Event()
        worker = threading.Thread(target=run, args=(self.url, "", [target], 0.02, stop), daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(stop.set)

        def wait_for(frame):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if target.frames and target.frames[-1] == frame:
                    return
                time.sleep(0.02)
            self.fail(f"display never showed {frame}; last was {target.frames[-1:]}")

        wait_for(frame_for(self.app.state()))
        self.app.command(dict(action="right", event_id="t1"))
        expected = frame_for(self.app.state())
        self.assertEqual(fields(expected)[0], 1)
        wait_for(expected)
        self.app.command(dict(action="select", event_id="t2"))
        expected = frame_for(self.app.state())
        self.assertNotEqual(fields(expected)[2], ["Ready", "", ""])
        wait_for(expected)

    def test_unreachable_website_shows_offline(self):
        self.assertEqual(fetch_state(self.url)["selected"], 0)
        target, stop = ListTarget(), threading.Event()
        worker = threading.Thread(target=run, args=("http://127.0.0.1:9", "", [target], 0.02, stop), daemon=True)
        worker.start()
        deadline = time.monotonic() + 3
        while not target.frames and time.monotonic() < deadline:
            time.sleep(0.02)
        stop.set()
        worker.join(2)
        self.assertEqual(target.frames[0], offline_frame())


if __name__ == "__main__":
    unittest.main()
