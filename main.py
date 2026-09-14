# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v12 — Edition Luxe
#  Box-design · Clean · Modern
# ══════════════════════════════════════════
import asyncio, base64, html, io, json, logging, os, random, re, threading, time
from datetime import datetime
from urllib.parse import quote

import qrcode
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                       InlineQueryResultArticle, InputTextMessageContent,
                       MenuButtonWebApp, ReactionTypeEmoji, Update, WebAppInfo)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                           ContextTypes, InlineQueryHandler,
                           MessageHandler, filters)

from tester import (S, LOCK, FORCE, refresh_loop, test_single, parse_config,
                    export_uri, current_sources, source_report, URI_RE)
from store import STORE

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER = "8343701928"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
APP_URL = ""
if REPO and "/" in REPO:
    _o, _n = REPO.split("/", 1)
    APP_URL = f"https://{_o.lower()}.github.io/{_n}/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


# ══════════════════════════════════════════
#  Design Primitives
# ══════════════════════════════════════════

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x):
    return str(x).translate(FA)


def bar(pct, n=10, on="▰", off="▱"):
    pct = max(0.0, min(1.0, float(pct)))
    filled = int(round(pct * n))
    return on * filled + off * (n - filled)


def stars(score):
    n = max(1, min(5, round(score / 20)))
    return "★" * n + "☆" * (5 - n)


def box_top(title, w=24):
    title = " " + title + " "
    pad = max(0, w - len(title))
    left = pad // 2
    right = pad - left
    return "┏" + ("━" * left) + title + ("━" * right) + "┓"


def box_bot(w=24):
    return "┗" + ("━" * w) + "┛"


def status_dot(online=True, testing=False):
    if testing:
        return "◌"
    return "◉" if online else "○"


