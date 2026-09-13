# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v10 — TITAN
# ══════════════════════════════════════════

import asyncio, base64, html, io, json, logging, os, random, re, threading
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

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(x):
    return str(x).translate(FA)

STARTED = datetime.now()
ADMIN_STATE = {}
PENDING = {}

BANNER = "✦ ━━━━━━━━━━━━━━━━━ ✦"
TAGLINE = "「 آزادی، یک اتصال فاصله دارد 」"
FILE_TAG = "「 این‌ها زنده‌اند؛ تو هم باش 」"
PREMIUM_TAG = "「 چیزهای خاص، برای تو 」"
STATS_TAG = "「 اعداد دروغ نمی‌گویند 」"
LOCK_TAG = "「 اول عضو شو، بعد برگرد 」"

def quality(ms):
    if ms < 300:
        return "🟩🟩🟩🟩🟩"
    if ms < 700:
        return "🟩🟩🟩🟩🟨"
    if ms < 1500:
        return "🟩🟩🟨🟨⬜️"
    return "🟨🟨⬜️⬜️⬜️"

def speed_bar(v):
    if not v:
        return "⬜️⬜️⬜️⬜️⬜️"
    if v >= 2:
        return "🟩🟩🟩🟩🟩"
    if v >= 1:
        return "🟩🟩🟩🟩🟨"
    if v >= 0.4:
        return "🟩🟩🟨🟨⬜️"
    return "🟨⬜️⬜️⬜️⬜️"

def fa_ago(dt):
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

def uptime():
    s = int((datetime.now() - STARTED).total_seconds())
    h, rem = divmod(s, 3600)
    return f"{fa(h)}س {fa(rem // 60)}د"

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
    except Exception:
        return True
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{ch.lstrip('@')}")],
        [InlineKeyboardButton("✅ بررسی", callback_data="recheck")],
    ])
    await update.effective_message.reply_html(
        f"⚡️ <b>HiVo Configs</b>\n\n{LOCK_TAG}", reply_markup=kb)
    return False

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

def qr_bytes(url):
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def card_text(c, title="🧪 نتیجه تست"):
    loc = f"{c.get('flag', '🌐')} {c.get('country') or 'نامشخص'}"
    if c.get("city"):
        loc += f" | {c['city']}"
    if c.get("speed"):
        sp = f"🚀 <b>{fa(c['speed'])}MB/s</b> {speed_bar(c['speed'])}"
    else:
        sp = "🚀 <i>سرعت‌سنجی ناموفق</i>"
    return (f"{BANNER}\n  {title}\n{BANNER}\n\n"
            f"🟢 <b>زنده</b> — تونل واقعی پاس شد\n"
            f"⭐️ امتیاز: <b>{fa(c.get('score', 0))}/۱۰۰</b>\n"
            f"🌍 {html.escape(loc)}\n"
            f"⏱ <b>{fa(c['latency'])}ms</b> {quality(c['latency'])}\n"
            f"{sp}\n"
            f"🔌 <tg-spoiler>{html.escape(str(c['host']))}:{fa(c['port'])}</tg-spoiler>")

def menu_text():
    wel = STORE.data["settings"].get("welcome", "").strip()
    g = S["good"]
    countries = len({c.get("country") for c in g if c.get("country")})
    up, down = STORE.vote_totals()
    return "\n".join([
        BANNER,
        "      ⚡️ <b>HiVo Configs</b>",
        TAGLINE,
        BANNER,
        "",
        wel or "「 کیفیت را حس کن، نه فقط ببین 」",
        "",
        f"🟢 زنده (تست تونل): <b>{fa(len(g))}</b>",
        f"🚀 سرعت‌سنجی‌شده: <b>{fa(S.get('fast', 0))}</b>",
        f"👑 اختصاصی: <b>{fa(len(STORE.premium()))}</b> · 🌍 کشور: <b>{fa(countries)}</b>",
        f"🗳 👍 {fa(up)} · 👎 {fa(down)}",
        f"🔄 {fa_ago(S['last'])} · ⏱ آپ‌تایم {uptime()}",
        "",
        "「 یک عدد بفرست، بقیه‌اش با ما 」",
    ])

