# UIFlow 1（M5StickC / M5StickC Plus）用サンプル
# UIFlow の「Python」タブに貼り付けて実行します。minibient_client.py は使わず単体で動きます。
#
#   d1: 加速度X [G]  d2: 加速度Y [G]  d3: 加速度Z [G]  d4: バッテリー電圧 [V]
#   ボタンA を押すと送信します（コメント「ボタン」付き）。前回の送信から30秒たつまでは WAIT と表示
from m5stack import *
from m5ui import *
from uiflow import *
import imu
import wifiCfg
import urequests
import time

# ===== ここを書きかえる =====
WIFI_SSID = "教室のWiFi名"
WIFI_PASSWORD = "WiFiのパスワード"
SERVER = "https://example.com"  # MiniBient のアドレス（https で暗号化して送ります）
# http で送る場合: SERVER = "http://example.com"
# 教室のパソコンで動かす場合の例: SERVER = "http://192.168.1.10:8080"
CHANNEL_ID = 10001
WRITE_KEY = "0123456789abcdef"
INTERVAL = 30                          # 秒（サーバーは25秒未満の間隔の送信を拒否します）
# ===========================

setScreenColor(0x000000)
label = M5TextBox(2, 2, "WiFi...", lcd.FONT_Default, 0xFFFFFF, rotate=0)
wifiCfg.doConnect(WIFI_SSID, WIFI_PASSWORD)
imu0 = imu.IMU()
URL = "%s/api/v2/channels/%d/data" % (SERVER, CHANNEL_ID)
last_sent = None


def send(comment=None):
    global last_sent
    ax, ay, az = imu0.acceleration
    vbat = axp.getBatVoltage()
    body = {"writeKey": WRITE_KEY, "d1": ax, "d2": ay, "d3": az, "d4": vbat}
    if comment:
        body["cmnt"] = comment
    try:
        r = urequests.post(URL, json=body, headers={"Content-Type": "application/json"})
        code = r.status_code
        r.close()
    except Exception as e:
        code = -1
    last_sent = time.ticks_ms()  # 送信が終わってから数える
    label.setText("%s\nX%+.2f\nY%+.2f\nZ%+.2f\n%.2fV" % ("OK" if code == 200 else "NG %d" % code, ax, ay, az, vbat))


def buttonA_wasPressed():
    if last_sent is not None and time.ticks_diff(time.ticks_ms(), last_sent) < INTERVAL * 1000:
        label.setText("WAIT %ds" % (INTERVAL - time.ticks_diff(time.ticks_ms(), last_sent) // 1000))
        return
    send("ボタン")


btnA.wasPressed(buttonA_wasPressed)

while True:
    if last_sent is None or time.ticks_diff(time.ticks_ms(), last_sent) >= INTERVAL * 1000:
        send()
    wait_ms(200)