def fa_ago(dt):
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return fa(s) + " ثانیه"
    if s < 3600:
        return fa(s // 60) + " دقیقه"
    if s < 86400:
        return fa(s // 3600) + " ساعت"
    return fa(s // 86400) + " روز"


def uptime():
    s = int((datetime.now() - STARTED).total_seconds())
    hh, rem = divmod(s, 3600)
    return fa(hh) + " ساعت"


def speed_str(v):
    if not v:
        return "—"
    return fa(v) + " MB/s"


def stab_str(v):
    if v is None:
        return "—"
    return fa(int(v * 100)) + "٪"


SEP = "━━━━━━━━━━━━━━━━━━━━━"
THIN = "─────────────────────"

STARTED = datetime.now()
ADMIN_STATE = {}
PENDING = {}
PENDING_TTL = 1800
PENDING_MAX = 2000


# ══════════════════════════════════════════
#  Core Helpers
# ══════════════════════════════════════════

def h(t):
    return html.escape(str(t))


def register(update):
    u = update.effective_user
    if u:
        STORE.touch(u.id, u.first_name or "", u.username or "")


async def react(message, emoji="⚡️"):
    try:
        await message.set_reaction(reaction=[ReactionTypeEmoji(emoji)])
    except Exception:
        pass


async def gate(update, ctx):
    st = STORE.data["settings"]
    ch = st.get("lock_channel", "")
    if not st.get("lock_on") or not ch:
        return True
    uid = update.effective_user.id
    if STORE.is_admin(uid):
        return True
    try:
        m = await ctx.bot.get_chat_member(ch, uid)
        if m.status not in ("left", "kicked"):
            return True
    except Exception as e:
        log.warning(f"gate: {ch!r}: {e}")
        return True
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◉  عضویت در کانال", url=f"https://t.me/{ch.lstrip('@')}")],
        [InlineKeyboardButton("✓  بررسی عضویت", callback_data="recheck")],
    ])
    await update.effective_message.reply_html(
        box_top("🔒 دسترسی محدود") + "\n"
        + SEP + "\n\n"
        + "  برای استفاده از ربات،\n"
        + "  اول باید عضو کانال بشی.\n\n"
        + SEP + "\n"
        + "  کانال: <code>" + h(ch) + "</code>",
        reply_markup=kb)
    return False


def qr_bytes(url):
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ══════════════════════════════════════════
#  Card & Message Builders
# ══════════════════════════════════════════

def card_text(c, title="کانفیگ زنده"):
    flag = c.get("flag", "🌐")
    country = c.get("country") or "نامشخص"
    city = " · " + c["city"] if c.get("city") else ""
    sc = c.get("score", 0)
    sp = c.get("speed") or 0
    stab = c.get("stability")

    sc_bar = bar(sc / 100, 10)
    st_bar = bar(stab if stab is not None else 0, 10)

    lines = [
        box_top("⚡ " + title),
        "",
        "  امتیاز  <b>" + fa(sc) + "</b> از ۱۰۰",
        "  " + sc_bar + "  " + stars(sc),
        "",
        SEP,
        "  " + status_dot(True) + " <b>پینگ</b>        " + fa(c["latency"]) + " ms",
        "  " + status_dot(True) + " <b>سرعت</b>       " + speed_str(c.get("speed")),
        "  " + status_dot(True) + " <b>پروتکل</b>     " + c.get("proto", "?").upper(),
        "  " + status_dot(True) + " <b>موقعیت</b>     " + flag + " " + h(country) + h(city),
        "  " + status_dot(True) + " <b>پایداری</b>    " + stab_str(stab),
        SEP,
        "",
        "  <code>" + h(c["host"]) + ":" + fa(c["port"]) + "</code>",
        "",
        box_bot(),
    ]
    return "\n".join(lines)


def menu_text():
    wel = STORE.data["settings"].get("welcome", "").strip()
    g = S["good"]
    countries = len({c.get("country") for c in g if c.get("country")})
    alive = len(g)
    fast = S.get("fast", 0)
    online = alive > 0
    dot = status_dot(online)

    parts = [
        box_top("⚡ HiVo Configs"),
        "",
        "  " + dot + " <b>ربات فعال</b>",
        "  <b>" + fa(alive) + "</b> کانفیگ زنده  ·  <b>" + fa(fast) + "</b> سرعت‌سنجی",
        "  <b>" + fa(countries) + "</b> کشور  ·  " + fa_ago(S["last"]) + " پیش",
        "",
        SEP,
    ]
    if wel:
        parts += ["", "<i>" + h(wel) + "</i>", "", SEP]
    parts += ["", "  ⏱ آپ‌تایم: " + uptime(), "", box_bot()]
    return "\n".join(parts)


def stats_text():
    g = S["good"]
    rate = round(len(g) * 100 / S["tested"]) if S["tested"] else 0
    avg = round(sum(c.get("score", 0) for c in g) / len(g)) if g else 0
    tops = sorted([x for x in g if x.get("speed")],
                   key=lambda c: -c.get("score", 0))[:5]
    top_lines = []
    for i, c in enumerate(tops, 1):
        f_ = c.get("flag", "🌐")
        top_lines.append(
            "  " + fa(i) + ".  " + stars(c.get("score", 0)) + "\n"
            + "      " + f_ + "  " + fa(c["latency"]) + "ms  ·  " + speed_str(c.get("speed"))
        )
    top_body = "\n".join(top_lines) or "  سکوت؛ فعلاً برترین‌ها در راهن"

    lines = [
        box_top("📊 آمار زنده"),
        "",
        "  ◉ <b>دریافت‌شده</b>     " + fa(S["fetched"]),
        "  ◉ <b>تست TCP</b>       " + fa(S["tested"]),
        "  ◉ <b>زنده نهایی</b>    " + fa(len(g)),
        "  ◉ <b>سرعت‌سنجی</b>     " + fa(S.get("fast", 0)),
        "  ◉ <b>میانگین امتیاز</b>  " + fa(avg),
        "  ◉ <b>نرخ تأیید</b>     " + fa(rate) + "٪",
        "  " + bar(rate / 100, 12),
        "",
        SEP,
        "  <b>🏆 برترین‌ها</b>",
        "<blockquote>" + top_body + "</blockquote>",
        "",
        SEP,
        "  از <b>" + fa(len(current_sources())) + "</b> منبع",
        "  آپ‌تایم: " + uptime(),
        "",
        box_bot(),
    ]
    return "\n".join(lines)


def help_text(is_admin=False):
    lines = [
        box_top("ℹ راهنما"),
        "",
        "  <b>دستورات:</b>",
        "  <code>/start</code>       منوی اصلی",
        "  <code>/configs N</code>   دریافت N کانفیگ",
        "  <code>/stats</code>       آمار زنده",
        "  <code>/sub</code>         لینک سابسکرایبشن",
        "  <code>/help</code>        همین پیام",
        "",
        SEP,
        "  <b>نکات:</b>",
        "  ◉  هر کانفیگی بفرستی، تستش می‌کنم",
        "  ◉  هرچی عدد بفرستی، همون تعداد می‌فرستم",
        "  ◉  تو هر چتی بنویس <code>@ربات 10</code>",
        "",
        SEP,
        "  <b>وضعیت‌ها:</b>",
        "  ◉  <b>زنده</b>       تونل واقعی پاس شد",
        "  ◌  <b>مشکوک</b>     پورت بازه، تونل پاس نشد",
        "  ○  <b>مرده</b>       حتی TCP هم جواب نداد",
        "",
        box_bot(),
    ]
    t = "\n".join(lines)
    if is_admin:
        t += "\n\n" + SEP + "\n  👑 ادمین: <code>/admin</code>"
    return t


def admin_panel_text():
    st = STORE.data["settings"]
    lock = "🟢 روشن" if st.get("lock_on") else "○ خاموش"
    lines = [
        box_top("👑 پنل مدیریت"),
        "",
        "  ┌─ 📊 داده‌ها",
        "  │   کاربران  ·  آمار",
        "  ├─ 🎯 محتوا",
        "  │   ویژه  ·  منابع",
        "  ├─ ⚙ تنظیمات",
        "  │   کانال  ·  متن",
        "  └─ 📣 ارتباطات",
        "      پیام همگانی",
        "",
        SEP,
        "  ◉ کاربران      " + fa(len(STORE.users())),
        "  ◉ ویژه          " + fa(len(STORE.premium())),
        "  ◉ منابع         " + fa(len(current_sources())),
        "  ◉ قفل کانال     " + lock,
        "",
        box_bot(),
    ]
    return "\n".join(lines)


def users_text():
    users = STORE.users()
    today = datetime.now().date().isoformat()
    active = sum(1 for u in users.values() if (u.get("last") or "").startswith(today))
    tot = STORE.data.get("totals", {})
    top = sorted(users.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:8]
    lines_list = []
    for i, (_, u) in enumerate(top, 1):
        lines_list.append("  " + fa(i) + ". " + h(u.get("name") or "—") + "  ·  " + fa(u.get("count", 0)))
    body = "\n".join(lines_list) or "  —"
    lines = [
        box_top("👥 کاربران"),
        "",
        "  ◉ کل           " + fa(len(users)),
        "  ◉ امروز        " + fa(active),
        "  ◉ فایل‌ها       " + fa(tot.get("files", 0)),
        "  ◉ کانفیگ‌ها    " + fa(tot.get("configs", 0)),
        "",
        SEP,
        "  <b>🏆 پرکاربردترها</b>",
        "<blockquote>" + body + "</blockquote>",
        "",
        box_bot(),
    ]
    return "\n".join(lines)


def sources_text():
    lines_list = []
    for r in source_report():
        name = r["url"].replace("https://raw.githubusercontent.com/", "")
        if len(name) > 42:
            name = name[:42] + "…"
        if r["cooldown"]:
            tag = "◌ " + fa(r["cooldown"] // 60) + "د"
        elif r["fail"]:
            tag = "○ " + fa(r["fail"])
        else:
            tag = "◉"
        lines_list.append("  " + tag + "  <code>" + h(name) + "</code>  " + fa(r["count"]))
    body = "\n".join(lines_list) or "  —"
    custom = STORE.sources()
    mode = "اختصاصی (" + fa(len(custom)) + ")" if custom else "پیش‌فرض"
    lines = [
        box_top("📡 منابع"),
        "",
        "  حالت: <b>" + mode + "</b>",
        "",
        "<blockquote expandable>" + body + "</blockquote>",
        "",
        box_bot(),
    ]
    return "\n".join(lines)


def settings_text():
    st = STORE.data["settings"]
    wel = st.get("welcome", "").strip() or "پیش‌فرض"
    lock = "🟢 روشن" if st.get("lock_on") else "○ خاموش"
    lines = [
        box_top("⚙ تنظیمات"),
        "",
        "  ◉ متن خوش‌آمد",
        "     <i>" + h(wel[:50]) + "</i>",
        "",
        "  ◉ قفل کانال     " + lock,
        "",
        box_bot(),
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════
#  Keyboards
# ══════════════════════════════════════════

def main_menu(is_admin=False):
    rows = [
        [InlineKeyboardButton("⚡  کانفیگ‌ها", callback_data="cfg")],
    ]
    mid = [InlineKeyboardButton("📊 آمار", callback_data="stat"),
           InlineKeyboardButton("🔗 ساب", callback_data="sub")]
    if APP_URL:
        mid.append(InlineKeyboardButton("📱 اپ", web_app=WebAppInfo(url=APP_URL)))
    rows.append(mid)
    rows.append([
        InlineKeyboardButton("ℹ راهنما", callback_data="help"),
        InlineKeyboardButton("⚙ تنظیمات", callback_data="set"),
    ])
    if is_admin:
        rows.append([InlineKeyboardButton("👑 پنل مدیریت", callback_data="adm")])
    return InlineKeyboardMarkup(rows)


def cfg_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 ۱۰ سریع‌ترین", callback_data="fast")],
        [
            InlineKeyboardButton("📄 ۵۰", callback_data="file:50"),
            InlineKeyboardButton("📄 ۱۰۰", callback_data="file:100"),
            InlineKeyboardButton("📄 ۵۰۰", callback_data="file:500"),
        ],
        [
            InlineKeyboardButton("📄 همه", callback_data="file:all"),
            InlineKeyboardButton("🎲 شانسی", callback_data="rnd"),
        ],
        [InlineKeyboardButton("🔍 جستجو و فیلتر", callback_data="srch")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def srch_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 بر اساس کشور", callback_data="cty")],
        [InlineKeyboardButton("🔌 بر اساس پروتکل", callback_data="prt")],
        [InlineKeyboardButton("📝 تست کانفیگ دلخواه", callback_data="tester")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="cfg")],
    ])


def stat_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("♻ بروزرسانی", callback_data="stat"),
         InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def help_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def sub_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 نمایش QR", callback_data="qr")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def countries_kb():
    cnt, flagmap = {}, {}
    for c in S["good"]:
        if c.get("country"):
            cnt[c["country"]] = cnt.get(c["country"], 0) + 1
            flagmap.setdefault(c["country"], c.get("flag", "🌐"))
    top = sorted(cnt.items(), key=lambda kv: -kv[1])[:10]
    rows = []
    for i in range(0, len(top), 2):
        chunk = top[i:i + 2]
        rows.append([
            InlineKeyboardButton(flagmap[n] + " " + n + "  ·  " + fa(ct),
                                  callback_data="cty2:" + n)
            for n, ct in chunk
        ])
    rows.append([InlineKeyboardButton("◀ بازگشت", callback_data="srch")])
    return InlineKeyboardMarkup(rows)


def protocols_kb():
    cnt = {}
    for c in S["good"]:
        cnt[c["proto"]] = cnt.get(c["proto"], 0) + 1
    names = {"vmess": "VMess", "vless": "VLESS", "trojan": "Trojan", "ss": "SS"}
    rows = []
    items = sorted(cnt.items(), key=lambda kv: -kv[1])
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        rows.append([
            InlineKeyboardButton(names.get(p, p.upper()) + "  ·  " + fa(ct),
                                  callback_data="prt2:" + p)
            for p, ct in chunk
        ])
    rows.append([InlineKeyboardButton("◀ بازگشت", callback_data="srch")])
    return InlineKeyboardMarkup(rows)


def admin_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 داده‌ها", callback_data="adm:data"),
            InlineKeyboardButton("🎯 محتوا", callback_data="adm:content"),
        ],
        [
            InlineKeyboardButton("⚙ تنظیمات", callback_data="adm:config"),
            InlineKeyboardButton("📣 ارتباط", callback_data="adm:comm"),
        ],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def adm_data_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 کاربران", callback_data="adm:users"),
         InlineKeyboardButton("📈 آمار", callback_data="stat")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_content_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 افزودن ویژه", callback_data="adm:add"),
         InlineKeyboardButton("📜 دیدن ویژه", callback_data="adm:list")],
        [InlineKeyboardButton("📡 منابع", callback_data="adm:sources")],
        [InlineKeyboardButton("🗑 پاک‌کردن ویژه", callback_data="adm:clear")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_config_kb():
    st = STORE.data["settings"]
    lock_label = "○ خاموش کن" if st.get("lock_on") else "🟢 روشن کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan"),
         InlineKeyboardButton(lock_label, callback_data="adm:lock")],
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_comm_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 پیام همگانی", callback_data="adm:bc")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def sources_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن", callback_data="src:add"),
         InlineKeyboardButton("➖ حذف", callback_data="src:del")],
        [InlineKeyboardButton("♻ ریست", callback_data="src:reset")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm:content")],
    ])


