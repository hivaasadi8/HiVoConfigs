# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════
#   ⚡️ CONFIG ELITE — ربات پریمیوم کانفیگ‌یاب
#   جمع‌آوری منابع عمومی + تست TCP Ping + تحویل زنده‌ها
# ══════════════════════════════════════════════

import asyncio
import base64
import html
import json
import logging
import os
import random
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

import requests
from telegram import (
    BotCommand,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ──────────────── تنظیمات ────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]

SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/all.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
]

TCP_TIMEOUT   = 4      # ثانیه — بیشتر از این یعنی مرده
MAX_TO_TEST   = 600    # حداکثر تست در هر دور
WORKERS       = 100    # تست همزمان
REFRESH_EVERY = 900    # هر چند ثانیه یک دور (۹۰۰ = ۱۵ دقیقه)
CHUNK         = 5      # تعداد کانفیگ در هر پیام
MAX_SEND      = 25     # سقف ارسال در هر درخواست

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite")

# وضعیت زنده ربات
S = {"good": [], "fetched": 0, "tested": 0, "last": None, "started": datetime.now()}
LOCK = threading.Lock()

# ──────────────── ابزارهای نمایش ────────────────
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def fa(x):
    return str(x).translate(FA)

FULL, EMPTY = "▰", "▱"

def quality(ms: int) -> str:
    """نوار کیفیت بر اساس پینگ"""
    if ms < 150:
        return FULL * 5
    if ms < 300:
        return FULL * 4 + EMPTY
    if ms < 600:
        return FULL * 3 + EMPTY * 2
    if ms < 1200:
        return FULL * 2 + EMPTY * 3
    return FULL + EMPTY * 4

def ago(dt) -> str:
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

PROTO = {
    "vmess": "🟣 VMess", "vless": "🔵 VLESS", "trojan": "🔴 Trojan",
    "ss": "🟡 Shadowsocks", "hysteria": "🟠 Hysteria", "hy2": "🟠 Hysteria2",
}

def proto_of(uri: str) -> str:
    low = uri[:10].lower()
    for k, v in PROTO.items():
        if low.startswith(k + "://"):
            return v
    return "⚙️ Other"

# ──────────────── استخراج و تست ────────────────
URI_RE = re.compile(r"(?:vmess|vless|trojan|ss|hysteria2?)://[^\s\"'<>\\]+", re.IGNORECASE)

def b64decode(s: str) -> str:
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s).decode("utf-8", "ignore")

def host_port(uri: str):
    """آدرس و پورت هر نوع کانفیگ را درمی‌آورد"""
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
        p = urlparse(uri)  # vless / trojan / hysteria
        return p.hostname, p.port
    except Exception:
        return None, None

def tcp_ping(host: str, port: int):
    """TCP پینگ — موفق = تأخیر به میلی‌ثانیه، ناموفق = None"""
    try:
        t0 = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
            return round((time.monotonic() - t0) * 1000)
    except Exception:
        return None

def test_one(uri: str):
    host, port = host_port(uri)
    if not host or not port or not (0 < port < 65536):
        return None
    ms = tcp_ping(host, port)
    return {"uri": uri, "host": host, "port": port, "latency": ms} if ms else None

def fetch_source(url: str):
    text = requests.get(url, timeout=30).text.strip()
    if "://" not in text:
        text = b64decode(text)  # بعضی منابع کل صفحه را base64 می‌دهند
    return URI_RE.findall(text)

def refresh_loop():
    """حلقه پس‌زمینه — هر ۱۵ دقیقه جمع‌آوری و تست"""
    while True:
        uris = []
        for url in SOURCES:
            try:
                uris += fetch_source(url)
                log.info(f"منبع OK: {url}")
            except Exception as e:
                log.warning(f"منبع خطا: {url} → {e}")
        uris = list(dict.fromkeys(uris))  # حذف تکراری
        random.shuffle(uris)
        S["fetched"] = len(uris)
        batch = uris[:MAX_TO_TEST]
        log.info(f"شروع تست {len(batch)} کانفیگ...")
        alive = []
        with ThreadPoolExecutor(WORKERS) as pool:
            for r in pool.map(test_one, batch):
                if r:
                    alive.append(r)
        alive.sort(key=lambda c: c["latency"])
        with LOCK:
            S["good"], S["tested"], S["last"] = alive, len(batch), datetime.now()
        log.info(f"✅ کانفیگ زنده: {len(alive)}")
        time.sleep(REFRESH_EVERY)

