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
    print("🌐 กำลังดึงรายชื่อหุ้นสหรัฐฯ จาก NASDAQ Trader Directory...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    tickers = []
    
    try:
        url_nasdaq = "https://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
        res = requests.get(url_nasdaq, headers=headers, timeout=15)
        df_nasdaq = pd.read_csv(io.StringIO(res.text), sep="|")
        df_nasdaq = df_nasdaq[(df_nasdaq['Test Issue'] == 'N') & (df_nasdaq['Symbol'].notnull())]
        tickers.extend(df_nasdaq['Symbol'].astype(str).str.strip().tolist())
    except Exception as e:
        print(f"⚠️ ดึง NASDAQ ไม่สำเร็จ: {e}")

    try:
        url_other = "https://ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt"
        res = requests.get(url_other, headers=headers, timeout=15)
        df_other = pd.read_csv(io.StringIO(res.text), sep="|")
        df_other = df_other[(df_other['Test Issue'] == 'N') & (df_other['ACT Symbol'].notnull())]
        tickers.extend(df_other['ACT Symbol'].astype(str).str.strip().tolist())
    except Exception as e:
        print(f"⚠️ ดึง Other Listed ไม่สำเร็จ: {e}")

    clean_tickers = []
    for t in tickers:
        t = t.replace('$', '-P').replace('.', '-')
        if any(c in t for c in ['=', '+', '*', '~', ' ']):
            continue
        if len(t) > 5:
            continue
        clean_tickers.append(t)

    clean_tickers = list(dict.fromkeys(clean_tickers))
    print(f"✅ พบหุ้นทั้งหมดในตลาด {len(clean_tickers)} ตัว กำลังเลือก {max_count} ตัว...")
    return clean_tickers[:max_count]

def calculate_technical_metrics(df):
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
    print(f"🚀 เริ่มกระบวนการสแกนหุ้น {total} ตัว (แบ่ง {total // BATCH_SIZE + 1} Batches)...")

    results = []

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i+BATCH_SIZE]
        batch_no = (i // BATCH_SIZE) + 1
        total_batches = (total // BATCH_SIZE) + 1
        print(f"📦 Batch {batch_no}/{total_batches} ({len(batch)} Tickers)...")

        try:
            data = yf.download(batch, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
            
            for t in batch:
                try:
                    if t not in data.columns.levels[0]:
                        continue
                    sub_df = data[t].dropna(subset=['Close'])
                    if len(sub_df) < 60:
                        continue

                    if float(sub_df['Close'].iloc[-1]) < 2.0:
                        continue

                    metrics = calculate_technical_metrics(sub_df)
                    if metrics:
                        results.append({
                            "Ticker": t,
                            "Asset_Type": "Common Stock",
                            "Status": metrics["Status"],
                            "Close": metrics["Close"],
                            "Historical_Return": metrics["Historical_Return"],
                            "Return_Period": metrics["Return_Period"],
                            "Div_Yield": 0.0,
                            "Vol_Ratio": metrics["Vol_Ratio"],
                            "ATR": metrics["ATR"],
                            "Suggested_Stop": metrics["Suggested_Stop"]
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"⚠️ Batch {batch_no} ผิดพลาด: {e}")

        time.sleep(1.5)

    if results:
        final_df = pd.DataFrame(results)
        final_df = final_df.sort_values(by=["Status", "Vol_Ratio"], ascending=[True, False])
        final_df.to_csv(CSV_FILE, index=False)
        pass_count = len(final_df[final_df['Status'] == 'PASS'])
        print(f"🎉 สแกนเสร็จสิ้น! บันทึกข้อมูล {len(final_df)} ตัวลงใน {CSV_FILE} (ผ่านเกณฑ์ PASS: {pass_count} ตัว)")
    else:
        print("❌ ไม่พบข้อมูลจากการสแกน")

if __name__ == "__main__":
    run_screener()
