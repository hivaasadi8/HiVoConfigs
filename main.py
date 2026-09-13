# -*- coding: utf-8 -*-
# HiVo Configs — main.py (FIXED)
import html, io, logging, os, random
import qrcode
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from tester import S, LOCK, test_single, parse_config, export_uri, current_sources
from store import STORE

BOT_TOKEN=os.environ.get('BOT_TOKEN','')
OWNER=str(os.environ.get('ADMIN_ID','8343701928'))
REPO=os.environ.get('GITHUB_REPOSITORY','hivaasadi8/HiVoConfigs')
APP_URL=f'https://{REPO.split("/")[0].lower()}.github.io/{REPO.split("/")[1]}/' if '/' in REPO else ''

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log=logging.getLogger('hivo.bot')
FA=str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹')
fa=lambda x: str(x).translate(FA)

def is_admin(uid): return str(uid)==OWNER or STORE.is_admin(str(uid))

def card(c, badge='⚡️ کانفیگ ویژه'):
    uri=export_uri(c)
    proto=c.get('proto','vless').upper()
    return (f'\U0001f60e {badge}\n━━━━━━\n'
      f"📍 {c.get('ps') or c.get('host')}\n"
      f'⚡️ {proto} | ⏱ {fa(c.get("latency",120))}ms\n━━━━━━\n'
      f'📋 <b>برای کپی لمس کنید:</b>\n<code>{html.escape(uri)}</code>\n━━━━━━\n'
      f'💡 v2rayNG • Streisand • Nekoray')

def menu(admin=False):
    rows=[]
    if APP_URL: rows.append([InlineKeyboardButton('📱 مینی‌اپ HiVo', web_app=WebAppInfo(url=APP_URL))])
    rows+=([[InlineKeyboardButton('⚡️ سریع‌ترین',callback_data='fast'),InlineKeyboardButton('🎲 تصادفی',callback_data='rnd')],
      [InlineKeyboardButton('📶 همراه اول',callback_data='op:mci'),InlineKeyboardButton('📶 ایرانسل',callback_data='op:mtn')],
      [InlineKeyboardButton('👑 ضدفیلتر VIP',callback_data='reality'),InlineKeyboardButton('🧪 تستر',callback_data='tester_menu')],
      [InlineKeyboardButton('🔗 ساب لینک',callback_data='sub_link'),InlineKeyboardButton('📦 فایل ۵۰تایی',callback_data='file:50')],
      [InlineKeyboardButton('📊 وضعیت',callback_data='stats')]])
    if admin: rows.append([InlineKeyboardButton('⚙️ پنل مدیریت',callback_data='admin:menu')])
    return InlineKeyboardMarkup(rows)

async def cmd_start(u,c):
    user=u.effective_user
    STORE.touch(user.id, user.first_name or '', user.username or '')
    await u.message.reply_html(f'👋 درود {html.escape(user.first_name)} گرامی\nبه <b>HiVo Configs</b> خوش آمدید ⚡️\nسرویس را انتخاب کنید:', reply_markup=menu(is_admin(user.id)))

async def cmd_sub(u,c):
    link=f'https://raw.githubusercontent.com/{REPO}/main/sub.txt'
    await u.message.reply_html(f'🔗 <b>لینک ساب:</b>\n<code>{html.escape(link)}</code>', reply_markup=menu(is_admin(u.effective_user.id)))

async def cmd_ping(u,c):
    with LOCK: n=len(S.get('good',[]))
    await u.message.reply_html(f'🏓 <b>آنلاینم!</b>\n🟢 {fa(n)} کانفیگ فعال')