def main_menu(is_admin=False):
    rows = []
    if APP_URL:
        rows.append([InlineKeyboardButton("📱 اپ HiVo", web_app=WebAppInfo(url=APP_URL))])
    rows.append([InlineKeyboardButton("⚡️ سریع‌ترین‌ها", callback_data="fast"),
                 InlineKeyboardButton("🎲 شانسی", callback_data="rnd"),
                 InlineKeyboardButton("🧪 تستر", callback_data="tester")])
    rows.append([InlineKeyboardButton("🌍 کشورها", callback_data="cty"),
                 InlineKeyboardButton("🔌 پروتکل‌ها", callback_data="prt")])
    rows.append([InlineKeyboardButton("👑 اختصاصی", callback_data="premium")])
    rows.append([InlineKeyboardButton("📄 ۵۰", callback_data="file:50"),
                 InlineKeyboardButton("📄 ۱۰۰", callback_data="file:100"),
                 InlineKeyboardButton("📄 ۲۰۰", callback_data="file:200")])
    rows.append([InlineKeyboardButton("📄 ۵۰۰", callback_data="file:500"),
                 InlineKeyboardButton("📄 همه", callback_data="file:all")])
    rows.append([InlineKeyboardButton("🔗 سابسکرایبشن", callback_data="sub"),
                 InlineKeyboardButton("📱 QR", callback_data="qr")])
    rows.append([InlineKeyboardButton("📊 آمار", callback_data="stats"),
                 InlineKeyboardButton("ℹ️ راهنما", callback_data="help"),
                 InlineKeyboardButton("♻️ تست مجدد", callback_data="retest")])
    if is_admin:
        rows.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="adm")])
    return InlineKeyboardMarkup(rows)

def stats_text():
    g = S["good"]
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    sub = "✅ فعال" if S.get("sub") else "—"
    up, down = STORE.vote_totals()
    avg = fa(round(sum(c.get("score", 0) for c in g) / len(g))) if g else "—"
    top = "\n".join(
        f"  {fa(i)}. ⭐️{fa(c.get('score', 0))} · 🚀 {fa(c['speed'])}MB/s"
        f" · ⏱ {fa(c['latency'])}ms"
        f" · <tg-spoiler>{html.escape(str(c['host']))}</tg-spoiler>"
        for i, c in enumerate(sorted([x for x in g if x.get("speed")],
                                     key=lambda c: -c.get("score", 0))[:8], 1)) or "  —"
    return (
        f"📊 <b>آمار</b> — {STATS_TAG}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📥 از {fa(len(current_sources()))} منبع: <b>{fa(S['fetched'])}</b>\n"
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>\n"
        f"🔌 TCP پیش‌تست (غیرقطعی): <b>{fa(S['tcp'])}</b>\n"
        f"🟢 زنده نهایی (تونل): <b>{fa(len(g))}</b>\n"
        f"🚀 سرعت‌سنجی‌شده: <b>{fa(S.get('fast', 0))}</b>\n"
        f"⭐️ میانگین امتیاز: <b>{avg}</b>\n"
        f"📈 نرخ تأیید: <b>{rate}</b>\n"
        f"🗳 رأی‌ها: 👍 {fa(up)} · 👎 {fa(down)}\n"
        f"🔗 سابسکرایبشن: <b>{sub}</b>\n\n"
        f"🏆 <b>برترین‌ها:</b>\n"
        f"<blockquote expandable>{top}</blockquote>\n\n"
        f"🔄 {fa_ago(S['last'])} · ⏱ {uptime()}")
  
def help_text(is_admin=False):
    t = (
        "ℹ️ <b>راهنما</b>\n「 ساده مثل نفس کشیدن 」\n\n"
        "<blockquote expandable>"
        "🔢 عدد بفرست ← فایل زنده‌ها\n"
        "🧪 کانفیگ بفرست ← تست تونل + سرعت\n"
        "⚡️ سریع‌ترین‌ها ← فقط سرعت‌سنجی‌شده‌ها\n"
        "🎲 شانسی ← تاس بنداز\n"
        "🌍 / 🔌 ← فیلتر کشور و پروتکل\n"
        "📱 اپ HiVo ← سرچ و دانلود\n"
        "🔍 هر چتی: <code>@ربات 10</code>\n"
        "🔗 ساب ← همیشه تازه\n"
        "👍👎 فقط به تست‌های زنده رأی بده"
        "</blockquote>\n\n"
        "「 هر کلید، دری را باز می‌کند 」")
    if is_admin:
        t += "\n\n👑 <b>ادمین:</b> /admin"
    return t

