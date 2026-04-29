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

# ======= حساب Core Code في Python =======
def calc_core_code(pivot_price):
    digits_str = str(pivot_price).replace(".", "").replace("-", "")
    first4 = digits_str[:4]
    total = sum(int(d) for d in first4)
    while total >= 10:
        total = sum(int(d) for d in str(total))
    return total if total != 0 else 9

def calc_family(core):
    if core in [1, 4, 7]: return 12
    if core in [2, 5, 8]: return 15
    if core in [3, 6, 9]: return 18
    return 12

def calc_levels(pivot, step, trend, count=4):
    levels = []
    for i in range(1, count + 1):
        if trend == "هابط":
            levels.append(round(pivot - step * i, 2))
        else:
            levels.append(round(pivot + step * i, 2))
    return levels

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
                return data
    except:
        pass
    return None

def default_trade(last_pivot=None):
    return {
        "phase": "waiting",
        "trend": None, "entry": None, "step": None,
        "sl": None, "tp1": None, "tp2": None, "tp3": None,
        "tp1_hit": False, "tp2_hit": False,
        "pivot": None, "last_pivot": last_pivot,
        "break_price": None,
        "level1": None, "level2": None, "level3": None, "level4": None,
        "next_zone": None, "next_dir": None,
        "next_alerted": False,
        "secured": False,
    }

trades = {}
for key in SYMBOLS:
    saved = load_trade(key)
    trades[key] = saved if saved else default_trade()

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
        return round(float(str(data["price"])), 2)
    except Exception as e:
        logging.error(f"خطأ سحب السعر [{symbol}]: {e}")
        return None

# ======= التحليل — Claude يختار Pivot فقط =======
def get_pivot_from_claude(symbol_key, h1_prices, m1_prices, current_price):
    system = """أنت نظام تداول متخصص في استراتيجية التوازن المفقود.

مهمتك الوحيدة:
1. حدد الاتجاه (صاعد/هابط) من بيانات H1
2. اختر الـ Pivot الصحيح:
   - هابط: آخر قمة واضحة نتج بعدها هبوط حقيقي
   - صاعد: آخر قاع واضح نتجت بعده موجة صاعدة حقيقية
3. تحقق من بيانات 1M:
   - هل يوجد كسر حقيقي لمستوى مع إغلاق؟
   - هل يوجد إعادة اختبار نظيفة؟
   - هل يوجد رفض واضح؟
   - هل يوجد تأكيد استمرار؟

شروط NO TRADE:
- الاتجاه غير واضح
- الـ Pivot غير واضح
- السعر تجاوز جميع المستويات
- لا يوجد كسر حقيقي
- السوق متذبذب
- الإشارة ضعيفة

أجب فقط بـ JSON:
{"trend":"هابط","pivot_price":0,"decision":"TRADE أو NO TRADE","signal_strength":"Strong أو Weak","note":"سبب واحد فقط"}"""

    user_msg = f"""[H1]:\n{chr(10).join([str(p) for p in h1_prices[-40:]])}\n\n[1M]:\n{chr(10).join([str(p) for p in m1_prices[-30:]])}\n\nالسعر الحالي: {current_price}\n\nJSON فقط."""

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
                "max_tokens": 300,
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

        # حساب Core Code والمستويات في Python — مو Claude
        pivot = result.get("pivot_price", 0)
        trend = result.get("trend", "")
        decision = result.get("decision", "NO TRADE")
        signal = result.get("signal_strength", "Weak")

        if not pivot or decision == "NO TRADE" or signal == "Weak":
            return None

        core = calc_core_code(pivot)
        family = calc_family(core)
        step = family * SYMBOLS[symbol_key]["step_multiplier"]
        levels = calc_levels(pivot, step, trend)

        entry = levels[0]
        sl = pivot  # المستوى السابق للدخول = الـ Pivot
        tp1 = levels[1]
        tp2 = levels[2]
        tp3 = levels[3]
        next_zone = round(levels[3] + (step if trend == "صاعد" else -step), 2)
        next_dir = "شراء" if trend == "هابط" else "بيع"

        logging.info(f"Pivot={pivot} | Core={core} | Family={family} | Step={step} | Levels={levels}")

        return {
            "trend": trend,
            "pivot_price": pivot,
            "core_code": core,
            "family": family,
            "step": step,
            "level1": levels[0],
            "level2": levels[1],
            "level3": levels[2],
            "level4": levels[3],
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "next_zone": next_zone,
            "next_dir": next_dir,
            "signal_strength": signal,
            "decision": decision,
            "note": result.get("note", "")
        }

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

    if next_zone:
        next_zone_str = format_zone(next_zone, step, "صاعد" if next_dir == "شراء" else "هابط")
        next_line = f"\n\n👀 <b>المنطقة القادمة:</b> {next_zone_str}\n{next_emoji} نفكر في {next_dir} منها"
    else:
        next_line = ""

    msg = f"""{sym['emoji']} <b>{sym['name']} {sym['display']}</b>
🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}

{trend_emoji} <b>الاتجاه:</b> {p['trend']}
📌 <b>Pivot ({p.get('pivot_type','Peak' if p['trend']=='هابط' else 'Trough')}):</b> {p.get('pivot_price')}
🔢 Core: {p.get('core_code')} | Family: {p.get('family')} | Step: {p.get('step')}

📊 <b>المستويات:</b>
  L1: {p.get('level1')}
  L2: {p.get('level2')}
  L3: {p.get('level3')}
  L4: {p.get('level4')}

{direction} — أمر معلق: <b>{entry_zone}</b>
🛑 SL: <b>{p['sl']}</b>
✅ TP1: <b>{p['tp1']}</b>
✅ TP2: <b>{p['tp2']}</b>
✅ TP3: <b>{p['tp3']}</b>

⏳ <b>الحالة:</b> انتظار الكسر + إعادة الاختبار على 1M
💪 قوة الإشارة: {p.get('signal_strength','—')}
💡 {p.get('note','')}{next_line}{DISCLAIMER}"""
    send_to_subscribers(symbol_key, msg)

