/*
 * MinibientClient のいちばん簡単な例（ESP32 / ESP8266 共通）
 * 乱数を d1 に 30秒おきに送ります（サーバーは25秒未満の間隔の送信を拒否します）。
 */
#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <WiFiClientSecureBearSSL.h>
  using SecureClient = BearSSL::WiFiClientSecure;
#else
  #include <WiFi.h>
  #include <WiFiClientSecure.h>
  using SecureClient = WiFiClientSecure;
#endif
#include "MinibientClient.h"

const char *WIFI_SSID     = "教室のWiFi名";
const char *WIFI_PASSWORD = "WiFiのパスワード";
const char *SERVER_HOST   = "example.com";
const uint16_t SERVER_PORT = 443;   // https。http なら 80
const unsigned int CHANNEL_ID = 10001;
const char *WRITE_KEY = "0123456789abcdef";

SecureClient client;   // https 用（http で送るなら WiFiClient client; に）
MinibientClient mb;

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.println(WiFi.localIP());
  client.setInsecure();  // 証明書の確認を省略（暗号化はされる）
  mb.begin(CHANNEL_ID, WRITE_KEY, &client, SERVER_HOST, SERVER_PORT);
}

void loop() {
  mb.set(1, random(0, 1000) / 10.0);
  if (mb.send()) {
    Serial.println("送信OK");
  } else {
    Serial.printf("送信失敗: %d %s\n", mb.status, mb.errorString().c_str());
    Serial.println(mb.response);
  }
  delay(30000);
}
