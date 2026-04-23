
import requests
import json
import time
import logging
from datetime import datetime

ANTHROPIC_API_KEY = "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"
TELEGRAM_TOKEN   = "8623822921:AAGRn6fNVa3PRkxirDnqnPFgeQAt42S_B5M"
TELEGRAM_CHAT_ID = "7278951055"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

DISCLAIMER = "\n\n⚠️ <i>التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً</i>"

trade = {
    "active": False,
    "trend": None,
    "entry": None,
    "sl": None,
    "tp1": None,
    "tp2": None,
    "tp3": None,
    "tp1_hit": False,
    "tp2_hit": False,
    "entry_hit": False,
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
    """سحب الأسعار من Yahoo Finance"""
    try:
        ranges = {"60m": "5d", "15m": "1d", "3m": "1d"}
        rng = ranges.get(interval, "1d")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={rng}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        prices = [round(p, 2) for p in closes if p is not None]
        result = prices[-count:] if len(prices) >= count else prices
        logging.info(f"[{interval}] سحب {len(result)} سعر — آخرها: {result[-1]}")
        return result
    except Exception as e:
        logging.error(f"خطأ سحب [{interval}]: {e}")
        return None


def analyze_with_claude(h1_prices, m15_prices, current_price):
    """Claude يحلل بناءً على H1 للاتجاه و M15 للمستويات"""
    system = """أنت نظام تداول رقمي متخصص في الذهب XAUUSD تطبق فقط منهج استراتيجية التوازن المفقود.

لديك فريمين:
- H1: لتحديد الاتجاه العام والـ Pivot الرئيسي
- M15: لرسم المستويات الرقمية

الخطوات الإلزامية:
1. من H1: حدد الاتجاه العام (صاعد/هابط) بوضوح من بنية السوق
2. من H1: اختر الـ Pivot — آخر قمة واضحة في الهابط، أو آخر قاع واضح في الصاعد
3. Core Code: أول 4 أرقام من سعر الـ Pivot بدون فاصلة، اجمعها حتى رقم واحد 1-9
4. العائلة: 1او4او7=12 | 2او5او8=15 | 3او6او9=18
5. Step = قيمة العائلة مباشرة (الذهب 4 خانات)
6. ابنِ 4 مستويات من الـ Pivot صعوداً أو هبوطاً
7. Entry=L1، SL=Pivot، TP1=L2، TP2=L3، TP3=L4

قاعدة مهمة: الصفقات مع الاتجاه فقط — هابط=بيع، صاعد=شراء

أجب فقط بـ JSON بدون أي نص إضافي:
{"trend":"هابط","pivot_type":"Peak","pivot_price":0,"core_code":0,"family":0,"step":0,"level1":0,"level2":0,"level3":0,"level4":0,"entry":0,"sl":0,"tp1":0,"tp2":0,"tp3":0,"note":""}"""

    h1_str = "\n".join([str(p) for p in h1_prices])
    m15_str = "\n".join([str(p) for p in m15_prices])

    user_msg = f"""بيانات الذهب XAUUSD:

[H1 - لتحديد الاتجاه والـ Pivot]:
{h1_str}

[M15 - للمستويات]:
{m15_str}

السعر الحالي: {current_price}

حلل وأعطني JSON فقط."""

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


def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=15
        )
    except Exception as e:
        logging.error(f"خطأ تيليجرام: {e}")


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
    send_telegram(msg)


def check_trade(current_price):
    global trade
    if not trade["active"]:
        return

    trend = trade["trend"]

    # تحقق الدخول
    if not trade["entry_hit"]:
        if (trend == "هابط" and current_price <= trade["entry"]) or \
           (trend == "صاعد" and current_price >= trade["entry"]):
            trade["entry_hit"] = True
            direction = "🔴 بيع" if trend == "هابط" else "🟢 شراء"
            send_telegram(f"""🚨 <b>تفعّلت الصفقة</b>
{direction} — دخول عند <b>{trade['entry']}</b>
💰 السعر الحالي: {current_price}

🛑 وقف الخسارة: <b>{trade['sl']}</b>
✅ الهدف الأول: <b>{trade['tp1']}</b>{DISCLAIMER}""")
        return

    # تحقق SL
    if (trend == "هابط" and current_price >= trade["sl"]) or \
       (trend == "صاعد" and current_price <= trade["sl"]):
        send_telegram(f"""🛑 <b>ضُرب وقف الخسارة</b>
💰 السعر: {current_price}

🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
        reset_trade()
        return

    # تحقق TP1
    if not trade["tp1_hit"]:
        if (trend == "هابط" and current_price <= trade["tp1"]) or \
           (trend == "صاعد" and current_price >= trade["tp1"]):
            trade["tp1_hit"] = True
            send_telegram(f"""✅ <b>تحقق TP1</b>
💰 السعر: {current_price}

📌 <b>انقل وقف الخسارة لنقطة الدخول: {trade['entry']}</b>
⏳ انتظار TP2: {trade['tp2']}{DISCLAIMER}""")
        return

    # تحقق TP2
    if not trade["tp2_hit"]:
        if (trend == "هابط" and current_price <= trade["tp2"]) or \
           (trend == "صاعد" and current_price >= trade["tp2"]):
            trade["tp2_hit"] = True
            send_telegram(f"""✅✅ <b>تحقق TP2</b>
💰 السعر: {current_price}

📌 <b>انقل وقف الخسارة لـ TP1: {trade['tp1']}</b>
⏳ انتظار TP3: {trade['tp3']}{DISCLAIMER}""")
        return

    # تحقق TP3
    if (trend == "هابط" and current_price <= trade["tp3"]) or \
       (trend == "صاعد" and current_price >= trade["tp3"]):
        send_telegram(f"""🎯 <b>تحققت الصفقة كاملة</b>
💰 السعر: {current_price}

🏆 <b>الصفقة ناجحة بالكامل</b>
🔍 <b>جاري البحث عن صفقة جديدة...</b>{DISCLAIMER}""")
        reset_trade()


def run():
    global trade
    logging.info("البوت بدأ")
    send_telegram("🤖 <b>بوت الذهب شغّال</b> — يراقب XAUUSD\nالفريم: H1 للاتجاه | M15 للمستويات | M3 للدخول")

    analysis_counter = 0

    while True:
        try:
            # سحب أسعار M3 للمراقبة اللحظية
            m3_prices = get_prices("3m", 10)
            if not m3_prices:
                time.sleep(60)
                continue

            current_price = m3_prices[-1]

            # تحقق من الصفقة الحالية كل دقيقة
            if trade["active"]:
                check_trade(current_price)

            # تحليل جديد كل 15 دقيقة
            analysis_counter += 1
            if analysis_counter >= 15:
                analysis_counter = 0

                h1_prices = get_prices("60m", 50)
                m15_prices = get_prices("15m", 30)

                if h1_prices and m15_prices:
                    result = analyze_with_claude(h1_prices, m15_prices, current_price)

                    if result:
                        new_trend = result["trend"]

                        # تغير الاتجاه
                        if trade["active"] and new_trend != trade["trend"]:
                            send_telegram(f"""🔄 <b>تغيّر الاتجاه</b>
الاتجاه الجديد: {new_trend}

❌ <b>الصفقة القديمة ملغاة</b>
🔍 <b>تحليل جديد...</b>{DISCLAIMER}""")
                            reset_trade()

                        # صفقة جديدة
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