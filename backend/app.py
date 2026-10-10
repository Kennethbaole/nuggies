"""Local companion/HUD server. Run: python3 -m backend.app"""

import argparse
import base64
from collections import deque
import json
import math
import mimetypes
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .envfile import load_env
from .calibration import Calibration, ExponentialSmoother
from .classifier import ThresholdClassifier
from .guided import GuidedTrial
from .ring import RingState
from .speech import ElevenLabsSpeech, SpeechUnavailable
from .state_machine import DoubleBlinkGate, GestureGate
from .suggestions import OllamaSuggestions, SuggestionBusy, SuggestionUnavailable

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
MAX_BODY = 4096
MAX_SUGGEST_BODY = 4 * 1024 * 1024  # base64 audio from the browser microphone
MIN_SUGGEST_INTERVAL = 1.0


class Application:
    def __init__(self, source="demo", calibration=None, sensor_actions=False):
        load_env()
        self.lock = threading.RLock()
        self.speech_lock = threading.Lock()
        self.ring = RingState()
        self.token = os.environ.get("APP_TOKEN", "")
        self.session_id = secrets.token_hex(12)
        self.speech = ElevenLabsSpeech(ROOT / ".cache" / "tts")
        self.suggester = OllamaSuggestions()  # Local Qwen model; works offline.
        self.suggest_lock = threading.Lock()
        self.last_suggest = 0.0
        self.samples = deque(maxlen=300)
        self.event_ids = deque(maxlen=256)
        self.audio_claims = deque(maxlen=128)
        self.blinks = DoubleBlinkGate()
        self.gate = GestureGate()
        self.source = source
        self.calibration = calibration
        self.classifier = ThresholdClassifier(calibration.threshold if calibration else 0.5)
        self.sensor_actions = sensor_actions
        self.smoother = None
        self.connected = source == "demo"
        self.error = ""
        self.demo_running = False
        self.last_received = None
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.trial_label = "unlabeled"
        self.guided = GuidedTrial()
        self.recording = False
        self.record_stop = threading.Event()

    def state(self):
        with self.lock:
            data = self.ring.snapshot()
            age = None if self.last_received is None else round((time.monotonic() - self.last_received) * 1000)
            data.update(session_id=self.session_id, input_mode=self.source,
                        connected=self.connected and (self.source == "demo" or age is not None and age < 2000),
                        last_sample_age_ms=age, input_error=self.error,
                        calibrated=self.calibration is not None,
                        sensor_actions=self.sensor_actions, demo_running=self.demo_running,
                        speech_provider="elevenlabs" if self.speech.available else "browser",
                        suggest_available=self.suggester.available,
                        trial_label=self.trial_label,
                        recording=self.recording, guided=self.guided.snapshot(time.monotonic()),
                        samples=list(self.samples))
            return data

    def command(self, payload):
        action = payload.get("action")
        if not isinstance(action, str):
            raise ValueError("action is required")
        event_id = payload.get("event_id")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 80:
            raise ValueError("event_id must be a nonempty string of at most 80 characters")
        with self.lock:
            if event_id in self.event_ids:
                return self.state()
            if action == "demo":
                if self.source != "demo":
                    raise ValueError("Synthetic scenario is available only in demo input mode")
                if type(payload.get("value")) is not bool:
                    raise ValueError("demo value must be boolean")
                self.demo_running = payload["value"]
                self.gate = GestureGate()
            elif action == "blink":
                result = self.blinks.update(round(time.monotonic() * 1000))
                if result:
                    self.ring.action(result, "simulated-blink")
            elif action == "repeat":
                if self.ring.confirmed:
                    self.ring.confirm(self.ring.confirmed)
                    self.ring.revision += 1
            elif action == "suggestions_clear":
                self.ring.clear_suggestions()
            elif action == "record_stop":
                if not self.recording:
                    raise ValueError("No recording is active")
                self.record_stop.set()
                self.recording = False
                self.guided.stop()
                self.trial_label = "unlabeled"
            elif action == "guided_start":
                if self.source != "serial" or not self.recording or not self.connected or self.sensor_actions:
                    raise ValueError("Guided testing requires live recording with sensor navigation disabled")
                self.guided.start(time.monotonic())
            elif action == "guided_stop":
                self.guided.stop()
                self.trial_label = "unlabeled"
            elif action == "label":
                if self.guided.status == "running":
                    raise ValueError("Stop the guided test before labeling manually")
                if payload.get("value") not in {"unlabeled", "neutral", "left", "right", "up", "down", "blink", "held_gaze"}:
                    raise ValueError("Unknown trial label")
                self.guided = GuidedTrial()
                self.trial_label = payload["value"]
            else:
                self.ring.action(action, "manual-demo", payload.get("value"))
            self.event_ids.append(event_id)
            return self.state()

    def suggest(self, payload):
        """Ask the local model for reply previews; the ring keeps its fallback on failure."""
        if payload.get("session_id") != self.session_id:
            raise ValueError("Suggestion session mismatch")
        heard_text, audio_b64 = payload.get("heard_text"), payload.get("audio_b64")
        if heard_text is not None and not isinstance(heard_text, str):
            raise ValueError("heard_text must be a string")
        audio = None
        if audio_b64 is not None:
            if not isinstance(audio_b64, str):
                raise ValueError("audio_b64 must be a string")
            try:
                audio = base64.b64decode(audio_b64, validate=True)
            except ValueError as error:
                raise ValueError("audio_b64 is not valid base64") from error
        if not self.suggester.available:
            raise SuggestionUnavailable("Reply suggestions are not configured (OLLAMA_MODEL); curated phrases remain")
        if not self.suggest_lock.acquire(blocking=False):
            raise SuggestionBusy("A suggestion request is already running")
        try:
            if time.monotonic() - self.last_suggest < MIN_SUGGEST_INTERVAL:
                raise SuggestionBusy("Please wait a moment before listening again")
            self.last_suggest = time.monotonic()
            with self.lock:
                contact = next((c for c in self.ring.config["contacts"] if c["id"] == self.ring.contact), None)
                context_revision = self.ring.revision
                recent = [item["text"] for item in self.ring.history[:4]]
                avoid = self.ring.shown + recent
                examples = [p["text"] for p in self.ring.config["phrases"][:4]]
            result = self.suggester.suggest(contact=contact, recent=recent, avoid=avoid, audio=audio,
                                            mime_type=payload.get("mime_type"), heard_text=heard_text,
                                            style_examples=examples)
            with self.lock:
                if self.ring.revision != context_revision:
                    raise SuggestionUnavailable("Conversation changed while replies were generated; request fresh suggestions")
                self.ring.set_suggestions(result.suggestions, result.heard, result.provider)
                return self.state()
        finally:
            self.suggest_lock.release()

    def ingest(self, sample):
        normalized = self.calibration.normalize(sample) if self.calibration else None
        if normalized is not None and self.smoother is not None:
            normalized = self.smoother.apply(normalized)
        with self.lock:
            self.connected = True
            self.last_received = time.monotonic()
            self.samples.append(dict(timestamp_ms=sample.timestamp_ms,
                                     horizontal=sample.horizontal, vertical=sample.vertical,
                                     units=sample.units, source=sample.source))
            if normalized is not None and self.sensor_actions:
                direction = self.classifier.classify(normalized).direction.value
                action = self.gate.update(direction, sample.timestamp_ms)
                if action:
                    self.ring.action(action, sample.source)

    def run_demo(self):
        from .scenarios import samples
        index = 0
        scenario = list(samples(rate=50))
        while not self.stop.wait(0.02):
            with self.lock:
                running = self.demo_running
            # Always show a clearly labeled synthetic neutral trace.
            if running:
                sample, label = scenario[index % len(scenario)]
                index += 1
                normalized = Calibration(8192, 8192, 1200, 1200).normalize(sample)
                action = self.gate.update(self.classifier.classify(normalized).direction.value,
                                          round(time.monotonic() * 1000))
            else:
                from .serial_input import ADCSample
                tick = time.monotonic() - self.started
                sample = ADCSample(round(8192 + math.sin(tick * 2) * 30),
                                   round(8192 + math.cos(tick * 3) * 25),
                                   round(time.time() * 1000), "synthetic_adc")
                action = None
            self.ingest(sample)
            if action:
                with self.lock:
                    self.ring.action(action, "synthetic_adc")

    def run_serial(self, port, record_path=None):
        import csv
        from contextlib import ExitStack
        try:
            import serial
            from .recording import ADCRecorder
            from .serial_input import SerialADCSource
            with ExitStack() as stack:
                label_writer = None
                trial_writer = None
                if record_path:
                    label_path = Path(record_path).with_suffix(".labels.csv")
                    trial_path = Path(record_path).with_suffix(".trials.csv")
                    if Path(record_path).exists() or label_path.exists() or trial_path.exists():
                        raise ValueError("Recording or label file already exists; choose a new name")
                connection = stack.enter_context(serial.Serial(port, 115200, timeout=0.5, exclusive=True))
                source = SerialADCSource(connection)
                raw_stream = stack.enter_context(open(record_path, "x", newline="")) if record_path else None
                recorder = ADCRecorder(raw_stream) if raw_stream else None
                if recorder:
                    label_stream = stack.enter_context(open(label_path, "x", newline=""))
                    label_writer = csv.writer(label_stream)
                    label_writer.writerow(("timestamp_ms", "intended_label"))
                    trial_stream = stack.enter_context(open(trial_path, "x", newline=""))
                    trial_writer = csv.writer(trial_stream)
                    trial_writer.writerow(("timestamp_ms", "intended_label", "trial_id", "phase", "cue", "run_id"))
                    with self.lock:
                        self.recording = True
                while not self.stop.is_set():
                    sample = source.read_sample()
                    if recorder and self.record_stop.is_set():
                        raw_stream.close()
                        label_stream.close()
                        trial_stream.close()
                        recorder = None
                    if recorder:
                        recorder.write(sample)
                        with self.lock:
                            guided = self.guided.snapshot(time.monotonic())
                            if guided["status"] == "running":
                                self.trial_label = guided["label"]
                            elif guided["status"] == "complete":
                                self.trial_label = "unlabeled"
                            label = self.trial_label
                        label_writer.writerow((sample.timestamp_ms, label))
                        label_stream.flush()
                        trial_writer.writerow((sample.timestamp_ms, label, guided["trial_id"], guided["phase"], guided["cue"], guided["run_id"]))
                        trial_stream.flush()
                    self.ingest(sample)
        except Exception as error:
            with self.lock:
                self.connected = False
                self.error = f"{type(error).__name__}: {error}"

        finally:
            with self.lock:
                self.recording = False
                if self.guided.status == "running":
                    self.guided.stop()
                self.trial_label = "unlabeled"

    def run_replay(self, path):
        from .recording import CSVReplaySource
        try:
            with open(path, newline="") as stream:
                source = CSVReplaySource(stream)
                first_time, started = None, time.monotonic()
                while not self.stop.is_set() and (sample := source.read_sample()) is not None:
                    if first_time is None:
                        first_time = sample.timestamp_ms
                    wait = started + (sample.timestamp_ms - first_time) / 1000 - time.monotonic()
                    if wait > 0 and self.stop.wait(wait):
                        break
                    self.ingest(sample)
            with self.lock:
                self.connected = False
                self.error = "Replay complete"
        except Exception as error:
            with self.lock:
                self.connected = False
                self.error = f"{type(error).__name__}: {error}"


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Do not put tokens or utterances into access logs.

        def reply(self, status, data, content_type="application/json"):
            body = json.dumps(data, allow_nan=False).encode() if content_type == "application/json" else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'self'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            if not app.token:
                return True
            provided = self.headers.get("Authorization", "")
            return secrets.compare_digest(provided, f"Bearer {app.token}")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path.startswith("/api/"):
                if not self.authorized():
                    return self.reply(401, dict(error="Enter the session token"))
                if path == "/api/state":
                    return self.reply(200, app.state())
                if path == "/api/health":
                    return self.reply(200, dict(ok=True, schema_version=1, session_id=app.session_id))
                return self.reply(404, dict(error="Unknown endpoint"))
            requested = FRONTEND / ("index.html" if path in ("/", "/hud", "/phone") else path.lstrip("/"))
            target = requested.resolve()
            if not target.is_relative_to(FRONTEND) or not target.is_file():
                return self.reply(404, dict(error="File not found"))
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            return self.reply(200, target.read_bytes(), content_type)

        def do_POST(self):
            # Browser requests must originate from this same server, preventing
            # a remote webpage from operating a local demo or spending TTS quota.
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                return self.reply(403, dict(error="Cross-origin action rejected"))
            if not self.authorized():
                return self.reply(401, dict(error="Enter the session token"))
            try:
                path = urlsplit(self.path).path
                limit = MAX_SUGGEST_BODY if path == "/api/suggest" else MAX_BODY
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= limit:
                    raise ValueError(f"Request must contain at most {limit} bytes")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                if path == "/api/action":
                    return self.reply(200, app.command(payload))
                if path == "/api/suggest":
                    return self.reply(200, app.suggest(payload))
                if path == "/api/speech":
                    # Only previously confirmed utterances may reach cloud TTS.
                    with app.lock:
                        selection_id = payload.get("selection_id")
                        if payload.get("session_id") != app.session_id:
                            raise ValueError("Speech session mismatch")
                        item = next((item for item in app.ring.history if item["id"] == selection_id), None)
                        if item is None:
                            raise ValueError("Unknown confirmed selection")
                        if selection_id in app.audio_claims:
                            return self.reply(409, dict(error="Selection already claimed for speech"))
                        app.audio_claims.append(selection_id)
                    if not app.speech.available:
                        return self.reply(200, dict(provider="browser", text=item["text"]))
                    if not app.speech_lock.acquire(blocking=False):
                        return self.reply(429, dict(error="Speech request in progress; use text display"))
                    try:
                        audio = app.speech.synthesize(item["text"])
                        return self.reply(200, audio, "audio/mpeg")
                    finally:
                        app.speech_lock.release()
                return self.reply(404, dict(error="Unknown endpoint"))
            except (ValueError, json.JSONDecodeError) as error:
                return self.reply(400, dict(error=str(error)))
            except SuggestionBusy as error:
                return self.reply(429, dict(error=str(error)))
            except (SpeechUnavailable, SuggestionUnavailable) as error:
                return self.reply(503, dict(error=str(error)))
    return Handler


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--serial-port")
    modes.add_argument("--replay")
    parser.add_argument("--record")
    parser.add_argument("--calibration")
    parser.add_argument("--enable-sensor-actions", action="store_true")
    parser.add_argument("--lowpass-hz", type=float)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("APP_TOKEN"):
        parser.error("Set APP_TOKEN before binding to a LAN/public interface")
    if args.record and not args.serial_port:
        parser.error("--record requires --serial-port")
    if args.enable_sensor_actions and (not args.calibration or not (args.serial_port or args.replay)):
        parser.error("Sensor actions require a calibration file and serial/replay source")
    try:
        calibration = Calibration.load(args.calibration) if args.calibration else None
        app = Application("serial" if args.serial_port else "replay" if args.replay else "demo", calibration, args.enable_sensor_actions)
        if args.lowpass_hz is not None:
            if calibration is None:
                parser.error("--lowpass-hz requires --calibration")
            app.smoother = ExponentialSmoother(calibration.sample_rate_hz, args.lowpass_hz)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    target, worker_args = (app.run_serial, (args.serial_port, args.record)) if args.serial_port else (app.run_replay, (args.replay,)) if args.replay else (app.run_demo, ())
    worker = threading.Thread(target=target, args=worker_args, daemon=True)
    worker.start()
    print(f"Ring companion: http://{args.host}:{args.port}\nHUD: http://{args.host}:{args.port}/hud", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
