# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs — Telegram Bot (v12)
#  Minimalist, Powerful, Production-Ready
# ══════════════════════════════════════════
import asyncio
import html
import io
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import qrcode
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    MenuButtonWebApp,
    ReactionTypeEmoji,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)
from rich.console import Console
from rich.logging import RichHandler

from tester import (
    S,
    LOCK,
    FORCE,
    refresh_loop,
    test_single,
    parse_config,
    export_uri,
    current_sources,
    source_report,
    URI_RE,
)
from store import STORE

# ══════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER = "8343701928"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
WELCOME_GIF = os.environ.get("WELCOME_GIF", "").strip()

APP_URL = ""
if REPO and "/" in REPO:
    _o, _n = REPO.split("/", 1)
    APP_URL = f"https://{_o.lower()}.github.io/{_n}/"

# ── Logger & Console ──
console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
)
log = logging.getLogger("hivo")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ══════════════════════════════════════════
#  Constants & State
# ══════════════════════════════════════════
STARTED = datetime.now()
ADMIN_STATE: Dict[int, str] = {}
PENDING: Dict[str, Any] = {}
PENDING_TTL = 1800
PENDING_MAX = 2000

FA_TRANS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(x: Any) -> str:
    return str(x).translate(FA_TRANS)


def h(t: Any) -> str:
    return html.escape(str(t))


def stars(score: int) -> str:
    n = max(1, min(5, round(score / 20)))
    return "★" * n + "☆" * (5 - n)


def fa_ago(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    if s < 86400:
        return f"{fa(s // 3600)} ساعت پیش"
    return f"{fa(s // 86400)} روز پیش"


def uptime() -> str:
    s = int((datetime.now() - STARTED).total_seconds())
    hh, rem = divmod(s, 3600)
    if hh == 0:
        return f"{fa(rem // 60)} دقیقه"
    return f"{fa(hh)} ساعت"


# ══════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════
def register(update: Update) -> None:
    u = update.effective_user
    if u:
        STORE.touch(u.id, u.first_name or "", u.username or "")


async def react(message, emoji: str = "⚡️") -> None:
    try:
        await message.set_reaction(reaction=[ReactionTypeEmoji(emoji)])
    except Exception:
        pass


# ══════════════════════════════════════════
#  Gate (Channel Lock)
# ══════════════════════════════════════════
async def gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
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
        log.warning(f"gate: {e}")
        return True

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◉  عضویت در کانال", url=f"https://t.me/{ch.lstrip('@')}")],
        [InlineKeyboardButton("✓  بررسی عضویت", callback_data="recheck")],
    ])
    await update.effective_message.reply_html(
        "<b>🔒 دسترسی محدود</b>\n\n"
        "برای استفاده از ربات، اول باید عضو کانال بشی.\n\n"
        f"<code>{h(ch)}</code>",
        reply_markup=kb,
    )
    return False


# ══════════════════════════════════════════
#  Card & Message Builders
# ══════════════════════════════════════════
def card_text(c: Dict[str, Any], title: str = "کانفیگ زنده") -> str:
    flag = c.get("flag", "🌐")
    country = c.get("country") or "نامشخص"
    city = f" · {c['city']}" if c.get("city") else ""
    sc = c.get("score", 0)
    speed = c.get("speed")
    stab = c.get("stability")

    parts = [f"<b>⚡ {title}</b>", "", f"{stars(sc)}  <b>{fa(sc)}</b> از ۱۰۰", ""]
    if speed:
        parts.append(f"⏱ {fa(c['latency'])}ms  ·  🚀 {fa(speed)} MB/s")
    else:
        parts.append(f"⏱ {fa(c['latency'])}ms")
    parts.append(f"🌍 {flag} {h(country)}{h(city)}  ·  {c.get('proto', '?').upper()}")
    if stab is not None:
        parts.append(f"◇ پایداری {fa(int(stab * 100))}٪")
    parts.append("")
    parts.append(f"<code>{h(c['host'])}:{fa(c['port'])}</code>")
    return "\n".join(parts)


def menu_text() -> str:
    wel = STORE.data["settings"].get("welcome", "").strip()
    g = S["good"]
    countries = len({c.get("country") for c in g if c.get("country")})

    parts = [
        "<b>⚡ HiVo Configs</b>",
        "",
        f"<b>{fa(len(g))}</b> کانفیگ زنده  ·  <b>{fa(S.get('fast', 0))}</b> سرعت‌سنجی",
        f"<b>{fa(countries)}</b> کشور  ·  {fa_ago(S['last'])}",
    ]
    if wel:
        parts += ["", f"<blockquote>{h(wel)}</blockquote>"]
    return "\n".join(parts)