def settings_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


# ══════════════════════════════════════════
#  Inline Query
# ══════════════════════════════════════════

async def on_inline(update, ctx):
    q = update.inline_query
    g = list(S["good"])
    if not g:
        await q.answer([], cache_time=5)
        return
    try:
        offset = int(q.offset or 0)
    except ValueError:
        offset = 0
    items = g[offset:offset + 12]
    results = []
    for i, c in enumerate(items, offset + 1):
        body = (
            "⚡ <b>HiVo Configs</b>\n"
            "★" + fa(c.get("score", 0)) + "  ·  " + fa(c["latency"]) + "ms\n\n"
            "<code>" + h(export_uri(c)) + "</code>"
        )
        results.append(InlineQueryResultArticle(
            id=str(i),
            title="★" + str(c.get("score", 0)) + "  ·  " + str(c["latency"]) + "ms  ·  HiVo",
            description=c["uri"][:90],
            input_message_content=InputTextMessageContent(
                message_text=body,
                parse_mode=ParseMode.HTML),
        ))
    await q.answer(results, cache_time=10, is_personal=True,
                    next_offset=str(offset + 12) if offset + 12 < len(g) else "")


# ══════════════════════════════════════════
#  Pending
# ══════════════════════════════════════════

def pending_put(c):
    now = time.time()
    PENDING[c["fp"]] = (now, c)
    stale = [k for k, (ts, _) in PENDING.items() if now - ts > PENDING_TTL]
    for k in stale:
        PENDING.pop(k, None)
    while len(PENDING) > PENDING_MAX:
        PENDING.pop(next(iter(PENDING)))