# ──────────────── متن‌ها و منوها ────────────────
def menu_text() -> str:
    g = S["good"]
    lines = [
        "✦ ━━━━━━━━━━━━━━━━ ✦",
        "    ⚡️ <b>CONFIG ELITE</b> ⚡️",
        "✦ ━━━━━━━━━━━━━━━━ ✦",
        "",
        "<i>کانفیگ‌های زنده با تست واقعی TCP Ping</i>",
        "",
        "📊 <b>وضعیت زنده شبکه</b>",
        f"├ 🟢 کانفیگ سالم: <b>{fa(len(g))}</b>",
        f"├ 🔬 تست‌شده در دور آخر: <b>{fa(S['tested'])}</b>",
    ]
    if g:
        best = min(c["latency"] for c in g)
        avg = sum(c["latency"] for c in g) // len(g)
        lines += [
            f"├ ⚡️ بهترین پینگ: <b>{fa(best)}ms</b> {quality(best)}",
            f"├ 🌡 میانگین پینگ: <b>{fa(avg)}ms</b>",
        ]
    lines.append(f"└ 🔄 آخرین بروزرسانی: <b>{ago(S['last'])}</b>")
    lines += ["", "<blockquote>یه عدد بفرست یا از دکمه‌ها استفاده کن 👇</blockquote>"]
    return "\n".join(lines)

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ ۵", callback_data="get:5"),
         InlineKeyboardButton("🚀 ۱۰", callback_data="get:10"),
         InlineKeyboardButton("💎 ۲۵", callback_data="get:25")],
        [InlineKeyboardButton("📊 آمار زنده", callback_data="stats")],
        [InlineKeyboardButton("♻️ تست مجدد", callback_data="retest"),
         InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
    ])

def stats_text() -> str:
    g = S["good"]
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    up = int((datetime.now() - S["started"]).total_seconds())
    hrs, rem = divmod(up, 3600)
    mins = rem // 60
    top = "\n".join(
        f"  {fa(i)}. ⏱ <b>{fa(c['latency'])}ms</b> {quality(c['latency'])}\n"
        f"      <code>{html.escape(str(c['host']))}:{fa(c['port'])}</code>"
        for i, c in enumerate(g[:5], 1)
    ) or "  —"
    return (
        "✦ ━━━━━━━━━━━━━━━━ ✦\n"
        "        📊 <b>آمار زنده</b>\n"
        "✦ ━━━━━━━━━━━━━━━━ ✦\n\n"
        f"📥 جمع‌آوری‌شده: <b>{fa(S['fetched'])}</b>\n"
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>\n"
        f"🟢 زنده: <b>{fa(len(g))}</b>\n"
        f"📈 نرخ موفقیت: <b>{rate}</b>\n\n"
        "🏆 <b>۵ کانفیگ برتر:</b>\n"
        f"{top}\n\n"
        f"⏱ آپ‌تایم ربات: <b>{fa(hrs)} ساعت و {fa(mins)} دقیقه</b>\n"
        f"🔄 آخرین بروزرسانی: <b>{ago(S['last'])}</b>\n\n"
        "⚡️ CONFIG ELITE"
    )

def help_text() -> str:
    return (
        "✦ ━━━━━━━━━━━━━━━━ ✦\n"
        "        ℹ️ <b>راهنما</b>\n"
        "✦ ━━━━━━━━━━━━━━━━ ✦\n\n"
        "├ 🔢 یه عدد بفرست (۱ تا ۲۵) ← همون تعداد کانفیگ سالم می‌گیری\n"
        "├ 📋 دکمه «کپی» ← کانفیگ‌ها با یه لمس کپی می‌شن\n"
        "├ 🔌 پروتکل‌ها: VMess / VLESS / Trojan / Shadowsocks / Hysteria\n\n"
        "📶 <b>راهنمای کیفیت پینگ:</b>\n"
        f"├ {FULL*5} فوق‌العاده (زیر ۱۵۰ms)\n"
        f"├ {FULL*4}{EMPTY} خیلی خوب\n"
        f"├ {FULL*3}{EMPTY*2} خوب\n"
        f"├ {FULL*2}{EMPTY*3} متوسط\n"
        f"└ {FULL}{EMPTY*4} ضعیف\n\n"
        "⚡️ CONFIG ELITE"
    )

