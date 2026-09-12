# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  CONFIG ELITE v4 — بدون سقف + پرچم کشورها
# ══════════════════════════════════════════

import asyncio, html, io, logging, os, re, threading
from datetime import datetime

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
try:
    from telegram import CopyTextButton
    HAS_COPY = True
except ImportError:
    HAS_COPY = False
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from tester import (S, LOCK, refresh_loop, retest_all)

BOT_TOKEN = os.environ["BOT_TOKEN"]
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite")

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(x):
    return str(x).translate(FA)

FULL, EMPTY = "▰", "▱"
def quality(ms):
    if ms < 300:
        return FULL * 5
    if ms < 700:
        return FULL * 4 + EMPTY
    if ms < 1500:
        return FULL * 3 + EMPTY * 2
    return FULL * 2 + EMPTY * 3

def ago(dt):
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

def menu_text():
    mode = "🧪 تست واقعی تونل Xray" if S["xray"] else "🔌 تست پورت TCP"
    return "\n".join([
        "⚡️ <b>HiVo Configs</b>",
        "━━━━━━━━━━━━━━━━━━",
        mode,
        "",
        f"🟢 سالم: <b>{fa(len(S['good']))}</b>",
        f"🔌 TCP زنده: <b>{fa(S['tcp'])}</b>",
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>",
        f"🔄 {ago(S['last'])}",
        "━━━━━━━━━━━━━━━━━━",
        "<i>هر عددی بفرست — بدون محدودیت</i>",
    ])

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 ۵۰", callback_data="file:50"),
         InlineKeyboardButton("📄 ۱۰۰", callback_data="file:100"),
         InlineKeyboardButton("📄 ۲۰۰", callback_data="file:200")],
        [InlineKeyboardButton("📄 ۵۰۰", callback_data="file:500"),
         InlineKeyboardButton("📄 همه", callback_data="file:all")],
        [InlineKeyboardButton("🔗 سابسکرایبشن", callback_data="sub")],
        [InlineKeyboardButton("📊 آمار", callback_data="stats"),
         InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
        [InlineKeyboardButton("♻️ تست مجدد", callback_data="retest")],
    ])

def stats_text():
    g = S["good"]
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    top = "\n".join(
        f"  {fa(i)}. ⏱ {fa(c['latency'])}ms {quality(c['latency'])}"
        f"  <code>{html.escape(str(c['host']))}</code>"
        for i, c in enumerate(g[:5], 1)
    ) or "  —"
    sub = "✅ فعال" if S["sub"] else "—"
    return (
        "📊 <b>آمار زنده</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📥 جمع‌آوری‌شده از ۱۲ منبع: <b>{fa(S['fetched'])}</b>\n"
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>\n"
        f"🔌 زنده TCP: <b>{fa(S['tcp'])}</b>\n"
        f"🟢 سالم نهایی: <b>{fa(len(g))}</b>\n"
        f"📈 نرخ موفقیت: <b>{rate}</b>\n"
        f"🔗 سابسکرایبشن: <b>{sub}</b>\n\n"
        f"🏆 <b>برترین‌ها:</b>\n{top}\n\n"
        f"🔄 {ago(S['last'])}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡️ HiVo Configs")

def help_text():
    return (
        "ℹ️ <b>راهنما</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📄 <b>فایل کانفیگ</b>\n"
        "هر عددی بفرست (۵۰، ۱۰۰، ۱۰۰۰…) ← فایل txt می‌گیری. باز کن، کپی کن، تو کلاینت Import کن.\n\n"
        "🔗 <b>سابسکرایبشن</b>\n"
        "لینک رو تو کلاینتت اضافه کن — هر ۱۵ دقیقه خودش آپدیت می‌شه.\n\n"
        "🌍 <b>اسم کانفیگ‌ها</b>\n"
        "هر کانفیگ = پرچم + کشور + شهر + پینگ واقعی.\n\n"
        "📶 <b>کیفیت پینگ</b> (لود واقعی از داخل تونل)\n"
        f"{FULL*5} عالی — {FULL*4}{EMPTY} خیلی خوب — {FULL*3}{EMPTY*2} خوب\n\n"
        "⚡️ HiVo Configs")

async def send_config_file(message, n):
    g = list(S["good"])
    if not g:
        await message.reply_text("⏳ هنوز آماده نشده — اولین نتایج ~۲ دقیقه دیگه میاد.")
        return
    if n is None or n >= len(g):
        items = g
        note = "همه"
    else:
        items = g[:n]
        note = fa(n)
    await message.chat.send_action("upload_document")
    content = "\n".join(c["uri"] for c in items) + "\n"
    buf = io.BytesIO(content.encode())
    caption = (
        f"⚡️ <b>HiVo Configs — {fa(len(items))} کانفیگ تأییدشده</b>\n"
        f"🧪 تست تونل واقعی | ⏱ بهترین: <b>{fa(items[0]['latency'])}ms</b>\n"
        "📥 باز کن ← کپی همه ← Import در کلاینت"
    )
    await message.reply_document(document=buf, filename=f"HiVo-Configs-{len(items)}.txt",
                                 caption=caption, parse_mode=ParseMode.HTML)

async def cmd_start(update: Update, ctx):
    await update.message.reply_html(menu_text(), reply_markup=main_menu())

async def cmd_stats(update: Update, ctx):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(stats_text(), reply_markup=kb)

async def cmd_help(update: Update, ctx):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(help_text(), reply_markup=kb)

async def cmd_configs(update: Update, ctx):
    n = None
    if ctx.args and ctx.args[0].isdigit():
        n = int(ctx.args[0])
    await send_config_file(update.message, n)

async def on_text(update: Update, ctx):
    m = re.search(r"\d+", update.message.text or "")
    if m:
        await send_config_file(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

async def on_button(update: Update, ctx):
    q = update.callback_query
    data = q.data
    await q.answer()
    kb_menu = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    if data.startswith("file:"):
        arg = data.split(":")[1]
        n = None if arg == "all" else int(arg)
        await send_config_file(q.message, n)
    elif data == "sub":
        url = S.get("sub")
        if url:
            txt = ("🔗 <b>سابسکرایبشن اختصاصی</b>\n\n"
                   f"<code>{html.escape(url)}</code>\n\n"
                   "لمسش کن تا کپی شه ← تو کلاینت (Subscription) اضافه‌ش کن.\n"
                   "✨ هر ۱۵ دقیقه خودکار آپدیت می‌شه.")
        else:
            txt = "⏳ هنوز ساخته نشده — بعد از اولین دور کامل (~۱۰ دقیقه) دوباره بزن."
        await q.message.reply_html(txt, reply_markup=kb_menu)
    elif data == "menu":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_html(menu_text(), reply_markup=main_menu())
    elif data == "stats":
        await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "help":
        await q.edit_message_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "retest":
        await q.edit_message_text("📡 <b>در حال تست مجدد…</b>", parse_mode=ParseMode.HTML)
        res = await asyncio.get_running_loop().run_in_executor(None, retest_all)
        with LOCK:
            if res:
                S["good"], S["last"] = res, datetime.now()
        best = f"{fa(res[0]['latency'])}ms" if res else "—"
        txt = (f"♻️ <b>تست مجدد شد</b>\n\n"
               f"🟢 سالم: <b>{fa(len(res))}</b>\n"
               f"⚡️ بهترین: <b>{best}</b>")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb_menu)

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 منوی اصلی"),
        BotCommand("configs", "📄 فایل کانفیگ — /configs 200"),
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
    log.info("HiVo Configs v4 started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