def pending_get(fp):
    item = PENDING.get(fp)
    if not item:
        return None
    ts, c = item
    if time.time() - ts > PENDING_TTL:
        PENDING.pop(fp, None)
        return None
    return c


# ══════════════════════════════════════════
#  Send Functions
# ══════════════════════════════════════════

async def send_config_file(message, n=None, items=None, title=None):
    g = sorted(list(S["good"]), key=lambda c: -c.get("score", 0)) if items is None else list(items)
    if not g:
        await message.reply_html(
            box_top("⏳ در راه است") + "\n\n"
            + "  " + SEP + "\n"
            + "  هنوز کانفیگی آماده نیست.\n"
            + "  چند دقیقه دیگه امتحان کن.\n\n"
            + box_bot())
        return
    its = g if (n is None or n >= len(g)) else g[:n]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    content = "\n".join(export_uri(c) for c in its) + "\n"
    buf = io.BytesIO(content.encode())
    best = its[0]
    header = "⚡ " + (title if title else "HiVo Configs")
    caption = (
        box_top(header) + "\n\n"
        + "  ◉ تعداد       <b>" + fa(len(its)) + "</b> کانفیگ\n"
        + "  ◉ بهترین       ★" + fa(best.get("score", 0)) + "  ·  " + fa(best["latency"]) + "ms\n\n"
        + SEP + "\n"
        + "  <i>تست تونل واقعی پاس شده</i>\n\n"
        + box_bot()
    )
    msg = await message.reply_document(
        document=buf, filename="HiVo-" + str(len(its)) + ".txt",
        caption=caption, parse_mode=ParseMode.HTML)
    await react(msg)
    STORE.add_totals(files=1, configs=len(its))


def premium_uri(uri):
    name = "HiVo Premium 👑"
    low = uri.lower()
    if low.startswith("vmess://"):
        try:
            s = uri[8:].strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            return "vmess://" + base64.b64encode(
                json.dumps(d, ensure_ascii=False).encode()).decode()
        except Exception:
            return uri
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")


