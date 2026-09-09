import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import io
import os

CSV_FILE = "daily_watchlist.csv"
TARGET_STOCKS = 3700  
TARGET_ETFS = 800     
BATCH_SIZE = 80       # ขนาด Batch สำหรับหลบการตรวจจับของ Yahoo

def get_categorized_universe():
    print("🌐 กำลังดึงฐานข้อมูลและแยกประเภท (Stock / ETF) จาก NASDAQ & NYSE...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    asset_dict = {}

    try:
        url_nasdaq = "https://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
        res = requests.get(url_nasdaq, headers=headers, timeout=15)
        df_nasdaq = pd.read_csv(io.StringIO(res.text), sep="|")
        df_nasdaq = df_nasdaq[df_nasdaq['Test Issue'] == 'N']
        for _, row in df_nasdaq.iterrows():
            t = str(row['Symbol']).strip()
            is_etf = str(row.get('ETF', 'N')).strip().upper() == 'Y'
            asset_dict[t] = "ETF" if is_etf else "Common Stock"
    except Exception as e:
        print(f"⚠️ ดึง NASDAQ ไม่สำเร็จ: {e}")

    try:
        url_other = "https://ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt"
        res = requests.get(url_other, headers=headers, timeout=15)
        df_other = pd.read_csv(io.StringIO(res.text), sep="|")
        df_other = df_other[df_other['Test Issue'] == 'N']
        for _, row in df_other.iterrows():
            t = str(row['ACT Symbol']).strip()
            is_etf = str(row.get('ETF', 'N')).strip().upper() == 'Y'
            asset_dict[t] = "ETF" if is_etf else "Common Stock"
    except Exception as e:
        print(f"⚠️ ดึง Other Listed ไม่สำเร็จ: {e}")

    clean_dict = {}
    for t, atype in asset_dict.items():
        t = t.replace('$', '-P').replace('.', '-')
        if any(c in t for c in ['=', '+', '*', '~', ' ', '^']):
            continue
        if len(t) > 5 or len(t) < 1:
            continue
        clean_dict[t] = atype

    # บังคับใส่รายการโปรด
    clean_dict["KSLV"] = "ETF"
    clean_dict["SPY"] = "ETF"
    clean_dict["QQQ"] = "ETF"

    print(f"📊 พบสินทรัพย์ในตลาดทั้งหมด {len(clean_dict)} ตัว")
    return clean_dict

def calculate_metrics(df):
    # ยอมรับหุ้นที่เพิ่งเข้าตลาดได้ 30 วันขึ้นไป
    if len(df) < 30:
        return None

    close = df['Close']
    volume = df['Volume']
    high = df['High']
    low = df['Low']

    latest_close = round(float(close.iloc[-1]), 2)
    
    # 🌟 ปลดล็อกข้อจำกัดด้านราคา: ไม่สนใจว่าราคาขั้นต่ำเท่าไหร่ (ลบ if latest_close < ... ทิ้งไปแล้ว)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma200 = close.rolling(window=200).mean() if len(close) >= 200 else None

    vol_20ma = volume.rolling(window=20).mean()
    latest_vol = float(volume.iloc[-1])
    avg_vol = float(vol_20ma.iloc[-1]) if pd.notnull(vol_20ma.iloc[-1]) and vol_20ma.iloc[-1] > 0 else latest_vol
    
    # 🌟 เงื่อนไขใหม่: ยอมรับเฉพาะสินทรัพย์ที่มี Volume เฉลี่ย 2,500 หุ้น/วัน ขึ้นไป
    if avg_vol < 2500:
        return None

    vol_ratio = round(latest_vol / avg_vol, 2)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(window=14).mean()
    latest_atr = round(float(atr14.iloc[-1]), 2) if pd.notnull(atr14.iloc[-1]) else 1.0

    latest_e20 = float(ema20.iloc[-1])
    latest_e50 = float(ema50.iloc[-1])
    latest_s200 = float(sma200.iloc[-1]) if sma200 is not None and pd.notnull(sma200.iloc[-1]) else None

    cond_short = latest_close > latest_e20
    cond_mid = latest_e20 > latest_e50
    cond_long = (latest_s200 is not None) and (latest_e50 > latest_s200)
    cond_vol = vol_ratio >= 1.05

    status = "PASS" if (cond_short and cond_mid and cond_long and cond_vol) else "FAIL"
    suggested_stop = round(latest_close - (2 * latest_atr), 2)

    return_1y = None
    if len(close) >= 250:
        return_1y = round(((latest_close - float(close.iloc[-250])) / float(close.iloc[-250])) * 100, 2)

    return {
        "Close": latest_close,
        "Status": status,
        "Vol_Ratio": vol_ratio,
        "ATR": latest_atr,
        "Suggested_Stop": suggested_stop,
        "Historical_Return": return_1y,
        "Return_Period": "1Y",
        "Avg_Volume": avg_vol
    }

def run_screener():
    asset_dict = get_categorized_universe()
    tickers = list(asset_dict.keys())
    total = len(tickers)
    results = []

    print(f"🚀 เริ่มดาวน์โหลดและวิเคราะห์ข้อมูลทั้งหมด {total} ตัว...")

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i+BATCH_SIZE]
        batch_no = (i // BATCH_SIZE) + 1
        total_batches = (total // BATCH_SIZE) + 1
        print(f"📦 Batch {batch_no}/{total_batches} ({len(batch)} Tickers)...")

        try:
            data = yf.download(batch, period="1y", interval="1d", group_by="ticker", threads=True, progress=False, timeout=40)

            for t in batch:
                try:
                    if t not in data.columns.levels[0]:
                        continue
                    sub_df = data[t].dropna(subset=['Close', 'Volume'])
                    
                    m = calculate_metrics(sub_df)
                    if m:
                        results.append({
                            "Ticker": t,
                            "Asset_Type": asset_dict[t],
                            "Status": m["Status"],
                            "Close": m["Close"],
                            "Historical_Return": m["Historical_Return"],
                            "Return_Period": m["Return_Period"],
                            "Div_Yield": 0.0,
                            "Vol_Ratio": m["Vol_Ratio"],
                            "ATR": m["ATR"],
                            "Suggested_Stop": m["Suggested_Stop"],
                            "Avg_Volume": m["Avg_Volume"]
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ Batch {batch_no} ขัดข้อง: {e}")

        # พัก 2.5 วินาที เพื่อป้องกัน Yahoo บล็อก
        time.sleep(2.5)

    if len(results) > 0:
        df_all = pd.DataFrame(results)
        
        df_stocks = df_all[df_all['Asset_Type'] == 'Common Stock']
        df_etfs = df_all[df_all['Asset_Type'] == 'ETF']

        # เรียงลำดับจากวอลุ่มสูงไปต่ำ และตัดให้พอดีกับโควตา
        df_stocks = df_stocks.sort_values(by="Avg_Volume", ascending=False).head(TARGET_STOCKS)
        df_etfs = df_etfs.sort_values(by="Avg_Volume", ascending=False).head(TARGET_ETFS)

        final_df = pd.concat([df_stocks, df_etfs])
        
        final_df = final_df.sort_values(by=["Status", "Vol_Ratio"], ascending=[True, False])
        final_df = final_df.drop(columns=["Avg_Volume"])
        final_df.to_csv(CSV_FILE, index=False)

        pass_count = len(final_df[final_df['Status'] == 'PASS'])
        print(f"🎉 สำเร็จ! บันทึกผล Stock: {len(df_stocks)} ตัว | ETF: {len(df_etfs)} ตัว ลงใน {CSV_FILE}")
        print(f"✅ ผ่านเกณฑ์ PASS ทั้งสิ้น: {pass_count} ตัว")
    else:
        print("❌ ไม่สามารถดึงข้อมูลได้เลย")

if __name__ == "__main__":
    run_screener()
