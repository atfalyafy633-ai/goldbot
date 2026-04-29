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
DISCLAIMER = "\n\n⚠️ التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً\n📌 لا تنسى تأمين الدخول"

SYMBOLS = {
    "gold": {
        "name": "الذهب", "symbol": "XAU/USD", "display": "XAUUSD",
        "emoji": "🥇", "step_multiplier": 1, "max_skip": 50,
    },
    "btc": {
        "name": "البيتكوين", "symbol": "BTC/USD", "display": "BTCUSD",
        "emoji": "🪙", "step_multiplier": 100, "max_skip": 1500,
    },
}

# ======= المشتركين =======
def load_subscribers():
    try:
        os.makedirs("/data", exist_ok=True)
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    new_data = {cid: ["gold"] for cid in data}
                    new_data[ADMIN_CHAT_ID] = ["gold", "btc"]
                    save_subscribers(new_data)
                    return new_data
                data[ADMIN_CHAT_ID] = data.get(ADMIN_CHAT_ID, ["gold", "btc"])
                return data
    except:
        pass
    return {ADMIN_CHAT_ID: ["gold", "btc"]}

def save_subscribers(subs):
    try:
        os.makedirs("/data", exist_ok=True)
        with open(SUBSCRIBERS_FILE, "w") as f:
            json.dump(subs, f)
    except Exception as e:
        logging.error(f"خطأ حفظ المشتركين: {e}")

subscribers = load_subscribers()

# ======= حفظ وتحميل الصفقة =======
def save_trade(symbol_key, t):
    try:
        os.makedirs("/data", exist_ok=True)
        with open(f"/data/trade_{symbol_key}.json", "w") as f:
            json.dump(t, f)
    except Exception as e:
        logging.error(f"خطأ حفظ صفقة {symbol_key}: {e}")

def load_trade(symbol_key):
    try:
        path = f"/data/trade_{symbol_key}.json"
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                logging.info(f"تحميل صفقة {symbol_key}: {data.get('phase')} | {data.get('entry')}")
                return data
    except Exception as e:
        logging.error(f"خطأ تحميل صفقة {symbol_key}: {e}")
    return None

def default_trade(last_pivot=None):
    return {
        "phase": "waiting",
        "trend": None, "entry": None, "step": None,
        "sl": None, "tp1": None, "tp2": None, "tp3": None,
        "tp1_hit": False, "tp2_hit": False,
        "pivot": None, "last_pivot": last_pivot,
        "break_price": None,
        "next_zone": None, "next_dir": None,
        "next_sl": None, "next_tp1": None, "next_tp2": None, "next_tp3": None,
        "next_alerted": False,
        "secured": False,  # هل الصفقة مؤمنة (بعد TP1)
    }

trades = {}
for key in SYMBOLS:
    trades[key] = default_trade()
    save_trade(key, trades[key])
logging.info("بدأ من صفر — لا صفقات قديمة")

def reset_trade(symbol_key):
    last_pivot = trades[symbol_key].get("pivot")
    trades[symbol_key] = default_trade(last_pivot)
    save_trade(symbol_key, trades[symbol_key])

# ======= الأسعار =======
def get_prices(symbol, interval="1h", count=50):
    try:
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": symbol, "interval": interval, "outputsize": count, "apikey": TWELVE_API_KEY}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("status") == "error":
            logging.error(f"Twelve error [{symbol}]: {data.get('message')}")
            return None
        values = data.get("values", [])
        if not values:
            return None
        prices = [round(float(v["close"]), 2) for v in reversed(values)]
        logging.info(f"[{symbol}][{interval}] {len(prices)} سعر — آخرها: {prices[-1]}")
        return prices
    except Exception as e:
        logging.error(f"خطأ سحب [{symbol}][{interval}]: {e}")
        return None

def get_current_price(symbol):
    try:
        url = "https://api.twelvedata.com/price"
        params = {"symbol": symbol, "apikey": TWELVE_API_KEY}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        price = round(float(str(data["price"])), 2)
        return price
    except Exception as e:
        logging.error(f"خطأ سحب السعر [{symbol}]: {e}")
        return None