async def send_premium(message):
    prem = STORE.premium()
    if not prem:
        await message.reply_html(
            box_top("👑 ویژه") + "\n\n"
            + "  " + SEP + "\n"
            + "  هنوز کانفیگ ویژه‌ای اضافه نشده.\n\n"
            + box_bot())
        return
    uris = [premium_uri(u) for u in prem]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    buf = io.BytesIO(("\n".join(uris) + "\n").encode())
    caption = (
        box_top("👑 HiVo Premium") + "\n\n"
        + "  ◉ تعداد  <b>" + fa(len(uris)) + "</b> کانفیگ ویژه\n\n"
        + box_bot())
    msg = await message.reply_document(
        document=buf, filename="HiVo-Premium.txt",
        caption=caption, parse_mode=ParseMode.HTML)
    await react(msg, "🔥")
    STORE.add_totals(files=1, configs=len(uris))


async def send_sub(message):
    url = S.get("sub")
    if not url:
        await message.reply_html(
            box_top("🔗 سابسکرایبشن") + "\n\n"
            + "  " + SEP + "\n"
            + "  هنوز آماده نیست.\n"
            + "  چند دقیقه دیگه امتحان کن.\n\n"
            + box_bot())
        return
    txt = (
        box_top("🔗 سابسکرایبشن") + "\n\n"
        + "  " + SEP + "\n"
        + "  <code>" + h(url) + "</code>\n"
        + "  " + SEP + "\n\n"
        + "  هر ۱۵ دقیقه بروز میشه.\n\n"
        + box_bot()
    )
    await message.reply_html(txt, reply_markup=sub_kb())


async def send_qr(message):
    url = S.get("sub")
    if not url:
        await message.reply_html("⏳ هنوز آماده نیست.")
        return
    msg = await message.reply_photo(
        photo=qr_bytes(url),
        caption=(box_top("📱 QR سابسکرایبشن") + "\n\n"
                 + "  <code>" + h(url) + "</code>\n\n"
                 + box_bot()),
        parse_mode=ParseMode.HTML)
    await react(msg)


async def run_single_test(message, uri):
    wait = await message.reply_html(
        box_top("🧪 در حال تست") + "\n\n"
        + "  " + status_dot(True, testing=True) + " اتصال واقعی...\n"
        + "  <i>حداکثر ۲۰ ثانیه</i>\n\n"
        + box_bot())
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, test_single, uri.strip())
    except Exception:
        log.exception("single test")
        await wait.edit_text(
            box_top("⚠ خطا") + "\n\n"
            + "  تست الان ممکن نشد.\n"
            + "  بعداً امتحان کن.\n\n"
            + box_bot())
        return
    if res is None:
        await wait.edit_text(
            box_top("○ پاسخ نداد") + "\n\n"
            + "  " + SEP + "\n"
            + "  این کانفیگ به آخر خط رسیده.\n\n"
            + box_bot())
        return
    if not res.get("deep"):
        await wait.edit_text(
            box_top("◌ مشکوک") + "\n\n"
            + "  ◉ <b>پینگ</b>       " + fa(res["latency"]) + " ms\n"
            + "  ◉ <b>میزبان</b>     <code>" + h(res["host"]) + ":" + fa(res["port"]) + "</code>\n\n"
            + "  " + SEP + "\n"
            + "  پورت بازه، ولی تونل واقعی\n"
            + "  پاس نشد.\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML)
        return
    vh = res["fp"]
    pending_put(res)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 کپی کانفیگ", copy_text=export_uri(res))],
        [InlineKeyboardButton("👍 وصل شدم", callback_data="vote:1:" + vh),
         InlineKeyboardButton("👎 نشد", callback_data="vote:0:" + vh)],
    ])
    await wait.edit_text(card_text(res), parse_mode=ParseMode.HTML, reply_markup=kb)
    await react(message)


async def do_broadcast(ctx, text, status_msg):
    users = STORE.users()
    ok = fail = 0
    for uid in list(users.keys()):
        try:
            await ctx.bot.send_message(int(uid), "📣 " + text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.08)
    extra = "  ·  ✗ " + fa(fail) if fail else ""
    await status_msg.edit_text("✓ رفت به " + fa(ok) + " نفر" + extra)


# ══════════════════════════════════════════
#  Commands
# ══════════════════════════════════════════

async def cmd_start(update, ctx):
    register(update)
    if not await gate(update, ctx):
        return
    await update.message.reply_html(
        menu_text(),
        reply_markup=main_menu(STORE.is_admin(update.effective_user.id)))


async def cmd_admin(update, ctx):
    register(update)
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(admin_panel_text(), reply_markup=admin_kb())


async def cmd_users(update, ctx):
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(users_text())


