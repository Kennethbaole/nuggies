# Exact EOG decision replay

Version 2 private JSONL audits record every full detector reset, including repeated
centering resets, with cause, input index, and whether it happened during or between
samples. Component segmenter resets are separate events. Communication on/off,
wheel on/off, speed test, recenter, serial/replay failure and sample/polling faults
are observable even when the displayed phase stays unchanged.

A session records the Git commit, detector source digest, profile digest and
settings. The first received sample captures the complete detector/filter/segmenter
checkpoint. Disabled intervals and the global index of the first CSV sample are
recorded. Each classified decision includes its rounded 50-frame window, per-label
best distances, and filter baseline/rest offset at threshold onset. These private
waveforms belong under ignored `recordings/`; never commit an audit or profile.

```sh
python -m scripts.eog_exact_replay recordings/SESSION.csv \
  recordings/SESSION.events.jsonl --profile recordings/PROFILE.json
```

Replay restores the checkpoint, applies external resets at their exact boundaries,
and lets raw-driven faults occur naturally. It fails on different profile/source,
missing CSV origin, inconsistent checkpoint time, or any differing decision/reset.
Use `--csv-start-index` only when the matching file's origin is independently known.
`--allow-code-mismatch` is an explicit development comparison, not source-verified replay.
Legacy logs lack this evidence and are rejected; the historical reset search is
covered in `EOG_FAILED_BLINK_REPRODUCTION.md`.

The equality assertion covers detector decisions, reset order, and classification
inputs. It does not reconstruct manual ring actions or infer confirmation intent,
speech delivery, or wearer accuracy. Transition logs still include application
confirmation results for review. Synthetic tests include disabled intervals,
nonzero CSV origin, repeated identical-phase resets, polling faults, clipping,
timestamp gaps, wrong profiles, and deliberately corrupted decisions.
