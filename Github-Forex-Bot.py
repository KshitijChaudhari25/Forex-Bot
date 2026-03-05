import os
import time
from datetime import datetime
import pandas as pd
import requests

# ==========================================
# 1. SETTINGS & CREDENTIALS
# ==========================================
TELEGRAM_BOT_TOKEN = "8668619199:AAG297_RzDBzL2pm-6Mfnq3H5Uo0Sf9RZbs"
TELEGRAM_CHAT_ID = "5405443836"
OANDA_API_TOKEN = "4568af08cae35a6a35fa8a5baae4519f-a2f5dcb65a4f774aa2cbd58782546b37"
OANDA_ACCOUNT_ID = "101-002-38695239-001" 

symbols = ["EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY", "USD_CAD"]  
RISK_REWARD_RATIO = 2.0 
MIN_PROFIT_PIPS = 20.0  

# ==========================================
# 2. THE BOT's PERMANENT MEMORY
# ==========================================
MEMORY_FILE = "memory.txt"

# Load past zones from the text file so we don't spam you
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r") as f:
        notified_zones = f.read().splitlines()
else:
    notified_zones = []

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_oanda_data(instrument, granularity="H1", count=1500):
    url = f"https://api-fxpractice.oanda.com/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {OANDA_API_TOKEN}", "Accept-Datetime-Format": "UNIX"}
    params = {"granularity": granularity, "count": count, "price": "M"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            return pd.DataFrame()
            
        data = response.json()
        candles = []
        for candle in data.get('candles', []):
            if candle['complete']: 
                candles.append({
                    'time': pd.to_datetime(float(candle['time']), unit='s'),
                    'Open': float(candle['mid']['o']), 'High': float(candle['mid']['h']),
                    'Low': float(candle['mid']['l']), 'Close': float(candle['mid']['c'])
                })
        df = pd.DataFrame(candles)
        if not df.empty:
            df.set_index('time', inplace=True)
        return df
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# 4. THE SCANNER ENGINE
# ==========================================
print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚙️ GitHub Actions Waking Up. Scanning...")

for current_symbol in symbols:
    print(f"   -> Analyzing {current_symbol}...")
    df = get_oanda_data(instrument=current_symbol, granularity="H1", count=1500)
    
    if df.empty:
        continue 

    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['High_Shift_2'] = df['High'].shift(2)
    df['Low_Shift_2'] = df['Low'].shift(2)
    df['Bullish_FVG'] = (df['Low'] > df['High_Shift_2']) & (df['Close'].shift(1) > df['Open'].shift(1))
    df['Bearish_FVG'] = (df['High'] < df['Low_Shift_2']) & (df['Close'].shift(1) < df['Open'].shift(1))
    
    avg_body = abs(df['Close'] - df['Open']).mean()
    new_alerts_message = ""

    for i in range(2, len(df)):
        current_close = df['Close'].iloc[i]
        current_trend = df['EMA_200'].iloc[i]
        zone_id = f"{current_symbol}_{df.index[i-2]}" 
        
        # --- BULLISH ---
        if df['Bullish_FVG'].iloc[i] and current_close > current_trend:
            top_of_gap = df['Low'].iloc[i]
            bottom_of_gap = df['High_Shift_2'].iloc[i]
            if (top_of_gap - bottom_of_gap) > (avg_body * 0.5):
                is_mitigated = any(df['Low'].iloc[j] < top_of_gap for j in range(i+1, len(df)))
                if not is_mitigated:
                    ob_top = max(df['Open'].iloc[i-2], df['Close'].iloc[i-2])
                    ob_bot = min(df['Open'].iloc[i-2], df['Close'].iloc[i-2])
                    risk = ob_top - ob_bot
                    pip_multiplier = 100 if "JPY" in current_symbol else 10000
                    profit_pips = (risk * RISK_REWARD_RATIO) * pip_multiplier
                    
                    if profit_pips >= MIN_PROFIT_PIPS and zone_id not in notified_zones:
                        entry, sl, tp = ob_top, ob_bot, ob_top + (risk * RISK_REWARD_RATIO)
                        new_alerts_message += f"🟢 <b>NEW BUY LIMIT</b>\n• <b>Entry:</b> {entry:.5f}\n• <b>SL:</b> {sl:.5f}\n• <b>TP:</b> {tp:.5f} ({profit_pips:.1f} pips)\n\n"
                        notified_zones.append(zone_id)
                        
                        # Save to permanent memory immediately
                        with open(MEMORY_FILE, "a") as f:
                            f.write(zone_id + "\n")

        # --- BEARISH ---
        if df['Bearish_FVG'].iloc[i] and current_close < current_trend:
            top_of_gap = df['Low_Shift_2'].iloc[i]
            bottom_of_gap = df['High'].iloc[i]
            if (top_of_gap - bottom_of_gap) > (avg_body * 0.5):
                is_mitigated = any(df['High'].iloc[j] > bottom_of_gap for j in range(i+1, len(df)))
                if not is_mitigated:
                    ob_top = max(df['Open'].iloc[i-2], df['Close'].iloc[i-2])
                    ob_bot = min(df['Open'].iloc[i-2], df['Close'].iloc[i-2])
                    risk = ob_bot - ob_top 
                    pip_multiplier = 100 if "JPY" in current_symbol else 10000
                    profit_pips = (abs(risk) * RISK_REWARD_RATIO) * pip_multiplier
                    
                    if profit_pips >= MIN_PROFIT_PIPS and zone_id not in notified_zones:
                        entry, sl, tp = ob_bot, ob_top, ob_bot - (abs(risk) * RISK_REWARD_RATIO)
                        new_alerts_message += f"🔴 <b>NEW SELL LIMIT</b>\n• <b>Entry:</b> {entry:.5f}\n• <b>SL:</b> {sl:.5f}\n• <b>TP:</b> {tp:.5f} ({profit_pips:.1f} pips)\n\n"
                        notified_zones.append(zone_id)
                        
                        # Save to permanent memory immediately
                        with open(MEMORY_FILE, "a") as f:
                            f.write(zone_id + "\n")

    if new_alerts_message != "":
        header = f"🎯 <b>ATHENA SNIPER ALERTS</b> 🎯\n<b>Asset:</b> {current_symbol}\n<b>Price:</b> {df['Close'].iloc[-1]:.5f}\n\n"
        send_telegram_alert(header + new_alerts_message)
        print(f"   📲 Alerts sent for {current_symbol}!")
    
    time.sleep(1) 

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 💤 Scan complete. Shutting down server until next hour.")