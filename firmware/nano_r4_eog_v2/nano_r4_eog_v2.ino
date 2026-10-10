// Experimental transport metadata. DO NOT FLASH without Kenneth's approval.
// A0 horizontal, A1 vertical; raw 14-bit averaged counts, 250 scheduled pairs/s.
// Device micros() timestamps wrap at uint32; host receipt time remains separate.
#include <Arduino.h>
constexpr uint32_t PERIOD_US=4000;
constexpr uint8_t OVERSAMPLE=1; // Allowed: 1, 2 or 4. No extra-bit claim.
static_assert(OVERSAMPLE==1 || OVERSAMPLE==2 || OVERSAMPLE==4, "Use 1, 2 or 4 reads");
uint32_t nextSampleUs, sequence=0;
void setup() {
  Serial.begin(115200); analogReadResolution(14);
  while (!Serial) delay(10);
  Serial.print("#nuggies-eog-v2,sketch=nano_r4_eog_v2,rate_hz=250,adc_bits=14,oversample=");
  Serial.println(OVERSAMPLE);
  Serial.println("sequence,device_timestamp_us,horizontal,vertical");
  nextSampleUs=micros();
}
void loop() {
  uint32_t now=micros();
  if (int32_t(now-nextSampleUs)<0) return;
  // Skip missed schedule slots, expose the gap in sequence; never burst catch up.
  uint32_t skipped=(now-nextSampleUs)/PERIOD_US;
  sequence+=skipped; nextSampleUs+=(skipped+1)*PERIOD_US;
  uint32_t timestamp=micros(), h=0, v=0;
  for (uint8_t i=0;i<OVERSAMPLE;i++) { h+=analogRead(A0); v+=analogRead(A1); }
  Serial.print(sequence++);Serial.print(',');Serial.print(timestamp);Serial.print(',');
  Serial.print((h+OVERSAMPLE/2)/OVERSAMPLE);Serial.print(',');
  Serial.println((v+OVERSAMPLE/2)/OVERSAMPLE);
}