def send_activated(symbol_key, current_price):
    sym = SYMBOLS[symbol_key]
    t = trades[symbol_key]
    direction = "🔴 بيع" if t["trend"] == "هابط" else "🟢 شراء"

    msg = f"""🚨 <b>تفعّلت صفقة {direction}</b>
{sym['emoji']} {sym['display']}
💰 السعر الحالي: {current_price}

🎯 الدخول: <b>{t['entry']}</b>
🛑 SL: <b>{t['sl']}</b>
✅ TP1: <b>{t['tp1']}</b>
✅ TP2: <b>{t['tp2']}</b>
✅ TP3: <b>{t['tp3']}</b>{DISCLAIMER}"""
    send_to_subscribers(symbol_key, msg)

# ======= متابعة الصفقة =======
RETEST_TOLERANCE = {"gold": 1.5, "btc": 15}

def check_trade(symbol_key, current_price):
    t = trades[symbol_key]
    tolerance = RETEST_TOLERANCE.get(symbol_key, 1.5)
    if t["phase"] == "waiting":
        return
    trend = t["trend"]
    entry = t["entry"]
    sym = SYMBOLS[symbol_key]

    if t["phase"] == "broken":
        if trend == "هابط":
            if current_price >= entry - tolerance:
                t["phase"] = "retest"
                save_trade(symbol_key, t)
        else:
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
                send_to_subscribers(symbol_key, f"""❌ <b>فشل الـ Retest — ملغاة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade(symbol_key)
        else:
            if current_price > entry + tolerance:
                t["phase"] = "active"
                save_trade(symbol_key, t)
                send_activated(symbol_key, current_price)
            elif current_price <= t["sl"]:
                send_to_subscribers(symbol_key, f"""❌ <b>فشل الـ Retest — ملغاة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
                reset_trade(symbol_key)
        return

    if t["phase"] == "active":
        # SL
        if (trend == "هابط" and current_price >= t["sl"]) or \
           (trend == "صاعد" and current_price <= t["sl"]):
            if t.get("secured"):
                send_to_subscribers(symbol_key, f"""🛑 <b>خرجنا بربح — الصفقة كانت مؤمنة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            else:
                send_to_subscribers(symbol_key, f"""🛑 <b>ضُرب وقف الخسارة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
🔍 جاري رصد فرصة جديدة...""")
            reset_trade(symbol_key)
            return

        # TP1
        if not t["tp1_hit"]:
            if (trend == "هابط" and current_price <= t["tp1"]) or \
               (trend == "صاعد" and current_price >= t["tp1"]):
                t["tp1_hit"] = True
                t["secured"] = True
                t["sl"] = t["entry"]
                save_trade(symbol_key, t)
                send_to_subscribers(symbol_key, f"""✅ <b>TP1 تحقق {t['tp1']}</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
🔒 SL نُقل لنقطة الدخول {t['entry']} — الصفقة مؤمنة
⏳ الهدف الثاني: {t['tp2']}""")
            return

        # TP2
        if not t["tp2_hit"]:
            if (trend == "هابط" and current_price <= t["tp2"]) or \
               (trend == "صاعد" and current_price >= t["tp2"]):
                t["tp2_hit"] = True
                save_trade(symbol_key, t)
                send_to_subscribers(symbol_key, f"""✅✅ <b>TP2 تحقق {t['tp2']}</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
⏳ الهدف الثالث: {t['tp3']}""")
            return

        # TP3
        if (trend == "هابط" and current_price <= t["tp3"]) or \
           (trend == "صاعد" and current_price >= t["tp3"]):
            send_to_subscribers(symbol_key, f"""🎯 <b>TP3 تحقق — الصفقة اكتملت</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}
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
            send_to_subscribers(symbol_key, f"""⚠️ <b>فات المستوى — فرصة جديدة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}""")
            reset_trade(symbol_key)
            return
        t["phase"] = "broken"
        t["break_price"] = current_price
        save_trade(symbol_key, t)

    elif trend == "صاعد" and current_price > entry:
        if (current_price - entry) > max_skip:
            send_to_subscribers(symbol_key, f"""⚠️ <b>فات المستوى — فرصة جديدة</b>
{sym['emoji']} {sym['display']} | السعر: {current_price}""")
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
اختر ما تريد متابعته:
1️⃣ /gold — الذهب
2️⃣ /btc — البيتكوين
3️⃣ /all — الكل
⚠️ التحليل اجتهادي — إدارة رأس المال أولاً""")
                    else:
                        send_to_one(chat_id, f"✅ مشترك بالفعل: {', '.join(subscribers[chat_id])}")

                elif text == "/gold":
                    subs = subscribers.get(chat_id, [])
                    if "gold" not in subs:
                        subs.append("gold")
                        subscribers[chat_id] = subs
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "✅ تم تسجيلك في الذهب 🥇")
                        send_to_one(ADMIN_CHAT_ID, f"👤 {first_name} — ذهب | {len(subscribers)} مشترك")
                    else:
                        send_to_one(chat_id, "✅ مشترك بالفعل في الذهب")

                elif text == "/btc":
                    subs = subscribers.get(chat_id, [])
                    if "btc" not in subs:
                        subs.append("btc")
                        subscribers[chat_id] = subs
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "✅ تم تسجيلك في البيتكوين 🪙")
                        send_to_one(ADMIN_CHAT_ID, f"👤 {first_name} — بيتكوين | {len(subscribers)} مشترك")
                    else:
                        send_to_one(chat_id, "✅ مشترك بالفعل في البيتكوين")

                elif text == "/all":
                    subscribers[chat_id] = list(SYMBOLS.keys())
                    save_subscribers(subscribers)
                    send_to_one(chat_id, "✅ تم تسجيلك في الكل 🥇🪙")
                    send_to_one(ADMIN_CHAT_ID, f"👤 {first_name} — الكل | {len(subscribers)} مشترك")

                elif text == "/stop":
                    if chat_id in subscribers and chat_id != ADMIN_CHAT_ID:
                        del subscribers[chat_id]
                        save_subscribers(subscribers)
                        send_to_one(chat_id, "تم إلغاء اشتراكك. عد بـ /start")

                elif text.startswith("/broadcast") and chat_id == ADMIN_CHAT_ID:
                    bm = text.replace("/broadcast", "").strip()
                    if bm:
                        count = 0
                        for cid in list(subscribers.keys()):
                            try:
                                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                    json={"chat_id": cid, "text": bm, "parse_mode": "HTML"}, timeout=15)
                                count += 1
                            except: pass
                        send_to_one(ADMIN_CHAT_ID, f"✅ أُرسل لـ {count} مشترك")

                elif text == "/count" and chat_id == ADMIN_CHAT_ID:
                    counts = {k: sum(1 for s in subscribers.values() if k in s) for k in SYMBOLS}
                    lines = [f"👥 إجمالي: {len(subscribers)}"]
                    for k, sym in SYMBOLS.items():
                        lines.append(f"{sym['emoji']} {sym['name']}: {counts[k]}")
                    send_to_one(ADMIN_CHAT_ID, "\n".join(lines))

        except Exception as e:
            logging.error(f"خطأ updates: {e}")
        time.sleep(2)

# ======= التشغيل =======
def run_symbol(symbol_key):
    sym = SYMBOLS[symbol_key]
    analysis_counter = 0
    logging.info(f"بدأ {symbol_key}")

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
                    m1 = get_prices(sym["symbol"], "1min", 30)
                    if h1 and m1:
                        result = get_pivot_from_claude(symbol_key, h1, m1, current_price)
                        if result:
                            new_pivot = result["pivot_price"]
                            if new_pivot != t.get("last_pivot"):
                                t.update({
                                    "trend": result["trend"],
                                    "entry": result["entry"],
                                    "step": result["step"],
                                    "sl": result["sl"],
                                    "tp1": result["tp1"],
                                    "tp2": result["tp2"],
                                    "tp3": result["tp3"],
                                    "pivot": new_pivot,
                                    "last_pivot": new_pivot,
                                    "level1": result["level1"],
                                    "level2": result["level2"],
                                    "level3": result["level3"],
                                    "level4": result["level4"],
                                    "next_zone": result.get("next_zone"),
                                    "next_dir": result.get("next_dir"),
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
    send_to_one(ADMIN_CHAT_ID, "🤖 <b>البوت شغّال</b> — الذهب 🥇 والبيتكوين 🪙\nH1 تحليل | 1M تنفيذ صارم")
    for key in SYMBOLS:
        th = threading.Thread(target=run_symbol, args=(key,), daemon=True)
        th.start()
        time.sleep(5)
    while True:
        time.sleep(60)

if __name__ == "__main__":
    run()