# ======= التحليل =======
def analyze_with_claude(symbol_key, h1_prices, m15_prices, current_price):
    step_multiplier = SYMBOLS[symbol_key]["step_multiplier"]
    system = f"""أنت نظام تداول رقمي تطبق فقط منهج استراتيجية التوازن المفقود.

الخطوات:
1. من H1: حدد الاتجاه العام (صاعد/هابط)
2. من H1: اختر الـ Pivot — آخر قمة في الهابط، آخر قاع في الصاعد
3. Core Code: أول 4 أرقام من Pivot بدون فاصلة، اجمعها حتى رقم 1-9
4. العائلة: 1او4او7=12 | 2او5او8=15 | 3او6او9=18
5. Step = قيمة العائلة × {step_multiplier}
6. ابنِ 4 مستويات صعوداً أو هبوطاً
7. Entry=L1، SL=Pivot، TP1=L2، TP2=L3، TP3=L4
8. المنطقة القادمة = L4 ± Step
9. هابط=بيع، صاعد=شراء

أجب فقط بـ JSON:
{{"trend":"هابط","pivot_type":"Peak","pivot_price":0,"core_code":0,"family":0,"step":0,"level1":0,"level2":0,"level3":0,"level4":0,"entry":0,"sl":0,"tp1":0,"tp2":0,"tp3":0,"next_zone":0,"next_dir":"شراء","next_sl":0,"next_tp1":0,"next_tp2":0,"next_tp3":0,"note":""}}"""

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
        return json.loads(clean)
    except Exception as e:
        logging.error(f"خطأ تحليل: {e}")
        return None

# ======= الإرسال =======
def send_to_subscribers(symbol_key, msg):
    for chat_id, syms in list(subscribers.items()):
        if symbol_key in syms:
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

def format_zone(price, step, trend):
    """تحويل نقطة لمنطقة ضيقة حول نقطة الدخول"""
    margin = 2 if step <= 100 else 20
    if trend == "هابط":
        return f"{price} — {round(price + margin, 2)}"
    else:
        return f"{round(price - margin, 2)} — {price}"

def send_new_trade(symbol_key, p, current_price):
    sym = SYMBOLS[symbol_key]
    direction = "🔴 بيع" if p["trend"] == "هابط" else "🟢 شراء"
    trend_emoji = "📉" if p["trend"] == "هابط" else "📈"
    step = p.get("step", 12)
    entry_zone = format_zone(p['entry'], step, p['trend'])
    next_zone = p.get("next_zone")
    next_dir = p.get("next_dir", "")
    next_emoji = "🟢" if next_dir == "شراء" else "🔴"

    if next_zone and next_zone != 0:
        next_zone_str = format_zone(next_zone, step, "صاعد" if next_dir == "شراء" else "هابط")
        next_line = f"\n\n👀 <b>المنطقة القادمة:</b> {next_zone_str}\n{next_emoji} نفكر في {next_dir} منها عند وصول السعر"
    else:
        next_line = "\n\n👀 لا توجد منطقة قادمة حالياً — نراقب السوق"

    msg = f"""{sym['emoji']} <b>{sym['name']} {sym['display']}</b>
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}

{trend_emoji} <b>الاتجاه:</b> {p['trend']}

{direction} — ضع أمر معلق بين: <b>{entry_zone}</b>
🛑 SL: <b>{p['sl']}</b>
✅ TP1: <b>{p['tp1']}</b>
✅ TP2: <b>{p['tp2']}</b>
✅ TP3: <b>{p['tp3']}</b>

⏳ <b>الحالة:</b> انتظار التفعيل
💰 <b>السعر الحالي:</b> {current_price}{next_line}{DISCLAIMER}"""
    send_to_subscribers(symbol_key, msg)

