import os
import requests
import json
import time
import logging
import threading
from datetime import datetime

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN   = "8623822921:AAGRn6fNVa3PRkxirDnqnPFgeQAt42S_B5M"
ADMIN_CHAT_ID    = "7278951055"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

DISCLAIMER = "\n\n⚠️ <i>التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً</i>"

subscribers = set()
subscribers.add(ADMIN_CHAT_ID)

trade = {
    "active": False, "trend": None, "entry": None,
    "sl": None, "tp1": None, "tp2": None, "tp3": None,
    "tp1_hit": False, "tp2_hit": False, "entry_hit": False,
    "pivot": None,
}


def reset_trade():
    global trade
    trade = {
        "active": False, "trend": None, "entry": None,
        "sl": None, "tp1": None, "tp2": None, "tp3": None,
        "tp1_hit": False, "tp2_hit": False, "entry_hit": False,
        "pivot": None,
    }


def get_prices(interval="60m", count=50):
    try:
        ranges = {"60m": "5d", "15m": "1d", "3m": "1d", "5m": "1d"}
        rng = ranges.get(interval, "1d")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={rng}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        result_data = data["chart"]["result"]
        if not result_data:
            return None
        closes = result_data[0]["indicators"]["quote"][0]["close"]
        prices = [round(p, 2) for p in closes if p is not None]
        if len(prices) < 5:
            return None
        result = prices[-count:] if len(prices) >= count else prices
        logging.info(f"[{interval}] {len(result)} سعر — آخرها: {result[-1]}")
        return result
    except Exception as e:
        logging.error(f"خطأ سحب [{interval}]: {e}")
        return None


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

أجب فقط بـ JSON:
{"trend":"هابط","pivot_type":"Peak","pivot_price":0,"core_code":0,"family":0,"step":0,"level1":0,"level2":0,"level3":0,"level4":0,"entry":0,"sl":0,"tp1":0,"tp2":0,"tp3":0,"note":""}"""

    user_msg = f"""[H1]:\n{chr(10).join([str(p) for p in h1_prices])}\n\n[M15]:\n{chr(10).join([str(p) for p in m15_prices])}\n\nالسعر الحالي: {current_price}\n\nJSON فقط."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,
                "system": system,
                "messages": [{"role": "user", "content": user_msg}]
            },
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
        logging.error(f"خطأ إرسال {chat_id}: {e}")


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


def check_trade(current_price):
    global trade
    if not trade["active"]:
        return
    trend = trade["trend"]

    if not trade["entry_hit"]:
        if (trend == "هابط" and current_price <= trade["entry"]) or \
           (trend == "صاعد" and current_price >= trade["entry"]):
            trade["entry_hit"] = True
            direction = "🔴 بيع" if trend == "هابط" else "🟢 شراء"
            send_to_all(f"""🚨 <b>تفعّلت الصفقة</b>
{direction} — دخول عند <b>{trade['entry']}</b>
💰 السعر الحالي: {current_price}

🛑 وقف الخسارة: <b>{trade['sl']}</b>
✅ الهدف الأول: <b>{trade['tp1']}</b>{DISCLAIMER}""")
        return

    if (trend == "هابط" and current_price >= trade["sl"]) or \
       (trend == "صاعد" and current_price <= trade["sl"]):
        send_to_all(f"""🛑 <b>ضُرب وقف الخسارة</b>
💰 السعر: {current_price}

🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
        reset_trade()
        return

    if not trade["tp1_hit"]:
        if (trend == "هابط" and current_price <= trade["tp1"]) or \
           (trend == "صاعد" and current_price >= trade["tp1"]):
            trade["tp1_hit"] = True
            send_to_all(f"""✅ <b>تحقق TP1</b>
💰 السعر: {current_price}

📌 <b>انقل وقف الخسارة لنقطة الدخول: {trade['entry']}</b>
⏳ انتظار TP2: {trade['tp2']}{DISCLAIMER}""")
        return

    if not trade["tp2_hit"]:
        if (trend == "هابط" and current_price <= trade["tp2"]) or \
           (trend == "صاعد" and current_price >= trade["tp2"]):
            trade["tp2_hit"] = True
            send_to_all(f"""✅✅ <b>تحقق TP2</b>
💰 السعر: {current_price}

📌 <b>انقل وقف الخسارة لـ TP1: {trade['tp1']}</b>
⏳ انتظار TP3: {trade['tp3']}{DISCLAIMER}""")
        return

    if (trend == "هابط" and current_price <= trade["tp3"]) or \
       (trend == "صاعد" and current_price >= trade["tp3"]):
        send_to_all(f"""🎯 <b>تحققت الصفقة كاملة</b>
💰 السعر: {current_price}

🏆 <b>الصفقة ناجحة بالكامل</b>
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
        reset_trade()


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
                        logging.info(f"مشترك جديد: {chat_id} ({first_name})")
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
                        send_to_one(chat_id, "تم إلغاء اشتراكك. يمكنك العودة بـ /start")

                elif text == "/count" and chat_id == ADMIN_CHAT_ID:
                    send_to_one(ADMIN_CHAT_ID, f"👥 عدد المشتركين: {len(subscribers)}")

        except Exception as e:
            logging.error(f"خطأ updates: {e}")
        time.sleep(2)


def run():
    global trade
    logging.info("البوت بدأ")

    t = threading.Thread(target=handle_updates, daemon=True)
    t.start()

    send_to_all("🤖 <b>بوت الذهب شغّال</b> — يراقب XAUUSD\nالفريم: H1 للاتجاه | M15 للمستويات")

    analysis_counter = 0

    while True:
        try:
            m5_prices = get_prices("5m", 10)
            if not m5_prices:
                time.sleep(60)
                continue

            current_price = m5_prices[-1]

            if trade["active"]:
                check_trade(current_price)

            analysis_counter += 1
            if analysis_counter >= 15:
                analysis_counter = 0

                h1_prices = get_prices("60m", 50)
                m15_prices = get_prices("15m", 30)

                if h1_prices and m15_prices:
                    result = analyze_with_claude(h1_prices, m15_prices, current_price)

                    if result:
                        if trade["active"] and result["trend"] != trade["trend"]:
                            send_to_all(f"""🔄 <b>تغيّر الاتجاه</b>
الاتجاه الجديد: {result['trend']}

❌ <b>الصفقة القديمة ملغاة</b>
🔍 <b>تحليل جديد...</b>{DISCLAIMER}""")
                            reset_trade()

                        if not trade["active"]:
                            trade["active"] = True
                            trade["trend"] = result["trend"]
                            trade["entry"] = result["entry"]
                            trade["sl"] = result["sl"]
                            trade["tp1"] = result["tp1"]
                            trade["tp2"] = result["tp2"]
                            trade["tp3"] = result["tp3"]
                            trade["pivot"] = result["pivot_price"]
                            send_new_trade(result, current_price)

        except Exception as e:
            logging.error(f"خطأ عام: {e}")

        time.sleep(60)


if __name__ == "__main__":
    run()