def stats_text() -> str:
    g = S["good"]
    rate = round(len(g) * 100 / S["tested"]) if S["tested"] else 0
    avg = round(sum(c.get("score", 0) for c in g) / len(g)) if g else 0
    tops = sorted([x for x in g if x.get("speed")], key=lambda c: -c.get("score", 0))[:5]
    top_lines = []
    for i, c in enumerate(tops, 1):
        f_ = c.get("flag", "🌐")
        top_lines.append(f"{fa(i)}.  {f_}  {fa(c['latency'])}ms  ·  {fa(c.get('speed', 0))} MB/s")
    top_body = "\n".join(top_lines) or "—"

    return (
        "<b>📊 آمار</b>\n\n"
        f"دریافت‌شده     <b>{fa(S['fetched'])}</b>\n"
        f"تست TCP       <b>{fa(S['tested'])}</b>\n"
        f"زنده          <b>{fa(len(g))}</b>\n"
        f"سرعت‌سنجی     <b>{fa(S.get('fast', 0))}</b>\n"
        f"میانگین امتیاز  <b>{fa(avg)}</b>\n"
        f"نرخ تأیید      <b>{fa(rate)}٪</b>\n\n"
        "<b>برترین‌ها</b>\n"
        f"<blockquote>{top_body}</blockquote>\n\n"
        f"از {fa(len(current_sources()))} منبع  ·  آپ‌تایم {uptime()}"
    )


def help_text(is_admin: bool = False) -> str:
    t = (
        "<b>ℹ راهنما</b>\n\n"
        "<b>دستورات</b>\n"
        "/start       منوی اصلی\n"
        "/configs N   دریافت N کانفیگ\n"
        "/stats       آمار زنده\n"
        "/sub         لینک سابسکرایبشن\n"
        "/help        همین پیام\n\n"
        "<b>نکات</b>\n"
        "هر کانفیگی بفرستی، تست می‌کنم\n"
        "هرچی عدد بفرستی، همون تعداد می‌فرستم\n"
        "تو هر چتی بنویس <code>@ربات 10</code>\n\n"
        "<b>وضعیت‌ها</b>\n"
        "زنده       تونل واقعی پاس شد\n"
        "مشکوک     پورت بازه، تونل پاس نشد\n"
        "مرده       حتی TCP هم جواب نداد"
    )
    if is_admin:
        t += "\n\nادمین: <code>/admin</code>"
    return t


def admin_panel_text() -> str:
    st = STORE.data["settings"]
    lock = "🟢 روشن" if st.get("lock_on") else "خاموش"
    return (
        "<b>👑 پنل مدیریت</b>\n\n"
        f"کاربران       <b>{fa(len(STORE.users()))}</b>\n"
        f"ویژه          <b>{fa(len(STORE.premium()))}</b>\n"
        f"منابع         <b>{fa(len(current_sources()))}</b>\n"
        f"قفل کانال     <b>{lock}</b>"
    )


def users_text() -> str:
    users = STORE.users()
    today = datetime.now().date().isoformat()
    active = sum(1 for u in users.values() if (u.get("last") or "").startswith(today))
    tot = STORE.data.get("totals", {})
    top = sorted(users.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:8]
    lines = [f"{fa(i)}.  {h(u.get('name') or '—')}  ·  {fa(u.get('count', 0))}" for i, (_, u) in enumerate(top, 1)]
    body = "\n".join(lines) or "—"

    return (
        "<b>👥 کاربران</b>\n\n"
        f"کل           <b>{fa(len(users))}</b>\n"
        f"امروز        <b>{fa(active)}</b>\n"
        f"فایل          <b>{fa(tot.get('files', 0))}</b>\n"
        f"کانفیگ       <b>{fa(tot.get('configs', 0))}</b>\n\n"
        "<b>پرکاربردترها</b>\n"
        f"<blockquote>{body}</blockquote>"
    )


