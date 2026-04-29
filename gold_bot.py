import requests
import json
import time
import logging
from datetime import datetime

# ========================================
ANTHROPIC_API_KEY = "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"
TELEGRAM_TOKEN   = "8623822921:AAGRn6fNVa3PRkxirDnqnPFgeQAt42S_B5M"
TELEGRAM_CHAT_ID = "7278951055"
CHECK_INTERVAL   = 180  # كل 3 دقائق
# ========================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

SYSTEM_PROMPT = """أنت نظام تداول رقمي متخصص في الذهب XAUUSD تطبق حرفياً منهج "استراتيجية التوازن المفقود".

== القواعد الإلزامية ==

1. تحديد الاتجاه من بيانات 1H:
   - صاعد: قمم أعلى وقيعان أعلى
   - هابط: قمم أقل وقيعان أقل
   - إذا الاتجاه غير واضح → status = "No Trade"

2. اختيار Pivot من بيانات 1H:
   - صاعد: آخر قاع واضح وليس ذبذبة صغيرة
   - هابط: آخر قمة واضحة وليست ذبذبة صغيرة
   - إذا الـ Pivot غير واضح → status = "No Trade"

3. Core Code:
   - خذ أول 4 أرقام من سعر Pivot بدون فاصلة عشرية
   - اجمعها حتى تصل لرقم واحد من 1 إلى 9
   - مثال: 4607 → 4+6+0+7=17 → 1+7=8

4. العائلة:
   - 1 أو 4 أو 7 → 12
   - 2 أو 5 أو 8 → 15
   - 3 أو 6 أو 9 → 18

5. Step = قيمة العائلة مباشرة (12 أو 15 أو 18)

6. المستويات: 4 مستويات بإضافة أو طرح Step من Pivot

7. فحص الكسر + إعادة الاختبار من بيانات 3M:
   - الكسر: تجاوز السعر للمستوى بإغلاق شمعة كاملة فوقه أو تحته
   - إعادة الاختبار: عودة السعر للمستوى بعد الكسر
   - إذا تحقق الشرطان → status = "Retest Confirmed" ← هذا هو إشعار الدخول
   - إذا تحقق الكسر فقط → status = "Breakout"
   - إذا لم يتحقق شيء → status = "Waiting"

8. SL = المستوى السابق للمستوى المكسور
9. TP1/TP2/TP3 = المستويات التالية

== مهم جداً ==
- لا دخول بدون كسر + إعادة اختبار
- لا تستخدم أي مؤشرات
- إذا الاتجاه أو الـ Pivot غير واضح → No Trade

أجب فقط بـ JSON بدون أي نص إضافي:
{
  "trend": "صاعد / هابط / غير واضح",
  "pivot_type": "Trough / Peak",
  "pivot_price": 0,
  "core_code": 0,
  "family": 0,
  "step": 0,
  "level1": 0,
  "level2": 0,
  "level3": 0,
  "level4": 0,
  "active_level": 0,
  "entry": 0,
  "sl": 0,
  "tp1": 0,
  "tp2": 0,
  "tp3": 0,
  "status": "Waiting / Breakout / Retest Confirmed / No Trade",
  "note": "سبب القرار في جملة واحدة"
}"""


def get_prices(interval, range_):
    """سحب أسعار الذهب"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval={interval}&range={range_}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        prices = [round(p, 2) for p in closes if p is not None]
        return prices
    except Exception as e:
        logging.error(f"خطأ سحب {interval}: {e}")
        return None


def analyze_with_claude(prices_1h, prices_3m):
    """إرسال البيانات لـ Claude للتحليل"""
    try:
        p1h = "\n".join([str(p) for p in prices_1h[-30:]])
        p3m = "\n".join([str(p) for p in prices_3m[-20:]])
        current = prices_3m[-1]

        user_msg = f"""بيانات الذهب XAUUSD:

== بيانات 1H (للتحليل والـ Pivot) - من الأقدم للأحدث ==
{p1h}

== بيانات 3M (للكسر وإعادة الاختبار) - من الأقدم للأحدث ==
{p3m}

السعر الحالي: {current}

