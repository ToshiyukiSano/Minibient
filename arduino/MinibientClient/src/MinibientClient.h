/*
 * MinibientClient - Ambient (ambidata.io) 互換サーバーへデータを送る小さなライブラリ
 *
 * 公式 Ambient ライブラリとほぼ同じ使い方で、送信先のサーバーとポートを指定できます。
 * MiniBient（自前サーバー）にも、本家 ambidata.io にも送れます。
 *
 *   MinibientClient ambient;
 *   ambient.begin(channelId, writeKey, &client, "192.168.1.10", 8080);
 *
 *   // https（暗号化）で送る場合: WiFiClientSecure を使い、ポートを 443 にする
 *   //   WiFiClientSecure client;
 *   //   client.setInsecure();   // 証明書の確認を省略（暗号化はされる）
 *   //   ambient.begin(channelId, writeKey, &client, "example.com", 443);
 *   // レンタルサーバーのサブフォルダーに置いた場合:
 *   // ambient.begin(channelId, writeKey, &client, "example.sakura.ne.jp", 80, "/minibient");
 *   ambient.set(1, 23.5);
 *   ambient.send();
 *
 * 対応: ESP32 (M5StickC / M5StickC Plus / Plus2 / M5Stack など), ESP8266
 */
#ifndef MINIBIENT_CLIENT_H
#define MINIBIENT_CLIENT_H

#include <Arduino.h>
#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
#else
  #include <WiFi.h>
  #include <HTTPClient.h>
#endif

#define MINIBIENT_CLIENT_NUM_PARAMS 11   // d1〜d8, lat(9), lng(10), created(11)
#define MINIBIENT_CLIENT_TIMEOUT    10000UL

class MinibientClient {
public:
  MinibientClient();

  // host には IP アドレス（"192.168.1.10"）かホスト名を指定します
  // basePath はサーバーをサブフォルダーに置いた場合のフォルダー（例 "/minibient"）
  // port が 443 のときは https で送ります（client には WiFiClientSecure を渡してください）
  bool begin(unsigned int channelId, const char *writeKey, WiFiClient *client,
             const char *host = "ambidata.io", uint16_t port = 80, const char *basePath = "");

  bool set(int field, double value);     // field: 1〜8 = d1〜d8, 9 = lat, 10 = lng
  bool set(int field, int value);
  bool set(int field, long value);
  bool set(int field, const char *value); // 11 = created（"2026-10-27 10:00:00" など）
  bool setcmnt(const char *comment);      // コメント（グラフ上で確認できます）
  bool clear(int field);
  void clearAll();
  void setHttps(bool on) { https_ = on; }  // 443 以外のポートで https を使う場合

  // 送信。成功すると true。結果の HTTP ステータスは status に入ります
  bool send(uint32_t timeoutMs = MINIBIENT_CLIENT_TIMEOUT);

  // まとめて送信。json は {"writeKey":"...","data":[{...},{...}]} の形
  bool bulk_send(const char *json, uint32_t timeoutMs = MINIBIENT_CLIENT_TIMEOUT);

  int status;          // 200 なら成功。負の値は接続エラー（HTTPClient のエラーコード）
  String response;     // サーバーからの返答（エラー内容の確認用）
  String errorString(); // status を日本語で説明

private:
  bool post(const String &path, const String &body, uint32_t timeoutMs);
  static void appendEscaped(String &out, const char *s);

  WiFiClient *client_;
  unsigned int channelId_;
  String writeKey_;
  String host_;
  String basePath_;
  uint16_t port_;
  bool https_;
  bool isSet_[MINIBIENT_CLIENT_NUM_PARAMS];
  String item_[MINIBIENT_CLIENT_NUM_PARAMS];
  bool cmntSet_;
  String cmnt_;
};

#endif