def sources_text() -> str:
    lines = []
    for r in source_report():
        name = r["url"].replace("https://raw.githubusercontent.com/", "")
        name = (name[:42] + "…") if len(name) > 42 else name
        if r["cooldown"]:
            tag = "⏸"
        elif r["fail"]:
            tag = "○"
        else:
            tag = "◉"
        lines.append(f"{tag}  <code>{h(name)}</code>  {fa(r['count'])}")
    body = "\n".join(lines) or "—"
    custom = STORE.sources()
    mode = f"اختصاصی ({fa(len(custom))})" if custom else "پیش‌فرض"

    return (
        "<b>📡 منابع</b>\n\n"
        f"حالت: <b>{mode}</b>\n\n"
        f"<blockquote expandable>{body}</blockquote>"
    )


def settings_text() -> str:
    st = STORE.data["settings"]
    wel = st.get("welcome", "").strip() or "—"
    lock = "🟢 روشن" if st.get("lock_on") else "خاموش"
    return (
        "<b>⚙ تنظیمات</b>\n\n"
        f"متن خوش‌آمد   <i>{h(wel[:50])}</i>\n"
        f"قفل کانال      <b>{lock}</b>"
    )


# ══════════════════════════════════════════
#  Keyboards
# ══════════════════════════════════════════
def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("⚡  کانفیگ‌ها", callback_data="cfg")]]
    mid = [
        InlineKeyboardButton("📊 آمار", callback_data="stat"),
        InlineKeyboardButton("🔗 ساب", callback_data="sub"),
    ]
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


def cfg_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 ۱۰ سریع‌ترین", callback_data="fast")],
        [
            InlineKeyboardButton("۵۰", callback_data="file:50"),
            InlineKeyboardButton("۱۰۰", callback_data="file:100"),
            InlineKeyboardButton("۵۰۰", callback_data="file:500"),
            InlineKeyboardButton("همه", callback_data="file:all"),
        ],
        [InlineKeyboardButton("🎲 شانسی", callback_data="rnd")],
        [InlineKeyboardButton("🔍 جستجو و فیلتر", callback_data="srch")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def srch_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 بر اساس کشور", callback_data="cty")],
        [InlineKeyboardButton("🔌 بر اساس پروتکل", callback_data="prt")],
        [InlineKeyboardButton("📝 تست کانفیگ دلخواه", callback_data="tester")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="cfg")],
    ])


def stat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("♻ بروزرسانی", callback_data="stat"),
         InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀ بازگشت", callback_data="menu")]])


def sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 نمایش QR", callback_data="qr")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def countries_kb() -> InlineKeyboardMarkup:
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
            InlineKeyboardButton(f"{flagmap[n]} {n}  ·  {fa(ct)}", callback_data=f"cty2:{n}")
            for n, ct in chunk
        ])
    rows.append([InlineKeyboardButton("◀ بازگشت", callback_data="srch")])
    return InlineKeyboardMarkup(rows)


def protocols_kb() -> InlineKeyboardMarkup:
    cnt = {}
    for c in S["good"]:
        cnt[c["proto"]] = cnt.get(c["proto"], 0) + 1
    names = {"vmess": "VMess", "vless": "VLESS", "trojan": "Trojan", "ss": "SS"}
    rows = []
    items = sorted(cnt.items(), key=lambda kv: -kv[1])
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        rows.append([
            InlineKeyboardButton(f"{names.get(p, p.upper())}  ·  {fa(ct)}", callback_data=f"prt2:{p}")
            for p, ct in chunk
        ])
    rows.append([InlineKeyboardButton("◀ بازگشت", callback_data="srch")])
    return InlineKeyboardMarkup(rows)


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 داده‌ها", callback_data="adm:data"),
         InlineKeyboardButton("🎯 محتوا", callback_data="adm:content")],
        [InlineKeyboardButton("⚙ تنظیمات", callback_data="adm:config"),
         InlineKeyboardButton("📣 ارتباط", callback_data="adm:comm")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


def adm_data_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 کاربران", callback_data="adm:users"),
         InlineKeyboardButton("📈 آمار", callback_data="stat")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_content_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 افزودن ویژه", callback_data="adm:add"),
         InlineKeyboardButton("📜 دیدن ویژه", callback_data="adm:list")],
        [InlineKeyboardButton("📡 منابع", callback_data="adm:sources")],
        [InlineKeyboardButton("🗑 پاک‌کردن ویژه", callback_data="adm:clear")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_config_kb() -> InlineKeyboardMarkup:
    st = STORE.data["settings"]
    lock_label = "خاموش کن" if st.get("lock_on") else "روشن کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan"),
         InlineKeyboardButton(lock_label, callback_data="adm:lock")],
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def adm_comm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📨 پیام همگانی", callback_data="adm:bc")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm")],
    ])


