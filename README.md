# HiVo Configs Pro

ربات تلگرامی جمع‌آوری، تست و رتبه‌بندی کانفیگ‌های Proxy/V2Ray.

## قابلیت‌ها
- جمع‌آوری همزمان از چند Source
- تشخیص Base64 و URIهای VMess/VLESS/Trojan/SS
- حذف تکراری‌ها با fingerprint
- TCP pre-check سریع
- تست واقعی تونل با Xray
- latency، speed، stability و score
- Geo lookup و فیلتر کشور/پروتکل
- رتبه‌بندی هوشمند و انتخاب سریع‌ترین‌ها
- فایل‌های ۵۰/۱۰۰/۲۰۰/۵۰۰/همه
- Subscription و QR
- تست کانفیگ تکی
- Vote
- Premium
- Channel lock
- پنل ادمین، مدیریت Source و Broadcast
- Inline mode
- ذخیره GitHub JSON با کنترل همزمانی
- cache و source health برای کاهش تست‌های تکراری
- تحمل خطا و ادامه کار در صورت خرابی یک Source/Xray

## اجرا
1. `pip install -r requirements.txt`
2. متغیرهای `.env` یا محیط اجرا را تنظیم کن.
3. `python main.py`

ربات برای تست واقعی به اجرای Xray روی همان ماشین نیاز دارد.
