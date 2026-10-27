#!/bin/sh
# MiniBient 設置トラブルの診断用（Python を使わない）。確認が済んだら削除してください。
echo "Content-Type: text/plain; charset=utf-8"
echo ""
echo "=== diag.cgi は動きました（シェルのCGIは動作OK） ==="
echo ""
echo "--- Python の場所 ---"
for p in /usr/local/bin/python3 /usr/bin/python3 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 /usr/local/bin/python3.9 /usr/local/bin/python3.8 /usr/local/bin/python /usr/bin/python; do
  if [ -x "$p" ]; then echo "あり: $p  ($($p --version 2>&1))"; fi
done
echo "PATH 上の python3: $(command -v python3 2>/dev/null || echo なし)"
echo ""
printf '%s\n' '--- index.cgi の1行目（\r が表示されたら改行コードが CRLF） ---'
head -1 index.cgi | od -c | head -3
echo ""
echo "--- ファイルとパーミッション ---"
ls -la
echo ""
echo "--- index.cgi を直接実行した結果 ---"
./index.cgi 2>&1 | head -40
echo ""
echo "--- check.cgi を直接実行した結果 ---"
./check.cgi 2>&1 | head -40
