# ambient_lite.py - Ambient 互換サーバー (MiniBient / ambidata.io) へ送る MicroPython / Python 用ライブラリ
#
# 公式 ambient-python-lib と同じ使い方で、送信先サーバーを指定できます。
#
#   import ambient_lite
#   am = ambient_lite.Ambient(10001, "0123456789abcdef", host="example.com", port=443)   # https
#   am = ambient_lite.Ambient(10001, "0123456789abcdef", host="192.168.1.10", port=8080)        # http
#   r = am.send({"d1": 23.5, "d2": 60})
#   print(r.status_code)
#   r.close()
#
try:
    import urequests as requests      # MicroPython / UIFlow 1
except ImportError:
    try:
        import requests2 as requests  # UIFlow 2
    except ImportError:
        import requests               # パソコンの Python


class Ambient:
    def __init__(self, channelId, writeKey, readKey=None, host="ambidata.io", port=80, path="", https=None):
        # path: サブフォルダーに置いた場合のフォルダー（例 "/minibient"）
        # https: None なら port が 443 のとき https で送る
        self.channelId = channelId
        self.writeKey = writeKey
        self.readKey = readKey
        path = ("/" + path.strip("/")) if path.strip("/") else ""
        if https is None:
            https = (port == 443)
        scheme = "https" if https else "http"
        default_port = 443 if https else 80
        hostport = host if port == default_port else "%s:%d" % (host, port)
        self.url = "%s://%s%s/api/v2/channels/%s" % (scheme, hostport, path, channelId)

    def send(self, data, timeout=None):
        """data は {"d1": 1.2, ...} か、そのリスト。リストなら一括送信"""
        if not isinstance(data, list):
            data = [data]
        body = {"writeKey": self.writeKey, "data": data}
        return requests.post(self.url + "/dataarray", json=body,
                             headers={"Content-Type": "application/json"})

    def read(self, n=1):
        """新しい順に n 件読み出して、古い順のリストで返す"""
        url = self.url + "/data?n=%d" % n
        if self.readKey:
            url += "&readKey=" + self.readKey
        r = requests.get(url)
        try:
            d = r.json()
        finally:
            r.close()
        d.reverse()
        return d