def admin_panel_text():
    st = STORE.data["settings"]
    lock = f"🟢 {st.get('lock_channel', '')}" if st.get("lock_on") else "⚪️ خاموش"
    return (
        "👑 <b>پنل ادمین</b>\n「 فرمان بده 」\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📜 اختصاصی: <b>{fa(len(STORE.premium()))}</b>\n"
        f"📡 منابع: <b>{fa(len(current_sources()))}</b>\n"
        f"📢 قفل کانال: <b>{lock}</b>")

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن اختصاصی", callback_data="adm:add"),
         InlineKeyboardButton("📜 دیدن", callback_data="adm:list")],
        [InlineKeyboardButton("🗑 پاک‌کردن اختصاصی‌ها", callback_data="adm:clear")],
        [InlineKeyboardButton("📡 منابع", callback_data="adm:src")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:bc"),
         InlineKeyboardButton("📊 کاربران", callback_data="adm:stats")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm:set")],
        [InlineKeyboardButton("🏠 منو", callback_data="menu")],
    ])

def sources_text():
    lines = []
    for r in source_report():
        name = r["url"].replace("https://raw.githubusercontent.com/", "")
        if len(name) > 46:
            name = name[:46] + "…"
        if r["cooldown"]:
            tag = f"⏸ {fa(r['cooldown'] // 60)}د"
        elif r["fail"]:
            tag = f"🟠 ×{fa(r['fail'])}"
        else:
            tag = "🟢"
        lines.append(f"{tag} <code>{html.escape(name)}</code> — ✅{fa(r['ok'])} · {fa(r['count'])} عدد")
    body = "\n".join(lines) or "—"
    custom = STORE.sources()
    mode = f"لیست اختصاصی ({fa(len(custom))})" if custom else "پیش‌فرض"
    return (f"📡 <b>منابع</b> — {mode}\n"
            f"<blockquote expandable>{body}</blockquote>\n\n"
            "منابع خراب خودکار استراحت می‌گیرند (⏸).")

def sources_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن", callback_data="src:add"),
         InlineKeyboardButton("➖ حذف", callback_data="src:del")],
        [InlineKeyboardButton("♻️ ریست به پیش‌فرض", callback_data="src:reset")],
        [InlineKeyboardButton("🔙 پنل", callback_data="adm")],
    ])

def settings_text():
    st = STORE.data["settings"]
    wel = st.get("welcome", "").strip() or "پیش‌فرض"
    return (
        "⚙️ <b>تنظیمات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"✏️ متن خوش‌آمد: <i>{html.escape(wel[:60])}</i>\n"
        f"📢 قفل کانال: <b>{'🟢 روشن' if st.get('lock_on') else '⚪️ خاموش'}</b>")

def settings_kb():
    st = STORE.data["settings"]
    lock_label = "🔓 خاموش کن" if st.get("lock_on") else "🔒 روشن کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan"),
         InlineKeyboardButton(lock_label, callback_data="adm:lock")],
        [InlineKeyboardButton("🔙 پنل", callback_data="adm")],
    ])

def users_text():
    users = STORE.users()
    today = datetime.now().date().isoformat()
    active = sum(1 for u in users.values() if (u.get("last") or "").startswith(today))
    tot = STORE.data.get("totals", {})
    top = sorted(users.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:8]
    lines = [f"{fa(i)}. {html.escape(u.get('name') or '—')} — {fa(u.get('count', 0))} بار"
             for i, (uid, u) in enumerate(top, 1)]
    body = "\n".join(lines) or "  —"
    return (
        "👑 <b>کاربران</b>\n「 هر اسم، یک داستان 」\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل: <b>{fa(len(users))}</b>\n"
        f"🟢 امروز: <b>{fa(active)}</b>\n"
        f"📄 فایل: <b>{fa(tot.get('files', 0))}</b>\n"
        f"⚡️ کانفیگ: <b>{fa(tot.get('configs', 0))}</b>\n\n"
        f"🏆 <b>پرکاربردتر‌ها:</b>\n{body}")

async def do_broadcast(ctx, text, status_msg):
    users = STORE.users()
    ok = fail = 0
    for uid in list(users.keys()):
        try:
            await ctx.bot.send_message(int(uid), f"📣 {text}")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)
    extra = f"\n❌ {fa(fail)}" if fail else ""
    await status_msg.edit_text(f"✅ رفت به {fa(ok)} نفر{extra}")

