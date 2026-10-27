#!/usr/bin/env python3
"""
M5StickC の代わりにダミーデータを送るテスト用スクリプト（標準ライブラリのみ）

  # 全チャネルに30秒おきに送る（管理パスワードでチャネル一覧を取得）
  python3 tools/simulate.py --server http://localhost:8080 --admin-password XXXX

  # 1チャネルだけ
  python3 tools/simulate.py --server http://localhost:8080 --channel 10001 --write-key abcdef0123456789

  # 過去1時間分のデータを一括で入れる（グラフの見た目確認用）
  python3 tools/simulate.py ... --backfill 3600
"""
import argparse
import json
import math
import random
import time
import urllib.request


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read().decode()


def sample(t, seed):
    rnd = random.Random(seed * 1000 + int(t))
    ph = seed * 0.7
    ax = 0.3 * math.sin(t / 7 + ph) + rnd.uniform(-0.05, 0.05)
    ay = 0.3 * math.cos(t / 9 + ph) + rnd.uniform(-0.05, 0.05)
    az = 1.0 + 0.05 * math.sin(t / 3 + ph) + rnd.uniform(-0.02, 0.02)
    batt = 4.15 - (t % 7200) / 7200 * 0.5
    return {"d1": round(ax, 3), "d2": round(ay, 3), "d3": round(az, 3), "d4": round(batt, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--admin-password")
    ap.add_argument("--channel", type=int)
    ap.add_argument("--write-key")
    ap.add_argument("--interval", type=float, default=30)
    ap.add_argument("--backfill", type=int, default=0, help="過去N秒分を一括送信して終了")
    a = ap.parse_args()

    if a.channel:
        targets = [(a.channel, a.write_key)]
    else:
        req = urllib.request.Request(a.server + "/api/admin/channels",
                                     headers={"X-Admin-Password": a.admin_password or ""})
        with urllib.request.urlopen(req) as r:
            targets = [(c["chId"], c["writeKey"]) for c in json.load(r)]
    print("対象チャネル:", [c for c, _ in targets])

    if a.backfill:
        now = time.time()
        for cid, wk in targets:
            data = []
            for t in range(int(now - a.backfill), int(now), int(a.interval)):
                d = sample(t, cid)
                d["created"] = int(t * 1000)
                data.append(d)
            print(cid, post("%s/api/v2/channels/%d/dataarray" % (a.server, cid), {"writeKey": wk, "data": data}))
        return

    while True:
        t = time.time()
        for cid, wk in targets:
            body = {"writeKey": wk}
            body.update(sample(t, cid))
            try:
                print(cid, *post("%s/api/v2/channels/%d/data" % (a.server, cid), body))
            except Exception as e:
                print(cid, "error", e)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
