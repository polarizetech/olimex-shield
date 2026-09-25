/*
 * EEG streaming sketch for Arduino + Olimex SHIELD-EKG-EMG.
 * Streams CSV lines "t_us,ch0,ch1" — microsecond timestamp + two raw ADC channels.
 * The bridge (apps/server/serve.py) reads column 1 (ch0) by default (`channelCol`), opens the
 * port at 115200 baud, and declares 250 Hz (apps/server/rig.py NOMINAL_RATE_HZ). If you change
 * SAMPLE_RATE or BAUD here, change them there too.
 *
 *   # ArduinoEKG ready
 *   # t_us,ch0,ch1
 *   4004,523,458
 *   8004,410,425
 *
 * Lines starting with '#' are skipped by the bridge. "# ArduinoEKG ready" is a legacy banner,
 * kept unchanged for compatibility with existing readers. The t_us column lets you verify the
 * true sample rate (consecutive deltas ~= 1e6 / SAMPLE_RATE); the bridge also measures the rate
 * it actually receives against the host clock.
 *
 * NOTE: This is a personal experimental rig, not a medical device.
 */

const int   CH0_PIN     = A0;
const int   CH1_PIN     = A1;
const long  BAUD        = 115200;
const int   SAMPLE_RATE = 250;            // Hz — must match the bridge's declared rate
const unsigned long PERIOD_US = 1000000UL / SAMPLE_RATE;

unsigned long nextSample = 0;

void setup() {
  Serial.begin(BAUD);
  analogReference(DEFAULT);
  Serial.println("# ArduinoEKG ready");
  Serial.println("# t_us,ch0,ch1");
  nextSample = micros();
}

void loop() {
  unsigned long now = micros();
  if ((long)(now - nextSample) >= 0) {
    nextSample += PERIOD_US;
    int ch0 = analogRead(CH0_PIN);   // 0..1023
    int ch1 = analogRead(CH1_PIN);
    Serial.print(now);  Serial.print(',');
    Serial.print(ch0);  Serial.print(',');
    Serial.println(ch1);
  }
}