def sources_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن", callback_data="src:add"),
         InlineKeyboardButton("➖ حذف", callback_data="src:del")],
        [InlineKeyboardButton("♻ ریست", callback_data="src:reset")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="adm:content")],
    ])


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan")],
        [InlineKeyboardButton("◀ بازگشت", callback_data="menu")],
    ])


# ══════════════════════════════════════════
#  Inline Query
# ══════════════════════════════════════════
async def on_inline(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
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
            f"{stars(c.get('score', 0))}  ·  {fa(c['latency'])}ms\n\n"
            f"<code>{h(export_uri(c))}</code>"
        )
        results.append(InlineQueryResultArticle(
            id=str(i),
            title=f"{stars(c.get('score', 0))}  ·  {c['latency']}ms  ·  HiVo",
            description=c["uri"][:90],
            input_message_content=InputTextMessageContent(message_text=body, parse_mode=ParseMode.HTML),
        ))
    await q.answer(
        results, cache_time=10, is_personal=True,
        next_offset=str(offset + 12) if offset + 12 < len(g) else "",
    )


# ══════════════════════════════════════════
#  Pending (for voting)
# ══════════════════════════════════════════
def pending_put(c: Dict[str, Any]) -> None:
    now = time.time()
    PENDING[c["fp"]] = (now, c)
    stale = [k for k, (ts, _) in PENDING.items() if now - ts > PENDING_TTL]
    for k in stale:
        PENDING.pop(k, None)
    while len(PENDING) > PENDING_MAX:
        PENDING.pop(next(iter(PENDING)))


def pending_get(fp: str) -> Optional[Dict[str, Any]]:
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
def qr_bytes(url: str) -> io.BytesIO:
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def send_welcome(message, is_admin: bool) -> None:
    kb = main_menu(is_admin)
    if WELCOME_GIF:
        try:
            await message.reply_animation(
                animation=WELCOME_GIF, caption=menu_text(),
                parse_mode=ParseMode.HTML, reply_markup=kb,
            )
            return
        except Exception as e:
            log.warning(f"welcome gif: {e}")
    await message.reply_html(menu_text(), reply_markup=kb)


async def send_config_file(message, n: Optional[int] = None,
                           items: Optional[List[Dict]] = None,
                           title: Optional[str] = None) -> None:
    g = sorted(list(S["good"]), key=lambda c: -c.get("score", 0)) if items is None else list(items)
    if not g:
        await message.reply_html("<b>هنوز آماده نیست</b>\n\nچند دقیقه دیگه امتحان کن.")
        return

    its = g if (n is None or n >= len(g)) else g[:n]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    content = "\n".join(export_uri(c) for c in its) + "\n"
    buf = io.BytesIO(content.encode())
    best = its[0]
    header = title or "HiVo Configs"
    caption = (
        f"<b>⚡ {header}</b>\n\n"
        f"{fa(len(its))} کانفیگ  ·  بهترین {stars(best.get('score', 0))}\n"
        "<i>تست تونل واقعی پاس شده</i>"
    )
    msg = await message.reply_document(
        document=buf, filename=f"HiVo-{len(its)}.txt",
        caption=caption, parse_mode=ParseMode.HTML,
    )
    await react(msg)
    STORE.add_totals(files=1, configs=len(its))


def premium_uri(uri: str) -> str:
    name = "HiVo Premium 👑"
    low = uri.lower()
    if low.startswith("vmess://"):
        try:
            s = uri[8:].strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            return "vmess://" + base64.b64encode(json.dumps(d, ensure_ascii=False).encode()).decode()
        except Exception:
            return uri
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")


async def send_premium(message) -> None:
    prem = STORE.premium()
    if not prem:
        await message.reply_html("<b>👑 ویژه</b>\n\nهنوز کانفیگ ویژه‌ای اضافه نشده.")
        return

    uris = [premium_uri(u) for u in prem]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    buf = io.BytesIO(("\n".join(uris) + "\n").encode())
    caption = f"<b>👑 HiVo Premium</b>\n\n{fa(len(uris))} کانفیگ ویژه"
    msg = await message.reply_document(
        document=buf, filename="HiVo-Premium.txt",
        caption=caption, parse_mode=ParseMode.HTML,
    )
    await react(msg, "🔥")
    STORE.add_totals(files=1, configs=len(uris))


