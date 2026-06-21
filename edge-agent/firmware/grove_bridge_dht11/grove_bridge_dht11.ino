#include <DHT.h>

static const int DHT_PIN = 3;
static const int LIGHT_PIN = A6;
static const int SOUND_PIN = A2;
static const unsigned long BAUD_RATE = 115200;

DHT dht(DHT_PIN, DHT11);

void setup() {
  Serial.begin(BAUD_RATE);
  dht.begin();
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();
  if (command != "READ") {
    return;
  }

  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  int light = analogRead(LIGHT_PIN);
  int sound = analogRead(SOUND_PIN);

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("{\"error\":\"DHT_READ_FAILED\"}");
    return;
  }

  Serial.print("{\"temperature_c\":");
  Serial.print(temperature, 2);
  Serial.print(",\"humidity_percent\":");
  Serial.print(humidity, 2);
  Serial.print(",\"light_raw\":");
  Serial.print(light);
  Serial.print(",\"sound_raw\":");
  Serial.print(sound);
  Serial.println("}");
}