def send_activated(symbol_key, current_price):
    sym = SYMBOLS[symbol_key]
    t = trades[symbol_key]
    direction = "🔴 بيع" if t["trend"] == "هابط" else "🟢 شراء"
    step = t.get("step", 12)
    next_zone = t.get("next_zone")
    next_dir = t.get("next_dir", "")
    next_emoji = "🟢" if next_dir == "شراء" else "🔴"

    if next_zone and next_zone != 0:
        next_zone_str = format_zone(next_zone, step, "صاعد" if next_dir == "شراء" else "هابط")
        next_line = f"\n\n👀 <b>المنطقة القادمة:</b> {next_zone_str}\n{next_emoji} نفكر في {next_dir} منها عند وصول السعر"
    else:
        next_line = "\n\n👀 لا توجد منطقة قادمة حالياً — نراقب السوق"

    msg = f"""🚨 <b>تفعّلت صفقة {direction} عند {t['entry']}</b>
{sym['emoji']} {sym['display']}
💰 السعر الحالي: {current_price}

🛑 SL: <b>{t['sl']}</b>
✅ TP1: <b>{t['tp1']}</b>
✅ TP2: <b>{t['tp2']}</b>
✅ TP3: <b>{t['tp3']}</b>{next_line}{DISCLAIMER}"""
    send_to_subscribers(symbol_key, msg)

# ======= متابعة الصفقة =======
RETEST_TOLERANCE = {"gold": 1, "btc": 10}