# ──────────────── ارسال کانفیگ ────────────────
async def deliver_message(message, n: int):
    g = list(S["good"])
    if not g:
        await message.reply_text("⏳ لیست هنوز آماده نشده — ۲ دقیقه دیگه دوباره امتحان کن.")
        return
    n = max(1, min(n, MAX_SEND, len(g)))
    await message.chat.send_action("typing")
    chunks = [g[i:i + CHUNK] for i in range(0, n, CHUNK)]
    total = len(chunks)
    for page, chunk in enumerate(chunks, 1):
        body = []
        for i, c in enumerate(chunk, start=(page - 1) * CHUNK + 1):
            body.append(
                f"{fa(i)}. {proto_of(c['uri'])} | ⏱ <b>{fa(c['latency'])}ms</b> {quality(c['latency'])}\n"
                f"<code>{html.escape(c['uri'])}</code>"
            )
        text = (
            "✦ ━━━━━━━━━━━━━━ ✦\n"
            f"  🚀 <b>کانفیگ‌های منتخب</b> — {fa(page)}/{fa(total)}\n"
            "✦ ━━━━━━━━━━━━━━ ✦\n\n" + "\n\n".join(body)
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📋 کپی این بخش",
                copy_text=CopyTextButton(text="\n".join(c["uri"] for c in chunk)),
            )
        ]])
        await message.reply_html(text, reply_markup=kb)
        await asyncio.sleep(0.4)
    await message.reply_html(
        f"✅ <b>{fa(n)} کانفیگ</b> تحویل داده شد — کم‌پینگ‌ترین‌ها اول!\n"
        "💡 دکمه «کپی» رو بزن و مستقیم توی برنامه‌ات Paste کن.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
        ),
    )

async def deliver_query(q, n: int):
    """انیمیشن لودینگ + ارسال"""
    for msg in ("⏳ <b>در حال آماده‌سازی…</b>", "🔎 <b>انتخاب کم‌پینگ‌ترین‌ها…</b>"):
        try:
            await q.edit_message_text(msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await asyncio.sleep(0.5)
    try:
        await q.message.delete()
    except Exception:
        pass
    await deliver_message(q.message, n)

# ──────────────── هندلرها ────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(menu_text(), reply_markup=main_menu())

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        stats_text(),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
        ),
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        help_text(),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
        ),
    )

async def cmd_configs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    n = 10
    if ctx.args and ctx.args[0].isdigit():
        n = int(ctx.args[0])
    await deliver_message(update.message, n)

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = re.search(r"\d+", update.message.text or "")
    if m:
        await deliver_message(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        await q.edit_message_text(
            stats_text(), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
            ),
        )
    elif data == "help":
        await q.edit_message_text(
            help_text(), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
            ),
        )
    elif data == "retest":
        await q.edit_message_text("📡 <b>در حال تست مجدد لیست فعال…</b>", parse_mode=ParseMode.HTML)

        def _retest():
            uris = [c["uri"] for c in list(S["good"])]
            if not uris:
                return []
            with ThreadPoolExecutor(WORKERS) as pool:
                return [r for r in pool.map(test_one, uris) if r]

        res = await asyncio.get_running_loop().run_in_executor(None, _retest)
        res.sort(key=lambda c: c["latency"])
        with LOCK:
            if res:
                S["good"], S["last"] = res, datetime.now()
        best = f"{fa(res[0]['latency'])}ms" if res else "—"
        await q.edit_message_text(
            f"♻️ <b>تست مجدد انجام شد</b>\n\n"
            f"🟢 زنده: <b>{fa(len(res))}</b>\n"
            f"⚡️ بهترین پینگ: <b>{best}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu")]]
            ),
        )

# ──────────────── اجرا ────────────────
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 منوی اصلی"),
        BotCommand("configs", "🚀 دریافت کانفیگ — مثلاً /configs 10"),
        BotCommand("stats", "📊 آمار زنده"),
        BotCommand("help", "ℹ️ راهنما"),
    ])
    await app.bot.set_my_description("⚡️ کانفیگ‌های زنده، تست‌شده با TCP Ping و مرتب بر اساس سرعت")
    await app.bot.set_my_short_description("⚡️ کانفیگ سالم، تست‌شده، کم‌پینگ‌ترین اول")

def main():
    threading.Thread(target=refresh_loop, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("configs", cmd_configs))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("⚡️ CONFIG ELITE روشن شد")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
