// MiniBient 共通スクリプト
const MB = {
  tzOffset: 9,
  info: null,

  async api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    const pw = MB.adminPw();
    if (pw && !headers["X-Admin-Password"]) headers["X-Admin-Password"] = pw;
    const res = await fetch(path, {
      method: opts.method || "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || ("HTTP " + res.status));
      err.status = res.status;
      throw err;
    }
    return data;
  },

  // M5StickC の送信先（サーバー名・ポート・サブフォルダー）
  target() {
    // M5StickC・curl の送信先。https で公開している場合（preferHttps）は https:443 を案内する
    const host = location.hostname;
    const base = (MB.info && MB.info.basePath) || "";
    const httpPort = location.protocol === "http:" && location.port ? location.port : "80";
    const httpUrl = `http://${host}${httpPort === "80" ? "" : ":" + httpPort}${base}`;
    if (MB.info && MB.info.preferHttps) {
      return { host, port: "443", base, https: true, url: `https://${host}${base}`, httpPort, httpUrl };
    }
    return { host, port: httpPort, base, https: false, url: httpUrl, httpPort, httpUrl };
  },


  adminPw() {
    try { return sessionStorage.getItem("mb_admin") || ""; } catch (_) { return ""; }
  },
  setAdminPw(v) {
    try { v ? sessionStorage.setItem("mb_admin", v) : sessionStorage.removeItem("mb_admin"); } catch (_) {}
  },

  async loadInfo() {
    try { MB.info = await MB.api("api/ui/info"); MB.tzOffset = MB.info.tzOffset; } catch (_) {}
    // https で公開している場合、http で開かれたら https のページに切り替える
    // （ブラウザー側で切り替えるので、サーバー設定と食い違って転送がくり返されることはない）
    if (MB.info && MB.info.preferHttps && location.protocol === "http:") {
      // https は標準のポート（443）で開く
      location.replace("https://" + location.hostname + location.pathname + location.search + location.hash);
      await new Promise(() => {});  // 切り替わるまで以降の処理を止める
    }
    return MB.info;
  },

  // サーバーの時差で表示（教室の全員が同じ時刻表示になるように）
  parts(ms) {
    const d = new Date(ms + MB.tzOffset * 3600000);
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return {
      y: d.getUTCFullYear(), M: p(d.getUTCMonth() + 1), d: p(d.getUTCDate()),
      h: p(d.getUTCHours()), m: p(d.getUTCMinutes()), s: p(d.getUTCSeconds()),
    };
  },
  fmt(ms, withDate = true) {
    const t = MB.parts(ms);
    return (withDate ? `${t.y}-${t.M}-${t.d} ` : "") + `${t.h}:${t.m}:${t.s}`;
  },
  today() {
    const t = MB.parts(Date.now());
    return `${t.y}-${t.M}-${t.d}`;
  },
  ago(ms) {
    if (!ms) return "受信なし";
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 60) return s + "秒前";
    if (s < 3600) return Math.floor(s / 60) + "分前";
    if (s < 86400) return Math.floor(s / 3600) + "時間前";
    return Math.floor(s / 86400) + "日前";
  },
  freshness(ms) {
    if (!ms) return "";
    const s = (Date.now() - ms) / 1000;
    return s < 60 ? "live" : s < 600 ? "recent" : "";
  },
  num(v) {
    if (v === null || v === undefined) return "—";
    const a = Math.abs(v);
    if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(2);
    return (Math.round(v * 100) / 100).toLocaleString("ja-JP", { maximumFractionDigits: 2 });
  },
  esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },

  toast(msg, isErr = false) {
    const el = document.createElement("div");
    el.className = "toast" + (isErr ? " err" : "");
    el.setAttribute("role", "status");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), isErr ? 5000 : 2500);
  },

  async copy(text) {
    // https のページなら Clipboard API、http のページ（M5StickC 用に http で公開している場合）は従来の方法でコピー
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); MB.toast("コピーしました"); return; } catch (_) {}
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);  // iPhone の Safari 対策
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) {}
    ta.remove();
    if (ok) MB.toast("コピーしました");
    else window.prompt("コピーできませんでした。下の文字を選択してコピーしてください", text);
  },


  sparkline(canvas, points, color) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!points || points.length < 2) {
      ctx.strokeStyle = "#dde4ec"; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
      return;
    }
    let x0 = points[0][0], x1 = points[points.length - 1][0];
    let y0 = Infinity, y1 = -Infinity;
    for (const p of points) { y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]); }
    if (y0 === y1) { y0 -= 1; y1 += 1; }
    if (x0 === x1) x1 = x0 + 1;
    const X = t => ((t - x0) / (x1 - x0)) * (w - 4) + 2;
    const Y = v => h - 3 - ((v - y0) / (y1 - y0)) * (h - 6);
    ctx.beginPath();
    points.forEach((p, i) => i ? ctx.lineTo(X(p[0]), Y(p[1])) : ctx.moveTo(X(p[0]), Y(p[1])));
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
    ctx.lineTo(X(x1), h); ctx.lineTo(X(x0), h); ctx.closePath();
    ctx.globalAlpha = 0.12; ctx.fillStyle = color; ctx.fill();
  },

  user() { return (MB.info && MB.info.user) || null; },

  async logout() {
    try { await MB.api("api/auth/logout", { method: "POST", body: {} }); } catch (_) {}
    location.href = "./";
  },

  header(active) {
    const u = MB.info && MB.info.user;
    const nav = [
      ["./", "みんなのチャネル", "home"],
      u ? ["me", "マイページ（" + MB.esc(u.displayName) + "）", "me"] : ["login", "ログイン / 登録", "login"],
      ["guide", "送信方法", "guide"],
      ["admin", "管理", "admin"],
    ];
    const el = document.createElement("header");
    el.className = "top";
    el.innerHTML = `<div class="top-inner">
      <a class="brand" href="./">
        <svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="6" fill="#0e7c86"/>
        <polyline points="4,22 10,22 13,10 18,26 21,15 24,19 28,19" fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/></svg>
        MiniBient</a>
      <nav>${nav.map(([h, t, k]) => `<a href="${h}" ${k === active ? 'aria-current="page"' : ""}>${t}</a>`).join("")}</nav>
    </div>`;
    document.body.prepend(el);
  },
};