def check_trade(symbol_key, current_price):
    t = trades[symbol_key]
    tolerance = RETEST_TOLERANCE.get(symbol_key, 1)

    if t["phase"] == "waiting":
        return

    trend = t["trend"]
    entry = t["entry"]
    sym = SYMBOLS[symbol_key]

    if t["phase"] == "broken":
        if trend == "هابط":
            if t["break_price"] is None or current_price > t["break_price"]:
                t["break_price"] = current_price
            if current_price >= entry - tolerance:
                t["phase"] = "retest"
                save_trade(symbol_key, t)
        else:
            if t["break_price"] is None or current_price < t["break_price"]:
                t["break_price"] = current_price
            if current_price <= entry + tolerance:
                t["phase"] = "retest"
                save_trade(symbol_key, t)
        return

    if t["phase"] == "retest":
        if trend == "هابط":
            if current_price < entry - tolerance:
                t["phase"] = "active"
                save_trade(symbol_key, t)
                send_activated(symbol_key, current_price)
            elif current_price >= t["sl"]:
                send_to_subscribers(symbol_key, f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade(symbol_key)
        else:
            if current_price > entry + tolerance:
                t["phase"] = "active"
                save_trade(symbol_key, t)
                send_activated(symbol_key, current_price)
            elif current_price <= t["sl"]:
                send_to_subscribers(symbol_key, f"""❌ <b>فشل الـ Retest — الصفقة ملغاة</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade(symbol_key)
        return

    if t["phase"] == "active":
        next_zone = t.get("next_zone")
        if next_zone and not t["next_alerted"]:
            if abs(current_price - next_zone) <= tolerance * 5:
                t["next_alerted"] = True
                save_trade(symbol_key, t)
                next_dir = t.get("next_dir", "")
                step = t.get("step", 12)
                next_zone_str = format_zone(next_zone, step, "صاعد" if next_dir == "شراء" else "هابط")
                send_to_subscribers(symbol_key, f"""👀 <b>السعر يقترب من منطقة {next_dir}</b>
{sym['emoji']} {sym['display']}
📍 المنطقة: {next_zone_str}
💰 السعر الحالي: {current_price}
⏳ انتظار التفعيل""")

        # تحقق SL
        if (trend == "هابط" and current_price >= t["sl"]) or \
           (trend == "صاعد" and current_price <= t["sl"]):
            if t.get("secured"):
                send_to_subscribers(symbol_key, f"""🛑 <b>خرجنا بربح — الصفقة كانت مؤمنة</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            else:
                send_to_subscribers(symbol_key, f"""🛑 <b>ضُرب وقف الخسارة</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            reset_trade(symbol_key)
            return

        # تحقق TP1
        if not t["tp1_hit"]:
            if (trend == "هابط" and current_price <= t["tp1"]) or \
               (trend == "صاعد" and current_price >= t["tp1"]):
                t["tp1_hit"] = True
                t["secured"] = True  # الصفقة مؤمنة بعد TP1
                save_trade(symbol_key, t)
                send_to_subscribers(symbol_key, f"""✅ <b>تحقق الهدف الأول {t['tp1']}</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
⏳ الهدف الثاني: {t['tp2']}""")
            return

        # تحقق TP2
        if not t["tp2_hit"]:
            if (trend == "هابط" and current_price <= t["tp2"]) or \
               (trend == "صاعد" and current_price >= t["tp2"]):
                t["tp2_hit"] = True
                save_trade(symbol_key, t)
                send_to_subscribers(symbol_key, f"""✅✅ <b>تحقق الهدف الثاني {t['tp2']} — الصفقة مؤمنة بالكامل</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
⏳ الهدف الثالث: {t['tp3']}""")
            return

        # تحقق TP3
        if (trend == "هابط" and current_price <= t["tp3"]) or \
           (trend == "صاعد" and current_price >= t["tp3"]):
            send_to_subscribers(symbol_key, f"""🎯 <b>تحقق الهدف الثالث — الصفقة اكتملت</b>
{sym['emoji']} {sym['display']}
💰 السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            reset_trade(symbol_key)

def check_break(symbol_key, current_price):
    t = trades[symbol_key]
    if t["phase"] != "waiting" or not t["trend"]:
        return
    trend = t["trend"]
    entry = t["entry"]
    sym = SYMBOLS[symbol_key]
    max_skip = sym.get("max_skip", 50)

    if trend == "هابط" and current_price < entry:
        if (entry - current_price) > max_skip:
            logging.info(f"فات المستوى {symbol_key} — إلغاء")
            send_to_subscribers(symbol_key, f"""⚠️ <b>فات المستوى — جاري البحث عن فرصة جديدة</b>
{sym["emoji"]} {sym["display"]}
💰 السعر الحالي: {current_price}""")
            reset_trade(symbol_key)
            return
        t["phase"] = "broken"
        t["break_price"] = current_price
        save_trade(symbol_key, t)

    elif trend == "صاعد" and current_price > entry:
        if (current_price - entry) > max_skip:
            logging.info(f"فات المستوى {symbol_key} — إلغاء")
            send_to_subscribers(symbol_key, f"""⚠️ <b>فات المستوى — جاري البحث عن فرصة جديدة</b>
{sym["emoji"]} {sym["display"]}
💰 السعر الحالي: {current_price}""")
            reset_trade(symbol_key)
            return
        t["phase"] = "broken"
        t["break_price"] = current_price
        save_trade(symbol_key, t)

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
                text = msg.get("text", "").strip()
                first_name = msg.get("chat", {}).get("first_name", "")

                if text == "/start":
                    if chat_id not in subscribers:
                        send_to_one(chat_id, f"""🥇 <b>أهلاً {first_name}!</b>

مرحباً بك في بوت التحليل 🎉

اختر الرموز التي تريد متابعتها:

1️⃣ /gold — الذهب XAUUSD
2️⃣ /btc — البيتكوين BTCUSD
3️⃣ /all — الكل

⚠️ التحليل اجتهادي قابل للصواب والخطأ — إدارة رأس المال أولاً""")
                    else:
                        send_to_one(chat_id, f"✅ أنت مشترك بالفعل\nرموزك: {', '.join(subscribers[chat_id])}")

                elif text == "/gold":
                    subs = subscribers.get(chat_id, [])
                    if "gold" not in subs:
                        subs.append("gold")
                        subscribers[chat_id] = subs
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "✅ تم تسجيلك في الذهب XAUUSD 🥇")
                        send_to_one(ADMIN_CHAT_ID, f"👤 مشترك جديد: {first_name} — الذهب | إجمالي: {len(subscribers)}")
                    else:
                        send_to_one(chat_id, "✅ أنت مشترك بالفعل في الذهب")

                elif text == "/btc":
                    subs = subscribers.get(chat_id, [])
                    if "btc" not in subs:
                        subs.append("btc")
                        subscribers[chat_id] = subs
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "✅ تم تسجيلك في البيتكوين BTCUSD 🪙")
                        send_to_one(ADMIN_CHAT_ID, f"👤 مشترك جديد: {first_name} — البيتكوين | إجمالي: {len(subscribers)}")
                    else:
                        send_to_one(chat_id, "✅ أنت مشترك بالفعل في البيتكوين")

                elif text == "/all":
                    subscribers[chat_id] = list(SYMBOLS.keys())
                    save_subscribers(subscribers)
                    send_to_one(chat_id, "✅ تم تسجيلك في جميع الرموز 🥇🪙")
                    send_to_one(ADMIN_CHAT_ID, f"👤 مشترك جديد: {first_name} — الكل | إجمالي: {len(subscribers)}")

                elif text == "/stop":
                    if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                        del subscribers[chat_id]
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "تم إلغاء اشتراكك. يمكنك العودة بـ /start")

                elif text.startswith("/broadcast") and chat_id == ADMIN_CHAT_ID:
                    broadcast_msg = text.replace("/broadcast", "").strip()
                    if broadcast_msg:
                        count = 0
                        for cid in list(subscribers.keys()):
                            try:
                                requests.post(
                                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                    json={"chat_id": cid, "text": broadcast_msg, "parse_mode": "HTML"},
                                    timeout=15
                                )
                                count += 1
                            except:
                                pass
                        send_to_one(ADMIN_CHAT_ID, f"✅ تم الإرسال لـ {count} مشترك")
                    else:
                        send_to_one(ADMIN_CHAT_ID, "اكتب الرسالة بعد الأمر\nمثال: /broadcast مرحباً بالجميع")

                elif text == "/count" and chat_id == ADMIN_CHAT_ID:
                    counts = {key: sum(1 for s in subscribers.values() if key in s) for key in SYMBOLS}
                    msg_lines = [f"👥 إجمالي المشتركين: {len(subscribers)}"]
                    for key, sym in SYMBOLS.items():
                        msg_lines.append(f"{sym['emoji']} {sym['name']}: {counts[key]}")
                    send_to_one(ADMIN_CHAT_ID, "\n".join(msg_lines))

        except Exception as e:
            logging.error(f"خطأ updates: {e}")
        time.sleep(2)

