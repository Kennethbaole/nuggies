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
import socket
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .envfile import load_env
from .calibration import Calibration, ExponentialSmoother
from .classifier import ThresholdClassifier
from .live_wheel import LiveWheelTest
from .guided_eog import GuidedConfig, GuidedEOGTest
from .eog_diagnostics import DiagnosticLog
from .eog_communication import EOGConfirmation
from .eog_pipeline import EOGPipeline, SCHEMA_VERSION as EOG_SCHEMA_VERSION
from .guided import GuidedTrial
from .community import MemberBook, NotesStore, notes_text, profile_fields
from .ring import RingState
from .speech import ElevenLabsSpeech, SpeechUnavailable
from .state_machine import DoubleBlinkGate, GestureGate
from .suggestions import OllamaSuggestions, SuggestionBusy, SuggestionUnavailable, format_timing
from .transcribe import RemoteTranscriber, TranscriptionUnavailable

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
MAX_BODY = 4096
MAX_SUGGEST_BODY = 4 * 1024 * 1024  # base64 audio from the browser microphone
MAX_COMMUNITY_BODY = 64 * 1024  # base64 notes file (a short .txt)
MIN_SUGGEST_INTERVAL = 1.0


def audio_from_payload(payload):
    audio_b64 = payload.get("audio_b64")
    if audio_b64 is None:
        return None
    if not isinstance(audio_b64, str):
        raise ValueError("audio_b64 must be a string")
    try:
        return base64.b64decode(audio_b64, validate=True)
    except ValueError as error:
        raise ValueError("audio_b64 is not valid base64") from error