async def cmd_broadcast(update, ctx):
    if not STORE.is_admin(update.effective_user.id):
        return
    parts = (update.message.text or "").split(" ", 1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await update.message.reply_html("استفاده:\n<code>/broadcast متن</code>")
        return
    status = await update.message.reply_text("📣 در راه‌اند...")
    await do_broadcast(ctx, text, status)


async def cmd_cancel(update, ctx):
    ADMIN_STATE.pop(update.effective_user.id, None)
    await update.message.reply_html(
        box_top("✓ لغو شد") + "\n\n"
        + "  بازگشت به حالت عادی.\n\n"
        + box_bot())


async def cmd_configs(update, ctx):
    register(update)
    if not await gate(update, ctx):
        return
    n = None
    if ctx.args and ctx.args[0].isdigit():
        n = int(ctx.args[0])
    await send_config_file(update.message, n)


async def cmd_stats(update, ctx):
    register(update)
    await update.message.reply_html(stats_text(), reply_markup=stat_kb())


async def cmd_sub(update, ctx):
    register(update)
    await send_sub(update.message)


async def cmd_help(update, ctx):
    register(update)
    await update.message.reply_html(
        help_text(STORE.is_admin(update.effective_user.id)),
        reply_markup=help_kb())


# ══════════════════════════════════════════
#  Text handler
# ══════════════════════════════════════════

async def on_text(update, ctx):
    register(update)
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()

    if STORE.is_admin(uid) and uid in ADMIN_STATE:
        state = ADMIN_STATE[uid]
        if txt.lower() == "/cancel":
            ADMIN_STATE.pop(uid, None)
            await update.message.reply_html("✓ لغو شد.")
            return
        if state == "src:add":
            if not txt.startswith("http"):
                await update.message.reply_html("✗ لینک معتبر بفرست (با http)")
                return
            ADMIN_STATE.pop(uid, None)
            ok = STORE.add_source(txt.strip())
            await update.message.reply_html("✓ منبع اضافه شد." if ok else "⚠ قبلاً اضافه شده.")
        elif state == "src:del":
            ADMIN_STATE.pop(uid, None)
            ok = STORE.remove_source(txt.strip())
            await update.message.reply_html("🗑 حذف شد." if ok else "⚠ پیدا نشد.")
        elif state == "premium":
            ADMIN_STATE.pop(uid, None)
            uris = URI_RE.findall(txt)
            if not uris:
                await update.message.reply_html("✗ کانفیگی پیدا نکردم.")
                return
            added = STORE.add_premium(uris)
            await update.message.reply_html(
                box_top("👑 ویژه") + "\n\n"
                + "  ✓ <b>" + fa(added) + "</b> کانفیگ اضافه شد\n"
                + "  ◉ کل: <b>" + fa(len(STORE.premium())) + "</b>\n\n"
                + box_bot())
        elif state == "welcome":
            ADMIN_STATE.pop(uid, None)
            if txt.lower() == "/off":
                STORE.set_setting("welcome", "")
                await update.message.reply_html("✓ برگشت به پیش‌فرض.")
            else:
                STORE.set_setting("welcome", txt)
                await update.message.reply_html("✓ متن تازه نشست.")
        elif state == "channel":
            ADMIN_STATE.pop(uid, None)
            if txt.lower() == "/off":
                STORE.set_setting("lock_on", False)
                await update.message.reply_html("📢 قفل خاموش شد.")
            else:
                if not txt.startswith("@"):
                    txt = "@" + txt
                STORE.set_setting("lock_channel", txt)
                STORE.set_setting("lock_on", True)
                await update.message.reply_html(
                    "📢 قفل روشن شد: <code>" + h(txt) + "</code>\n"
                    "⚠ ربات باید ادمین کانال باشه.")
        elif state == "broadcast":
            ADMIN_STATE.pop(uid, None)
            status = await update.message.reply_text("📣 در راه‌اند...")
            await do_broadcast(ctx, txt, status)
        return

    if "://" in txt:
        if not await gate(update, ctx):
            return
        m = URI_RE.search(txt)
        if m:
            await run_single_test(update.message, m.group(0))
            return

    if not await gate(update, ctx):
        return
    m = re.search(r"\d+", txt)
    if m:
        n = min(500, max(1, int(m.group())))
        await send_config_file(update.message, n)
    else:
        await cmd_start(update, ctx)


# ══════════════════════════════════════════
#  Callback handler
# ══════════════════════════════════════════

async def on_button(update, ctx):
    register(update)
    q = update.callback_query
    data = q.data
    await q.answer()
    uid = q.from_user.id
    is_admin = STORE.is_admin(uid)

    if data == "recheck":
        if await gate(update, ctx):
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.message.reply_html(menu_text(),
                                        reply_markup=main_menu(is_admin))
        return

    if data.startswith("vote:"):
        val = 1 if data.split(":")[1] == "1" else -1
        vh = data.split(":")[2]
        host = (pending_get(vh) or {}).get("host") or STORE.get_vote_host(vh)
        if not host:
            await q.answer("منقضی شده", show_alert=False)
            return
        STORE.vote(uid, vh, host, val)
        return

    if data == "menu":
        try:
            await q.edit_message_text(menu_text(), parse_mode=ParseMode.HTML,
                                       reply_markup=main_menu(is_admin))
        except Exception:
            try:
                await q.message.delete()
            except Exception:
                pass
            await q.message.reply_html(menu_text(),
                                        reply_markup=main_menu(is_admin))
        return

    if data == "cfg":
        await q.edit_message_text(
            box_top("⚡ کانفیگ‌ها") + "\n\n"
            + "  چند تا و چطور می‌خوای؟\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=cfg_menu())
        return

    if data == "srch":
        await q.edit_message_text(
            box_top("🔍 جستجو و فیلتر") + "\n\n"
            + "  چطور می‌خوای فیلتر کنی؟\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=srch_menu())
        return

    if data == "stat":
        if not await gate(update, ctx):
            return
        try:
            await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML,
                                       reply_markup=stat_kb())
        except Exception:
            await q.message.reply_html(stats_text(), reply_markup=stat_kb())
        return

    if data == "help":
        await q.edit_message_text(help_text(is_admin),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=help_kb())
        return

    if data == "set":
        await q.edit_message_text(settings_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=settings_kb())
        return

    if data == "sub":
        await send_sub(q.message)
        return

    if data == "qr":
        await send_qr(q.message)
        return

    if data == "prem":
        if not await gate(update, ctx):
            return
        await send_premium(q.message)
        return

    if data.startswith("file:"):
        if not await gate(update, ctx):
            return
        arg = data.split(":")[1]
        await send_config_file(q.message, None if arg == "all" else int(arg))
        return

    if data == "fast":
        if not await gate(update, ctx):
            return
        fasts = sorted([c for c in S["good"] if c.get("speed")],
                       key=lambda c: -c["speed"])[:10]
        if fasts:
            await send_config_file(q.message, items=fasts, title="۱۰ سریع‌ترین")
        else:
            await q.message.reply_html(
                box_top("⏳ سرعت‌سنجی") + "\n\n"
                + "  هنوز نتیجه نداده.\n"
                + "  ۲ دقیقه دیگه امتحان کن.\n\n"
                + box_bot())
        return

    if data == "rnd":
        if not await gate(update, ctx):
            return
        g = list(S["good"])
        if not g:
            await q.message.reply_html(
                box_top("⏳ خالی") + "\n\n"
                + "  هنوز کانفیگی نیست.\n\n"
                + box_bot())
            return
        await q.message.reply_dice(emoji="🎲")
        await asyncio.sleep(2.5)
        c = random.choice(g)
        pending_put(c)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 کپی", copy_text=export_uri(c))],
            [InlineKeyboardButton("👍 وصل شدم", callback_data="vote:1:" + c["fp"]),
             InlineKeyboardButton("👎 نشد", callback_data="vote:0:" + c["fp"])],
            [InlineKeyboardButton("🎲 یکی دیگه", callback_data="rnd")],
        ])
        await q.message.reply_html(card_text(c, "کانفیگ شانسی"),
                                    parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "tester":
        await q.edit_message_text(
            box_top("📝 تست کانفیگ") + "\n\n"
            + "  هر کانفیگی داری بفرست:\n"
            + "  vmess / vless / trojan / ss\n\n"
            + "  تونل واقعی + سرعت + امتیاز\n"
            + "  حداکثر ۲۰ ثانیه\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ بازگشت", callback_data="srch")],
            ]))
        return

    if data == "retest":
        FORCE.set()
        await q.edit_message_text(
            box_top("♻ دور تازه") + "\n\n"
            + "  " + status_dot(True, testing=True) + " شروع شد.\n"
            + "  نتایج زنده می‌آن.\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML)
        return

    if data == "cty":
        await q.edit_message_text(
            box_top("🌍 فیلتر کشور") + "\n\n"
            + "  یکی رو انتخاب کن:\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=countries_kb())
        return

    if data.startswith("cty2:"):
        if not await gate(update, ctx):
            return
        name = data.split(":", 1)[1]
        items = sorted([c for c in S["good"] if c.get("country") == name],
                       key=lambda c: -c.get("score", 0))
        await send_config_file(q.message, items=items, title=name)
        return

    if data == "prt":
        await q.edit_message_text(
            box_top("🔌 فیلتر پروتکل") + "\n\n"
            + "  یکی رو انتخاب کن:\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=protocols_kb())
        return

    if data.startswith("prt2:"):
        if not await gate(update, ctx):
            return
        p = data.split(":", 1)[1]
        items = sorted([c for c in S["good"] if c["proto"] == p],
                       key=lambda c: -c.get("score", 0))
        await send_config_file(q.message, items=items, title=p.upper())
        return

    if data == "adm" and is_admin:
        await q.edit_message_text(admin_panel_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=admin_kb())
        return

    if data == "adm:data" and is_admin:
        await q.edit_message_text(
            box_top("📊 داده‌ها") + "\n\n"
            + "  ┌─ 👥 کاربران\n"
            + "  └─ 📈 آمار\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=adm_data_kb())
        return

    if data == "adm:content" and is_admin:
        await q.edit_message_text(
            box_top("🎯 محتوا") + "\n\n"
            + "  ┌─ 👑 کانفیگ ویژه\n"
            + "  ├─ 📡 منابع\n"
            + "  └─ 🗑 پاک‌سازی\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=adm_content_kb())
        return

    if data == "adm:config" and is_admin:
        await q.edit_message_text(
            box_top("⚙ تنظیمات") + "\n\n"
            + "  ┌─ 📢 کانال قفل\n"
            + "  └─ ✏️ متن خوش‌آمد\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=adm_config_kb())
        return

    if data == "adm:comm" and is_admin:
        await q.edit_message_text(
            box_top("📣 ارتباطات") + "\n\n"
            + "  └─ 📨 پیام همگانی\n\n"
            + box_bot(),
            parse_mode=ParseMode.HTML, reply_markup=adm_comm_kb())
        return

    if data == "adm:users" and is_admin:
        await q.edit_message_text(users_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup([
                                       [InlineKeyboardButton("◀ بازگشت",
                                                              callback_data="adm:data")]]))
        return

    if data == "adm:sources" and is_admin:
        await q.edit_message_text(sources_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=sources_kb())
        return

    if data == "src:add" and is_admin:
        ADMIN_STATE[uid] = "src:add"
        await q.message.reply_html(
            box_top("➕ افزودن منبع") + "\n\n"
            + "  لینک raw که داخلش\n"
            + "  کانفیگ باشه بفرست.\n\n"
            + "  <code>/cancel</code> برای لغو\n\n"
            + box_bot())
        return

    if data == "src:del" and is_admin:
        ADMIN_STATE[uid] = "src:del"
        await q.message.reply_html(
            box_top("➖ حذف منبع") + "\n\n"
            + "  لینک دقیق رو بفرست.\n\n"
            + "  <code>/cancel</code> برای لغو\n\n"
            + box_bot())
        return

    if data == "src:reset" and is_admin:
        STORE.reset_sources()
        await q.message.reply_html(
            box_top("♻ ریست") + "\n\n"
            + "  منابع به پیش‌فرض برگشت.\n\n"
            + box_bot())
        return

    if data == "adm:add" and is_admin:
        ADMIN_STATE[uid] = "premium"
        await q.message.reply_html(
            box_top("👑 افزودن ویژه") + "\n\n"
            + "  کانفیگ‌ها رو بفرست\n"
            + "  (هر خط یکی).\n\n"
            + "  <code>/cancel</code> برای لغو\n\n"
            + box_bot())
        return

    if data == "adm:list" and is_admin:
        prem = STORE.premium()
        if not prem:
            await q.message.reply_html(
                box_top("📜 ویژه") + "\n\n"
                + "  خالیه.\n\n"
                + box_bot())
        else:
            buf = io.BytesIO(("\n".join(prem) + "\n").encode())
            await q.message.reply_document(
                buf, filename="premium-raw.txt",
                caption="📜 " + fa(len(prem)) + " کانفیگ ویژه")
        return

    if data == "adm:clear" and is_admin:
        n = STORE.clear_premium()
        await q.message.reply_html(
            box_top("🗑 پاک شد") + "\n\n"
            + "  " + fa(n) + " کانفیگ حذف شد.\n\n"
            + box_bot())
        await q.edit_message_text(admin_panel_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=admin_kb())
        return

    if data == "adm:bc" and is_admin:
        ADMIN_STATE[uid] = "broadcast"
        await q.message.reply_html(
            box_top("📨 پیام همگانی") + "\n\n"
            + "  متن پیام رو بفرست.\n\n"
            + "  <code>/cancel</code> برای لغو\n\n"
            + box_bot())
        return

    if data == "adm:wel" and is_admin:
        ADMIN_STATE[uid] = "welcome"
        await q.message.reply_html(
            box_top("✏️ متن خوش‌آمد") + "\n\n"
            + "  متن رو بفرست.\n\n"
            + "  <code>/off</code> پیش‌فرض\n"
            + "  <code>/cancel</code> لغو\n\n"
            + box_bot())
        return

    if data == "adm:chan" and is_admin:
        ADMIN_STATE[uid] = "channel"
        await q.message.reply_html(
            box_top("📢 کانال قفل") + "\n\n"
            + "  آیدی کانال با @ بفرست.\n"
            + "  ⚠ ربات باید ادمین باشه.\n\n"
            + "  <code>/off</code> خاموشی\n"
            + "  <code>/cancel</code> لغو\n\n"
            + box_bot())
        return

    if data == "adm:lock" and is_admin:
        st = STORE.data["settings"]
        STORE.set_setting("lock_on", not st.get("lock_on"))
        await q.edit_message_text(settings_text(),
                                   parse_mode=ParseMode.HTML,
                                   reply_markup=adm_config_kb())
        return


async def on_error(update, ctx):
    log.error("handler", exc_info=ctx.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠ خطای موقت. دوباره امتحان کن.")
    except Exception:
        pass


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "منوی اصلی"),
        BotCommand("configs", "دریافت کانفیگ"),
        BotCommand("stats", "آمار زنده"),
        BotCommand("sub", "لینک سابسکرایبشن"),
        BotCommand("help", "راهنما"),
    ])
    await app.bot.set_my_description(
        "HiVo Configs — کانفیگ‌های تست‌شده با تونل واقعی.")
    await app.bot.set_my_short_description("کانفیگ زنده، تست واقعی.")
    if APP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="HiVo", web_app=WebAppInfo(url=APP_URL)))
            log.info("menu button -> " + APP_URL)
        except Exception as e:
            log.warning("menu: " + str(e))


async def post_shutdown(app):
    ok = STORE.save()
    log.info("final save: " + str(ok))


def main():
    STORE.load()
    forced = os.environ.get("ADMIN_ID", "").strip()
    if forced:
        STORE.set_admin(forced)
    elif STORE.data.get("admin") is None:
        STORE.set_admin(OWNER)

    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=STORE.autosave_loop, daemon=True).start()

    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())

    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("configs", cmd_configs))
    app.add_handler(CommandHandler("sub", cmd_sub))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    log.info("HiVo Configs v12 started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("fatal")
        raise