# ======= التشغيل =======
def run_symbol(symbol_key):
    sym = SYMBOLS[symbol_key]
    analysis_counter = 0
    logging.info(f"بدأ تحليل {symbol_key}")

    while True:
        try:
            current_price = get_current_price(sym["symbol"])
            if not current_price:
                time.sleep(60)
                continue

            t = trades[symbol_key]

            if t["phase"] == "waiting" and t["trend"]:
                check_break(symbol_key, current_price)
            elif t["phase"] in ["broken", "retest", "active"]:
                check_trade(symbol_key, current_price)

            if t["phase"] == "waiting":
                analysis_counter += 1
                if analysis_counter >= 15:
                    analysis_counter = 0
                    h1 = get_prices(sym["symbol"], "1h", 50)
                    m15 = get_prices(sym["symbol"], "15min", 30)
                    if h1 and m15:
                        result = analyze_with_claude(symbol_key, h1, m15, current_price)
                        if result:
                            new_pivot = result["pivot_price"]
                            if new_pivot != t.get("last_pivot"):
                                t.update({
                                    "trend": result["trend"],
                                    "entry": result["entry"],
                                    "step": result.get("step", 12),
                                    "sl": result["sl"],
                                    "tp1": result["tp1"],
                                    "tp2": result["tp2"],
                                    "tp3": result["tp3"],
                                    "pivot": new_pivot,
                                    "last_pivot": new_pivot,
                                    "next_zone": result.get("next_zone"),
                                    "next_dir": result.get("next_dir"),
                                    "next_sl": result.get("next_sl"),
                                    "next_tp1": result.get("next_tp1"),
                                    "next_tp2": result.get("next_tp2"),
                                    "next_tp3": result.get("next_tp3"),
                                    "next_alerted": False,
                                    "secured": False,
                                })
                                save_trade(symbol_key, t)
                                send_new_trade(symbol_key, result, current_price)
            else:
                analysis_counter = 0

        except Exception as e:
            logging.error(f"خطأ {symbol_key}: {e}")

        time.sleep(60)

def run():
    logging.info("البوت بدأ")

    t = threading.Thread(target=handle_updates, daemon=True)
    t.start()

    send_to_one(ADMIN_CHAT_ID, "🤖 <b>البوت شغّال</b> — الذهب 🥇 والبيتكوين 🪙")

    for key in SYMBOLS:
        th = threading.Thread(target=run_symbol, args=(key,), daemon=True)
        th.start()
        time.sleep(5)

    while True:
        time.sleep(60)

if __name__ == "__main__":
    run()