async def send_sub(message) -> None:
    url = S.get("sub")
    if not url:
        await message.reply_html("<b>🔗 سابسکرایبشن</b>\n\nهنوز آماده نیست. چند دقیقه دیگه امتحان کن.")
        return
    txt = (
        "<b>🔗 سابسکرایبشن</b>\n\n"
        f"<code>{h(url)}</code>\n\n"
        "<i>هر ۱۵ دقیقه بروز میشه.</i>"
    )
    await message.reply_html(txt, reply_markup=sub_kb())


async def send_qr(message) -> None:
    url = S.get("sub")
    if not url:
        await message.reply_html("هنوز آماده نیست.")
        return
    msg = await message.reply_photo(
        photo=qr_bytes(url),
        caption=f"<b>📱 QR سابسکرایبشن</b>\n\n<code>{h(url)}</code>",
        parse_mode=ParseMode.HTML,
    )
    await react(msg)


async def run_single_test(message, uri: str) -> None:
    wait = await message.reply_html(
        "<b>🧪 در حال تست</b>\n\nاتصال واقعی...\n<i>حداکثر ۲۰ ثانیه</i>"
    )
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, test_single, uri.strip())
    except Exception:
        log.exception("single test")
        await wait.edit_text("تست الان ممکن نشد. بعداً امتحان کن.")
        return

    if res is None:
        await wait.edit_text("<b>پاسخ نداد</b>\n\nاین کانفیگ به آخر خط رسیده.")
        return

    if not res.get("deep"):
        await wait.edit_text(
            "<b>پورت باز، تونل پاس نشد</b>\n\n"
            f"{fa(res['latency'])}ms\n"
            f"<code>{h(res['host'])}:{fa(res['port'])}</code>\n\n"
            "<i>سالم اعلام نمی‌شه.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    vh = res["fp"]
    pending_put(res)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 کپی کانفیگ", copy_text=export_uri(res))],
        [InlineKeyboardButton("👍 وصل شدم", callback_data=f"vote:1:{vh}"),
         InlineKeyboardButton("👎 نشد", callback_data=f"vote:0:{vh}")],
    ])
    await wait.edit_text(card_text(res), parse_mode=ParseMode.HTML, reply_markup=kb)
    await react(message)


async def do_broadcast(ctx: ContextTypes.DEFAULT_TYPE, text: str, status_msg) -> None:
    users = STORE.users()
    ok = fail = 0
    for uid in list(users.keys()):
        try:
            await ctx.bot.send_message(int(uid), f"📣 {text}")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.08)
    extra = f"  ·  {fa(fail)} ناموفق" if fail else ""
    await status_msg.edit_text(f"رفت به {fa(ok)} نفر{extra}")


# ══════════════════════════════════════════
#  Commands
# ══════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    if not await gate(update, ctx):
        return
    is_admin = STORE.is_admin(update.effective_user.id)
    await send_welcome(update.message, is_admin)


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(admin_panel_text(), reply_markup=admin_kb())


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(users_text())


