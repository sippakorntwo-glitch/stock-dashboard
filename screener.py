import yfinance as yf
import pandas as pd
import numpy as np
import time
import requests
import io
import os

CSV_FILE = "daily_watchlist.csv"
TARGET_TICKER_COUNT = 2500
BATCH_SIZE = 100

def get_us_stock_universe(max_count=2500):
    print("🌐 กำลังดึงรายชื่อหุ้นสหรัฐฯ จากแหล่งข้อมูลหลัก...")
    tickers = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    # 1. ดึงรายชื่อหุ้นตลาดสหรัฐฯ ครบวงจรจาก GitHub Financial Datasets (เสถียร ไม่บล็อก)
    try:
        url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            lines = res.text.splitlines()
            tickers.extend([line.strip().upper() for line in lines if line.strip()])
            print(f"✅ ดึงรายชื่อสำเร็จ: {len(tickers)} ตัว")
    except Exception as e:
        print(f"⚠️ ดึงจากแหล่งหลักไม่สำเร็จ: {e}")

    # 2. แหล่งสำรองกรณีแรกไม่ผ่าน (S&P 500 + NASDAQ 100 + Russell 1000)
    if len(tickers) < 500:
        try:
            url_sp500 = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            df_sp = pd.read_csv(url_sp500)
            tickers.extend(df_sp['Symbol'].dropna().tolist())
        except Exception:
            pass

    # คลีนข้อมูล Ticker ให้สะอาด
    clean_tickers = []
    for t in tickers:
        t = t.replace('$', '-P').replace('.', '-')
        if any(c in t for c in ['=', '+', '*', '~', ' ', '^']):
            continue
        if len(t) > 5 or len(t) < 1:
            continue
        clean_tickers.append(t)

    clean_tickers = list(dict.fromkeys(clean_tickers))
    print(f"📊 จัดเตรียมรายชื่อหุ้นสำหรับสแกนทั้งสิ้น: {min(len(clean_tickers), max_count)} ตัว")
    return clean_tickers[:max_count]

def calculate_metrics(df):
    if len(df) < 50:
        return None

    close = df['Close']
    volume = df['Volume']
    high = df['High']
    low = df['Low']

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma200 = close.rolling(window=200).mean() if len(close) >= 200 else None

    vol_20ma = volume.rolling(window=20).mean()
    latest_vol = float(volume.iloc[-1])
    avg_vol = float(vol_20ma.iloc[-1]) if pd.notnull(vol_20ma.iloc[-1]) and vol_20ma.iloc[-1] > 0 else latest_vol
    vol_ratio = round(latest_vol / avg_vol, 2)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(window=14).mean()
    latest_atr = round(float(atr14.iloc[-1]), 2) if pd.notnull(atr14.iloc[-1]) else 1.0

    latest_close = round(float(close.iloc[-1]), 2)
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
        "Return_Period": "1Y"
    }

def run_screener():
    tickers = get_us_stock_universe(max_count=TARGET_TICKER_COUNT)
    total = len(tickers)
    results = []

    print(f"🚀 เริ่มดาวน์โหลดและวิเคราะห์หุ้น {total} ตัว...")

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i+BATCH_SIZE]
        batch_no = (i // BATCH_SIZE) + 1
        total_batches = (total // BATCH_SIZE) + 1
        print(f"📦 กำลังประมวลผล Batch {batch_no}/{total_batches} ({len(batch)} ตัว)...")

        try:
            data = yf.download(
                tickers=batch,
                period="1y",
                interval="1d",
                group_by="ticker",
                threads=True,
                progress=False,
                timeout=30
            )

            for t in batch:
                try:
                    if t not in data.columns.levels[0]:
                        continue
                    sub_df = data[t].dropna(subset=['Close'])
                    if len(sub_df) < 50:
                        continue
                    if float(sub_df['Close'].iloc[-1]) < 1.0:
                        continue

                    m = calculate_metrics(sub_df)
                    if m:
                        results.append({
                            "Ticker": t,
                            "Asset_Type": "Common Stock",
                            "Status": m["Status"],
                            "Close": m["Close"],
                            "Historical_Return": m["Historical_Return"],
                            "Return_Period": m["Return_Period"],
                            "Div_Yield": 0.0,
                            "Vol_Ratio": m["Vol_Ratio"],
                            "ATR": m["ATR"],
                            "Suggested_Stop": m["Suggested_Stop"]
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ Batch {batch_no} ขัดข้อง: {e}")

        time.sleep(1.5)

    if len(results) > 0:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by=["Status", "Vol_Ratio"], ascending=[True, False])
        final_df.to_csv(CSV_FILE, index=False)
        pass_count = len(final_df[final_df['Status'] == 'PASS'])
        print(f"🎉 สำเร็จ! บันทึก {len(final_df)} ตัวลงใน {CSV_FILE} (ผ่านเกณฑ์: {pass_count} ตัว)")
    else:
        print("❌ ไม่สามารถดึงข้อมูลได้")

if __name__ == "__main__":
    run_screener()