async def send_config_file(message, n=None, items=None, title=None):
    g = sorted(list(S["good"]), key=lambda c: -c.get("score", 0)) if items is None else list(items)
    if not g:
        await message.reply_text("⏳ 「 چیزهای خوب، زمان می‌برند 」")
        return
    its = g if (n is None or n >= len(g)) else g[:n]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    content = "\n".join(export_uri(c) for c in its) + "\n"
    buf = io.BytesIO(content.encode())
    best = its[0]
    sp = f" · 🚀 {fa(best['speed'])}MB/s" if best.get("speed") else ""
    caption = (
        f"⚡️ <b>{title or 'HiVo Configs'} — {fa(len(its))} زنده</b>\n"
        f"{FILE_TAG}\n"
        f"⭐️ {fa(best.get('score', 0))} · ⏱ {fa(best['latency'])}ms{sp} {quality(best['latency'])}")
    msg = await message.reply_document(document=buf, filename=f"HiVo-{len(its)}.txt",
                                       caption=caption, parse_mode=ParseMode.HTML)
    await react(msg)
    STORE.add_totals(files=1, configs=len(its))

async def send_premium(message):
    prem = STORE.premium()
    if not prem:
        await message.reply_html(
            "👑 <b>اختصاصی</b>\n\n「 هنوز چیزی اینجا نیست؛ ولی به‌زودی 」")
        return
    uris = [premium_uri(u) for u in prem]
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    buf = io.BytesIO(("\n".join(uris) + "\n").encode())
    caption = f"👑 <b>HiVo Premium — {fa(len(uris))} ویژه</b>\n{PREMIUM_TAG}"
    msg = await message.reply_document(document=buf, filename="HiVo-Premium.txt",
                                       caption=caption, parse_mode=ParseMode.HTML)
    await react(msg, "🔥")
    STORE.add_totals(files=1, configs=len(uris))

async def send_sub_qr(message):
    url = S.get("sub")
    if not url:
        await message.reply_html("⏳ 「 هنوز در راه است 」")
        return
    msg = await message.reply_photo(photo=qr_bytes(url),
                                    caption=("🔗 <b>QR سابسکرایبشن</b>\n"
                                             "از گوشی دوم اسکن کن یا لینک را بگیر:\n"
                                             f"<code>{html.escape(url)}</code>"),
                                    parse_mode=ParseMode.HTML)
    await react(msg)

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
        results.append(InlineQueryResultArticle(
            id=str(i),
            title=f"⭐️{c.get('score', 0)} · {c['latency']}ms — HiVo",
            description=c["uri"][:90],
            input_message_content=InputTextMessageContent(
                message_text=f"⚡️ <b>HiVo Configs</b> — ⭐️{c.get('score', 0)} · {c['latency']}ms\n"
                             f"<code>{html.escape(export_uri(c))}</code>",
                parse_mode=ParseMode.HTML),
        ))
    await q.answer(results, cache_time=10, is_personal=True,
                   next_offset=str(offset + 12) if offset + 12 < len(g) else "")

async def run_single_test(message, uri):
    wait = await message.reply_html("🧪 <b>در حال اتصال واقعی…</b>\n「 حداکثر ~۲۰ ثانیه 」")
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, test_single, uri.strip())
    except Exception:
        log.exception("single test")
        await wait.edit_text("⚠️ تست الان ممکن نشد — کمی بعد دوباره امتحان کن.")
        return
    if res is None:
        await wait.edit_text("☠️ <b>پاسخ نداد</b>\n「 این یکی به آخر خط رسیده 」")
        return
    if not res.get("deep"):
        await wait.edit_text(
            f"{BANNER}\n 🟡 <b>پورت باز است — تونل پاس نشد</b>\n{BANNER}\n\n"
            f"⏱ {fa(res['latency'])}ms {quality(res['latency'])}\n"
            f"🔌 <tg-spoiler>{html.escape(str(res['host']))}:{fa(res['port'])}</tg-spoiler>\n\n"
            "「 سالم اعلام نمی‌شود؛ فقط گزارش واقعی 」")
        return
    vh = res["fp"]
    PENDING[vh] = res
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 کپی کانفیگ", copy_text=export_uri(res))],
        [InlineKeyboardButton("👍 وصل شد", callback_data=f"vote:1:{vh}"),
         InlineKeyboardButton("👎 نشد", callback_data=f"vote:0:{vh}")]])
    await wait.edit_text(card_text(res), parse_mode=ParseMode.HTML, reply_markup=kb)
    await react(message)