async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not STORE.is_admin(update.effective_user.id):
        return
    parts = (update.message.text or "").split(" ", 1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await update.message.reply_html("استفاده:\n<code>/broadcast متن</code>")
        return
    status = await update.message.reply_text("در راه‌اند...")
    await do_broadcast(ctx, text, status)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ADMIN_STATE.pop(update.effective_user.id, None)
    await update.message.reply_html("لغو شد.")


async def cmd_configs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    if not await gate(update, ctx):
        return
    n = int(ctx.args[0]) if (ctx.args and ctx.args[0].isdigit()) else None
    await send_config_file(update.message, n)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    await update.message.reply_html(stats_text(), reply_markup=stat_kb())


async def cmd_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    await send_sub(update.message)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    await update.message.reply_html(
        help_text(STORE.is_admin(update.effective_user.id)), reply_markup=help_kb()
    )


# ══════════════════════════════════════════
#  Text handler
# ══════════════════════════════════════════
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()

    # Admin state machine
    if STORE.is_admin(uid) and uid in ADMIN_STATE:
        await handle_admin_state(update, ctx, uid, txt)
        return

    # URI
    if "://" in txt:
        if not await gate(update, ctx):
            return
        m = URI_RE.search(txt)
        if m:
            await run_single_test(update.message, m.group(0))
            return

    if not await gate(update, ctx):
        return

    # Number → file
    m = re.search(r"\d+", txt)
    if m:
        n = min(500, max(1, int(m.group())))
        await send_config_file(update.message, n)
    else:
        await cmd_start(update, ctx)


async def handle_admin_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             uid: int, txt: str) -> None:
    state = ADMIN_STATE[uid]
    if txt.lower() == "/cancel":
        ADMIN_STATE.pop(uid, None)
        await update.message.reply_html("لغو شد.")
        return

    if state == "src:add":
        if not txt.startswith("http"):
            await update.message.reply_html("لینک معتبر بفرست (با http).")
            return
        ADMIN_STATE.pop(uid, None)
        ok = STORE.add_source(txt.strip())
        await update.message.reply_html("منبع اضافه شد." if ok else "قبلاً اضافه شده.")

    elif state == "src:del":
        ADMIN_STATE.pop(uid, None)
        ok = STORE.remove_source(txt.strip())
        await update.message.reply_html("حذف شد." if ok else "پیدا نشد.")

    elif state == "premium":
        ADMIN_STATE.pop(uid, None)
        uris = URI_RE.findall(txt)
        if not uris:
            await update.message.reply_html("کانفیگی پیدا نکردم.")
            return
        added = STORE.add_premium(uris)
        await update.message.reply_html(
            f"<b>👑 ویژه</b>\n\n{fa(added)} کانفیگ اضافه شد\nکل: {fa(len(STORE.premium()))}"
        )

    elif state == "welcome":
        ADMIN_STATE.pop(uid, None)
        if txt.lower() == "/off":
            STORE.set_setting("welcome", "")
            await update.message.reply_html("برگشت به پیش‌فرض.")
        else:
            STORE.set_setting("welcome", txt)
            await update.message.reply_html("متن نشست.")

    elif state == "channel":
        ADMIN_STATE.pop(uid, None)
        if txt.lower() == "/off":
            STORE.set_setting("lock_on", False)
            await update.message.reply_html("قفل خاموش شد.")
        else:
            if not txt.startswith("@"):
                txt = "@" + txt
            STORE.set_setting("lock_channel", txt)
            STORE.set_setting("lock_on", True)
            await update.message.reply_html(
                f"قفل روشن شد: <code>{h(txt)}</code>\n⚠ ربات باید ادمین کانال باشه."
            )

    elif state == "broadcast":
        ADMIN_STATE.pop(uid, None)
        status = await update.message.reply_text("در راه‌اند...")
        await do_broadcast(ctx, txt, status)


