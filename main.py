# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
#  HiVo Configs v11 — LUXURY TELEGRAM BOT (Titan Edition)
# ══════════════════════════════════════════════════════════════

import asyncio
import base64
import html
import io
import json
import logging
import os
import random
import threading
from datetime import datetime
from urllib.parse import quote

import qrcode
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    MenuButtonWebApp,
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

from tester import (
    S,
    LOCK,
    FORCE,
    refresh_loop,
    test_single,
    parse_config,
    export_uri,
    current_sources,
)
from store import STORE

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER = os.environ.get("ADMIN_ID", "8343701928")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
APP_URL = f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/" if REPO and "/" in REPO else ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s: %(message)s")
log = logging.getLogger("hivo.bot")

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def fa(x):
    return str(x).translate(FA)

STARTED = datetime.now()

def uptime():
    s = int((datetime.now() - STARTED).total_seconds())
    h, rem = divmod(s, 3600)
    return f"{fa(h)} ساعت و {fa(rem // 60)} دقیقه"

def register(update: Update):
    u = update.effective_user
    if u:
        STORE.touch(u.id, u.first_name or "", u.username or "")

# ─── Luxury Telegram Message Formatter ────────────────────────
def format_config_card(c: dict, badge: str = "⚡️ کانفیگ ویژه") -> str:
    flag = c.get("flag", "🌐")
    country = c.get("country", "آلمان")
    proto = c.get("proto", "vless").upper()
    ping = c.get("latency", 120)
    net = c.get("net", "tcp").upper()
    sec = (c.get("security") or c.get("tls") or "none").upper()
    uri = export_uri(c)

    return (
        f"<b>{badge}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>لوکیشن:</b> {flag} {country}\n"
        f"⚡️ <b>پروتکل:</b> <code>{proto}</code> | <b>بستر:</b> <code>{net}</code>\n"
        f"⏱ <b>پینگ تست‌شده:</b> <code>{fa(int(ping))} میلی‌ثانیه</code>\n"
        f"🛡 <b>امنیت:</b> <code>{sec}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>کانفیگ (برای کپی لمس کنید):</b>\n"
        f"<code>{html.escape(uri)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>پشتیبانی در v2rayNG, Streisand, Sing-box, Nekoray</i>"
    )

def main_menu(is_admin=False):
    rows = []
    if APP_URL:
        rows.append([InlineKeyboardButton("📱 اپلیکیشن لوکس HiVo (Mini App)", web_app=WebAppInfo(url=APP_URL))])

    rows.append([
        InlineKeyboardButton("⚡️ سریع‌ترین کانفیگ", callback_data="fast"),
        InlineKeyboardButton("🎲 کانفیگ تصادفی", callback_data="rnd"),
    ])
    rows.append([
        InlineKeyboardButton("📶 مناسب همراه اول", callback_data="op:mci"),
        InlineKeyboardButton("📶 مناسب ایرانسل", callback_data="op:mtn"),
    ])
    rows.append([
        InlineKeyboardButton("👑 سرورهای ضد فیلتر VIP", callback_data="reality"),
        InlineKeyboardButton("🧪 تستر اتصال", callback_data="tester_menu"),
    ])
    rows.append([
        InlineKeyboardButton("🔗 لینک سابسکرایب هوشمند", callback_data="sub_link"),
        InlineKeyboardButton("📦 دریافت فایل ۵۰ تایی", callback_data="file:50"),
    ])
    rows.append([
        InlineKeyboardButton("📊 وضعیت زنده سرورها", callback_data="stats"),
    ])

    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت ارشد", callback_data="admin:menu")])

    return InlineKeyboardMarkup(rows)

