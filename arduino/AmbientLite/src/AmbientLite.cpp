#include "AmbientLite.h"

static const char *kKeys[AMBIENT_LITE_NUM_PARAMS] = {
  "d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "lat", "lng", "created"
};

AmbientLite::AmbientLite()
  : status(0), client_(nullptr), channelId_(0), port_(80), https_(false), cmntSet_(false) {
  clearAll();
}

bool AmbientLite::begin(unsigned int channelId, const char *writeKey, WiFiClient *client,
                        const char *host, uint16_t port, const char *basePath) {
  if (client == nullptr || writeKey == nullptr || host == nullptr) return false;
  basePath_ = basePath ? basePath : "";
  https_ = (port == 443);
  // 先頭の / を補い、末尾の / を取る
  if (basePath_.length() > 0 && basePath_[0] != '/') basePath_ = "/" + basePath_;
  while (basePath_.length() > 0 && basePath_[basePath_.length() - 1] == '/')
    basePath_.remove(basePath_.length() - 1);
  channelId_ = channelId;
  writeKey_ = writeKey;
  client_ = client;
  host_ = host;
  port_ = port;
  clearAll();
  return true;
}

bool AmbientLite::set(int field, const char *value) {
  int i = field - 1;
  if (i < 0 || i >= AMBIENT_LITE_NUM_PARAMS || value == nullptr) return false;
  isSet_[i] = true;
  item_[i] = value;
  return true;
}

bool AmbientLite::set(int field, double value) {
  if (isnan(value) || isinf(value)) return false;
  char buf[24];
  snprintf(buf, sizeof(buf), "%.8g", value);
  return set(field, (const char *)buf);
}

bool AmbientLite::set(int field, int value) { return set(field, (long)value); }

bool AmbientLite::set(int field, long value) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%ld", value);
  return set(field, (const char *)buf);
}

bool AmbientLite::setcmnt(const char *comment) {
  if (comment == nullptr) return false;
  cmntSet_ = true;
  cmnt_ = comment;
  return true;
}

bool AmbientLite::clear(int field) {
  int i = field - 1;
  if (i < 0 || i >= AMBIENT_LITE_NUM_PARAMS) return false;
  isSet_[i] = false;
  return true;
}

void AmbientLite::clearAll() {
  for (int i = 0; i < AMBIENT_LITE_NUM_PARAMS; i++) {
    isSet_[i] = false;
    item_[i] = "";
  }
  cmntSet_ = false;
  cmnt_ = "";
}

void AmbientLite::appendEscaped(String &out, const char *s) {
  for (; *s; s++) {
    char c = *s;
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if ((unsigned char)c < 0x20) out += ' ';
    else out += c;
  }
}

bool AmbientLite::send(uint32_t timeoutMs) {
  String body;
  body.reserve(256);
  body += "{\"writeKey\":\"";
  appendEscaped(body, writeKey_.c_str());
  body += "\"";
  for (int i = 0; i < AMBIENT_LITE_NUM_PARAMS; i++) {
    if (!isSet_[i]) continue;
    body += ",\"";
    body += kKeys[i];
    body += "\":\"";
    appendEscaped(body, item_[i].c_str());
    body += "\"";
  }
  if (cmntSet_) {
    body += ",\"cmnt\":\"";
    appendEscaped(body, cmnt_.c_str());
    body += "\"";
  }
  body += "}";

  bool ok = post(basePath_ + "/api/v2/channels/" + String(channelId_) + "/data", body, timeoutMs);
  clearAll();  // 公式ライブラリと同じく、送信後はセットした値をクリア
  return ok;
}

bool AmbientLite::bulk_send(const char *json, uint32_t timeoutMs) {
  if (json == nullptr) return false;
  return post(basePath_ + "/api/v2/channels/" + String(channelId_) + "/dataarray", String(json), timeoutMs);
}

bool AmbientLite::post(const String &path, const String &body, uint32_t timeoutMs) {
  status = 0;
  response = "";
  if (client_ == nullptr) { status = -100; return false; }
  if (WiFi.status() != WL_CONNECTED) { status = -101; return false; }

  HTTPClient http;
  http.setTimeout(timeoutMs);
#if !defined(ESP8266)
  http.setConnectTimeout(timeoutMs);
#endif
  if (!http.begin(*client_, host_, port_, path, https_)) {
    status = -102;
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  status = http.POST(body);
  if (status > 0) response = http.getString();
  http.end();
  return status == 200;
}

String AmbientLite::errorString() {
  switch (status) {
    case 200: return "OK";
    case 0:    return "まだ送信していません";
    case -100: return "begin() を呼んでいません";
    case -101: return "WiFi に接続していません";
    case -102: return "接続の準備に失敗しました";
    case -1:   return https_ ? "サーバーに接続できません（https の場合は WiFiClientSecure と setInsecure() を確認）"
                         : "サーバーに接続できません（アドレス・ポート・同じWiFiか確認）";
    case 301:
    case 302:
    case 307:
    case 308:  return "https に転送されました（サーバー側の常時SSL設定を確認）";
    case -11:  return "サーバーからの返答がありません（タイムアウト）";
    case 400:  return "送ったデータの形式が正しくありません";
    case 403:  return "ライトキーが違います";
    case 404:  return "チャネルIDが違います";
    case 429:  return "送信間隔が短すぎます";
    default:
      if (status < 0) return "通信エラー (" + String(status) + ")";
      return "HTTP " + String(status);
  }
}
