"""Continuous, reproducible synthetic EOG-like streams in raw ADC counts.

These are engineering test signals for exercising the pipeline before real
recordings exist. They are NOT validated biological waveforms: amplitudes,
durations, and noise levels below are placeholders to be replaced by values
measured from real BioAmp recordings.

Output uses the same raw format as the Nano (14-bit counts, two channels) and
the same CSV columns as backend/recording.py, so detection, replay, and the
recorder treat synthetic and live data identically. Intended labels are kept
separately from the measured channels (a sidecar .labels.json file).

Usage:
    python3 -m backend.eog_scenarios --scenario demo --out demo.csv
    python3 -m backend.eog_scenarios --list
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass, field

from .recording import FIELDS

FS = 250                 # samples per second, matches the 250 Hz firmware
ADC_MAX = 16383          # 14-bit
ADC_MID = 8192           # BioAmp output rests near mid-supply
START_MS = 1_700_000_000_000  # fixed so files are byte-for-byte reproducible


@dataclass(frozen=True)
class SignalParams:
    """Placeholder magnitudes in ADC counts; tune from real recordings."""

    noise_sd: float = 40.0          # broadband noise per channel
    hum_amplitude: float = 30.0     # 60 Hz mains pickup
    drift_amplitude: float = 300.0  # slow electrode/baseline wander
    drift_period_s: float = 25.0
    glance_amplitude: float = 1500.0  # horizontal step for a glance
    glance_ramp_s: float = 0.05       # saccade duration
    blink_amplitude: float = 2500.0   # vertical bump for a blink
    blink_crosstalk: float = 0.10     # fraction of blink seen on horizontal


@dataclass
class Scenario:
    """A timeline of intended actions; labels are what the user meant to do."""

    name: str
    duration_s: float
    actions: list[tuple[float, str, dict]] = field(default_factory=list)


# Each action: (start time s, kind, options). Kinds:
#   glance_right / glance_left  -> expected NEXT / PREV
#   blink                        -> natural single blink, expected nothing
#   double_blink                 -> expected SELECT
#   long_blink                   -> expected BACK
EXPECTED = {
    "glance_right": "NEXT",
    "glance_left": "PREV",
    "double_blink": "SELECT",
    "long_blink": "BACK",
    "blink": None,
}


def _scenarios() -> dict[str, Scenario]:
    return {
        "neutral": Scenario("neutral", 30.0, []),
        "glances": Scenario("glances", 20.0, [
            (3.0, "glance_right", {"hold_s": 0.4}),
            (6.0, "glance_left", {"hold_s": 0.4}),
            (9.0, "glance_right", {"hold_s": 0.6}),
            (12.0, "glance_right", {"hold_s": 0.3}),
            (15.0, "glance_left", {"hold_s": 0.5}),
        ]),
        "blinks": Scenario("blinks", 24.0, [
            (3.0, "blink", {}),
            (6.0, "double_blink", {}),
            (10.0, "blink", {}),
            (13.0, "long_blink", {}),
            (17.0, "double_blink", {}),
            (21.0, "blink", {}),
        ]),
        "demo": Scenario("demo", 30.0, [
            (3.0, "glance_right", {"hold_s": 0.4}),
            (5.0, "glance_right", {"hold_s": 0.4}),
            (7.0, "blink", {}),
            (9.0, "glance_left", {"hold_s": 0.4}),
            (12.0, "double_blink", {}),
            (16.0, "glance_right", {"hold_s": 0.5}),
            (19.0, "blink", {}),
            (22.0, "long_blink", {}),
            (26.0, "double_blink", {}),
        ]),
    }


SCENARIOS = _scenarios()


def _smoothstep(x: float) -> float:
    """0 -> 1 with zero slope at both ends (a smooth saccade-like ramp)."""
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _glance_shape(t: float, ramp: float, hold: float) -> float:
    """Step out, hold, step back. Returns 0..1."""
    if t < 0 or t > 2 * ramp + hold:
        return 0.0
    if t < ramp:
        return _smoothstep(t / ramp)
    if t < ramp + hold:
        return 1.0
    return 1.0 - _smoothstep((t - ramp - hold) / ramp)


def _blink_shape(t: float, duration: float) -> float:
    """Single smooth bump (half-sine squared). Returns 0..1."""
    if t < 0 or t > duration:
        return 0.0
    return math.sin(math.pi * t / duration) ** 2


def _long_blink_shape(t: float, plateau: float, ramp: float = 0.08) -> float:
    if t < 0 or t > 2 * ramp + plateau:
        return 0.0
    if t < ramp:
        return _smoothstep(t / ramp)
    if t < ramp + plateau:
        return 1.0
    return 1.0 - _smoothstep((t - ramp - plateau) / ramp)


def generate(scenario: str | Scenario, seed: int = 0,
             params: SignalParams = SignalParams(), fs: int = FS):
    """Return (samples, labels).

    samples: list of (horizontal_adc, vertical_adc) ints, clipped to 0..16383.
    labels:  list of dicts {"time_s", "kind", "expected"} describing intent.
    """
    if isinstance(scenario, str):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
        scenario = SCENARIOS[scenario]
    rng = random.Random(seed)
    n = int(round(scenario.duration_s * fs))
    drift_phase_h = rng.uniform(0, 2 * math.pi)
    drift_phase_v = rng.uniform(0, 2 * math.pi)
    hum_phase = rng.uniform(0, 2 * math.pi)

    # Natural variation per event so tests do not pass by exact matching.
    events = []
    for start, kind, opts in scenario.actions:
        jitter = rng.uniform(0.85, 1.15)
        if kind in ("glance_right", "glance_left"):
            sign = 1.0 if kind == "glance_right" else -1.0
            events.append(("h", start, sign * params.glance_amplitude * jitter,
                           lambda t, o=opts: _glance_shape(t, params.glance_ramp_s, o.get("hold_s", 0.4))))
        elif kind == "blink":
            dur = rng.uniform(0.18, 0.30)
            events.append(("v", start, params.blink_amplitude * jitter, lambda t, d=dur: _blink_shape(t, d)))
        elif kind == "double_blink":
            d1, d2 = rng.uniform(0.18, 0.26), rng.uniform(0.18, 0.26)
            gap = rng.uniform(0.10, 0.20)  # time between the two blinks
            amp = params.blink_amplitude * jitter
            events.append(("v", start, amp, lambda t, d=d1: _blink_shape(t, d)))
            events.append(("v", start + d1 + gap, amp, lambda t, d=d2: _blink_shape(t, d)))
        elif kind == "long_blink":
            plateau = rng.uniform(1.0, 1.4)
            events.append(("v", start, params.blink_amplitude * jitter,
                           lambda t, p=plateau: _long_blink_shape(t, p)))
        else:
            raise ValueError(f"unknown action kind {kind!r}")

    samples = []
    for i in range(n):
        t = i / fs
        h = ADC_MID + params.drift_amplitude * math.sin(2 * math.pi * t / params.drift_period_s + drift_phase_h)
        v = ADC_MID + params.drift_amplitude * math.sin(2 * math.pi * t / (params.drift_period_s * 1.3) + drift_phase_v)
        hum = params.hum_amplitude * math.sin(2 * math.pi * 60 * t + hum_phase)
        h += hum + rng.gauss(0, params.noise_sd)
        v += hum + rng.gauss(0, params.noise_sd)
        for channel, start, amp, shape in events:
            value = amp * shape(t - start)
            if value == 0.0:
                continue
            if channel == "h":
                h += value
            else:
                v += value
                h += params.blink_crosstalk * value
        samples.append((int(min(ADC_MAX, max(0, round(h)))),
                        int(min(ADC_MAX, max(0, round(v))))))

    labels = [{"time_s": start, "kind": kind, "expected": EXPECTED[kind]}
              for start, kind, _ in scenario.actions]
    return samples, labels


def write_scenario_csv(path: str, samples, fs: int = FS) -> None:
    """Write in backend/recording.py's format so --replay can read it."""
    period_ms = 1000 / fs
    with open(path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        for i, (h, v) in enumerate(samples):
            writer.writerow((START_MS + round(i * period_ms), h, v, "synthetic_scenario", "adc_counts"))


def labels_path_for(csv_path: str) -> str:
    return csv_path + ".labels.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a reproducible synthetic EOG scenario as a raw ADC recording.")
    parser.add_argument("--scenario", default="demo", help="Scenario name (see --list)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", help="New CSV path (never overwritten); labels go to <out>.labels.json")
    parser.add_argument("--list", action="store_true", help="List scenarios and exit")
    args = parser.parse_args()
    if args.list:
        for name, sc in SCENARIOS.items():
            kinds = ", ".join(k for _, k, _ in sc.actions) or "no actions"
            print(f"{name:8} {sc.duration_s:4.0f} s  {kinds}")
        return
    if not args.out:
        parser.error("--out is required")
    try:
        samples, labels = generate(args.scenario, args.seed)
        write_scenario_csv(args.out, samples)
        with open(labels_path_for(args.out), "x", encoding="utf-8") as stream:
            json.dump({"scenario": args.scenario, "seed": args.seed, "fs": FS, "labels": labels}, stream, indent=2)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    print(f"Wrote {len(samples)} samples ({len(samples) / FS:.1f} s) to {args.out}")
    print(f"Wrote {len(labels)} labels to {labels_path_for(args.out)}")


if __name__ == "__main__":
    main()
