import yfinance as yf
import pandas as pd
import numpy as np
import os
import requests
import json
from datetime import datetime, timezone, timedelta

CSV_FILE = "daily_watchlist.csv"

def send_line_notification(passed_items):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not token or not user_id:
        return

    if not passed_items:
        return

    tz_bkk = timezone(timedelta(hours=7))
    time_now = datetime.now(tz=timezone.utc).astimezone(tz_bkk).strftime("%H:%M:%S")

    msg_lines = [
        f"🚨 [Stock Alert] หุ้นผ่านเกณฑ์ PASS รอบ {time_now}",
        f"พบทั้งหมด: {len(passed_items)} ตัว\n"
    ]

    for item in passed_items[:10]:  # จำกัดไม่เกิน 10 ตัวแรกต่อข้อความ ป้องกันข้อความยาวเกิน
        ticker = item.get('Ticker', '-')
        close = item.get('Close', 0.0)
        stop = item.get('Suggested_Stop', 0.0)
        vol = item.get('Vol_Ratio', 1.0)
        msg_lines.append(
            f"🟢 {ticker}\n"
            f"   • ราคา: ${close:.2f}\n"
            f"   • Stop Loss: ${stop:.2f}\n"
            f"   • Volume: {vol:.2f}x\n"
        )

    if len(passed_items) > 10:
        msg_lines.append(f"...และอีก {len(passed_items) - 10} ตัว ตรวจสอบเพิ่มเติมบน Dashboard")
        
    msg_lines.append("📊 เปิดดูแอป: https://my-stock-terminal.streamlit.app")
    full_message = "\n".join(msg_lines)

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": full_message}]
    }

    try:
        requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    except Exception as e:
        print(f"⚠️ ส่ง LINE Error: {e}")

def fast_update():
    if not os.path.exists(CSV_FILE):
        print("⚠️ ไม่พบไฟล์ daily_watchlist.csv ข้ามการอัปเดต")
        return

    df = pd.read_csv(CSV_FILE)
    if 'Ticker' not in df.columns or df.empty:
        print("⚠️ ข้อมูลใน CSV ว่างเปล่า")
        return

    tickers = df['Ticker'].dropna().astype(str).tolist()
    total = len(tickers)
    
    print(f"⚡ เริ่มอัปเดตราคาล่าสุด ({total} รายการ)...")
    
    # แบ่งรอบดึงราคาทีละ 250 ตัว เพื่อความเสถียร
    batch_size = 250
    updated_count = 0
    passed_list = []

    for i in range(0, total, batch_size):
        sub_tickers = tickers[i:i+batch_size]
        try:
            data = yf.download(sub_tickers, period="5d", interval="1d", group_by="ticker", threads=True, progress=False)
            
            for idx in range(i, min(i+batch_size, total)):
                row = df.iloc[idx]
                t = str(row['Ticker'])
                try:
                    if t not in data.columns.levels[0]:
                        continue
                    sub_df = data[t].dropna(subset=['Close'])
                    if sub_df.empty:
                        continue

                    latest_close = round(float(sub_df['Close'].iloc[-1]), 2)
                    df.at[idx, 'Close'] = latest_close
                    
                    if 'ATR' in row and pd.notnull(row['ATR']):
                        df.at[idx, 'Suggested_Stop'] = round(latest_close - (2 * float(row['ATR'])), 2)

                    if row.get('Status') == 'PASS':
                        passed_list.append({
                            'Ticker': t,
                            'Close': latest_close,
                            'Suggested_Stop': df.at[idx, 'Suggested_Stop'] if 'Suggested_Stop' in df.columns else None,
                            'Vol_Ratio': row.get('Vol_Ratio', 1.0)
                        })

                    updated_count += 1
                except Exception:
                    continue
        except Exception:
            continue

    df.to_csv(CSV_FILE, index=False)
    print(f"✅ อัปเดตราคาสำเร็จ {updated_count}/{total} รายการลงใน {CSV_FILE}")

    send_line_notification(passed_list)

if __name__ == "__main__":
    fast_update()