# ══════════════════════════════════════════
#  Callback handler
# ══════════════════════════════════════════
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    register(update)
    q = update.callback_query
    data = q.data
    await q.answer()
    uid = q.from_user.id
    is_admin = STORE.is_admin(uid)

    # ── Recheck gate ──
    if data == "recheck":
        if await gate(update, ctx):
            try:
                await q.message.delete()
            except Exception:
                pass
            await send_welcome(q.message, is_admin)
        return

    # ── Votes ──
    if data.startswith("vote:"):
        val = 1 if data.split(":")[1] == "1" else -1
        vh = data.split(":")[2]
        host = (pending_get(vh) or {}).get("host") or STORE.get_vote_host(vh)
        if not host:
            await q.answer("منقضی شده", show_alert=False)
            return
        STORE.vote(uid, vh, host, val)
        return

    # ── Main navigation ──
    if data == "menu":
        try:
            await q.edit_message_text(menu_text(), parse_mode=ParseMode.HTML,
                                       reply_markup=main_menu(is_admin))
        except Exception:
            try:
                await q.message.delete()
            except Exception:
                pass
            await send_welcome(q.message, is_admin)
        return

    if data == "cfg":
        await q.edit_message_text(
            "<b>⚡ کانفیگ‌ها</b>\n\nچند تا و چطور می‌خوای؟",
            parse_mode=ParseMode.HTML, reply_markup=cfg_menu(),
        )
        return

    if data == "srch":
        await q.edit_message_text(
            "<b>🔍 جستجو و فیلتر</b>\n\nچطور می‌خوای فیلتر کنی؟",
            parse_mode=ParseMode.HTML, reply_markup=srch_menu(),
        )
        return

    if data == "stat":
        if not await gate(update, ctx):
            return
        try:
            await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML, reply_markup=stat_kb())
        except Exception:
            await q.message.reply_html(stats_text(), reply_markup=stat_kb())
        return

    if data == "help":
        await q.edit_message_text(help_text(is_admin), parse_mode=ParseMode.HTML, reply_markup=help_kb())
        return

    if data == "set":
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())
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

    # ── Files ──
    if data.startswith("file:"):
        if not await gate(update, ctx):
            return
        arg = data.split(":")[1]
        await send_config_file(q.message, None if arg == "all" else int(arg))
        return

    if data == "fast":
        if not await gate(update, ctx):
            return
        fasts = sorted([c for c in S["good"] if c.get("speed")], key=lambda c: -c["speed"])[:10]
        if fasts:
            await send_config_file(q.message, items=fasts, title="۱۰ سریع‌ترین")
        else:
            await q.message.reply_html("سرعت‌سنجی هنوز نتیجه نداده.")
        return

    if data == "rnd":
        if not await gate(update, ctx):
            return
        g = list(S["good"])
        if not g:
            await q.message.reply_html("هنوز کانفیگی نیست.")
            return
        await q.message.reply_dice(emoji="🎲")
        await asyncio.sleep(2.5)
        c = random.choice(g)
        pending_put(c)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 کپی", copy_text=export_uri(c))],
            [InlineKeyboardButton("👍 وصل شدم", callback_data=f"vote:1:{c['fp']}"),
             InlineKeyboardButton("👎 نشد", callback_data=f"vote:0:{c['fp']}")],
            [InlineKeyboardButton("🎲 یکی دیگه", callback_data="rnd")],
        ])
        await q.message.reply_html(card_text(c, "کانفیگ شانسی"),
                                    parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data == "tester":
        await q.edit_message_text(
            "<b>📝 تست کانفیگ</b>\n\n"
            "هر کانفیگی داری بفرست:\n"
            "vmess / vless / trojan / ss\n\n"
            "تونل واقعی + سرعت + امتیاز\n"
            "حداکثر ۲۰ ثانیه",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ بازگشت", callback_data="srch")],
            ]),
        )
        return

    if data == "retest":
        FORCE.set()
        await q.edit_message_text(
            "<b>♻ دور تازه شروع شد</b>\n\nنتایج زنده می‌آن.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Country / Protocol ──
    if data == "cty":
        await q.edit_message_text(
            "<b>🌍 فیلتر کشور</b>\n\nیکی رو انتخاب کن:",
            parse_mode=ParseMode.HTML, reply_markup=countries_kb(),
        )
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
            "<b>🔌 فیلتر پروتکل</b>\n\nیکی رو انتخاب کن:",
            parse_mode=ParseMode.HTML, reply_markup=protocols_kb(),
        )
        return

    if data.startswith("prt2:"):
        if not await gate(update, ctx):
            return
        p = data.split(":", 1)[1]
        items = sorted([c for c in S["good"] if c["proto"] == p],
                       key=lambda c: -c.get("score", 0))
        await send_config_file(q.message, items=items, title=p.upper())
        return

    # ── Admin ──
    if data == "adm" and is_admin:
        await q.edit_message_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        return

    if data == "adm:data" and is_admin:
        await q.edit_message_text("<b>📊 داده‌ها</b>\n\nکدوم؟",
                                   parse_mode=ParseMode.HTML, reply_markup=adm_data_kb())
        return

    if data == "adm:content" and is_admin:
        await q.edit_message_text("<b>🎯 محتوا</b>\n\nکدوم؟",
                                   parse_mode=ParseMode.HTML, reply_markup=adm_content_kb())
        return

    if data == "adm:config" and is_admin:
        await q.edit_message_text("<b>⚙ تنظیمات</b>\n\nکدوم؟",
                                   parse_mode=ParseMode.HTML, reply_markup=adm_config_kb())
        return

    if data == "adm:comm" and is_admin:
        await q.edit_message_text("<b>📣 ارتباطات</b>\n\nکدوم؟",
                                   parse_mode=ParseMode.HTML, reply_markup=adm_comm_kb())
        return

    if data == "adm:users" and is_admin:
        await q.edit_message_text(
            users_text(), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀ بازگشت", callback_data="adm:data")],
            ]),
        )
        return

    if data == "adm:sources" and is_admin:
        await q.edit_message_text(sources_text(), parse_mode=ParseMode.HTML, reply_markup=sources_kb())
        return

    if data == "src:add" and is_admin:
        ADMIN_STATE[uid] = "src:add"
        await q.message.reply_html("لینک raw که داخلش کانفیگ باشه بفرست.\n\n/cancel برای لغو")
        return

    if data == "src:del" and is_admin:
        ADMIN_STATE[uid] = "src:del"
        await q.message.reply_html("لینک دقیق رو بفرست.\n\n/cancel برای لغو")
        return

    if data == "src:reset" and is_admin:
        STORE.reset_sources()
        await q.message.reply_html("منابع به پیش‌فرض برگشت.")
        return

    if data == "adm:add" and is_admin:
        ADMIN_STATE[uid] = "premium"
        await q.message.reply_html(
            "<b>👑 افزودن ویژه</b>\n\n"
            "کانفیگ‌ها رو بفرست (هر خط یکی).\n\n/cancel برای لغو"
        )
        return

    if data == "adm:list" and is_admin:
        prem = STORE.premium()
        if not prem:
            await q.message.reply_html("خالیه.")
        else:
            buf = io.BytesIO(("\n".join(prem) + "\n").encode())
            await q.message.reply_document(
                buf, filename="premium-raw.txt",
                caption=f"📜 {fa(len(prem))} کانفیگ ویژه",
            )
        return

    if data == "adm:clear" and is_admin:
        n = STORE.clear_premium()
        await q.message.reply_html(f"{fa(n)} کانفیگ حذف شد.")
        await q.edit_message_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        return

    if data == "adm:bc" and is_admin:
        ADMIN_STATE[uid] = "broadcast"
        await q.message.reply_html("متن پیام رو بفرست.\n\n/cancel برای لغو")
        return

    if data == "adm:wel" and is_admin:
        ADMIN_STATE[uid] = "welcome"
        await q.message.reply_html("متن رو بفرست.\n\n/off پیش‌فرض — /cancel لغو")
        return

    if data == "adm:chan" and is_admin:
        ADMIN_STATE[uid] = "channel"
        await q.message.reply_html(
            "آیدی کانال با @ بفرست.\n"
            "⚠ ربات باید ادمین باشه.\n\n"
            "/off خاموشی — /cancel لغو"
        )
        return

    if data == "adm:lock" and is_admin:
        st = STORE.data["settings"]
        STORE.set_setting("lock_on", not st.get("lock_on"))
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=adm_config_kb())
        return


