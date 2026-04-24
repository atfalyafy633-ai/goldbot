import os
import requests
import json
import time
import logging
import threading
from datetime import datetime

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TWELVE_API_KEY    = os.environ.get("TWELVE_API_KEY", "")
TELEGRAM_TOKEN    = "8623822921:AAGRn6fNVa3PRkxirDnqnPFgeQAt42S_B5M"
ADMIN_CHAT_ID     = "7278951055"
SUBSCRIBERS_FILE  = "/data/subscribers.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
DISCLAIMER = "\n\n⚠️ <i>التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً</i>"

# ======= المشتركين =======
def load_subscribers():
    try:
        os.makedirs("/data", exist_ok=True)
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r") as f:
                subs = set(json.load(f))
                subs.add(ADMIN_CHAT_ID)
                return subs
    except:
        pass
    return {ADMIN_CHAT_ID}

def save_subscribers(subs):
    try:
        os.makedirs("/data", exist_ok=True)
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(list(subs), f)
    except Exception as e:
        logging.error(f"خطأ حفظ المشتركين: {e}")

subscribers = load_subscribers()

# ======= الصفقة =======
# مراحل الدخول:
# "waiting"  = انتظار الكسر
# "broken"   = تم الكسر، انتظار الـ Retest
# "retest"   = تم الـ Retest، انتظار التأكيد
# "active"   = دخلنا الصفقة

trade = {
    "phase": "waiting",   # waiting / broken / retest / active
    "trend": None,
    "entry": None,
    "sl": None,
    "tp1": None, "tp2": None, "tp3": None,
    "tp1_hit": False, "tp2_hit": False,
    "pivot": None, "last_pivot": None,
    "break_price": None,   # أعلى/أدنى سعر بعد الكسر
}

def reset_trade():
    global trade
    last_pivot = trade.get("pivot")
    trade = {
        "phase": "waiting",
        "trend": None, "entry": None,
        "sl": None, "tp1": None, "tp2": None, "tp3": None,
        "tp1_hit": False, "tp2_hit": False,
        "pivot": None, "last_pivot": last_pivot,
        "break_price": None,
    }

# ======= الأسعار =======
def get_prices(interval="1h", count=50):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": "XAU/USD", "interval": interval, "outputsize": count, "apikey": TWELVE_API_KEY}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "error":
            logging.error(f"Twelve error: {data.get('message')}")
            return None
        values = data.get("values", [])
        if not values:
            return None
        prices = [round(float(v["close"]), 2) for v in reversed(values)]
        logging.info(f"[{interval}] {len(prices)} سعر — آخرها: {prices[-1]}")
        return prices
    except Exception as e:
        logging.error(f"خطأ سحب [{interval}]: {e}")
        return None

def get_current_price():
    try:
        url = "https://api.twelvedata.com/price"
        params = {"symbol": "XAU/USD", "apikey": TWELVE_API_KEY}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        price = round(float(data["price"]), 2)
        logging.info(f"السعر الحالي: {price}")
        return price
    except Exception as e:
        logging.error(f"خطأ سحب السعر: {e}")
        return None