class Application:
    def __init__(self, source="demo", calibration=None, sensor_actions=False, eog_profile=None, eog_pulse_confirmation=False, eog_return_guard=False, eog_demo_tolerance=False):
        load_env()
        self.lock = threading.RLock()
        self.speech_lock = threading.Lock()
        self.ring = RingState()
        self.token = os.environ.get("APP_TOKEN", "")
        self.session_id = secrets.token_hex(12)
        self.speech = ElevenLabsSpeech(ROOT / ".cache" / "tts")
        self.suggester = OllamaSuggestions()  # Local Qwen model; works offline.
        # Qwen speech-to-text on the Jetson (ASR_URL) is the only way audio becomes text;
        # the reply model only ever receives the transcript.
        self.transcriber = RemoteTranscriber()
        self.notes = NotesStore()  # Per-member notes that guide replies; see backend/community.py.
        self.member_book = MemberBook()
        self.ring.config["contacts"] = self.member_book.apply_profiles(self.ring.config["contacts"] + [
            contact for contact in self.member_book.load()
            if contact["id"] not in {known["id"] for known in self.ring.config["contacts"]}])
        self.suggest_lock = threading.Lock()
        self.last_suggest = 0.0
        self.log_timing = False  # main() turns this on: one line per suggestion request.
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
        self.input_transport = {}
        self.demo_running = False
        self.last_received = None
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.trial_label = "unlabeled"
        self.guided = GuidedTrial()
        self.recording = False
        self.record_stop = threading.Event()
        self.wheel_test = False
        self.eog_communication = False
        self.eog_confirmation = EOGConfirmation(pulse_mode=eog_pulse_confirmation)
        self.eog_log = None
        self.received_samples = 0
        self.pending_eog_check = None
        self.speed_attempts = {}
        if eog_profile and (source not in ("serial","replay") or sensor_actions):
            raise ValueError("Guided EOG requires serial/replay input with calibrated actions disabled")
        self.wheel_detector = GuidedEOGTest(eog_profile,(GuidedConfig.demo if eog_demo_tolerance else GuidedConfig)(pulse_confirmation=eog_pulse_confirmation,excursion_guard=eog_return_guard)) if eog_profile else LiveWheelTest()
        self.eog_pipeline=EOGPipeline(self.wheel_detector.profile,self.wheel_detector.config,detector=self.wheel_detector,confirmation=self.eog_confirmation) if eog_profile else None
        self.eog_events=deque(maxlen=64)
        self.wheel_test_selections = deque(maxlen=128)

    def _eog_boundary(self):
        if self.eog_log:
            timestamp=self.samples[-1]['timestamp_ms'] if self.samples else None
            self.eog_log.boundary(self.received_samples-1,timestamp,self.wheel_test)

    def _reset_eog(self,cause):
        self._eog_boundary()
        if self.eog_pipeline:
            self.eog_pipeline.input_index=self.received_samples-1
            self.eog_pipeline.reset(cause)
            self.eog_events.extend(self.eog_pipeline.pending_events);self.eog_pipeline.pending_events=[]
        elif isinstance(self.wheel_detector,GuidedEOGTest):self.wheel_detector.reset(cause=cause)
        else:self.wheel_detector.reset()
        if self.eog_log:self.eog_log.record(self.wheel_detector,enabled=self.wheel_test)

    def state(self):
        with self.lock:
            data = self.ring.snapshot()
            age = None if self.last_received is None else round((time.monotonic() - self.last_received) * 1000)
            if self.wheel_test and isinstance(self.wheel_detector,GuidedEOGTest) and age is not None and age>=1000:
                self._eog_boundary()
                if self.eog_pipeline and self.wheel_detector.phase!='signal_lost':
                    self.eog_pipeline.fault('no_samples')
                    self.eog_events.extend(self.eog_pipeline.pending_events);self.eog_pipeline.pending_events=[]
                else:self.wheel_detector.fault("no_samples")
                self.eog_confirmation.clear()
                if self.eog_log:self.eog_log.record(self.wheel_detector)
            timing=[x["cue_to_detection_ms"] for x in self.speed_attempts.values() if x.get("correct") and not x.get("early_candidate")]
            data.update(eog_paused=bool(self.eog_pipeline and self.eog_pipeline.paused and self.eog_communication and self.wheel_test),eog_schema_version=EOG_SCHEMA_VERSION,eog_events=list(self.eog_events),eog_choice_pending=self.eog_confirmation.target is not None and self.eog_communication and self.wheel_test, eog_confirmation_ready=self.eog_confirmation.ready_sample is not None and self.wheel_detector.phase in ("ready","recovery") and self.eog_communication and self.wheel_test, eog_communication=self.eog_communication and self.wheel_test, eog_confirmation=self.eog_confirmation.message, pending_eog_check=self.pending_eog_check,speed_results=list(self.speed_attempts.values()),speed_median_ms=statistics.median(timing) if timing else None,eog_engine="waveform" if isinstance(self.wheel_detector,GuidedEOGTest) else "legacy", session_id=self.session_id, input_mode=self.source,
                        connected=self.connected and (self.source == "demo" or age is not None and age < 2000),
                        last_sample_age_ms=age, input_error=self.error,input_transport=self.input_transport,
                        calibrated=self.calibration is not None,
                        sensor_actions=self.sensor_actions or self.wheel_test, demo_running=self.demo_running,
                        wheel_test=self.wheel_test, wheel_message=self.wheel_detector.message,
                        gaze_hover=self.wheel_detector.snapshot(),
                        speech_provider="elevenlabs" if self.speech.available else "browser",
                        suggest_available=self.suggester.available,
                        transcribe_available=self.transcriber.available,
                        has_notes=bool(self.notes.text(self.ring.contact)),
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
                if self.eog_communication and self.wheel_test:
                    raise ValueError("Use biological double blinks in communication mode")
                result = self.blinks.update(round(time.monotonic() * 1000))
                if result:
                    self.ring.action(result, "simulated-blink")
            elif action == "repeat":
                if self.ring.confirmed:
                    self.ring.confirm(self.ring.confirmed)
                    self.ring.revision += 1
            elif action == "suggestions_clear":
                self.ring.clear_suggestions()
            elif action == "default_choices":
                self.eog_confirmation.clear()
                self.ring.default_choices()
            elif action == "eog_communication":
                if type(payload.get("value")) is not bool:
                    raise ValueError("eog_communication value must be boolean")
                enabled = payload["value"]
                if enabled and (not isinstance(self.wheel_detector,GuidedEOGTest) or self.source != "serial" or not self.state()["connected"] or self.sensor_actions or self.guided.status == "running"):
                    raise ValueError("Communication requires connected waveform serial input and stopped cues")
                self.eog_communication = enabled
                self.wheel_test = enabled
                self.ring.cardinal_layout = enabled
                self.ring.screen = "home"; self.ring.selected = 6 if enabled else 0
                self.ring.pages = {"home": 0, "needs": 0}
                self.ring.revision += 1
                self.pending_eog_check = None
                self.eog_confirmation.clear()
                self._reset_eog("communication_on" if enabled else "communication_off")
            elif action == "speed_test":
                if not isinstance(self.wheel_detector,GuidedEOGTest) or self.source!="serial" or not self.state()["connected"] or not self.recording or self.sensor_actions or self.guided.status=="running":
                    raise ValueError("Speed check requires connected recorded waveform input and stopped cues")
                if self.eog_communication:
                    self.ring.pages={"home":0,"needs":0};self.ring.selected=0
                self.eog_communication=False;self.ring.cardinal_layout=False;self.eog_confirmation.clear()
                self.speed_attempts={};self.pending_eog_check="speed"
                self.wheel_test=True;self._reset_eog("speed_test")
            elif action == "wheel_test":
                if type(payload.get("value")) is not bool:
                    raise ValueError("wheel_test value must be boolean")
                if payload["value"]:
                    if ((self.source != "serial" and not (self.source == "replay" and isinstance(self.wheel_detector,GuidedEOGTest))) or not self.state()["connected"] or self.sensor_actions
                            or self.guided.status == "running"):
                        raise ValueError("Wheel test requires connected serial, stopped guided cues, and disabled calibrated control")
                if not payload["value"] and self.guided.mode in ("diagnostic","speed"):self.guided.stop()
                self.pending_eog_check=None
                if self.eog_communication:
                    self.ring.pages={"home":0,"needs":0};self.ring.selected=0
                self.eog_communication=False;self.ring.cardinal_layout=False;self.eog_confirmation.clear()
                self.ring.revision += 1
                self.wheel_test = payload["value"]
                self._reset_eog("wheel_test_on" if self.wheel_test else "wheel_test_off")
            elif action == "eog_recenter":
                if not self.wheel_test or not isinstance(self.wheel_detector,GuidedEOGTest):
                    raise ValueError("Recenter requires an active guided EOG test")
                if self.guided.mode in ("diagnostic","speed"):self.guided.stop()
                self.pending_eog_check=None
                self.eog_confirmation.clear()
                self._reset_eog("recenter")
            elif action == "record_stop":
                if not self.recording:
                    raise ValueError("No recording is active")
                self.pending_eog_check=None
                self.record_stop.set()
                if self.eog_log:self.eog_log.recording("recording_stop",self.received_samples-1)
                self.recording = False
                self.guided.stop()
                self.trial_label = "unlabeled"
            elif action == "guided_start":
                if self.eog_communication:
                    raise ValueError("Stop communication mode before guided testing")
                mode=payload.get("value") or "horizontal"
                diagnostic=mode in ("diagnostic","speed")
                if self.source != "serial" or not self.recording or not self.connected or self.sensor_actions:
                    raise ValueError("Guided testing requires live recording with calibrated navigation disabled")
                if diagnostic:
                    if not self.wheel_test or not self.state()["connected"] or not isinstance(self.wheel_detector,GuidedEOGTest) or self.wheel_detector.phase!="ready":
                        raise ValueError("Diagnostic check requires the guided EOG test to be Ready")
                elif self.wheel_test:
                    raise ValueError("Stop the eye wheel test before acquisition-only protocols")
                if mode=="speed":self.speed_attempts={}
                self.guided.start(time.monotonic(), mode)
            elif action == "guided_stop":
                self.guided.stop()
                self.pending_eog_check=None
                self.trial_label = "unlabeled"
            elif action == "label":
                if self.guided.status == "running":
                    raise ValueError("Stop the guided test before labeling manually")
                if payload.get("value") not in {"unlabeled", "neutral", "left", "right", "up", "down", "blink", "double_blink", "held_gaze"}:
                    raise ValueError("Unknown trial label")
                self.guided = GuidedTrial()
                self.trial_label = payload["value"]
            else:
                self.eog_confirmation.clear()
                self.ring.action(action, "manual-demo", payload.get("value"))
            self.event_ids.append(event_id)
            return self.state()

    def transcribe(self, payload):
        """Speech-to-text only, through Qwen on the Jetson; the ring is not changed."""
        if payload.get("session_id") != self.session_id:
            raise ValueError("Transcription session mismatch")
        audio = audio_from_payload(payload)
        if audio is None:
            raise ValueError("audio_b64 is required")
        if not self.suggest_lock.acquire(blocking=False):
            raise SuggestionBusy("A listening request is already running")
        try:
            transcript = self.transcriber.transcribe(audio, payload.get("mime_type"))
        finally:
            self.suggest_lock.release()
        return dict(text=transcript.text, language=transcript.language,
                    model=transcript.model, latency_ms=transcript.latency_ms)

    def hear(self, audio, mime_type):
        """Turn audio into text with Qwen; TranscriptionUnavailable propagates."""
        text = self.transcriber.transcribe(audio, mime_type).text
        if not text:
            raise SuggestionUnavailable("No speech was heard; try again closer to the microphone")
        return text

    def community(self):
        """Community page: every member and the notes saved for each."""
        with self.lock:
            members = [dict(member) for member in self.ring.config["contacts"]]
        for member in members:
            member["notes"] = self.notes.load(member["id"])
        return dict(session_id=self.session_id, members=members, suggest_available=self.suggester.available)

    def community_command(self, payload):
        """Add and edit members and manage their notes; preview asks the reply model without touching the ring."""
        if payload.get("session_id") != self.session_id:
            raise ValueError("Community session mismatch")
        action, member_id = payload.get("action"), payload.get("member_id")
        if action == "add_member":
            with self.lock:
                member = self.member_book.add(payload.get("name"), payload.get("relationship"),
                                              self.ring.config["contacts"])
                self.ring.config["contacts"] = self.ring.config["contacts"] + [member]
                self.ring.revision += 1
            return self.community()
        with self.lock:
            member = next((dict(m) for m in self.ring.config["contacts"] if m["id"] == member_id), None)
        if member is None:
            raise ValueError("Unknown member")
        if action == "save_notes":
            file_b64 = payload.get("file_b64")
            if not isinstance(file_b64, str):
                raise ValueError("file_b64 must be a string")
            try:
                data = base64.b64decode(file_b64, validate=True)
            except ValueError as error:
                raise ValueError("file_b64 is not valid base64") from error
            self.notes.save(member_id, notes_text(data), payload.get("filename"))
        elif action == "remove_notes":
            self.notes.remove(member_id)
        elif action == "update_member":
            fields = profile_fields(payload)
            with self.lock:
                self.member_book.save_profile(member_id, fields)
                self.ring.config["contacts"] = [dict(m, **fields) if m["id"] == member_id else m
                                                for m in self.ring.config["contacts"]]
        elif action == "preview":
            return self.preview(member, payload.get("heard"))
        else:
            raise ValueError("Unknown community action")
        with self.lock:
            self.ring.revision += 1  # Open companions refresh their notes indicator.
        return self.community()

    def preview(self, member, heard):
        """Fresh suggestions for something this member might say, shaped by their notes.
        Nothing reaches the ring, history or speech."""
        if not isinstance(heard, str) or not heard.strip():
            raise ValueError("Type something they might say")
        if not self.suggester.available:
            raise SuggestionUnavailable("Reply suggestions are not configured (OLLAMA_MODEL), so there is nothing to preview")
        if not self.suggest_lock.acquire(blocking=False):
            raise SuggestionBusy("Suggestions are already being generated; try again in a moment")
        try:
            notes = self.notes.text(member["id"])
            with self.lock:
                examples = [p["text"] for p in self.ring.config["phrases"][:4]]
            result = self.suggester.suggest(contact=member, heard_text=heard[:300],
                                            style_examples=examples, notes=notes)
        finally:
            self.suggest_lock.release()
        return dict(heard=result.heard, suggestions=[item["text"] for item in result.suggestions],
                    used_notes=bool(notes), model=result.model, latency_ms=result.latency_ms)

    def suggest(self, payload):
        """Hear audio with Qwen, then ask the local model for reply previews.

        Listening needs only ASR_URL: without a reply model the transcript is shown
        and the phrases stay. The ring keeps its fallback on failure."""
        if payload.get("session_id") != self.session_id:
            raise ValueError("Suggestion session mismatch")
        heard_text = payload.get("heard_text")
        if heard_text is not None and not isinstance(heard_text, str):
            raise ValueError("heard_text must be a string")
        audio = audio_from_payload(payload)
        if audio is not None and not self.transcriber.available:
            raise TranscriptionUnavailable("Speech-to-text is not configured (ASR_URL); type what they said instead")
        if audio is None and not self.suggester.available:
            raise SuggestionUnavailable("Reply suggestions are not configured (OLLAMA_MODEL); curated phrases remain")
        if not self.suggest_lock.acquire(blocking=False):
            raise SuggestionBusy("A suggestion request is already running")
        try:
            if time.monotonic() - self.last_suggest < MIN_SUGGEST_INTERVAL:
                raise SuggestionBusy("Please wait a moment before listening again")
            self.last_suggest = time.monotonic()
            if audio is not None:
                heard_text = self.hear(audio, payload.get("mime_type"))
                if not self.suggester.available:
                    with self.lock:
                        self.ring.show_heard(heard_text)
                        return self.state()
            with self.lock:
                contact = next((c for c in self.ring.config["contacts"] if c["id"] == self.ring.contact), None)
                context_revision = self.ring.revision
                recent = [item["text"] for item in self.ring.history[:4]]
                avoid = self.ring.shown + recent
                examples = [p["text"] for p in self.ring.config["phrases"][:4]]
                notes = self.notes.text(self.ring.contact)
            result = self.suggester.suggest(contact=contact, recent=recent, avoid=avoid,
                                            heard_text=heard_text, style_examples=examples, notes=notes)
            if self.log_timing:
                print(f"Suggestions ({result.model}) {format_timing(result.timing)}", flush=True)
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
            self.received_samples += 1
            self.connected = True
            self.last_received = time.monotonic()
            self.samples.append(dict(timestamp_ms=sample.timestamp_ms,
                                     horizontal=sample.horizontal, vertical=sample.vertical,
                                     units=sample.units, source=sample.source))
            if self.eog_log:self.eog_log.before_sample(self.wheel_detector,self.received_samples-1,sample.timestamp_ms,self.wheel_test)
            if self.wheel_test:
                pipeline_result=None
                if self.eog_pipeline:
                    choices={i:dict(id=(self.ring.screen,self.ring.contact,i,item['action'],item['value'],item['text'],item['enabled']),label=item['label'],enabled=item['enabled']) for i,item in enumerate(self.ring.slots())}
                    self.eog_pipeline.set_choices(choices,self.ring.selected)
                    pipeline_result=self.eog_pipeline.process(sample.horizontal,sample.vertical,sample.timestamp_ms,
                        sample_index=self.received_samples-1,communication=self.eog_communication)
                    self.eog_events.extend(pipeline_result['events'])
                    slot=next((e['slot'] for e in pipeline_result['events'] if e['type']=='gaze_accepted'),None)
                else:
                    if len(self.samples)>1 and sample.timestamp_ms-self.samples[-2]['timestamp_ms']>500:self.wheel_detector.reset()
                    slot=self.wheel_detector.process(sample.horizontal,sample.vertical)
                if self.pending_eog_check and self.wheel_detector.phase=="ready":
                    self.guided.start(time.monotonic(),self.pending_eog_check);self.pending_eog_check=None
                if self.guided.mode=="speed" and self.guided.status=="running":
                    cue=self.guided.snapshot(time.monotonic())
                    for trial,result in self.speed_attempts.items():
                        if trial!=cue["trial_id"] or cue["phase"]!="movement":result["complete"]=True
                    if cue["phase"]=="movement":
                        result=self.speed_attempts.setdefault(cue["trial_id"],dict(trial=cue["trial_id"],intended=cue["label"],detected=None,correct=False,complete=False))
                        if slot is not None and result["detected"] is None:
                            event=self.wheel_detector.last_result
                            elapsed=round(cue["phase_elapsed_s"]*1000)
                            window=(event["emitted_sample"]-event["onset_sample"])*4
                            result.update(detected=event["label"],correct=event["label"]==cue["label"],cue_to_detection_ms=elapsed,candidate_to_detection_ms=window,early_candidate=elapsed<window)
                            event.update(speed_trial=cue["trial_id"],cue_to_detection_ms=elapsed,candidate_to_detection_ms=window,early_candidate=elapsed<window)
                if slot is not None:
                    self.ring.action("focus", "eog-communication" if self.eog_communication else "eye-wheel-test", slot)
                if pipeline_result and self.eog_communication:
                    for event in pipeline_result['events']:
                        if event['type']=='selection':
                            self.ring.action('select','eog-communication')
                            event['selection_id']=self.ring.selection_id
                    if self.eog_log:
                        self.eog_log.write(dict(kind='pipeline',sample_index=self.received_samples-1,
                            state=pipeline_result['state'],events=pipeline_result['events'])) if pipeline_result['events'] else None
                if self.guided.mode in ("diagnostic","speed") and self.guided.status=="running":
                    now=time.monotonic();cue=self.guided.snapshot(now)
                    self.guided.pause(now,cue["phase"]=="prepare" and self.wheel_detector.phase!="ready")
                if self.eog_log:self.eog_log.record(self.wheel_detector,self.received_samples-1,sample.timestamp_ms)
            elif normalized is not None and self.sensor_actions:
                direction = self.classifier.classify(normalized).direction.value
                action = self.gate.update(direction, sample.timestamp_ms)
                if action:
                    self.ring.action(action, sample.source)
            if self.eog_log:self.eog_log.after_sample()

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
                with self.lock:
                    self.error = ""
                source = SerialADCSource(connection)
                raw_stream = stack.enter_context(open(record_path, "x", newline="")) if record_path else None
                recorder = ADCRecorder(raw_stream,include_device_metadata=True) if raw_stream else None
                if recorder:
                    label_stream = stack.enter_context(open(label_path, "x", newline=""))
                    label_writer = csv.writer(label_stream)
                    label_writer.writerow(("timestamp_ms", "intended_label"))
                    trial_stream = stack.enter_context(open(trial_path, "x", newline=""))
                    trial_writer = csv.writer(trial_stream)
                    trial_writer.writerow(("timestamp_ms", "intended_label", "trial_id", "phase", "cue", "run_id"))
                    with self.lock:
                        self.recording = True
                        if self.eog_log:self.eog_log.recording("recording_start",self.received_samples)
                while not self.stop.is_set():
                    sample = source.read_sample()
                    with self.lock:self.input_transport=source.snapshot()
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
                self.wheel_test = False
                self.pending_eog_check=None
                self._reset_eog("serial_error")

        finally:
            with self.lock:
                self.recording = False
                if self.guided.status == "running":
                    self.guided.stop()
                self.trial_label = "unlabeled"

    def run_serial_forever(self, port, retry_s=2.0):
        """Reopen the port after an unplug or a missing Nano, so a boot-time service recovers."""
        while not self.stop.is_set():
            self.run_serial(port)
            self.stop.wait(retry_s)

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
                self.wheel_test = False
                self.pending_eog_check=None
                self._reset_eog("replay_error")


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
                if path == "/api/community":
                    return self.reply(200, app.community())
                if path == "/api/health":
                    return self.reply(200, dict(ok=True, schema_version=1, session_id=app.session_id))
                return self.reply(404, dict(error="Unknown endpoint"))
            requested = FRONTEND / ("index.html" if path in ("/", "/hud", "/phone") else
                                    "community.html" if path in ("/community", "/contacts") else path.lstrip("/"))
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
                limit = {"/api/suggest": MAX_SUGGEST_BODY, "/api/transcribe": MAX_SUGGEST_BODY,
                         "/api/community": MAX_COMMUNITY_BODY}.get(path, MAX_BODY)
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
                if path == "/api/transcribe":
                    return self.reply(200, app.transcribe(payload))
                if path == "/api/community":
                    return self.reply(200, app.community_command(payload))
                if path == "/api/speech":
                    # Only previously confirmed utterances may reach cloud TTS.
                    with app.lock:
                        selection_id = payload.get("selection_id")
                        if (app.wheel_test and not app.eog_communication) or selection_id in app.wheel_test_selections:
                            raise ValueError("Speech is disabled for experimental wheel-test selections")
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
            except (SpeechUnavailable, SuggestionUnavailable, TranscriptionUnavailable) as error:
                return self.reply(503, dict(error=str(error)))
    return Handler


class DualStackServer(ThreadingHTTPServer):
    """Binds an IPv6 host such as `::` while still accepting IPv4 clients."""

    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


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
    parser.add_argument("--eog-log", help="New private JSONL path for diagnostic transitions and decisions")
    parser.add_argument("--eog-pulse-confirmation", action="store_true", help="Experimental independent blink pairing; requires profile")
    parser.add_argument("--eog-return-guard", action="store_true", help="Remember uncertain excursions and suppress their opposite return commands")
    parser.add_argument("--eog-demo-tolerance", action="store_true", help="Demonstration only: accept looser direction matches and shorten retry; more false directions")
    parser.add_argument("--eog-profile", help="Private frozen waveform profile; enables guided cardinal diagnostic mode")
    parser.add_argument("--enable-sensor-actions", action="store_true")
    parser.add_argument("--lowpass-hz", type=float)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("APP_TOKEN"):
        parser.error("Set APP_TOKEN before binding to a LAN/public interface")
    if args.eog_demo_tolerance and not args.eog_profile:
        parser.error("--eog-demo-tolerance requires --eog-profile")
    if args.eog_return_guard and not args.eog_profile:
        parser.error("--eog-return-guard requires --eog-profile")
    if args.eog_pulse_confirmation and not args.eog_profile:
        parser.error("--eog-pulse-confirmation requires --eog-profile")
    if args.eog_log and not args.eog_profile:
        parser.error("--eog-log requires --eog-profile")
    if args.record and not args.serial_port:
        parser.error("--record requires --serial-port")
    if args.enable_sensor_actions and (not args.calibration or not (args.serial_port or args.replay)):
        parser.error("Sensor actions require a calibration file and serial/replay source")
    try:
        calibration = Calibration.load(args.calibration) if args.calibration else None
        app = Application("serial" if args.serial_port else "replay" if args.replay else "demo", calibration, args.enable_sensor_actions, args.eog_profile, args.eog_pulse_confirmation, args.eog_return_guard, args.eog_demo_tolerance)
        if args.lowpass_hz is not None:
            if calibration is None:
                parser.error("--lowpass-hz requires --calibration")
            app.smoother = ExponentialSmoother(calibration.sample_rate_hz, args.lowpass_hz)
        server_class = DualStackServer if ":" in args.host else ThreadingHTTPServer
        server = server_class((args.host, args.port), make_handler(app))
        if args.eog_log:
            try:app.eog_log=DiagnosticLog(args.eog_log,app.wheel_detector)
            except OSError:
                server.server_close()
                raise
    except (ValueError, OSError) as error:
        parser.error(str(error))
    serial_target = (app.run_serial, (args.serial_port, args.record)) if args.record else (app.run_serial_forever, (args.serial_port,))
    target, worker_args = serial_target if args.serial_port else (app.run_replay, (args.replay,)) if args.replay else (app.run_demo, ())
    worker = threading.Thread(target=target, args=worker_args, daemon=True)
    worker.start()
    app.log_timing = True
    if app.suggester.available:  # Load the reply model now so the first suggestion skips the cold start.
        threading.Thread(target=app.suggester.warm, daemon=True).start()
    print(f"Ring companion: http://{args.host}:{args.port}\nHUD: http://{args.host}:{args.port}/hud", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
        worker.join(timeout=2)
        if app.eog_log:app.eog_log.close()


if __name__ == "__main__":
    main()
