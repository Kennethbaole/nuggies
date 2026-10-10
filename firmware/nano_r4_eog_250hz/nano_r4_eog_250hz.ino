// Nano R4 EOG acquisition sketch: A0 (horizontal Pill) and A1 (vertical Pill)
// sampled at a fixed 250 Hz. Output format is unchanged from the bench sketch
// (header "horizontal,vertical", then "A0,A1" raw 14-bit counts per line), so
// backend/serial_input.py, recording, and replay work without changes.
//
// Why 250 Hz: blinks last ~100-400 ms and glances ramp in ~50 ms; the 10 Hz
// bench sketch is too slow to see their shape. 250 Hz also lets a 100 ms
// moving average cancel 60 Hz mains hum on the host.
//
// Timing uses a fixed schedule (next += period) so the rate does not drift.
// Each line is ~12 bytes; 250 lines/s is ~3 KB/s, well within 115200 baud.
// The host treats sample index / 250 as time; host receipt timestamps jitter
// because USB delivers data in bursts.
//
// Safety: while electrodes are on a person, the computer reading this board
// must run on battery (charger unplugged), never on wall power.

const unsigned long SAMPLE_PERIOD_US = 4000;  // 250 Hz
unsigned long nextSampleUs;

void setup() {
  Serial.begin(115200);
  analogReadResolution(14);
  while (!Serial) {
    delay(10);
  }
  Serial.println("horizontal,vertical");
  nextSampleUs = micros();
}

void loop() {
  // Unsigned subtraction handles micros() wrap-around (~70 minutes).
  if ((long)(micros() - nextSampleUs) < 0) {
    return;
  }
  nextSampleUs += SAMPLE_PERIOD_US;

  int horizontal = analogRead(A0);
  int vertical = analogRead(A1);
  Serial.print(horizontal);
  Serial.print(',');
  Serial.println(vertical);
}
