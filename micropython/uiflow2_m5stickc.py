# UIFlow 2（M5StickC Plus / Plus2 など）用サンプル
# UIFlow 2 の Python 画面に貼り付けて実行します。WiFi は UIFlow 2 の設定でつないでおきます。
#
#   d1: 加速度X [G]  d2: 加速度Y [G]  d3: 加速度Z [G]  d4: バッテリー電圧 [V]
import M5
from M5 import *
import requests2
import time

# ===== ここを書きかえる =====
SERVER = "https://example.com"  # MiniBient のアドレス（https で暗号化して送ります）
# http で送る場合: SERVER = "http://example.com"
# 教室のパソコンで動かす場合の例: SERVER = "http://192.168.1.10:8080"
CHANNEL_ID = 10001
WRITE_KEY = "0123456789abcdef"
INTERVAL_MS = 30000   # サーバーは25秒未満の間隔の送信を拒否します
# ===========================

URL = "%s/api/v2/channels/%d/data" % (SERVER, CHANNEL_ID)
last = -INTERVAL_MS


def send(comment=None):
    ax, ay, az = Imu.getAccel()
    vbat = Power.getBatteryVoltage() / 1000
    body = {"writeKey": WRITE_KEY, "d1": ax, "d2": ay, "d3": az, "d4": vbat}
    if comment:
        body["cmnt"] = comment
    try:
        r = requests2.post(URL, json=body, headers={"Content-Type": "application/json"})
        code = r.status_code
        r.close()
    except Exception:
        code = -1
    Lcd.fillScreen(0x000000)
    Lcd.setCursor(0, 0)
    Lcd.print("%s\nX%+.2f\nY%+.2f\nZ%+.2f\n%.2fV" % ("OK" if code == 200 else "NG %d" % code, ax, ay, az, vbat))


M5.begin()
Lcd.setRotation(1)
Lcd.setTextSize(2)

while True:
    M5.update()
    if BtnA.wasPressed():
        if time.ticks_diff(time.ticks_ms(), last) >= INTERVAL_MS:
            send("ボタン")
            last = time.ticks_ms()  # 送信が終わってから数える
        else:
            Lcd.fillScreen(0x000000)
            Lcd.setCursor(0, 0)
            Lcd.print("WAIT %ds" % ((INTERVAL_MS - time.ticks_diff(time.ticks_ms(), last)) // 1000 + 1))
    if time.ticks_diff(time.ticks_ms(), last) >= INTERVAL_MS:
        send()
        last = time.ticks_ms()
    time.sleep_ms(20)
