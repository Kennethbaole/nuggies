# Signal pipeline and capture tools

`ADCSample` stores raw counts. `Calibration` explicitly applies baseline, scale
and polarity to produce normalized `EOGSample` values. The threshold classifier
chooses the stronger axis; equal diagonals are ambiguous and return CENTER.
Optional exponential smoothing requires a documented rate and cutoff below
Nyquist. These are engineering tools, not validated biological decisions.

## Capture and replay

```sh
.venv/bin/python -m scripts.doctor
mkdir -p recordings
.venv/bin/python -m backend.main --serial-port PORT --count 200 --record recordings/trial-01.csv
python3 -m backend.main --replay examples/nano_r4_bench.csv --realtime
```

Replace PORT with the discovered device and close Serial Monitor. Use a new
filename for each capture; existing recordings are never replaced. CLI capture
is raw-only and has no label UI. Keep an accompanying private setup/trial note.
An interactive terminal can run `python3 -m backend.main` for keyboard-generated
samples; these exercise classification and do not represent biological signals.

## Reproducible signal fixtures

```sh
python3 -m backend.scenarios /tmp/nuggies-trial.csv --rate 100
python3 -m scripts.fit_calibration /tmp/nuggies-trial.csv /tmp/nuggies-trial.labels.csv /tmp/nuggies-calibration.json --sample-rate 100
```

Use fresh output filenames. The rate here describes the synthetic fixture,
not the bench firmware. The fitter requires at least five samples each for
neutral/left/right/up/down, fits median baseline/separation and rejects duplicate
label timestamps. Override the host-time rate estimate with the measured MCU
rate. Example profiles are arbitrary; evaluate real profiles on separate trials.

`GestureGate` allows left/right after a hold, cooldown and neutral rearm. A stale
gap requires observed neutral. `DoubleBlinkGate` only pairs already detected
blink events. Biological blink detection is not implemented; vertical gaze does
not confirm a phrase. Record neutral, movements, held gaze, returns and blinks
before selecting signal-processing parameters.