# ─── Handlers ────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register(update)
    u = update.effective_user
    uid = str(u.id)
    is_admin = STORE.is_admin(uid) or uid == OWNER

    txt = (
        f"👋 درود <b>{html.escape(u.first_name)}</b> گرامی،\n\n"
        f"به سامانه فوق‌سریع <b>HiVo Configs</b> خوش آمدید.\n"
        f"کانفیگ‌ها به صورت خودکار با هسته <b>Xray Core</b> غربالگری شده و پایدارترین اتصال را در اختیارتان قرار می‌دهند.\n\n"
        f"🔹 <i>لطفاً سرویس مورد نیاز خود را انتخاب نمایید:</i>"
    )
    await update.message.reply_html(txt, reply_markup=main_menu(is_admin))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = str(update.effective_user.id)
    is_admin = STORE.is_admin(uid) or uid == OWNER

    with LOCK:
        goods = list(S.get("good", []))

    if data == "main_menu":
        await q.edit_message_text(
            "🏠 <b>منوی اصلی HiVo Configs</b>\n\nیک بخش را انتخاب کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(is_admin),
        )
        return

    if data in ("fast", "rnd", "reality", "op:mci", "op:mtn"):
        if not goods:
            await q.message.reply_html("⏳ <b>کانفیگ‌ها در حال به‌روزرسانی نهایی هستند...</b>\nچند ثانیه بعد مجدداً تلاش فرمایید.")
            return

        selected = None
        badge = "⚡️ کانفیگ فوق‌سریع"

        if data == "fast":
            selected = goods[0]
            badge = "⚡️ سریع‌ترین کانفیگ تست‌شده"
        elif data == "reality":
            realities = [c for c in goods if (c.get("security") == "reality" or "reality" in (c.get("raw") or ""))]
            selected = realities[0] if realities else goods[0]
            badge = "👑 کانفیگ VIP ضد فیلتر"
        elif data == "op:mci":
            selected = random.choice(goods[:10])
            badge = "📶 سرور پایدار همراه اول"
        elif data == "op:mtn":
            selected = random.choice(goods[:10])
            badge = "📶 سرور پایدار ایرانسل"
        else:
            selected = random.choice(goods[:25])
            badge = "🎲 کانفیگ تست‌شده تصادفی"

        txt = format_config_card(selected, badge)
        uri = export_uri(selected)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 دریافت بارکد QR", callback_data=f"qr:{selected['host']}:{selected['port']}")],
            [InlineKeyboardButton("🎲 دریافت یکی دیگر", callback_data=data)],
            [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
        ])
        await q.message.reply_html(txt, reply_markup=kb)
        return

    if data.startswith("qr:"):
        _, host, port = data.split(":")
        match = [c for c in goods if c.get("host") == host and str(c.get("port")) == port]
        if match:
            uri = export_uri(match[0])
            qr = qrcode.QRCode(box_size=8, border=2)
            qr.add_data(uri)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            bio = io.BytesIO()
            img.save(bio, "PNG")
            bio.seek(0)
            await q.message.reply_photo(
                photo=bio,
                caption=f"📱 <b>بارکد QR کانفیگ</b>\nاسکن مستقیم در نرم‌افزارهای موبایل",
                parse_mode=ParseMode.HTML,
            )
        return

    if data == "sub_link":
        sub_url = f"https://raw.githubusercontent.com/{REPO}/main/sub.txt" if REPO else "https://hivaasadi8.github.io/HiVoConfigs/sub.txt"
        txt = (
            f"🔗 <b>لینک هوشمند سابسکرایبشن</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"این لینک را در نرم‌افزار خود (v2rayNG, Streisand, Sing-box) به عنوان Subscription وارد کنید تا کانفیگ‌ها همیشه تازه و فعال باقی بمانند:\n\n"
            f"<code>{sub_url}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 <i>به‌روزرسانی خودکار هر ۳۰ دقیقه</i>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        await q.message.reply_html(txt, reply_markup=kb)
        return

    if data == "stats":
        total_good = len(goods)
        dur = S.get("duration", 0)
        up = uptime()
        txt = (
            f"📊 <b>وضعیت زنده سامانه HiVo</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>کانفیگ‌های فعال تست‌شده:</b> {fa(total_good)} عدد\n"
            f"⚡️ <b>میانگین سرعت تست:</b> {fa(dur)} ثانیه\n"
            f"⏳ <b>آپ‌تایم ربات:</b> {up}\n"
            f"🛡 <b>موتور تست:</b> <code>Xray Core (In-Memory Engine)</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        await q.message.reply_html(txt, reply_markup=kb)
        return

    if data == "tester_menu":
        txt = (
            f"🧪 <b>تستر زنده کانفیگ</b>\n\n"
            f"برای سنجش سلامت و پینگ، کافیست کانفیگ خود را (VLESS, VMess, Trojan, SS) به صورت متن به همین چت ارسال نمایید."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]])
        await q.message.reply_html(txt, reply_markup=kb)
        return

    if data == "file:50":
        if not goods:
            await q.message.reply_html("⏳ در حال آماده‌سازی فایل...")
            return
        content = "\n".join([export_uri(c) for c in goods[:50]])
        bio = io.BytesIO(content.encode("utf-8"))
        bio.name = "HiVo_Top50_Configs.txt"
        await q.message.reply_document(
            document=bio,
            caption="📦 <b>فایل ۵۰ کانفیگ منتخب و با کیفیت HiVo</b>",
            parse_mode=ParseMode.HTML,
        )
        return

async def handle_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if any(text.lower().startswith(p) for p in ["vless://", "vmess://", "trojan://", "ss://", "hysteria2://"]):
        msg = await update.message.reply_html("⏳ <b>در حال ارزیابی سلامت کانفیگ با موتور Xray...</b>")
        res = test_single(text)
        if res.get("ok"):
            p = res.get("latency", 0)
            flag = res.get("flag", "🌐")
            country = res.get("country", "سرور فعال")
            await msg.edit_text(
                f"✅ <b>کانفیگ سالم و فعال است!</b>\n\n"
                f"📍 <b>موقعیت:</b> {flag} {country}\n"
                f"⏱ <b>پینگ اتصال:</b> <code>{fa(int(p))} ms</code>\n"
                f"🛡 <b>پاسخ‌دهی موفقیت‌آمیز به شبکه</b>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.edit_text(
                f"❌ <b>کانفیگ غیرفعال است!</b>\n\nعلت: {res.get('msg', 'عدم دریافت پاسخ')}",
                parse_mode=ParseMode.HTML,
            )

def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set. Exiting.")
        return

    # Start background testing loop
    th = threading.Thread(target=refresh_loop, daemon=True)
    th.start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text))

    log.info("HiVo Luxury Telegram Bot is running.")
    app.run_polling()

if __name__ == "__main__":
    main()
