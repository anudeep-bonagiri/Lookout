#include <WiFi.h>
#include <HTTPClient.h>

// Fill these in at the event. The demo still runs if this device is unplugged.
const char* WIFI_SSID = "VENUE_WIFI";
const char* WIFI_PASSWORD = "VENUE_PASSWORD";
const char* ALARM_URL = "http://YOUR_DOMAIN/api/alarms/active?home_id=rosa";

const int LED_PIN = 2;
const int BUZZER_PIN = 4;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED_PIN, LOW);
    delay(1000);
    return;
  }

  HTTPClient http;
  http.begin(ALARM_URL);
  int code = http.GET();
  bool active = false;
  if (code == 200) {
    String body = http.getString();
    active = body.indexOf("\"active\":true") >= 0;
  }
  http.end();

  digitalWrite(LED_PIN, active ? HIGH : LOW);
  if (active) {
    tone(BUZZER_PIN, 880, 180);
  } else {
    noTone(BUZZER_PIN);
  }
  delay(2000);
}