# ══════════════════════════════════════════
#  Error handler
# ══════════════════════════════════════════
async def on_error(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("handler error", exc_info=ctx.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("خطای موقت. دوباره امتحان کن.")
    except Exception:
        pass


# ══════════════════════════════════════════
#  Setup & Main
# ══════════════════════════════════════════
async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "منوی اصلی"),
        BotCommand("configs", "دریافت کانفیگ"),
        BotCommand("stats", "آمار زنده"),
        BotCommand("sub", "لینک سابسکرایبشن"),
        BotCommand("help", "راهنما"),
    ])
    await app.bot.set_my_description("HiVo Configs — کانفیگ‌های تست‌شده با تونل واقعی.")
    await app.bot.set_my_short_description("کانفیگ زنده، تست واقعی.")
    if APP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="HiVo", web_app=WebAppInfo(url=APP_URL))
            )
            log.info(f"menu button → {APP_URL}")
        except Exception as e:
            log.warning(f"menu: {e}")


async def post_shutdown(app: Application) -> None:
    ok = STORE.save()
    log.info(f"final save: {ok}")


def main() -> None:
    STORE.load()
    forced = os.environ.get("ADMIN_ID", "").strip()
    if forced:
        STORE.set_admin(forced)
    elif STORE.data.get("admin") is None:
        STORE.set_admin(OWNER)

    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=STORE.autosave_loop, daemon=True).start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("configs", cmd_configs))
    app.add_handler(CommandHandler("sub", cmd_sub))
    app.add_handler(CommandHandler("help", cmd_help))

    # Inline
    app.add_handler(InlineQueryHandler(on_inline))

    # Callbacks
    app.add_handler(CallbackQueryHandler(on_button))

    # Text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Errors
    app.add_error_handler(on_error)

    log.info("HiVo Configs v12 started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.fatal("fatal")
        raise