حلل البيانات وأعطني JSON فقط."""

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 800,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}]
            },
            timeout=40
        )

        logging.info(f"Claude status: {r.status_code}")

        if r.status_code != 200:
            logging.error(f"Claude error: {r.text[:300]}")
            return None

        raw = r.json()["content"][0]["text"]
        logging.info(f"Claude: {raw[:300]}")
        clean = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

    except Exception as e:
        logging.error(f"خطأ تحليل: {e}")
        return None


def send_telegram(msg):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=15
        )
        logging.info(f"Telegram: {r.status_code}")
    except Exception as e:
        logging.error(f"خطأ تيليجرام: {e}")


def format_message(p, current_price):
    trend_emoji = "📈" if p["trend"] == "صاعد" else "📉" if p["trend"] == "هابط" else "➡️"
    status_map = {
        "Waiting": "⏳ انتظار الكسر",
        "Breakout": "🚨 كسر — انتظار إعادة الاختبار",
        "Retest Confirmed": "✅ تأكد الدخول — ادخل الصفقة",
        "No Trade": "🚫 لا صفقة الآن"
    }
    status_text = status_map.get(p.get("status", ""), "⏳ انتظار")

    # رسالة الدخول إذا تأكد الريتست
    alert = ""
    if p.get("status") == "Retest Confirmed":
        alert = "\n\n🔔 <b>تنبيه دخول — شرط الكسر + إعادة الاختبار تحقق!</b>"

    return f"""🥇 <b>تحليل الذهب XAUUSD</b>
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}

{trend_emoji} <b>الاتجاه:</b> {p['trend']}
📌 <b>Pivot ({p.get('pivot_type','')}):</b> {p.get('pivot_price',0)}
🔢 Core: {p.get('core_code',0)} | Family: {p.get('family',0)} | Step: {p.get('step',0)}

📊 <b>المستويات:</b>
  L1: {p.get('level1',0)}
  L2: {p.get('level2',0)}
  L3: {p.get('level3',0)}
  L4: {p.get('level4',0)}

🎯 <b>الصفقة:</b>
  دخول: <b>{p.get('entry',0)}</b>
  🛑 SL: <b>{p.get('sl',0)}</b>
  ✅ TP1: <b>{p.get('tp1',0)}</b>
  ✅ TP2: <b>{p.get('tp2',0)}</b>
  ✅ TP3: <b>{p.get('tp3',0)}</b>

📋 <b>الحالة:</b> {status_text}
💡 {p.get('note','')}
💰 <b>السعر الحالي:</b> {current_price}{alert}"""


last_status = None
last_pivot = None

def run():
    global last_status, last_pivot
    logging.info("البوت بدأ")
    send_telegram("🤖 <b>بوت الذهب شغّال</b>\nيراقب XAUUSD على فريمات 1H و 3M\nكل 3 دقائق")

    while True:
        try:
            # سحب البيانات من الفريمين
            prices_1h = get_prices("1h", "1mo")
            prices_3m = get_prices("3m", "5d")

            if not prices_1h or not prices_3m:
                logging.warning("فشل سحب البيانات")
                time.sleep(60)
                continue

            current_price = prices_3m[-1]
            logging.info(f"السعر الحالي: {current_price}")

            # التحليل
            result = analyze_with_claude(prices_1h, prices_3m)

            if not result:
                logging.warning("فشل التحليل")
                time.sleep(60)
                continue

            status = result.get("status", "")
            pivot = result.get("pivot_price", 0)

            # إرسال فوري إذا تأكد الدخول
            if status == "Retest Confirmed":
                send_telegram(format_message(result, current_price))
                logging.info("تأكد الدخول — تم الإرسال فوراً")

            # إرسال عند تغيّر الحالة أو الـ Pivot
            elif status != last_status or pivot != last_pivot:
                send_telegram(format_message(result, current_price))
                logging.info(f"تغيّر: {status} | Pivot: {pivot}")

            else:
                logging.info(f"لا تغيير — {status}")

            last_status = status
            last_pivot = pivot

        except Exception as e:
            logging.error(f"خطأ عام: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run()
