#include <Wire.h>
#include <MPU6050.h>

MPU6050 mpu;

const int touchPin = 2;     // touch sensor digital output
const int relayPin = 7;     // relay module IN pin

// Active LOW relay module: LOW = relay ON, HIGH = relay OFF
const bool RELAY_ON = LOW;
const bool RELAY_OFF = HIGH;

const int FLAT_THRESHOLD = 14000;   // tune for your mounting

void setup() {
  Serial.begin(115200);
  Wire.begin();
  mpu.initialize();

  pinMode(touchPin, INPUT);
  pinMode(relayPin, OUTPUT);
  digitalWrite(relayPin, RELAY_OFF);
}

void loop() {
  int16_t ax, ay, az;
  mpu.getAcceleration(&ax, &ay, &az);

  bool isFlat = abs(az) > FLAT_THRESHOLD;
  bool isTouched = digitalRead(touchPin) == HIGH;

  // Only cut power when flat AND nobody is holding the handle
  bool relayOn = !(isFlat && !isTouched);
  digitalWrite(relayPin, relayOn ? RELAY_ON : RELAY_OFF);

  // Format: DATA,ax,ay,az,touch,relay
  Serial.print("DATA,");
  Serial.print(ax);  Serial.print(",");
  Serial.print(ay);  Serial.print(",");
  Serial.print(az);  Serial.print(",");
  Serial.print(isTouched ? 1 : 0); Serial.print(",");
  Serial.println(relayOn ? 1 : 0);

  delay(100);
}