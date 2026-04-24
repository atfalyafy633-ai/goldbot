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

DISCLAIMER = "\n\n⚠️ التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً"

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
# phase: waiting / broken / retest / active
trade = {
    "phase": "waiting",
    "trend": None, "entry": None,
    "sl": None, "tp1": None, "tp2": None, "tp3": None,
    "tp1_hit": False, "tp2_hit": False,
    "pivot": None, "last_pivot": None,
    "break_price": None,
    "next_zone": None,    # المنطقة القادمة
    "next_dir": None,     # اتجاه المنطقة القادمة
    "next_sl": None,
    "next_tp1": None, "next_tp2": None, "next_tp3": None,
    "next_alerted": False,  # هل أرسلنا تنبيه اقتراب
}

def reset_trade():
    global trade
    trade = {
        "phase": "waiting",
        "trend": None, "entry": None,
        "sl": None, "tp1": None, "tp2": None, "tp3": None,
        "tp1_hit": False, "tp2_hit": False,
        "pivot": None, "last_pivot": trade.get("pivot"),
        "break_price": None,
        "next_zone": None, "next_dir": None,
        "next_sl": None,
        "next_tp1": None, "next_tp2": None, "next_tp3": None,
        "next_alerted": False,
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
6. ابنِ 4 مستويات — المستوى التالي بعد TP3 هو المنطقة القادمة
7. Entry=L1، SL=Pivot، TP1=L2، TP2=L3، TP3=L4
8. المنطقة القادمة = L4 + Step (في الهابط) أو L4 - Step (في الصاعد) — وهي منطقة الصفقة الثانية بالاتجاه المعاكس
9. هابط=بيع، صاعد=شراء

أجب فقط بـ JSON:
{
  "trend": "هابط",
  "pivot_type": "Peak",
  "pivot_price": 0,
  "core_code": 0,
  "family": 0,
  "step": 0,
  "level1": 0,
  "level2": 0,
  "level3": 0,
  "level4": 0,
  "entry": 0,
  "sl": 0,
  "tp1": 0,
  "tp2": 0,
  "tp3": 0,
  "next_zone": 0,
  "next_dir": "شراء",
  "next_sl": 0,
  "next_tp1": 0,
  "next_tp2": 0,
  "next_tp3": 0,
  "note": ""
}"""

    user_msg = f"""[H1]:\n{chr(10).join([str(p) for p in h1_prices])}\n\n[M15]:\n{chr(10).join([str(p) for p in m15_prices])}\n\nالسعر الحالي: {current_price}\n\nJSON فقط."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 800, "system": system, "messages": [{"role": "user", "content": user_msg}]},
            timeout=45
        )
        if r.status_code != 200:
            logging.error(f"Claude error: {r.text[:200]}")
            return None
        raw = r.json()["content"][0]["text"]
        clean = raw.replace("```json","").replace("```","").strip()
        result = json.loads(clean)
        logging.info(f"Claude: {result['trend']} | Entry: {result['entry']} | Next: {result.get('next_zone')}")
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

# ======= نماذج الرسائل =======
def send_new_trade(p, current_price):
    direction = "🔴 بيع" if p["trend"] == "هابط" else "🟢 شراء"
    trend_emoji = "📉" if p["trend"] == "هابط" else "📈"
    next_zone = p.get("next_zone")
    next_dir = p.get("next_dir", "")
    next_emoji = "🟢" if next_dir == "شراء" else "🔴"

    if next_zone and next_zone != 0:
        next_line = f"\n\n👀 <b>المنطقة القادمة:</b> {next_zone}\n{next_emoji} نفكر في {next_dir} منها عند وصول السعر"
    else:
        next_line = "\n\n👀 لا توجد منطقة قادمة حالياً — نراقب السوق"

    msg = f"""🥇 <b>الذهب XAUUSD</b>
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}

{trend_emoji} <b>الاتجاه:</b> {p['trend']}

{direction} — ضع أمر معلق عند: <b>{p['entry']}</b>
🛑 SL: <b>{p['sl']}</b>
✅ TP1: <b>{p['tp1']}</b>
✅ TP2: <b>{p['tp2']}</b>
✅ TP3: <b>{p['tp3']}</b>

⏳ <b>الحالة:</b> انتظار التفعيل
💰 <b>السعر الحالي:</b> {current_price}{next_line}{DISCLAIMER}"""
    send_to_all(msg)


def send_activated(current_price):
    direction = "🔴 بيع" if trade["trend"] == "هابط" else "🟢 شراء"
    next_zone = trade.get("next_zone")
    next_dir = trade.get("next_dir", "")
    next_emoji = "🟢" if next_dir == "شراء" else "🔴"

    if next_zone and next_zone != 0:
        next_line = f"\n\n👀 <b>المنطقة القادمة:</b> {next_zone}\n{next_emoji} نفكر في {next_dir} منها عند وصول السعر"
    else:
        next_line = "\n\n👀 لا توجد منطقة قادمة حالياً — نراقب السوق"

    msg = f"""🚨 <b>تفعّلت صفقة {direction} عند {trade['entry']}</b>
💰 السعر الحالي: {current_price}

🛑 SL: <b>{trade['sl']}</b>
✅ TP1: <b>{trade['tp1']}</b>
✅ TP2: <b>{trade['tp2']}</b>
✅ TP3: <b>{trade['tp3']}</b>{next_line}{DISCLAIMER}"""
    send_to_all(msg)


# ======= متابعة الصفقة =======
RETEST_TOLERANCE = 3