# ======= التحليل =======
def analyze_with_claude(h1_prices, m15_prices, current_price):
    system = """أنت نظام تداول رقمي متخصص في الذهب XAUUSD تطبق فقط منهج استراتيجية التوازن المفقود.

لديك فريمين:
- H1: لتحديد الاتجاه العام والـ Pivot الرئيسي
- M15: لرسم المستويات الرقمية

الخطوات:
1. من H1: حدد الاتجاه العام (صاعد/هابط)
2. من H1: اختر الـ Pivot — آخر قمة في الهابط، آخر قاع في الصاعد
3. Core Code: أول 4 أرقام من Pivot بدون فاصلة، اجمعها حتى رقم 1-9
4. العائلة: 1او4او7=12 | 2او5او8=15 | 3او6او9=18
5. Step = قيمة العائلة
6. 4 مستويات صعوداً أو هبوطاً
7. Entry=L1، SL=Pivot، TP1=L2، TP2=L3، TP3=L4
8. هابط=بيع، صاعد=شراء

مهم: اختر Pivot جديد يعكس الوضع الحالي للسوق.

أجب فقط بـ JSON:
{"trend":"هابط","pivot_type":"Peak","pivot_price":0,"core_code":0,"family":0,"step":0,"level1":0,"level2":0,"level3":0,"level4":0,"entry":0,"sl":0,"tp1":0,"tp2":0,"tp3":0,"note":""}"""

    user_msg = f"""[H1]:\n{chr(10).join([str(p) for p in h1_prices])}\n\n[M15]:\n{chr(10).join([str(p) for p in m15_prices])}\n\nالسعر الحالي: {current_price}\n\nJSON فقط."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 600, "system": system, "messages": [{"role": "user", "content": user_msg}]},
            timeout=45
        )
        if r.status_code != 200:
            logging.error(f"Claude error: {r.text[:200]}")
            return None
        raw = r.json()["content"][0]["text"]
        clean = raw.replace("```json","").replace("```","").strip()
        result = json.loads(clean)
        logging.info(f"Claude: {result['trend']} | Pivot: {result['pivot_price']} | Entry: {result['entry']}")
        return result
    except Exception as e:
        logging.error(f"خطأ تحليل: {e}")
        return None

# ======= الإرسال =======
def send_to_all(msg):
    for chat_id in list(subscribers):
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=15
            )
        except Exception as e:
            logging.error(f"خطأ إرسال {chat_id}: {e}")

def send_to_one(chat_id, msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=15
        )
    except Exception as e:
        logging.error(f"خطأ إرسال: {e}")

def send_new_trade(p, current_price):
    direction = "🔴 بيع" if p["trend"] == "هابط" else "🟢 شراء"
    trend_emoji = "📉" if p["trend"] == "هابط" else "📈"
    msg = f"""🥇 <b>تحليل الذهب XAUUSD</b>
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}

{trend_emoji} <b>الاتجاه:</b> {p['trend']}
📌 <b>Pivot ({p['pivot_type']}):</b> {p['pivot_price']}

📊 <b>المستويات:</b>
L1: {p['level1']} | L2: {p['level2']}
L3: {p['level3']} | L4: {p['level4']}

🎯 <b>الصفقة:</b>
{direction} عند: <b>{p['entry']}</b>
🛑 SL: <b>{p['sl']}</b>
✅ TP1: <b>{p['tp1']}</b>
✅ TP2: <b>{p['tp2']}</b>
✅ TP3: <b>{p['tp3']}</b>

⏳ <b>الحالة:</b> انتظار Break + Retest
💰 <b>السعر الحالي:</b> {current_price}{DISCLAIMER}"""
    send_to_all(msg)

# ======= متابعة الصفقة - Break + Retest الصحيح =======
def check_trade(current_price):
    global trade
    if trade["phase"] == "waiting":
        return

    trend   = trade["trend"]
    entry   = trade["entry"]
    retest_tolerance = 3  # نقاط تسامح للـ Retest

    # ===== مرحلة: انتظار الكسر =====
    if trade["phase"] == "broken":
        if trend == "هابط":
            # بعد الكسر للأسفل، نتابع أعلى سعر (للـ Retest)
            if trade["break_price"] is None or current_price > trade["break_price"]:
                trade["break_price"] = current_price

            # الـ Retest: السعر ارتد للأعلى ووصل قرب مستوى الدخول
            if current_price >= entry - retest_tolerance:
                trade["phase"] = "retest"
                logging.info(f"Retest تم عند {current_price}")
                send_to_all(f"""🔄 <b>Retest عند مستوى الدخول</b>
💰 السعر: {current_price}
📍 مستوى الدخول: {entry}

⏳ <b>انتظار تأكيد الاستمرار للأسفل...</b>{DISCLAIMER}""")

        else:  # صاعد
            # بعد الكسر للأعلى، نتابع أدنى سعر (للـ Retest)
            if trade["break_price"] is None or current_price < trade["break_price"]:
                trade["break_price"] = current_price

            # الـ Retest: السعر نزل ووصل قرب مستوى الدخول
            if current_price <= entry + retest_tolerance:
                trade["phase"] = "retest"
                logging.info(f"Retest تم عند {current_price}")
                send_to_all(f"""🔄 <b>Retest عند مستوى الدخول</b>
