# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#   ⚡️ CONFIG ELITE v2 — تست واقعی تونل Xray
# ══════════════════════════════════════════

import asyncio, base64, html, json, logging, os, platform, random, re
import socket, subprocess, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote, urlsplit

import requests
import socks
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
try:
    from telegram import CopyTextButton
    HAS_COPY = True
except ImportError:
    HAS_COPY = False
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

BOT_TOKEN = os.environ["BOT_TOKEN"]

SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
]

TCP_TIMEOUT   = 4
MAX_TO_TEST   = 600
DEEP_LIMIT    = 80
WORKERS       = 100
DEEP_WORKERS  = 12
DEEP_TIMEOUT  = 10
REFRESH_EVERY = 900

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite")

S = {"good": [], "tcp": 0, "fetched": 0, "tested": 0, "last": None,
     "started": datetime.now(), "xray": False}
LOCK = threading.Lock()
XRAY_BIN = None

def ensure_xray():
    global XRAY_BIN
    arch = {"x86_64": "64", "aarch64": "arm64-v8a", "armv7l": "arm32-v7a"}.get(platform.machine(), "64")
    name = f"Xray-linux-{arch}.zip"
    for _ in range(3):
        try:
            rel = requests.get("https://api.github.com/repos/XTLS/Xray-core/releases/latest",
                               timeout=30, headers={"User-Agent": "cfg-bot"}).json()
            url = next(a["browser_download_url"] for a in rel["assets"] if a["name"] == name)
            open("xray.zip", "wb").write(requests.get(url, timeout=180).content)
            with zipfile.ZipFile("xray.zip") as z:
                z.extract("xray")
            os.chmod("xray", 0o755)
            XRAY_BIN = os.path.abspath("xray")
            log.info("Xray installed")
            return True
        except Exception as e:
            log.warning(f"xray download failed: {e}")
            time.sleep(5)
    return False

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(x):
    return str(x).translate(FA)

FULL, EMPTY = "▰", "▱"
def quality(ms):
    if ms < 300: return FULL * 5
    if ms < 700: return FULL * 4 + EMPTY
    if ms < 1500: return FULL * 3 + EMPTY * 2
    if ms < 3000: return FULL * 2 + EMPTY * 3
    return FULL + EMPTY * 4

def ago(dt):
    if not dt: return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60: return f"{fa(s)} ثانیه پیش"
    if s < 3600: return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

PROTO = {"vmess": "🟣 VMess", "vless": "🔵 VLESS", "trojan": "🔴 Trojan",
         "ss": "🟡 Shadowsocks", "hysteria": "🟠 Hysteria", "hy2": "🟠 Hysteria2"}
def proto_of(uri):
    low = uri[:10].lower()
    for k, v in PROTO.items():
        if low.startswith(k + "://"):
            return v
    return "⚙️ Other"

URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)

