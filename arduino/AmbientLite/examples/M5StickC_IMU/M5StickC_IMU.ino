/*
 * M5StickC の加速度とバッテリー電圧を MiniBient（Ambient 互換サーバー）に送るサンプル
 *
 * 対応機種: M5StickC / M5StickC Plus / M5StickC Plus2（M5Unified ライブラリを使用）
 * 必要なライブラリ: M5Unified（ライブラリマネージャーからインストール）, AmbientLite
 *
 *   d1: 加速度X [G]   d2: 加速度Y [G]   d3: 加速度Z [G]   d4: バッテリー電圧 [V]
 *
 * ボタンA（正面の大きなボタン）を押すと、その場で送信し「ボタン」とコメントを付けます。
 * 送信は30秒ごと。サーバーは前回の受信から25秒以内の送信を受け付けないので、ボタンも前回から30秒たつまでは残り秒数を表示します。
 */
#include <M5Unified.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include "AmbientLite.h"

// ===== ここを書きかえる =================================
const char *WIFI_SSID     = "教室のWiFi名";
const char *WIFI_PASSWORD = "WiFiのパスワード";

const char *SERVER_HOST = "example.com";  // MiniBient サーバーのアドレス
const uint16_t SERVER_PORT = 443;                // 443 = https（暗号化）。http で送るなら 80
const char *SERVER_PATH = "";                    // サーバーをフォルダーに置いた場合は "/minibient" など
// 教室のパソコンで MiniBient を動かす場合の例: SERVER_HOST = "192.168.1.10", SERVER_PORT = 8080

const unsigned int CHANNEL_ID = 10001;           // 配布されたチャネルID
const char *WRITE_KEY = "0123456789abcdef";      // 配布されたライトキー

const uint32_t SEND_INTERVAL_MS = 30 * 1000;     // 送信間隔（30秒）。サーバーは25秒未満の間隔の送信を拒否します
// =====================================================

WiFiClientSecure secureClient;   // https 用
WiFiClient plainClient;          // http 用
AmbientLite ambient;
uint32_t lastSend = 0;
uint32_t sentCount = 0;

void showStatus(const char *line1, const String &line2, uint16_t color) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setCursor(0, 0);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.println(line1);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.println(line2);
}

void connectWiFi() {
  showStatus("WiFi connecting", WIFI_SSID, TFT_YELLOW);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
    if (millis() - start > 20000) {  // 20秒つながらなければやり直し
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      start = millis();
    }
  }
  Serial.printf("\nWiFi OK: %s\n", WiFi.localIP().toString().c_str());
  showStatus("WiFi OK", WiFi.localIP().toString(), TFT_GREEN);
}

void sendData(const char *comment) {
  float ax = 0, ay = 0, az = 0;
  M5.Imu.getAccel(&ax, &ay, &az);
  float vbat = M5.Power.getBatteryVoltage() / 1000.0f;  // mV → V

  ambient.set(1, ax);
  ambient.set(2, ay);
  ambient.set(3, az);
  ambient.set(4, vbat);
  if (comment) ambient.setcmnt(comment);

  bool ok = ambient.send();
  if (ok) sentCount++;

  Serial.printf("ax=%.3f ay=%.3f az=%.3f vbat=%.2f -> %d %s\n",
                ax, ay, az, vbat, ambient.status, ambient.errorString().c_str());

  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setCursor(0, 0);
  M5.Display.setTextColor(ok ? TFT_GREEN : TFT_RED, TFT_BLACK);
  M5.Display.printf("%s #%lu\n", ok ? "SEND OK" : "SEND NG", (unsigned long)sentCount);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.printf("X %+.2f\nY %+.2f\nZ %+.2f\nBAT %.2fV\n", ax, ay, az, vbat);
  if (!ok) M5.Display.printf("err %d\n", ambient.status);  // 429 = 前回から25秒以内に送った
}

void setup() {
  auto cfg = M5.config();
  M5.begin(cfg);
  Serial.begin(115200);
  M5.Display.setRotation(1);
  M5.Display.setTextSize(2);

  connectWiFi();
  if (SERVER_PORT == 443) {
    secureClient.setInsecure();  // 証明書の確認を省略（通信の暗号化はされます）
    ambient.begin(CHANNEL_ID, WRITE_KEY, &secureClient, SERVER_HOST, SERVER_PORT, SERVER_PATH);
  } else {
    ambient.begin(CHANNEL_ID, WRITE_KEY, &plainClient, SERVER_HOST, SERVER_PORT, SERVER_PATH);
  }
  sendData("起動");
  lastSend = millis();
}

void loop() {
  M5.update();

  if (WiFi.status() != WL_CONNECTED) connectWiFi();

  if (M5.BtnA.wasPressed()) {
    uint32_t elapsed = millis() - lastSend;
    if (elapsed >= SEND_INTERVAL_MS) {
      sendData("ボタン");
      lastSend = millis();  // 送信が終わってから数え始める
    } else {
      M5.Display.fillScreen(TFT_BLACK);
      M5.Display.setCursor(0, 0);
      M5.Display.setTextColor(TFT_YELLOW, TFT_BLACK);
      M5.Display.printf("WAIT %lus\n", (unsigned long)((SEND_INTERVAL_MS - elapsed) / 1000 + 1));
    }
  }
  if (millis() - lastSend >= SEND_INTERVAL_MS) {
    sendData(nullptr);
    lastSend = millis();
  }
  delay(10);
}
