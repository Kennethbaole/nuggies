# Raw acquisition and recording

A0 is horizontal and A1 is vertical. USB serial runs at 115200 baud and sends
`horizontal,vertical` followed by two integer ADC counts (0–16383) per line.
The supplied Nano R4 sketch uses 14-bit resolution and sequential channel reads
with a 100 ms delay. It is a roughly 10 Hz voltage-check sketch, not final EOG
acquisition firmware. Acquisition timestamps are host receipt times.

`SerialADCSource` skips malformed rows and buffers partial lines with a bounded
buffer. Five seconds without valid data raises an error. `ADCRecorder` flushes
raw samples to CSV; `CSVReplaySource` preserves timestamps, source and units.
The fixture in examples/nano_r4_bench.csv is voltage bench data, not eye signals.
Raw counts never go directly into a normalized direction classifier.

Install pyserial only for live acquisition:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.doctor
```

Close Arduino Serial Monitor before Python opens the port. Discover the actual
port; do not assume a fixed device name. A disconnect stops acquisition and
requires restart. CLI and browser capture commands will be added with those
components.

Before connecting electrodes, confirm the exact Pill revision, electrode leads,
connectors and body-connected power arrangement against manufacturer guidance:
https://docs.upsidedownlabs.tech/hardware/bioamp/bioamp-exg-pill/index.html
Record placement, firmware, rate and power setup privately with each trial.
No body-connected acquisition has been validated by software tests.