def b64decode(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")

def host_port(uri):
    try:
        low = uri.lower()
        if low.startswith("vmess://"):
            d = json.loads(b64decode(uri[8:]))
            return str(d.get("add", "")).strip(), int(d.get("port", 0))
        if low.startswith("ss://"):
            rest = uri[5:].split("#")[0].split("/?")[0]
            if "@" in rest:
                rest = rest.split("@", 1)[1].split("?")[0]
            else:
                rest = b64decode(rest).rsplit("@", 1)[-1].split("?")[0]
            host, port = rest.rsplit(":", 1)
            return host.strip("[]"), int(port)
        p = urlparse(uri)
        return p.hostname, p.port
    except Exception:
        return None, None

def tcp_ping(host, port):
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None

def test_one(uri):
    host, port = host_port(uri)
    if not host or not port or not (0 < port < 65536):
        return None
    ms = tcp_ping(host, port)
    return {"uri": uri, "host": host, "port": port, "latency": ms} if ms else None

def fetch_source(url):
    text = requests.get(url, timeout=30).text.strip()
    if "://" not in text:
        text = b64decode(text)
    return URI_RE.findall(text)

def build_stream(net, params, tls=False):
    net = (net or "tcp").lower()
    stream = {"network": net}
    security = params.get("security", "")
    if not security and tls:
        security = "tls"
    if security in ("tls", "reality"):
        stream["security"] = security
        s = {"serverName": params.get("sni") or params.get("host") or "",
             "fingerprint": params.get("fp", "chrome")}
        if params.get("alpn"):
            s["alpn"] = params["alpn"].split(",")
        if security == "reality":
            s["publicKey"] = params.get("pbk", "")
            s["shortId"] = params.get("sid", "")
        key = "realitySettings" if security == "reality" else "tlsSettings"
        stream[key] = s
    if net == "ws":
        ws = {"path": params.get("path", "/")}
        if params.get("host"):
            ws["headers"] = {"Host": params["host"]}
        stream["wsSettings"] = ws
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": params.get("serviceName", "")}
    elif net == "xhttp":
        stream["xhttpSettings"] = {"path": params.get("path", "/"), "host": params.get("host", "")}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": params.get("path", "/"), "host": params.get("host", "")}
    elif net == "h2":
        stream["httpSettings"] = {"path": params.get("path", "/"), "host": [params.get("host", "")]}
    return stream

def build_outbound(uri):
    try:
        low = uri.lower()
        if low.startswith("vmess://"):
            d = json.loads(b64decode(uri[8:]))
            params = {"host": d.get("host", ""), "path": d.get("path", ""), "sni": d.get("sni", "")}
            tls = str(d.get("tls", "")).lower() == "tls"
            return {"protocol": "vmess",
                    "settings": {"vnext": [{"address": d["add"], "port": int(d["port"]),
                                            "users": [{"id": d["id"], "security": d.get("scy", "auto"), "level": 0}]}]},
                    "streamSettings": build_stream(d.get("net", "tcp"), params, tls)}
        if low.startswith("vless://"):
            p = urlsplit(uri)
            q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
            return {"protocol": "vless",
                    "settings": {"vnext": [{"address": p.hostname, "port": p.port,
                                            "users": [{"id": unquote(p.username or ""), "encryption": "none",
                                                       "flow": q.get("flow", ""), "level": 0}]}]},
                    "streamSettings": build_stream(q.get("type", "tcp"), q)}
        if low.startswith("trojan://"):
            p = urlsplit(uri)
            q = {k: v[0] for k, v in parse_qs(p.query, keep_blank_values=True).items()}
            return {"protocol": "trojan",
                    "settings": {"servers": [{"address": p.hostname, "port": p.port,
                                              "password": unquote(p.username or q.get("password", "")), "level": 0}]},
                    "streamSettings": build_stream(q.get("type", "tcp"), q, tls=True)}
        if low.startswith("ss://"):
            body = uri[5:].split("#")[0]
            if "@" in body:
                userinfo, hostport = body.rsplit("@", 1)
                if ":" not in userinfo:
                    userinfo = b64decode(userinfo)
                userinfo = unquote(userinfo)
            else:
                body = b64decode(body).split("/?")[0]
                userinfo, hostport = body.rsplit("@", 1)
            method, pwd = userinfo.split(":", 1)
            hostport = hostport.split("?")[0]
            host, port = hostport.rsplit(":", 1)
            return {"protocol": "shadowsocks",
                    "settings": {"servers": [{"address": host.strip("[]"), "port": int(port),
                                              "method": method, "password": pwd}]}}
    except Exception:
        return None
    return None

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def _socks_http_ok(port):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", port)
    s.settimeout(6)
    try:
        s.connect(("www.gstatic.com", 80))
        req = b"GET /generate_204 HTTP/1.1\r\nHost: www.gstatic.com\r\n\r\n"
        s.sendall(req)
        data = s.recv(64)
        return b"204" in data
    finally:
        try: s.close()
        except Exception: pass

def deep_test(c):
    if XRAY_BIN is None:
        return None
    proto = c["uri"].lower().split(":")[0]
    if proto not in ("vmess", "vless", "trojan", "ss"):
        return None
    out = build_outbound(c["uri"])
    if out is None:
        return None
    port = _free_port()
    path = f"/tmp/xt_{port}.json"
    cfg = {"log": {"loglevel": "none"},
           "inbounds": [{"listen": "127.0.0.1", "port": port, "protocol": "socks",
                         "settings": {"udp": False}}],
           "outbounds": [out]}
    try:
        with open(path, "w") as f:
            json.dump(cfg, f)
        proc = subprocess.Popen([XRAY_BIN, "run", "-c", path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.monotonic()
        deadline = t0 + DEEP_TIMEOUT
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    if _socks_http_ok(port):
                        ms = round((time.monotonic() - t0) * 1000)
                        return {**c, "latency": ms}
                except Exception:
                    time.sleep(0.4)
            return None
        finally:
            try: proc.kill()
            except Exception: pass
    except Exception:
        return None
    finally:
        try: os.remove(path)
        except Exception: pass

def refresh_loop():
    global XRAY_BIN
    S["xray"] = ensure_xray()
    while True:
        uris = []
        for url in SOURCES:
            try:
                uris += fetch_source(url)
            except Exception as e:
                log.warning(f"source error: {e}")
        uris = list(dict.fromkeys(uris))
        random.shuffle(uris)
        S["fetched"] = len(uris)
        batch = uris[:MAX_TO_TEST]
        log.info(f"stage1: tcp ping {len(batch)}")
        tcp_alive = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for r in pool.map(test_one, batch):
                if r:
                    tcp_alive.append(r)
        tcp_alive.sort(key=lambda c: c["latency"])
        S["tcp"] = len(tcp_alive)

        if S["xray"] and tcp_alive:
            cands = tcp_alive[:DEEP_LIMIT]
            log.info(f"stage2: real tunnel test {len(cands)}")
            alive = []
            with ThreadPoolExecutor(DEEP_WORKERS) as pool:
                for r in pool.map(deep_test, cands):
                    if r:
                        alive.append(r)
            if alive:
                tcp_alive = alive
        tcp_alive.sort(key=lambda c: c["latency"])
        with LOCK:
            S["good"], S["tested"], S["last"] = tcp_alive, len(batch), datetime.now()
        log.info(f"done: {len(tcp_alive)} alive")
        time.sleep(REFRESH_EVERY)

def menu_text():
    g = S["good"]
    mode = "🧪 <b>تست واقعی تونل (Xray)</b>" if S["xray"] else "🔌 تست پورت (TCP)"
    lines = [
        "✦ ━━━━━━━━━━━━━━━━ ✦",
        "    ⚡️ <b>CONFIG ELITE</b> ⚡️",
        "✦ ━━━━━━━━━━━━━━━━ ✦",
        "",
        mode,
        "<i>فقط کانفیگ‌هایی که واقعاً اینترنت رد کردن</i>",
        "",
        "📊 <b>وضعیت زنده</b>",
        f"├ 🟢 سالم نهایی: <b>{fa(len(g))}</b>",
        f"├ 🔌 زنده از TCP: <b>{fa(S['tcp'])}</b>",
        f"├ 🔬 تست‌شده: <b>{fa(S['tested'])}</b>",
    ]
    if g:
        best = min(c["latency"] for c in g)
        lines.append(f"├ ⚡️ بهترین: <b>{fa(best)}ms</b> {quality(best)}")
    lines.append(f"└ 🔄 بروزرسانی: <b>{ago(S['last'])}</b>")
    lines += ["", "<blockquote>یه عدد بفرست یا دکمه بزن 👇</blockquote>"]
    return "\n".join(lines)

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ ۵", callback_data="get:5"),
         InlineKeyboardButton("🚀 ۱۰", callback_data="get:10"),
         InlineKeyboardButton("💎 ۲۵", callback_data="get:25")],
        [InlineKeyboardButton("📊 آمار", callback_data="stats"),
         InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
        [InlineKeyboardButton("♻️ تست مجدد", callback_data="retest")],
    ])

def stats_text():
    g = S["good"]
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    up = int((datetime.now() - S["started"]).total_seconds())
    hrs, rem = divmod(up, 3600)
    mins = rem // 60
    top = "\n".join(
        f"  {fa(i)}. ⏱ <b>{fa(c['latency'])}ms</b> {quality(c['latency'])}\n"
        f"      <code>{html.escape(str(c['host']))}:{fa(c['port'])}</code>"
        for i, c in enumerate(g[:5], 1)) or "  —"
    return (
        "✦ ━━━━━━━━━━━━━━━━ ✦\n"
        "        📊 <b>آمار زنده</b>\n"
        "✦ ━━━━━━━━━━━━━━━━ ✦\n\n"
        f"📥 جمع‌آوری‌شده: <b>{fa(S['fetched'])}</b>\n"
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>\n"
        f"🔌 زنده TCP: <b>{fa(S['tcp'])}</b>\n"
        f"🟢 سالم نهایی: <b>{fa(len(g))}</b>\n"
        f"📈 نرخ موفقیت: <b>{rate}</b>\n"
        f"🧪 هسته Xray: <b>{'فعال ✅' if S['xray'] else 'غیرفعال ❌'}</b>\n\n"
        f"🏆 <b>۵ کانفیگ برتر:</b>\n{top}\n\n"
        f"⏱ آپ‌تایم: <b>{fa(hrs)}س {fa(mins)}د</b> | 🔄 {ago(S['last'])}\n\n"
        "⚡️ CONFIG ELITE")

def help_text():
    return (
        "✦ ━━━━━━━━━━━━━━━━ ✦\n"
        "        ℹ️ <b>راهنما</b>\n"
        "✦ ━━━━━━━━━━━━━━━━ ✦\n\n"
        "├ 🔢 عدد بفرست (۱ تا ۲۵) ← کانفیگ می‌گیری\n"
        "├ 🧪 هر کانفیگ با اتصال واقعی تونل تست شده\n"
        "├ ⏱ پینگ = زمان لود واقعی از داخل تونل\n"
        "├ 📋 دکمه «کپی» ← کپی با یه لمس\n"
        "├ 🔌 VMess / VLESS / Trojan / Shadowsocks\n\n"
        "📶 <b>کیفیت پینگ:</b>\n"
        f"├ {FULL*5} عالی (زیر ۳۰۰ms)\n"
        f"├ {FULL*4}{EMPTY} خیلی خوب\n"
        f"├ {FULL*3}{EMPTY*2} خوب\n"
        f"└ {FULL*2}{EMPTY*3} قابل قبول\n\n"
        "⚡️ CONFIG ELITE")

async def deliver_message(message, n):
    g = list(S["good"])
    if not g:
        await message.reply_text("⏳ لیست هنوز آماده نشده — تست تونل ۳ تا ۵ دقیقه طول می‌کشه.")
        return
    n = max(1, min(n, 25, len(g)))
    await message.chat.send_action("typing")
    chunks = [g[i:i + 5] for i in range(0, n, 5)]
    total = len(chunks)
    for page, chunk in enumerate(chunks, 1):
        body = []
        rows = []
        start_i = (page - 1) * 5 + 1
        for j, c in enumerate(chunk):
            i = start_i + j
            body.append(
                f"{fa(i)}. {proto_of(c['uri'])} | ⏱ <b>{fa(c['latency'])}ms</b> {quality(c['latency'])}\n"
                f"<code>{html.escape(c['uri'])}</code>")
            if HAS_COPY and len(c["uri"]) <= 250:
                label = f"📋 کپی کانفیگ {fa(i)}"
                rows.append([InlineKeyboardButton(label, copy_text=CopyTextButton(text=c["uri"]))])
        text = ("✦ ━━━━━━━━━━━━━━ ✦\n"
                f"  🚀 <b>کانفیگ‌های تأییدشده</b> — {fa(page)}/{fa(total)}\n"
                "✦ ━━━━━━━━━━━━━━━━ ✦\n\n" + "\n\n".join(body))
        kb = InlineKeyboardMarkup(rows) if rows else None
        await message.reply_html(text, reply_markup=kb)
        await asyncio.sleep(0.4)
    await message.reply_html(
        f"✅ <b>{fa(n)} کانفیگ</b> — همه با اتصال واقعی تست شدن!\n"
        "💡 دکمه «کپی» رو بزن و تو برنامه‌ات Paste کن.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]]))

async def deliver_query(q, n):
    for msg in ("⏳ <b>در حال آماده‌سازی…</b>", "🔎 <b>انتخاب سریع‌ترین‌ها…</b>"):
        try:
            await q.edit_message_text(msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await asyncio.sleep(0.4)
    try:
        await q.message.delete()
    except Exception:
        pass
    await deliver_message(q.message, n)

async def cmd_start(update: Update, ctx):
    await update.message.reply_html(menu_text(), reply_markup=main_menu())

async def cmd_stats(update: Update, ctx):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(stats_text(), reply_markup=kb)

async def cmd_help(update: Update, ctx):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(help_text(), reply_markup=kb)

async def cmd_configs(update: Update, ctx):
    n = 10
    if ctx.args and ctx.args[0].isdigit():
        n = int(ctx.args[0])
    await deliver_message(update.message, n)

async def on_text(update: Update, ctx):
    m = re.search(r"\d+", update.message.text or "")
    if m:
        await deliver_message(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

async def retest_now():
    items = list(S["good"])
    if not items:
        return []
    if S["xray"]:
        with ThreadPoolExecutor(DEEP_WORKERS) as pool:
            results = pool.map(deep_test, items)
            return [r for r in results if r]
    uris = [c["uri"] for c in items]
    with ThreadPoolExecutor(WORKERS) as pool:
        results = pool.map(test_one, uris)
        return [r for r in results if r]

async def on_button(update: Update, ctx):
    q = update.callback_query
    data = q.data
    await q.answer()
    if data.startswith("get:"):
        await deliver_query(q, int(data.split(":")[1]))
    elif data == "menu":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_html(menu_text(), reply_markup=main_menu())
    elif data == "stats":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
        await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML, reply_markup=kb)
    elif data == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
        await q.edit_message_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=kb)
    elif data == "retest":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
        await q.edit_message_text("📡 <b>در حال تست مجدد…</b>", parse_mode=ParseMode.HTML)
        res = await asyncio.get_running_loop().run_in_executor(None, retest_now)
        res.sort(key=lambda c: c["latency"])
        with LOCK:
            if res:
                S["good"], S["last"] = res, datetime.now()
        best = f"{fa(res[0]['latency'])}ms" if res else "—"
        txt = (f"♻️ <b>تست مجدد شد</b>\n\n🟢 سالم: <b>{fa(len(res))}</b>\n"
               f"⚡️ بهترین: <b>{best}</b>")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def post_init(app: Application):
    await app.bot.set_my_commands([
                BotCommand("start", "🏠 منوی اصلی"),
        BotCommand("configs", "🚀 دریافت کانفیگ — /configs 10"),
        BotCommand("stats", "📊 آمار"),
        BotCommand("help", "ℹ️ راهنما"),
    ])

def main():
    threading.Thread(target=refresh_loop, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("configs", cmd_configs))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("CONFIG ELITE v2 started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