async def on_cb(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    uid=str(u.effective_user.id); admin=is_admin(uid)
    with LOCK: goods=list(S.get('good',[]))
    if d=='main_menu':
        await q.edit_message_text('🏠 منوی اصلی:', reply_markup=menu(admin)); return
    if d in ('fast','rnd','reality','op:mci','op:mtn'):
        if not goods:
            await q.message.reply_html('⏳ کانفیگ‌ها در حال به‌روزرسانی‌اند، ۱ دقیقه بعد تلاش کنید.'); return
        badge={'fast':'⚡️ سریع‌ترین','rnd':'🎲 تصادفی','reality':'👑 VIP','op:mci':'📶 همراه اول','op:mtn':'📶 ایرانسل'}[d]
        pool=goods
        if d=='reality':
            r=[x for x in goods if 'reality' in (x.get('raw') or '')]
            pool=r or goods
        pick=pool[0] if d in ('fast','reality') else random.choice(pool[:25])
        idx=goods.index(pick)  # FIXED: index-based, no host:port split
        kb=InlineKeyboardMarkup([[InlineKeyboardButton('📱 QR',callback_data=f'qr:{idx}')],[InlineKeyboardButton('🎲 یکی دیگر',callback_data=d)],[InlineKeyboardButton('🔙 منو',callback_data='main_menu')]])
        await q.message.reply_html(card(pick,badge), reply_markup=kb); return
    if d.startswith('qr:'):
        try:
            idx=int(d.split(':')[1])
            c=goods[idx]
            qr=qrcode.QRCode(box_size=8,border=2); qr.add_data(export_uri(c)); qr.make(fit=True)
            img=qr.make_image(fill_color='black',back_color='white')
            bio=io.BytesIO(); img.save(bio,'PNG'); bio.seek(0)
            await q.message.reply_photo(bio, caption='📱 اسکن در v2rayNG')
        except Exception: await q.message.reply_html('❌ این کانفیگ منقضی شده، یکی دیگر بگیرید.')
        return
    if d=='sub_link':
        link=f'https://raw.githubusercontent.com/{REPO}/main/sub.txt'
        await q.message.reply_html(f'🔗 ساب:\n<code>{html.escape(link)}</code>\n🔄 آپدیت هر ۴۵ دقیقه', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙',callback_data='main_menu')]])); return
    if d=='stats':
        await q.message.reply_html(f"📊 🟢 {fa(len(goods))} کانفیگ فعال\n⏱ تست: {fa(S.get('duration',0))}s\n📚 سورس فعال: {fa(S.get('active_sources',0))}/{fa(S.get('sources_count',0))}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙',callback_data='main_menu')]])); return
    if d=='tester_menu':
        await q.message.reply_html('🧪 کانفیگت را بفرست تا تست کنم (vless/vmess/trojan/ss)', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙',callback_data='main_menu')]])); return
    if d=='file:50':
        if not goods: await q.message.reply_html('⏳ آماده نیست'); return
        bio=io.BytesIO('\n'.join(export_uri(x) for x in goods[:50]).encode()); bio.name='HiVo_Top50.txt'
        await q.message.reply_document(bio, caption='📦 ۵۰ کانفیگ برتر HiVo'); return
    if d=='admin:menu':
        if not admin: return
        await q.message.reply_html(f"⚙️ پنل\n👥 کاربران: {fa(STORE.count())}\n📚 سورس‌ها:\n"+"\n".join('• '+s for s in current_sources()), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙',callback_data='main_menu')]])); return

async def on_text(u,c):
    t=(u.message.text or '').strip()
    if t.lower().startswith(('vless://','vmess://','trojan://','ss://','hysteria')):
        m=await u.message.reply_html('⏳ در حال تست…')
        r=test_single(t)
        if r.get('ok'): await m.edit_text(f"✅ سالم است! ⏱ {fa(r.get('latency',0))}ms", parse_mode=ParseMode.HTML)
        else: await m.edit_text(f"❌ خراب است: {r.get('msg','')}", parse_mode=ParseMode.HTML)

async def on_err(u,c): log.error('update error: %s', c.error)
async def post_init(app):
    await app.bot.set_my_commands([BotCommand('start','شروع'),BotCommand('sub','لینک ساب'),BotCommand('ping','تست ربات')])

def main():
    if not BOT_TOKEN: log.error('BOT_TOKEN is not set'); return
    from tester import refresh_loop
    import threading
    threading.Thread(target=refresh_loop, daemon=True).start()
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start',cmd_start))
    app.add_handler(CommandHandler('sub',cmd_sub))
    app.add_handler(CommandHandler('ping',cmd_ping))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_err)
    log.info('HiVo bot running')
    app.run_polling()

if __name__=='__main__': main()
    
