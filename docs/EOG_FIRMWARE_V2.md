# Optional Nano capture metadata sketch

`firmware/nano_r4_eog_v2/nano_r4_eog_v2.ino` is a proposed alternative sketch.
**It has not been flashed, compiled against the board package, or validated on hardware.**
Kenneth must explicitly approve flashing. The existing acquisition sketch is unchanged.

The sketch emits a `#nuggies-eog-v2` metadata line with sketch name, nominal rate,
ADC bits and oversampling count, then rows:

```text
sequence,device_timestamp_us,horizontal,vertical
0,123456,8192,8000
```

It schedules 250 pairs/s and uses `micros()` at the start of acquisition. A0/A1
reads remain sequential. `OVERSAMPLE` may be 1 (default), 2 or 4; integer averages
remain 14-bit counts, without a claim of extra effective resolution. If acquisition
or serial falls behind, it skips schedule slots and exposes those skips in sequence
numbers instead of bursting to catch up. Both sequence and micros wrap at uint32.
Worst-case row bandwidth remains below 115200 baud's nominal payload capacity;
actual ADC/serial execution timing needs a board measurement.

The host parser accepts legacy two-count rows and these four-field rows. It retains
sequence/device time on ADCSample, tracks sequence gaps/duplicates/resets and received
rate from device intervals, and reads the metadata header. `/api/state.input_transport`
exposes those diagnostics. Counts of gaps include firmware schedule misses and
transport loss; they cannot distinguish the two alone.

New app serial recordings append `sequence,device_timestamp_us` to the existing
five CSV columns. These fields are blank for legacy firmware. Replay accepts both
schemas, preserves host receipt timestamps and device metadata, and validates the
uint32 ranges. Existing recorded files are unchanged. The live detector still assumes
250 Hz; transport metrics are diagnostics, not automatic resampling or rate correction.

Before deployment: compile for the confirmed Nano R4 board package, measure 1/2/4-read
loop timing, verify header/rate and wrap/drop handling, and approve a flash explicitly.
Keep body electrodes disconnected during firmware/assembly changes.