💰 السعر: {current_price}
📍 مستوى الدخول: {entry}

⏳ <b>انتظار تأكيد الاستمرار للأعلى...</b>{DISCLAIMER}""")
        return

    # ===== مرحلة: تأكيد بعد الـ Retest =====
    if trade["phase"] == "retest":
        if trend == "هابط":
            # تأكيد: السعر عاد للنزول تحت الدخول
            if current_price < entry - retest_tolerance:
                trade["phase"] = "active"
                send_to_all(f"""🚨 <b>تفعّلت الصفقة</b>
🔴 بيع — دخول عند <b>{entry}</b>
💰 السعر الحالي: {current_price}

🛑 وقف الخسارة: <b>{trade['sl']}</b>
✅ الهدف الأول: <b>{trade['tp1']}</b>{DISCLAIMER}""")
            # إذا السعر تجاوز الـ SL — ألغِ
            elif current_price >= trade["sl"]:
                send_to_all(f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
💰 السعر: {current_price}
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
                reset_trade()
        else:  # صاعد
            # تأكيد: السعر عاد للصعود فوق الدخول
            if current_price > entry + retest_tolerance:
                trade["phase"] = "active"
                send_to_all(f"""🚨 <b>تفعّلت الصفقة</b>
🟢 شراء — دخول عند <b>{entry}</b>
💰 السعر الحالي: {current_price}

🛑 وقف الخسارة: <b>{trade['sl']}</b>
✅ الهدف الأول: <b>{trade['tp1']}</b>{DISCLAIMER}""")
            # إذا السعر تجاوز الـ SL — ألغِ
            elif current_price <= trade["sl"]:
                send_to_all(f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
💰 السعر: {current_price}
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
                reset_trade()
        return

    # ===== مرحلة: الصفقة نشطة =====
    if trade["phase"] == "active":
        # تحقق SL
        if (trend == "هابط" and current_price >= trade["sl"]) or \
           (trend == "صاعد" and current_price <= trade["sl"]):
            send_to_all(f"""🛑 <b>ضُرب وقف الخسارة</b>
