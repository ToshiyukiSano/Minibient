# MiniBient — Ambient 互換の IoT データ可視化サーバー

M5StickC などのマイコンから送ったデータを保存して、グラフで見られるサーバーです。
[Ambient](https://ambidata.io/) と同じ API でデータを受け取るので、Ambient 向けの送り方がほぼそのまま使えます。
講座で使いやすいように、**招待コード制のユーザー登録**、**受講者分のチャネルの一括作成とキーカードの印刷**、**全員のデータの一覧表示**ができます。

- Python 3.8 以降だけで動きます（追加インストール不要）。Windows / Mac / Linux / Raspberry Pi / VPS
- **さくらのレンタルサーバーなど CGI しか使えない共用サーバーでも動きます**（[6章](#6-さくらのレンタルサーバーで動かすcgi版)）
- グラフ用ライブラリ（Chart.js）を同梱しているので、**インターネットにつながらない教室 LAN でも動きます**
- データは `minibient.db`（SQLite ファイル）1つに保存されます

```
minibient/
├── server.py              サーバー本体
├── static/                画面（HTML/CSS/JS）
├── tools/simulate.py      M5StickC の代わりにダミーデータを送るテスト用
├── arduino/AmbientLite/   Arduino 用ライブラリ（送信先を指定できる Ambient 互換）
├── micropython/           UIFlow 1 / UIFlow 2 / MicroPython 用
├── sakura/                レンタルサーバー（CGI）用の index.cgi・.htaccess・check.cgi
├── start.bat / start.sh   起動用
└── Dockerfile, minibient.service   常時運用したい場合
```

---

## 1. 起動する

```bash
python3 server.py            # Windows は start.bat をダブルクリックでも可
```

起動すると次のように表示されます。

```
 画面      : http://localhost:8080/
            http://192.168.1.10:8080/   ← M5StickC からはこのアドレス
 管理画面  : http://localhost:8080/admin
 管理パスワード: Xy3k...（admin_password.txt にも保存）
```

M5StickC に書き込むサーバーアドレスは、2行目の **`192.168.x.x` のほう** です（`localhost` はそのパソコン自身を指すので M5StickC からは使えません）。

### 主なオプション

| 引数 | 環境変数 | 既定値 | 内容 |
|---|---|---|---|
| `--port` | `MB_PORT` | 8080 | 待ち受けポート |
| `--admin-password` | `MB_ADMIN_PASSWORD` | 自動生成 | 管理画面のパスワード |
| `--registration` | `MB_REGISTRATION` | invite | ユーザー登録：`invite`=招待コードが必要 / `open`=誰でも / `closed`=停止 |
| `--invite-code` | `MB_INVITE_CODE` | 自動生成 | 招待コードを固定する（未指定なら管理画面で確認・作り直し） |
| `--max-channels` | `MB_MAX_CHANNELS` | 3 | 1ユーザーが持てるチャネル数 |
| `--db` | `MB_DB` | `./minibient.db` | 保存先ファイル |
| `--max-rows` | `MB_MAX_ROWS` | 200000 | 1チャネルの最大保存件数（超えると古い順に削除） |
| `--min-interval` | `MB_MIN_INTERVAL` | 25 | 同じチャネルへの最短送信間隔（秒）。前回の受信からこれより短い送信は 429 で拒否。0 で無制限 |
| `--tz` | `MB_TZ_OFFSET` | 9 | 時差（日本は 9） |

### うまくつながらないとき

- **Windows のファイアウォール**：初回起動時の「アクセスを許可する」で「プライベートネットワーク」を許可してください。出なかった場合は「Windows Defender ファイアウォールによるアプリケーションの許可」で Python を許可します
- **M5StickC とパソコンが同じ WiFi か**：ゲスト WiFi や「プライバシーセパレーター（AP アイソレーション）」が有効な WiFi では、端末同士が通信できません。講座用にはモバイルルーターを1台用意するのが確実です
- M5StickC は **2.4GHz の WiFi** にしかつながりません
- 同じ WiFi につないだスマホで `http://192.168.x.x:8080/` が開ければ、M5StickC からも届きます

---

## 2. 講座の準備（講師）

受講者には **ユーザー登録** をしてもらいます。ログインすると「マイページ」に自分のチャネルとキーが表示されるので、1ヶ月の間にキーを忘れても自分で確認できます。

1. `http://サーバー/admin` を開き、管理パスワードでログイン
2. 「ユーザー登録」に表示される **招待コード**（8文字）を受講者に伝えます。「登録用リンクをコピー」で、コード入力済みの登録ページのURLを配ることもできます
3. 受講者は「ログイン / 登録」→「はじめての方」で登録し、マイページでチャネルを作ります（1人3個まで）
4. 当日は `http://サーバー/` をプロジェクターに映すと、全員のデータが5秒おきに更新されます。送信中のチャネルは左端が緑になります

**キーカードを配る方法と組み合わせる場合**
「チャネルをまとめて作る」で受講者分のチャネルを作り、「キーカードを印刷」で配ることもできます。講座で送るデータが決まっていれば、「データの名前と単位をあらかじめ決めておく」で「加速度X」などを設定しておくと、グラフに最初から名前が付きます。受講者はユーザー登録後、マイページの「配られたキーカードのチャネルを追加する」にチャネルIDとライトキーを入れると、そのチャネルを自分のアカウントに追加できます。

**講座中の管理**
- 全員の登録が済んだら招待コードを「作り直す」と、それ以降は知らない人が登録できなくなります（登録済みの人はそのまま使えます）
- パスワードを忘れた受講者には、「ユーザー一覧」の「仮パスワード発行」で仮パスワードを伝えます。ログインすると自分のパスワードへの変更を求められます
- チャネルの持ち主は、チャネル一覧の「変更」で付け替えられます。ユーザーを削除しても、チャネルとデータは残ります

リハーサルには、ダミーデータを送るスクリプトが便利です。

```bash
python3 tools/simulate.py --server http://localhost:8080 --admin-password XXXX              # 全チャネルに30秒おき
python3 tools/simulate.py --server http://localhost:8080 --admin-password XXXX --backfill 3600   # 過去1時間分を一括（30秒間隔）
```

講座後のデータは、各チャネルのページの「CSV ダウンロード」で Excel で開ける CSV として取り出せます。

---

## 3. M5StickC から送る

### Arduino IDE の場合

公式の Ambient ライブラリは送信先が `ambidata.io` に固定されているため、送信先を指定できる **AmbientLite** を同梱しています。

1. 同梱の `arduino/AmbientLite.zip` を Arduino IDE の「スケッチ → ライブラリをインクルード → .ZIP 形式のライブラリをインストール」で追加
   （または `AmbientLite` フォルダーを `Documents/Arduino/libraries/` にコピー）
2. ライブラリマネージャーで **M5Unified** をインストール
3. 「ファイル → スケッチ例 → AmbientLite → M5StickC_IMU」を開き、先頭の WiFi・サーバー・チャネルID・ライトキーを書きかえて書き込み

公式 Ambient ライブラリで書いたプログラムからの変更点は3行だけです。

```diff
- #include "Ambient.h"
- Ambient ambient;
- ambient.begin(channelId, writeKey, &client);
+ #include "AmbientLite.h"
+ AmbientLite ambient;
+ ambient.begin(channelId, writeKey, &client, "192.168.1.10", 8080);
```

`set()` / `setcmnt()` / `send()` / `bulk_send()` はそのまま使えます。送信に失敗したら `ambient.status` と `ambient.errorString()`（「ライトキーが違います」など）で原因がわかります。
本家に送りたいときは `begin(..., "ambidata.io", 80)` にすれば ambidata.io にも送れます。

### UIFlow の場合

- **UIFlow 1**（M5StickC / Plus）：`micropython/uiflow1_m5stickc.py` を Python タブに貼り付け
- **UIFlow 2**（Plus / Plus2）：`micropython/uiflow2_m5stickc.py`
- ブロックで作る場合は、HTTP の POST ブロックで URL を `http://サーバー:8080/api/v2/channels/チャネルID/data`、ヘッダー `Content-Type: application/json`、本文を `{"writeKey":"ライトキー","d1":値}` にします

### パソコンからの動作確認

```bash
curl -X POST http://192.168.1.10:8080/api/v2/channels/10001/data \
  -H "Content-Type: application/json" \
  -d '{"writeKey":"0123456789abcdef","d1":23.5,"d2":60}'
```

---

## 4. API（Ambient 互換）

| メソッド | パス | 内容 |
|---|---|---|
| POST | `/api/v2/channels/{id}/data` | 1件送信。`{"writeKey", "d1"〜"d8", "lat", "lng", "created", "cmnt"}` |
| POST | `/api/v2/channels/{id}/dataarray` | 一括送信。`{"writeKey", "data":[{...}, ...]}`（最大 10000 件） |
| GET | `/api/v2/channels/{id}/data` | 読み出し（新しい順）。`n`, `skip`, `date=YYYY-MM-DD`, `start`/`end`。非公開なら `readKey` |
| GET | `/api/v2/channels/{id}` | チャネル情報（名前・フィールド名・件数など） |
| PUT | `/api/v2/channels/{id}/data` | `{"writeKey","created","cmnt"}` でコメント、`"hide"` で非表示 |
| DELETE | `/api/v2/channels/{id}/data?writeKey=...` | 全データ削除 |

- 値は数値でも文字列（`"23.5"`）でも受け付けます
- `created` は省略するとサーバー受信時刻。`"2026-10-27 10:00:00.000"`（日本時間）、ISO 8601、UNIX 時刻（秒/ミリ秒）、負数（現在からの相対ミリ秒）に対応
- 成功時は HTTP 200 `{"status":"ok","count":1}`。キー違いは 403、チャネルなしは 404、前回の受信から25秒たっていない送信は 429（保存されません）
- 送信間隔の制限は1チャネル単位です。一括送信（`/dataarray`）は1回の送信として数えます。管理パスワード付きの送信は制限されません
- 拡張：`GET .../data?after=<ミリ秒>` でそれ以降のデータだけを取得（画面の自動更新に使用）

本家 Ambient との違い：マイコンからの送信はライトキーだけで行います（ログインは不要）。チャネルの設定変更は、持ち主がログインするか、チャネル画面の「設定」でライトキーを入れると行えます。送信間隔は既定で25秒以上（`--min-interval` で変更）です。

画面用の API（`/api/auth/*`, `/api/me/*`, `/api/ui/*`, `/api/admin/*`）は、ログインの Cookie または管理パスワード（`X-Admin-Password` ヘッダー）で認証します。

---

## 5. 常時運用する場合

**Raspberry Pi / Linux（systemd）**

```bash
sudo cp -r minibient /opt/minibient
sudo cp /opt/minibient/minibient.service /etc/systemd/system/
sudo systemctl enable --now minibient
journalctl -u minibient -f      # 管理パスワードの確認
```

**Docker**

```bash
docker build -t minibient .
docker run -d -p 8080:8080 -v minibient-data:/data -e MB_ADMIN_PASSWORD=好きなパスワード minibient
```

**インターネット上に公開する場合の注意**
M5StickC からの送信は HTTP（暗号化なし）です。ライトキーが盗み見られても困らない用途（講座のデモなど）に留めてください。ブラウザーの閲覧だけ HTTPS にしたい場合は、Caddy などのリバースプロキシで HTTPS と HTTP の両方を受けるようにします（AmbientLite は HTTPS 送信には未対応です）。管理パスワードは必ず長いものを設定してください。

---

## 6. さくらのレンタルサーバーで動かす（CGI版）

共用のレンタルサーバーでは常駐するプログラムを動かせないため、アクセスのたびに起動する **CGI** として動かします。プログラム本体（server.py）は同じものを使います。
以下は `https://あなたのドメイン/minibient/` に置く例です。

### 置くもの

ファイルマネージャーか FTP（SFTP）で、`www` の下に `minibient` フォルダーを作り、次を入れます。

```
www/minibient/
├── index.cgi      ← sakura フォルダーから
├── .htaccess      ← sakura フォルダーから（ドットで始まるファイルです）
├── check.cgi      ← sakura フォルダーから（確認が済んだら削除）
├── server.py
└── static/        ← フォルダーごと
```

- `index.cgi` と `check.cgi` のパーミッションを **755**（または 705）にします
- `minibient` フォルダーは 755（または 705）。グループや他人が書き込める設定（775 や 777）だとエラーになります
- 改行コードが LF のまま転送されるよう、FTP は「バイナリーモード」で送ります

### 動作確認と初期設定

1. `https://あなたのドメイン/minibient/check.cgi` を開き、すべて OK になるのを確認します
   - 500 エラーになる場合は、`check.cgi` と `index.cgi` の1行目 `#!/usr/local/bin/python3` がサーバーの Python の場所と合っていない可能性があります。SSH で `which python3` を実行して確認し、書きかえてください（`/usr/local/bin/python` の場合もあります）
2. `https://あなたのドメイン/minibient/` を開くと「みんなのチャネル」が表示されます
3. 管理パスワードは、ホームフォルダーの `minibient_data/admin_password.txt`（`www` の外）に自動で作られます。ファイルマネージャーで開いて確認してください。決めたパスワードを使いたい場合は、`index.cgi` 冒頭の `ADMIN_PASSWORD = ""` に書きます
   - 招待コードは管理画面に表示されます。ユーザー登録の受付方法は `index.cgi` の `REGISTRATION`（`"invite"` / `"open"` / `"closed"`）、1人が持てるチャネル数は `MAX_CHANNELS` で変えられます
4. 確認が済んだら `check.cgi` を削除します

データ（`minibient.db`）も同じ `minibient_data` フォルダーに保存されます。Web からは見えない場所です。保存先は `index.cgi` の `DATA_DIR` で変えられます。

### M5StickC からの送り方

M5StickC は **http（ポート 80）** で、フォルダー名を付けて送ります。チャネルページの「送信方法」に、そのまま使えるコードが表示されます。

```cpp
ambient.begin(10001, "ライトキー", &client, "あなたのドメイン", 80, "/minibient");
```

UIFlow の場合は `SERVER = "http://あなたのドメイン/minibient"` です。

### うまく送れないとき

- **「https に転送されました」（ステータス 301 / 302）**：サイト全体を https に転送する設定（常時 SSL 化）が効いています。同梱の `.htaccess` は、`minibient` フォルダーにだけ上の階層の転送ルールが効かないようにしてあります。それでも転送される場合は、コントロールパネル側の常時 SSL 化の設定を確認してください
- **403 エラーで、画面に MiniBient のエラーメッセージ（「writeKey が違います」など）が出ない**：さくらの **WAF（ウェブアプリケーションファイアウォール）** に止められている可能性があります。コントロールパネルの WAF のログを確認し、必要ならそのドメインの WAF を無効にしてください
- **送信の間隔**：既定では、同じチャネルへの送信は前回の受信から25秒以上あける必要があります（`index.cgi` の `MIN_INTERVAL`）。25秒以内に届いた送信は「429」で拒否され、保存されません。M5StickC は30秒ごとに送る想定で、通信の遅れで間隔が多少縮んでもはじかれないよう5秒の余裕を見ています。10名×30秒おきならCGIでも負荷は問題ありません

### https（SSL）で公開する場合

SSL を設定したら `index.cgi` の `PREFER_HTTPS = True` にします（常駐版は `--prefer-https`）。
- ブラウザーで http のページを開くと、自動で https のページに切り替わります（ブラウザー側で切り替えるので、サーバー設定との食い違いで転送がくり返されることはありません）
- 送信方法ページ・チャネル画面の「送信方法」・キーカードは https（ポート 443）で案内します
- **http での送信も引き続き受け付けます**。サーバー（さくらのコントロールパネル）の「HTTPS に転送する」設定はオフのままにしてください。オンにすると http で送る M5StickC が失敗します

M5StickC から https で送るには、AmbientLite（1.1 以降）で `WiFiClientSecure` を使い、ポートを 443 にします。

```cpp
#include <WiFiClientSecure.h>
WiFiClientSecure client;
...
client.setInsecure();   // 証明書の確認を省略（通信は暗号化されます）
ambient.begin(10001, "ライトキー", &client, "example.com", 443);
```

`setInsecure()` は証明書の確認を省略する設定です。Let's Encrypt の証明書が3ヶ月ごとに更新されても止まらないので、講座用途ではこれが扱いやすい方法です。https の送信は暗号化の準備のぶん、http より1〜2秒ほど長くかかります。UIFlow は `SERVER = "https://example.com"` のように https で書くだけで送れます。

### VPS やリバースプロキシでサブフォルダーに置く場合

常駐版（`python3 server.py`）をサブフォルダーで公開するときは、`--base-path /minibient` を付けて起動します。

---

## ライセンス

MIT License（[LICENSE](LICENSE)）。同梱の Chart.js も MIT ライセンスです（`static/vendor/chart.js.LICENSE.md`）。

MiniBient は [Ambient](https://ambidata.io/) とデータ送信の形式（API）をそろえた独立したソフトウェアで、アンビエントデーター株式会社とは関係ありません。
