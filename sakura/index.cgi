#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
#
# MiniBient を CGI で動かすための入口（さくらのレンタルサーバーなど）
#
# このファイル・.htaccess・server.py・static フォルダーを同じフォルダーに置きます。
#   例: ~/www/minibient/  →  https://あなたのドメイン/minibient/
#
# 1行目の Python のパスがサーバーと違う場合は書きかえてください（check.cgi で確認できます）。
# 改行コードは LF、パーミッションは 755（または 705）にしてください。

# ===== 設定 =====================================================
# 管理画面のパスワード。空にすると自動生成して DATA_DIR/admin_password.txt に保存します
ADMIN_PASSWORD = ""

# データの保存先。Web から見えない場所（www の外）にしてください。
# 空にするとホームフォルダーの minibient_data（例: /home/ユーザー名/minibient_data）
DATA_DIR = ""

# 受講者のユーザー登録
#   "invite" = 招待コードを知っている人だけ登録できる（おすすめ）
#   "open"   = 誰でも登録できる
#   "closed" = 新しい登録を受け付けない（講座が始まって全員登録したら、こうしておくと安心）
REGISTRATION = "invite"
INVITE_CODE = ""       # 招待コードを固定したい場合に書く。空なら管理画面に表示され、作り直しもできます
MAX_CHANNELS = 3       # 1人が持てるチャネルの数
# https（SSL）で公開している場合は True。ブラウザーで http で開いても https に切り替わり、
# 送信方法ページやキーカードも https で案内します（M5StickC などからの http の送信も引き続き受け付けます）。
# SSL を設定していない場合は False にしてください。
PREFER_HTTPS = True
TZ_OFFSET = 9          # 時差（日本は 9）
MAX_ROWS = 200000      # 1チャネルあたりの最大保存件数
MIN_INTERVAL = 25      # 同じチャネルへの最短送信間隔（秒）。前回の受信からこれより短い送信は拒否します。0 で無制限
                       # （M5StickC は30秒ごとに送る想定。通信の遅れで間隔が多少縮んでもはじかれないよう5秒の余裕を見ています）
# ================================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import server
    server.run_cgi(data_dir=DATA_DIR or None, admin_password=ADMIN_PASSWORD,
                   registration=REGISTRATION, invite_code=INVITE_CODE, max_channels=MAX_CHANNELS,
                   tz_offset=TZ_OFFSET, prefer_https=PREFER_HTTPS,
                   max_rows=MAX_ROWS, min_interval=MIN_INTERVAL)
except Exception:
    import traceback
    sys.stdout.write("Status: 500 Internal Server Error\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n")
    sys.stdout.write("MiniBient の起動に失敗しました\n\n")
    traceback.print_exc(file=sys.stdout)
