// Nano R4 bench acquisition sketch tested through Arduino IDE.
// A0/A1: raw 14-bit ADC counts. CSV header followed by two integers per line.
// This 10 Hz bench test is not the final EOG acquisition firmware.
void setup() {
  Serial.begin(115200);
  analogReadResolution(14);
  while (!Serial) {
    delay(10);
  }
  Serial.println("horizontal,vertical");
}

void loop() {
  int horizontal = analogRead(A0);
  int vertical = analogRead(A1);
  Serial.print(horizontal);
  Serial.print(",");
  Serial.println(vertical);
  delay(100);
}