def check_trade(current_price):
    global trade
    if trade["phase"] == "waiting":
        return

    trend = trade["trend"]
    entry = trade["entry"]

    # ===== انتظار الكسر =====
    if trade["phase"] == "broken":
        if trend == "هابط":
            if trade["break_price"] is None or current_price > trade["break_price"]:
                trade["break_price"] = current_price
            if current_price >= entry - RETEST_TOLERANCE:
                trade["phase"] = "retest"
                logging.info(f"Retest عند {current_price}")
        else:
            if trade["break_price"] is None or current_price < trade["break_price"]:
                trade["break_price"] = current_price
            if current_price <= entry + RETEST_TOLERANCE:
                trade["phase"] = "retest"
                logging.info(f"Retest عند {current_price}")
        return

    # ===== تأكيد الـ Retest =====
    if trade["phase"] == "retest":
        if trend == "هابط":
            if current_price < entry - RETEST_TOLERANCE:
                trade["phase"] = "active"
                send_activated(current_price)
            elif current_price >= trade["sl"]:
                send_to_all(f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade()
        else:
            if current_price > entry + RETEST_TOLERANCE:
                trade["phase"] = "active"
                send_activated(current_price)
            elif current_price <= trade["sl"]:
                send_to_all(f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade()
        return

    # ===== الصفقة نشطة =====
    if trade["phase"] == "active":

        # تنبيه اقتراب المنطقة القادمة
        next_zone = trade.get("next_zone")
        next_dir = trade.get("next_dir")
        if next_zone and not trade["next_alerted"]:
            distance = abs(current_price - next_zone)
            if distance <= 5:
                trade["next_alerted"] = True
                next_emoji = "🟢" if next_dir == "شراء" else "🔴"
                send_to_all(f"""👀 <b>السعر يقترب من منطقة {next_dir} {next_zone}</b>
💰 السعر الحالي: {current_price}
⏳ انتظار التفعيل""")

        # تحقق SL
        if (trend == "هابط" and current_price >= trade["sl"]) or \
           (trend == "صاعد" and current_price <= trade["sl"]):
            send_to_all(f"""🛑 <b>ضُرب وقف الخسارة</b>
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            reset_trade()
            return

        # تحقق TP1
        if not trade["tp1_hit"]:
            if (trend == "هابط" and current_price <= trade["tp1"]) or \
               (trend == "صاعد" and current_price >= trade["tp1"]):
                trade["tp1_hit"] = True
                send_to_all(f"""✅ <b>تحقق الهدف الأول {trade['tp1']}</b>
💰 السعر: {current_price}
⏳ الهدف الثاني: {trade['tp2']}""")
            return

        # تحقق TP2
        if not trade["tp2_hit"]:
            if (trend == "هابط" and current_price <= trade["tp2"]) or \
               (trend == "صاعد" and current_price >= trade["tp2"]):
                trade["tp2_hit"] = True
                send_to_all(f"""✅✅ <b>تحقق الهدف الثاني {trade['tp2']}</b>
💰 السعر: {current_price}
⏳ الهدف الثالث: {trade['tp3']}""")
            return

        # تحقق TP3
        if (trend == "هابط" and current_price <= trade["tp3"]) or \
           (trend == "صاعد" and current_price >= trade["tp3"]):
            send_to_all(f"""🎯 <b>تحقق الهدف الثالث — الصفقة اكتملت</b>
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            reset_trade()


# ======= انتظار الكسر =======
def check_break(current_price):
    global trade
    if trade["phase"] != "waiting" or not trade["trend"]:
        return

    trend = trade["trend"]
    entry = trade["entry"]

    if trend == "هابط" and current_price < entry:
        trade["phase"] = "broken"
        trade["break_price"] = current_price
        logging.info(f"كسر للأسفل عند {current_price}")
    elif trend == "صاعد" and current_price > entry:
        trade["phase"] = "broken"
        trade["break_price"] = current_price
        logging.info(f"كسر للأعلى عند {current_price}")


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

⚠️ التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً""")
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

            # متابعة الصفقة الحالية
            if trade["phase"] == "waiting" and trade["trend"]:
                check_break(current_price)
            elif trade["phase"] in ["broken", "retest", "active"]:
                check_trade(current_price)

            # تحليل جديد فقط لما ما في صفقة نشطة
            if trade["phase"] == "waiting":
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

                            if new_pivot != last_pivot:
                                trade["trend"]       = result["trend"]
                                trade["entry"]       = result["entry"]
                                trade["sl"]          = result["sl"]
                                trade["tp1"]         = result["tp1"]
                                trade["tp2"]         = result["tp2"]
                                trade["tp3"]         = result["tp3"]
                                trade["pivot"]       = new_pivot
                                trade["last_pivot"]  = new_pivot
                                trade["next_zone"]   = result.get("next_zone")
                                trade["next_dir"]    = result.get("next_dir")
                                trade["next_sl"]     = result.get("next_sl")
                                trade["next_tp1"]    = result.get("next_tp1")
                                trade["next_tp2"]    = result.get("next_tp2")
                                trade["next_tp3"]    = result.get("next_tp3")
                                trade["next_alerted"] = False
                                send_new_trade(result, current_price)
                            else:
                                logging.info(f"نفس الـ Pivot ({new_pivot}) — انتظار")
            else:
                analysis_counter = 0  # أوقف العداد لما في صفقة

        except Exception as e:
            logging.error(f"خطأ عام: {e}")

        time.sleep(60)


if __name__ == "__main__":
    run()
