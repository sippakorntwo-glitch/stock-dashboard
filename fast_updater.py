import yfinance as yf
import pandas as pd
import numpy as np
import os

CSV_FILE = "daily_watchlist.csv"

def fast_update():
    if not os.path.exists(CSV_FILE):
        print("⚠️ ไม่พบไฟล์ daily_watchlist.csv ข้ามการอัปเดต")
        return

    df = pd.read_csv(CSV_FILE)
    if 'Ticker' not in df.columns or df.empty:
        print("⚠️ ข้อมูลใน CSV ไม่ถูกต้องหรือว่างเปล่า")
        return

    tickers = df['Ticker'].dropna().astype(str).tolist()
    total = len(tickers)
    
    print(f"⚡ เริ่มดึงราคาล่าสุดรอบ 5 นาที ({total} รายการ)...")
    
    # ดึงข้อมูลย้อนหลัง 5 วัน เพื่อนำแท่งเทียนวันล่าสุดมาอัปเดตอย่างรวดเร็ว
    data = yf.download(tickers, period="5d", interval="1d", group_by="ticker", threads=True, progress=False)

    updated_count = 0
    for idx, row in df.iterrows():
        t = str(row['Ticker'])
        try:
            if t not in data.columns.levels[0]:
                continue
            
            sub_df = data[t].dropna(subset=['Close'])
            if sub_df.empty:
                continue

            latest_close = round(float(sub_df['Close'].iloc[-1]), 2)
            df.at[idx, 'Close'] = latest_close
            
            # อัปเดต Volume Ratio หากมีข้อมูล Volume
            if 'Volume' in sub_df.columns and not sub_df['Volume'].dropna().empty:
                latest_vol = float(sub_df['Volume'].iloc[-1])
                # อ้างอิง ATR / Vol_SMA หากมีอยู่ในตารางเดิม
                if 'ATR' in row and pd.notnull(row['ATR']):
                    df.at[idx, 'Suggested_Stop'] = round(latest_close - (2 * float(row['ATR'])), 2)

            updated_count += 1
        except Exception:
            continue

    df.to_csv(CSV_FILE, index=False)
    print(f"✅ อัปเดตราคาสำเร็จ {updated_count} รายการลงใน {CSV_FILE}")

if __name__ == "__main__":
    fast_update()