💰 السعر: {current_price}
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
            reset_trade()
            return

        # تحقق TP1
        if not trade["tp1_hit"]:
            if (trend == "هابط" and current_price <= trade["tp1"]) or \
               (trend == "صاعد" and current_price >= trade["tp1"]):
                trade["tp1_hit"] = True
                send_to_all(f"""✅ <b>تحقق TP1</b>
💰 السعر: {current_price}
📌 <b>انقل وقف الخسارة لنقطة الدخول: {trade['entry']}</b>
⏳ انتظار TP2: {trade['tp2']}{DISCLAIMER}""")
            return

        # تحقق TP2
        if not trade["tp2_hit"]:
            if (trend == "هابط" and current_price <= trade["tp2"]) or \
               (trend == "صاعد" and current_price >= trade["tp2"]):
                trade["tp2_hit"] = True
                send_to_all(f"""✅✅ <b>تحقق TP2</b>
💰 السعر: {current_price}
📌 <b>انقل وقف الخسارة لـ TP1: {trade['tp1']}</b>
⏳ انتظار TP3: {trade['tp3']}{DISCLAIMER}""")
            return

        # تحقق TP3
        if (trend == "هابط" and current_price <= trade["tp3"]) or \
           (trend == "صاعد" and current_price >= trade["tp3"]):
            send_to_all(f"""🎯 <b>تحققت الصفقة كاملة</b>
💰 السعر: {current_price}
🏆 <b>الصفقة ناجحة بالكامل</b>
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
            reset_trade()

# ======= انتظار الكسر =======
def check_break(current_price):
    global trade
    if trade["phase"] != "waiting":
        return

    trend = trade["trend"]
    entry = trade["entry"]

    if trend == "هابط":
        # الكسر: السعر نزل تحت مستوى الدخول
        if current_price < entry:
            trade["phase"] = "broken"
            trade["break_price"] = current_price
            logging.info(f"كسر للأسفل عند {current_price} | Entry: {entry}")
    else:  # صاعد
        # الكسر: السعر طلع فوق مستوى الدخول
        if current_price > entry:
            trade["phase"] = "broken"
            trade["break_price"] = current_price
            logging.info(f"كسر للأعلى عند {current_price} | Entry: {entry}")

# ======= استقبال المشتركين =======
def handle_updates():
    offset = 0
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                first_name = msg.get("chat", {}).get("first_name", "")

                if text == "/start":
                    if chat_id not in subscribers:
                        subscribers.add(chat_id)
                        save_subscribers(subscribers)
                        send_to_one(chat_id, f"""🥇 <b>أهلاً {first_name}!</b>

تم تسجيلك في بوت تحليل الذهب XAUUSD 🎉

ستصلك تحليلات الذهب تلقائياً بمجرد توفر فرصة تداول.

⚠️ <i>التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً</i>""")
                        send_to_one(ADMIN_CHAT_ID, f"👤 مشترك جديد: {first_name} | إجمالي: {len(subscribers)}")
                    else:
                        send_to_one(chat_id, "✅ أنت مشترك بالفعل — ستصلك التحليلات تلقائياً.")

                elif text == "/stop":
                    if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                        subscribers.discard(chat_id)
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "تم إلغاء اشتراكك. يمكنك العودة بـ /start")

                elif text == "/count" and chat_id == ADMIN_CHAT_ID:
                    send_to_one(ADMIN_CHAT_ID, f"👥 عدد المشتركين: {len(subscribers)}")

        except Exception as e:
            logging.error(f"خطأ updates: {e}")
        time.sleep(2)

# ======= التشغيل الرئيسي =======
def run():
    global trade
    logging.info("البوت بدأ")

    t = threading.Thread(target=handle_updates, daemon=True)
    t.start()

    send_to_all("🤖 <b>بوت الذهب شغّال</b> — يراقب XAUUSD\nالفريم: H1 للاتجاه | M15 للمستويات")

    analysis_counter = 0

    while True:
        try:
            current_price = get_current_price()
            if not current_price:
                time.sleep(60)
                continue

            # تحقق الكسر أو متابعة الصفقة
            if trade["phase"] == "waiting" and trade["trend"]:
                check_break(current_price)
            elif trade["phase"] in ["broken", "retest", "active"]:
                check_trade(current_price)

            # تحليل جديد كل 15 دقيقة
            analysis_counter += 1
            if analysis_counter >= 15:
                analysis_counter = 0

                h1_prices  = get_prices("1h", 50)
                m15_prices = get_prices("15min", 30)

                if h1_prices and m15_prices:
                    result = analyze_with_claude(h1_prices, m15_prices, current_price)

                    if result:
                        new_pivot  = result["pivot_price"]
                        last_pivot = trade.get("last_pivot")

                        # تغير الاتجاه
                        if trade["phase"] != "waiting" and result["trend"] != trade["trend"]:
                            send_to_all(f"""🔄 <b>تغيّر الاتجاه</b>
الاتجاه الجديد: {result['trend']}
❌ <b>الصفقة القديمة ملغاة</b>
🔍 <b>تحليل جديد...</b>{DISCLAIMER}""")
                            reset_trade()

                        # صفقة جديدة فقط إذا Pivot مختلف
                        if trade["phase"] == "waiting" and new_pivot != last_pivot:
                            trade["trend"]      = result["trend"]
                            trade["entry"]      = result["entry"]
                            trade["sl"]         = result["sl"]
                            trade["tp1"]        = result["tp1"]
                            trade["tp2"]        = result["tp2"]
                            trade["tp3"]        = result["tp3"]
                            trade["pivot"]      = new_pivot
                            trade["last_pivot"] = new_pivot
                            send_new_trade(result, current_price)
                        elif trade["phase"] == "waiting" and new_pivot == last_pivot:
                            logging.info(f"نفس الـ Pivot ({new_pivot}) — انتظار")

        except Exception as e:
            logging.error(f"خطأ عام: {e}")

        time.sleep(60)

if __name__ == "__main__":
    run()
