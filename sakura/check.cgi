#!/usr/local/bin/python3
# -*- coding: utf-8 -*-
# 設置前の確認用。ブラウザーで開いて、すべて OK なら index.cgi が動きます。確認が終わったら削除してください。
import os
import sys

print("Content-Type: text/plain; charset=utf-8")
print()
print("MiniBient 動作確認")
print("=" * 40)

ok = True


def item(name, good, detail=""):
    global ok
    ok = ok and good
    print("[%s] %s %s" % ("OK" if good else "NG", name, detail))


v = sys.version_info
item("Python のバージョン", v >= (3, 8), "%s (%s)" % (sys.version.split()[0], sys.executable))

try:
    import sqlite3
    item("sqlite3 モジュール", True, sqlite3.sqlite_version)
except Exception as e:
    item("sqlite3 モジュール", False, str(e))

here = os.path.dirname(os.path.abspath(__file__))
item("server.py がある", os.path.isfile(os.path.join(here, "server.py")), here)
item("static フォルダーがある", os.path.isdir(os.path.join(here, "static")))

data_dir = os.path.join(os.path.expanduser("~"), "minibient_data")
try:
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    test = os.path.join(data_dir, ".write_test")
    with open(test, "w") as fp:
        fp.write("ok")
    os.remove(test)
    item("データ保存先に書き込める", True, data_dir)
except Exception as e:
    item("データ保存先に書き込める", False, "%s (%s)  → index.cgi の DATA_DIR を変更してください" % (data_dir, e))

try:
    sys.path.insert(0, here)
    import server  # noqa: F401
    item("server.py を読み込める", True, "version " + server.VERSION)
except Exception as e:
    item("server.py を読み込める", False, repr(e))

print()
print("SCRIPT_NAME:", os.environ.get("SCRIPT_NAME"))
print("SERVER_NAME:", os.environ.get("SERVER_NAME"))
print("HTTPS      :", os.environ.get("HTTPS", "(なし)"))
print()
print("すべて OK です。このファイル（check.cgi）は削除してください。" if ok else "NG の項目を直してください。")