async def cmd_start(update, ctx):
    register(update)
    if not await gate(update, ctx):
        return
    await update.message.reply_html(menu_text(),
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
    raw = update.message.text or ""
    parts = raw.split(" ", 1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await update.message.reply_html("استفاده: <code>/broadcast متن</code>")
        return
    status = await update.message.reply_text("📣 در راه‌اند…")
    await do_broadcast(ctx, text, status)

async def cmd_cancel(update, ctx):
    ADMIN_STATE.pop(update.effective_user.id, None)
    await update.message.reply_html("「 برگشتی 」")

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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(stats_text(), reply_markup=kb)

def countries_kb():
    cnt, flagmap = {}, {}
    for c in S["good"]:
        if c.get("country"):
            cnt[c["country"]] = cnt.get(c["country"], 0) + 1
            flagmap.setdefault(c["country"], c.get("flag", "🌐"))
    top = sorted(cnt.items(), key=lambda kv: -kv[1])[:12]
    rows = [[InlineKeyboardButton(f"{flagmap[n]} {n} ({fa(ct)})", callback_data=f"cty2:{n}")]
            for n, ct in top]
    rows.append([InlineKeyboardButton("🔙 منو", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def protocols_kb():
    cnt = {}
    for c in S["good"]:
        cnt[c["proto"]] = cnt.get(c["proto"], 0) + 1
    names = {"vmess": "🟣 VMess", "vless": "🔵 VLESS", "trojan": "🔴 Trojan", "ss": "🟡 SS"}
    rows = [[InlineKeyboardButton(f"{names.get(p, p)} ({fa(ct)})", callback_data=f"prt2:{p}")]
            for p, ct in sorted(cnt.items(), key=lambda kv: -kv[1])]
    rows.append([InlineKeyboardButton("🔙 منو", callback_data="menu")])
    return InlineKeyboardMarkup(rows)
  
async def on_text(update, ctx):
    register(update)
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    if STORE.is_admin(uid) and uid in ADMIN_STATE:
        state = ADMIN_STATE[uid]
        if txt.lower() == "/cancel":
            ADMIN_STATE.pop(uid, None)
            await update.message.reply_html("「 برگشتی 」")
            return
        if state == "src:add":
            if not txt.startswith("http"):
                await update.message.reply_html("❌ لینک معتبر بفرست (با http)")
                return
            ADMIN_STATE.pop(uid, None)
            ok = STORE.add_source(txt.strip())
            await update.message.reply_html("✅ منبع اضافه شد — از دور بعد اعمال می‌شود." if ok
                                            else "⚠️ قبلاً اضافه شده.")
        elif state == "src:del":
            ADMIN_STATE.pop(uid, None)
            ok = STORE.remove_source(txt.strip())
            await update.message.reply_html("🗑 حذف شد." if ok
                                            else "⚠️ تو لیست اختصاصی نبود (منابع پیش‌فرض حذف نمی‌شن).")
        elif state == "premium":
            ADMIN_STATE.pop(uid, None)
            uris = URI_RE.findall(txt)
            if not uris:
                await update.message.reply_html("❌ کانفیگی پیدا نکردم. دوباره بفرست.")
                return
            added = STORE.add_premium(uris)
            await update.message.reply_html(
                f"👑 <b>{fa(added)} کانفیگ اختصاصی اضافه شد</b>\n"
                f"📜 کل: <b>{fa(len(STORE.premium()))}</b>\n\n「 ذخیره شد 」")
        elif state == "welcome":
            ADMIN_STATE.pop(uid, None)
            if txt.lower() == "/off" or txt == "خاموش":
                STORE.set_setting("welcome", "")
                await update.message.reply_html("✏️ برگشت به پیش‌فرض.")
            else:
                STORE.set_setting("welcome", txt)
                await update.message.reply_html("✏️ 「 متن تازه نشست 」")
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
                    f"📢 قفل روشن شد: <code>{html.escape(txt)}</code>\n"
                    "⚠️ ربات باید ادمین کانال باشد.")
        elif state == "broadcast":
            ADMIN_STATE.pop(uid, None)
            status = await update.message.reply_text("📣 در راه‌اند…")
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
        await send_config_file(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

async def on_button(update, ctx):
    register(update)
    q = update.callback_query
    data = q.data
    await q.answer()
    uid = q.from_user.id
    is_admin = STORE.is_admin(uid)
    kb_menu = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])

    if data == "recheck":
        if await gate(update, ctx):
            await q.message.reply_html(menu_text(), reply_markup=main_menu(is_admin))
        return

    if data.startswith("vote:"):
        val = 1 if data.split(":")[1] == "1" else -1
        vh = data.split(":")[2]
        host = (PENDING.get(vh) or {}).get("host") or STORE.get_vote_host(vh)
        if not host:
            await q.answer("این رأی منقضی شده", show_alert=False)
            return
        st = STORE.vote(uid, vh, host, val)
        if st == "same":
            await q.answer("قبلاً همین رأی رو دادی 🗳")
        else:
            await q.answer("ثبت شد ✅ مرسی!")
        return

    if data.startswith("file:"):
        if not await gate(update, ctx):
            return
        arg = data.split(":")[1]
        await send_config_file(q.message, None if arg == "all" else int(arg))
    elif data == "premium":
        if not await gate(update, ctx):
            return
        await send_premium(q.message)
    elif data == "qr":
        await send_sub_qr(q.message)
    elif data == "fast":
        if not await gate(update, ctx):
            return
        fasts = sorted([c for c in S["good"] if c.get("speed")],
                       key=lambda c: -c["speed"])[:50]
        if fasts:
            await send_config_file(q.message, items=fasts, title="⚡️ سریع‌ترین‌ها")
        else:
            await q.message.reply_html("⏳ 「 سرعت‌سنجی هنوز نتیجه نداده — ۲ دقیقه صبر 」")
    elif data == "rnd":
        if not await gate(update, ctx):
            return
        g = list(S["good"])
        if not g:
            await q.message.reply_html("⏳ 「 هنوز چیزی نیست 」")
            return
        await q.message.reply_dice(emoji="🎲")
        await asyncio.sleep(2.5)
        c = random.choice(g)
        PENDING[c["fp"]] = c
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 کپی کانفیگ", copy_text=export_uri(c))],
            [InlineKeyboardButton("👍 وصل شد", callback_data=f"vote:1:{c['fp']}"),
             InlineKeyboardButton("👎 نشد", callback_data=f"vote:0:{c['fp']}")],
            [InlineKeyboardButton("🎲 یکی دیگه", callback_data="rnd")]])
        await q.message.reply_html(card_text(c, "🎲 شانسی"),
                                   parse_mode=ParseMode.HTML, reply_markup=kb)
    elif data == "tester":
        await q.message.reply_html(
            "🧪 <b>تستر تکی</b>\n\n"
            "هر کانفیگی داری (vmess:// یا vless:// یا trojan:// یا ss://) بفرست —\n"
            "تونل واقعی + سرعت + امتیاز، حداکثر ~۲۰ ثانیه.\n\n"
            "「 محک بزن، اگر دوام آورد مال توئه 」")
    elif data == "cty":
        await q.message.reply_html("🌍 <b>یک کشور انتخاب کن</b>", reply_markup=countries_kb())
    elif data.startswith("cty2:"):
        if not await gate(update, ctx):
            return
        name = data.split(":", 1)[1]
        items = sorted([c for c in S["good"] if c.get("country") == name],
                       key=lambda c: -c.get("score", 0))
        await send_config_file(q.message, items=items, title=name)
    elif data == "prt":
        await q.message.reply_html("🔌 <b>یک پروتکل انتخاب کن</b>", reply_markup=protocols_kb())
    elif data.startswith("prt2:"):
        if not await gate(update, ctx):
            return
        p = data.split(":", 1)[1]
        items = sorted([c for c in S["good"] if c["proto"] == p],
                       key=lambda c: -c.get("score", 0))
        await send_config_file(q.message, items=items, title=f"🔌 {p.upper()}")
    elif data == "sub":
        url = S.get("sub")
        if url:
            txt = ("🔗 <b>سابسکرایبشن</b>\n\n"
                   f"<code>{html.escape(url)}</code>\n\n"
                   "「 فقط کانفیگ‌های تونل‌پس‌داده — هر ۱۵ دقیقه تازه 」")
        else:
            txt = "⏳ 「 هنوز در راه است 」"
        await q.message.reply_html(txt, reply_markup=kb_menu)
    elif data == "menu":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_html(menu_text(), reply_markup=main_menu(is_admin))
    elif data == "stats":
        await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "help":
        await q.edit_message_text(help_text(is_admin), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "retest":
        FORCE.set()
        await q.edit_message_text("📡 「 دور تازه شروع شد — نتایج زنده می‌آید 」",
                                  parse_mode=ParseMode.HTML)
    elif data == "adm" and is_admin:
        await q.edit_message_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif data == "adm:src" and is_admin:
        await q.edit_message_text(sources_text(), parse_mode=ParseMode.HTML, reply_markup=sources_kb())
    elif data == "src:add" and is_admin:
        ADMIN_STATE[uid] = "src:add"
        await q.message.reply_html("🔗 <b>لینک منبع را بفرست</b>\n"
                                   "(لینک raw که داخلش لینک کانفیگ باشد)\n\n/cancel انصراف")
    elif data == "src:del" and is_admin:
        ADMIN_STATE[uid] = "src:del"
        await q.message.reply_html("🔗 <b>لینک منبع را دقیقاً بفرست</b> تا حذف شود\n\n/cancel انصراف")
    elif data == "src:reset" and is_admin:
        STORE.reset_sources()
        await q.message.reply_html("♻️ منابع به پیش‌فرض برگشت — از دور بعد اعمال می‌شود.")
    elif data == "adm:add" and is_admin:
        ADMIN_STATE[uid] = "premium"
        await q.message.reply_html(
            "➕ <b>کانفیگ‌های اختصاصی را بفرست</b>\n(چند خط — هر خط یک کانفیگ)\n\n/cancel برای انصراف")
    elif data == "adm:list" and is_admin:
        prem = STORE.premium()
        if not prem:
            await q.message.reply_html("📜 「 خالی است 」")
        else:
            buf = io.BytesIO(("\n".join(prem) + "\n").encode())
            await q.message.reply_document(buf, filename="premium-raw.txt",
                                           caption=f"📜 {fa(len(prem))} کانفیگ اختصاصی")
    elif data == "adm:clear" and is_admin:
        n = STORE.clear_premium()
        await q.message.reply_html(f"🗑 {fa(n)} کانفیگ پاک شد.")
        await q.message.reply_html(admin_panel_text(), reply_markup=admin_kb())
    elif data == "adm:bc" and is_admin:
        ADMIN_STATE[uid] = "broadcast"
        await q.message.reply_html("📣 <b>متن پیام را بفرست</b>\n\n/cancel برای انصراف")
    elif data == "adm:stats" and is_admin:
        await q.edit_message_text(users_text(), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("🔙 پنل", callback_data="adm")]]))
    elif data == "adm:set" and is_admin:
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())
    elif data == "adm:wel" and is_admin:
        ADMIN_STATE[uid] = "welcome"
        await q.message.reply_html(
            "✏️ <b>متن خوش‌آمد را بفرست</b>\n(کوتاه و از ته دل)\n\n/off برای پیش‌فرض — /cancel انصراف")
    elif data == "adm:chan" and is_admin:
        ADMIN_STATE[uid] = "channel"
        await q.message.reply_html(
            "📢 <b>آیدی کانال را بفرست</b> (با @)\nربات باید ادمین کانال باشد.\n\n/off برای خاموشی — /cancel انصراف")
    elif data == "adm:lock" and is_admin:
        st = STORE.data["settings"]
        STORE.set_setting("lock_on", not st.get("lock_on"))
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())

async def on_error(update, ctx):
    log.error("handler error", exc_info=ctx.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("⚠️ یه خطای موقت پیش اومد — دوباره امتحان کن.")
    except Exception:
        pass

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 داشبورد"),
        BotCommand("configs", "📄 فایل — /configs 200"),
        BotCommand("stats", "📊 آمار"),
        BotCommand("help", "ℹ️ راهنما"),
    ])
    await app.bot.set_my_description(
        "مرزها را نقاشی کردند؛ ما راهی ساختیم ⚡️ تونل واقعی، سرعت واقعی، امتیاز واقعی.")
    await app.bot.set_my_short_description(TAGLINE + " ⚡️")
    if APP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="⚡️ HiVo", web_app=WebAppInfo(url=APP_URL)))
            log.info(f"menu button → {APP_URL}")
        except Exception as e:
            log.warning(f"menu button: {e}")

async def post_shutdown(app):
    ok = STORE.save()
    log.info(f"final save: {ok}")

def main():
    STORE.load()
    forced = os.environ.get("ADMIN_ID", "").strip()
    STORE.set_admin(forced or OWNER)
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
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("HiVo Configs v10 started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
