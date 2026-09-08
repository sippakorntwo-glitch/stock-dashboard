import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import os
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="Personal Daily Trend Terminal",
    page_icon="📈",
    layout="wide"
)

# สั่งให้หน้าเว็บรีเฟรชตัวเองทุก 5 นาที (300,000 มิลลิวินาที) อัตโนมัติ
st_autorefresh(interval=300 * 1000, key="auto_refresh_5min")

CSV_FILE = "daily_watchlist.csv"

# --- คำนวณเวลาที่อัปเดตล่าสุดของไฟล์ CSV (แปลงเป็นเวลาไทย UTC+7) ---
last_updated_str = "ไม่พบข้อมูลเวลา"
if os.path.exists(CSV_FILE):
    mtime = os.path.getmtime(CSV_FILE)
    tz_bkk = timezone(timedelta(hours=7))
    updated_dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone(tz_bkk)
    last_updated_str = updated_dt.strftime("%d/%m/%Y %H:%M:%S (เวลาไทย)")

# --- Header & UI แสดงเวลาอัปเดตล่าสุด ---
header_col1, header_col2 = st.columns([3, 2])

with header_col1:
    st.title("📈 In-House Trend Trading Terminal")
    st.caption("ระบบมอนิเตอร์และวิเคราะห์หุ้น S&P 500, Nasdaq 100 และ US Dividend ETFs/REITs")

with header_col2:
    st.markdown("<div style='text-align: right; padding-top: 15px;'>", unsafe_allow_html=True)
    st.info(f"🕒 **อัปเดตล่าสุดเมื่อ:** `{last_updated_str}`\n\n🔄 *รีเฟรชข้อมูลอัตโนมัติทุก 5 นาที*")
    st.markdown("</div>", unsafe_allow_html=True)

if not os.path.exists(CSV_FILE):
    st.warning("⚠️ ยังไม่พบไฟล์ 'daily_watchlist.csv' กรุณารอการรันสคริปต์อัปเดต")
    st.stop()

df_all = pd.read_csv(CSV_FILE)

if df_all.empty:
    st.error("ไฟล์ daily_watchlist.csv ว่างเปล่า กรุณาสั่งรัน updater ใหม่อีกครั้ง")
    st.stop()

# --- แถบตัวกรอง ---
st.markdown("### 🎛️ Data Filters")
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    asset_type_filter = st.selectbox(
        "🏷️ ประเภทสินทรัพย์:",
        ["ทั้งหมด (All Assets)", "หุ้นสามัญ (Common Stock)", "หุ้น/กองทุนปันผล (Dividend Asset)"]
    )

with col2:
    status_filter = st.radio(
        "⚡ สถานะแนวโน้ม:",
        ["ทั้งหมด", "เฉพาะที่ผ่านเกณฑ์ (PASS Only)"],
        horizontal=True
    )

with col3:
    search_query = st.text_input("🔍 ค้นหา Ticker:", "").strip().upper()

df_filtered = df_all.copy()

if asset_type_filter == "หุ้นสามัญ (Common Stock)":
    df_filtered = df_filtered[df_filtered['Asset_Type'] == 'Common Stock']
elif asset_type_filter == "หุ้น/กองทุนปันผล (Dividend Asset)":
    df_filtered = df_filtered[df_filtered['Asset_Type'] == 'Dividend Asset']

if status_filter == "เฉพาะที่ผ่านเกณฑ์ (PASS Only)":
    df_filtered = df_filtered[df_filtered['Status'] == 'PASS']

if search_query:
    df_filtered = df_filtered[df_filtered['Ticker'].astype(str).str.contains(search_query, na=False)]

st.divider()

# --- ตารางแสดงผลหลัก ---
col_table, col_panel = st.columns([3, 1])

with col_table:
    st.subheader(f"📋 รายการสินทรัพย์ ({len(df_filtered)} ตัว)")
    
    if not df_filtered.empty:
        formatted_df = df_filtered.copy()

        if 'Historical_Return' in formatted_df.columns and 'Return_Period' in formatted_df.columns:
            formatted_df['Return_Display'] = formatted_df.apply(
                lambda r: f"{r['Historical_Return']:+.2f}% ({r['Return_Period']})" if pd.notnull(r['Historical_Return']) else "-",
                axis=1
            )
        elif 'Return_3Y' in formatted_df.columns:
            formatted_df['Return_Display'] = formatted_df['Return_3Y'].apply(
                lambda x: f"{x:+.2f}% (3Y)" if pd.notnull(x) else "-"
            )
        else:
            formatted_df['Return_Display'] = "-"

        available_cols = ['Ticker', 'Asset_Type', 'Status', 'Close', 'Return_Display', 'Div_Yield', 'Vol_Ratio', 'Suggested_Stop']
        render_cols = [c for c in available_cols if c in formatted_df.columns]

        st.dataframe(
            formatted_df[render_cols].style.format({
                "Close": "${:.2f}",
                "Div_Yield": lambda x: f"{x:.2f}%" if pd.notnull(x) and x > 0 else "-",
                "Vol_Ratio": "{:.2f}x",
                "Suggested_Stop": lambda x: f"${x:.2f}" if pd.notnull(x) else "-"
            }),
            column_config={
                "Ticker": st.column_config.Column("Ticker", help="ชื่อย่อหลักทรัพย์"),
                "Asset_Type": st.column_config.Column("Asset Type", help="Common Stock หรือ Dividend Asset"),
                "Status": st.column_config.Column("Status", help="PASS คือผ่านเกณฑ์ครบทุกข้อ / FAIL คือไม่ผ่านเกณฑ์"),
                "Close": st.column_config.Column("Close ($)", help="ราคาปิดล่าสุด (USD)"),
                "Return_Display": st.column_config.Column("Historical Return", help="ผลตอบแทนย้อนหลัง"),
                "Div_Yield": st.column_config.Column("Div Yield (%)", help="อัตราปันผลตอบแทนต่อปี (TTM)"),
                "Vol_Ratio": st.column_config.Column("Vol Ratio", help="Volume ล่าสุด ÷ ค่าเฉลี่ย 20 วัน"),
                "Suggested_Stop": st.column_config.Column("Suggested Stop ($)", help="จุดตัดขาดทุนแนะนำ: Close - (2 x ATR 14)"),
            },
            use_container_width=True,
            height=340,
            hide_index=True
        )
    else:
        st.warning("ไม่พบสินทรัพย์ที่ตรงกับเงื่อนไขตัวกรอง")

with col_panel:
    st.subheader("⚡ Quick Viewer")
    if not df_filtered.empty:
        selected_ticker = st.selectbox("เลือก Ticker ดูกราฟและวิเคราะห์:", df_filtered['Ticker'])
        target_info = df_filtered[df_filtered['Ticker'] == selected_ticker].iloc[0]
        
        status_badge = "🟢 PASS" if target_info['Status'] == 'PASS' else "🔴 FAIL"
        st.markdown(f"**สถานะ:** `{status_badge}` | `{target_info['Asset_Type']}`")
        st.metric("ราคาปิดล่าสุด", f"${target_info['Close']}")
        
        if 'Return_Period' in target_info and pd.notnull(target_info.get('Historical_Return')):
            st.metric(f"ผลตอบแทน ({target_info['Return_Period']})", f"{target_info['Historical_Return']:+.2f}%")
            
        if pd.notnull(target_info.get('Div_Yield')) and target_info['Div_Yield'] > 0:
            st.metric("Dividend Yield (TTM)", f"{target_info['Div_Yield']:.2f}%")
            
        if pd.notnull(target_info.get('Suggested_Stop')):
            st.metric(
                "Suggested Stop (2x ATR)",
                f"${target_info['Suggested_Stop']}",
                delta=f"-${round(target_info['Close'] - target_info['Suggested_Stop'], 2)}",
                delta_color="inverse"
            )
    else:
        st.stop()

st.divider()

# --- กราฟ Candlestick ---
st.subheader(f"📊 กราฟแท่งเทียน: {selected_ticker} (Daily)")

with st.spinner(f"กำลังโหลดข้อมูลกราฟ {selected_ticker}..."):
    df_chart = yf.download(selected_ticker, period="1y", interval="1d", progress=False)
    if isinstance(df_chart.columns, pd.MultiIndex):
        df_chart.columns = df_chart.columns.get_level_values(0)

    df_chart['EMA20'] = df_chart['Close'].ewm(span=20, adjust=False).mean()
    df_chart['EMA50'] = df_chart['Close'].ewm(span=50, adjust=False).mean()
    df_chart['SMA200'] = df_chart['Close'].rolling(window=200).mean() if len(df_chart) >= 200 else np.nan

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="OHLC"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA20'], line=dict(color='#FFA500', width=1.5), name="EMA 20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA50'], line=dict(color='#2196F3', width=1.5), name="EMA 50"), row=1, col=1)
    
    if pd.notnull(df_chart['SMA200']).any():
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA200'], line=dict(color='#E91E63', width=2), name="SMA 200"), row=1, col=1)

    if pd.notnull(target_info.get('Suggested_Stop')):
        fig.add_hline(
            y=target_info['Suggested_Stop'],
            line_dash="dash",
            line_color="red",
            annotation_text=f"Stop: ${target_info['Suggested_Stop']}",
            annotation_position="bottom right",
            row=1, col=1
        )

    vol_colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df_chart['Close'], df_chart['Open'])]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=vol_colors, name="Volume"), row=2, col=1)

    fig.update_layout(height=550, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig, use_container_width=True)

# --- ตารางวิเคราะห์ทางเทคนิครายตัว (Dynamic Insight Engine: Price + % Added) ---
st.subheader(f"🔍 เจาะลึกผลวิเคราะห์เชิงเทคนิคและ Actionable Insights: {selected_ticker}")

curr_c = float(df_chart['Close'].iloc[-1])
curr_o = float(df_chart['Open'].iloc[-1])
curr_e20 = float(df_chart['EMA20'].iloc[-1])
curr_e50 = float(df_chart['EMA50'].iloc[-1])
curr_s200 = float(df_chart['SMA200'].iloc[-1]) if pd.notnull(df_chart['SMA200'].iloc[-1]) else None

# คำนวณส่วนต่างทั้งรูปจำนวนเงิน ($) และเปอร์เซ็นต์ (%)
diff_e20_dollar = round(curr_c - curr_e20, 2)
diff_e20_pct = round(((curr_c - curr_e20) / curr_e20) * 100, 2)

diff_e20_e50_dollar = round(curr_e20 - curr_e50, 2)
diff_e20_e50_pct = round(((curr_e20 - curr_e50) / curr_e50) * 100, 2)

diff_s200_dollar = round(curr_c - curr_s200, 2) if curr_s200 else None
diff_s200_pct = round(((curr_c - curr_s200) / curr_s200) * 100, 2) if curr_s200 else None

# ความชันและค่าเปลี่ยนของ SMA200 ในรอบ 20 วัน
s200_slope = None
s200_diff_dollar = 0.0
s200_diff_pct = 0.0
if curr_s200 is not None and len(df_chart) >= 20 and pd.notnull(df_chart['SMA200'].iloc[-20]):
    old_s200 = float(df_chart['SMA200'].iloc[-20])
    s200_diff_dollar = round(curr_s200 - old_s200, 2)
    s200_diff_pct = round(((curr_s200 - old_s200) / old_s200) * 100, 2)
    s200_slope = curr_s200 > old_s200

vol_ratio = float(target_info['Vol_Ratio'])
vol_diff_pct = round((vol_ratio - 1.0) * 100, 1)

stop_val = target_info.get('Suggested_Stop')
stop_dollar_diff = round(curr_c - float(stop_val), 2) if pd.notnull(stop_val) else None
risk_pct = round((stop_dollar_diff / curr_c) * 100, 2) if stop_dollar_diff is not None else None

# --- กลไกวิเคราะห์ Insights รายข้อ (พร้อมดึงราคาและ % มาอธิบาย) ---
# ข้อ 1
if curr_c > curr_e20:
    c1_status = "✅ ผ่าน"
    if diff_e20_pct > 6.0:
        c1_desc = f"ราคาวิ่งฉีกเหนือแนวรับ EMA20 สูงถึง {diff_e20_dollar:+.2f}$ ({diff_e20_pct:+.2f}%) เริ่มเข้าโซน Overextended ระยะสั้น เสี่ยงโดนแรงขายทำกำไร รอจังหวะย่อตัวใกล้แนวรับปลอดภัยกว่า"
    else:
        c1_desc = f"ราคายืนเหนือ EMA20 ที่ระยะ {diff_e20_dollar:+.2f}$ ({diff_e20_pct:+.2f}%) เป็นระยะแกว่งตัวที่ดี โมเมนตัมฝั่งซื้อยังคุมเทรนด์และยังไม่หลุดแนวย่อแรก"
else:
    c1_status = "❌ ไม่ผ่าน"
    c1_desc = f"ราคาหลุดต่ำกว่า EMA20 อยู่ที่ {diff_e20_dollar:+.2f}$ ({diff_e20_pct:+.2f}%) เสียโมเมนตัมขาขึ้นระยะสั้น แนวโน้มกำลังพักฐานหรือลงไปทดสอบแนวรับลึก"

# ข้อ 2
if curr_e20 > curr_e50:
    c2_status = "✅ ผ่าน"
    c2_desc = f"โครงสร้าง Trend Expansion เส้นสั้นแยกห่างเส้นกลาง {diff_e20_e50_dollar:+.2f}$ ({diff_e20_e50_pct:+.2f}%) สะท้อนแรงส่งรอบ 1-2 เดือนยังเสถียร ไม่พบสัญญาณชะลอตัวของเงินทุนรอบกลาง"
else:
    c2_status = "❌ ไม่ผ่าน"
    c2_desc = f"EMA20 อยู่ใต้ EMA50 {diff_e20_e50_dollar:+.2f}$ ({diff_e20_e50_pct:+.2f}%) สภาวะแนวโน้มระยะกลางอยู่ในช่วงปรับฐานหรือเป็นเทรนด์ขาลง ไม่ใช่จังหวะ Buy & Hold"

# ข้อ 3
if curr_s200 and curr_e50 > curr_s200:
    c3_status = "✅ ผ่าน"
    c3_desc = f"ยืนยันสภาวะ Bull Market Stage 2 ราคาปัจจุบันยืนเหนือฐานทุนสถาบัน 200 วันถึง {diff_s200_dollar:+.2f}$ ({diff_s200_pct:+.2f}%) ภาพใหญ่เป็นขาขึ้นแข็งแกร่ง"
elif curr_s200:
    c3_status = "❌ ไม่ผ่าน"
    c3_desc = f"ราคาหรือ EMA50 ต่ำกว่า SMA200 อยู่ {diff_s200_dollar:+.2f}$ ({diff_s200_pct:+.2f}%) ภาพใหญ่ยังติดอยู่ใน Bear Market การขึ้นมีโอกาสเป็นเพียง Technical Rebound"
else:
    c3_status = "⚠️ ข้อมูลไม่พอ"
    c3_desc = "หุ้นเพิ่งเข้าตลาดไม่ถึง 200 วันทำการ ข้อมูลไม่เพียงพอสำหรับการวิเคราะห์รอบมหภาค"

# ข้อ 4
if s200_slope:
    c4_status = "✅ ผ่าน"
    c4_desc = f"เส้นฐานเฉลี่ยสถาบันยกตัวขึ้น {s200_diff_dollar:+.2f}$ ({s200_diff_pct:+.2f}%) ในรอบเดือน ยืนยันว่ามีเงินทุนสะสมระยะยาว (Net Accumulation) ชัดเจน"
elif s200_slope is False:
    c4_status = "❌ ไม่ผ่าน"
    c4_desc = f"SMA200 ชี้ลง/ทรงตัว ({s200_diff_dollar:+.2f}$ หรือ {s200_diff_pct:+.2f}%) ต้นทุนเฉลี่ยของตลาดยังไหลลง โอกาสเกิด False Breakout ด้านบนมีสูง"
else:
    c4_status = "⚠️ ข้อมูลไม่พอ"
    c4_desc = "ไม่มีข้อมูลประวัติศาสตร์ระยะยาว 200 วัน"

# ข้อ 5
is_bullish_candle = curr_c >= curr_o
if vol_ratio >= 1.05:
    c5_status = "✅ ผ่าน"
    if is_bullish_candle:
        c5_desc = f"Institutional Buying: วอลุ่มหนาแน่นกว่าค่าเฉลี่ย +{vol_diff_pct}% พร้อมแท่งเทียนปิดบวก สะท้อนการเข้าซื้อสะสมของเม็ดเงินใหญ่ (Smart Money)"
    else:
        c5_desc = f"Volume Spike on Pullback: วอลุ่มเข้ามากกว่าปกติ +{vol_diff_pct}% แต่แท่งเทียนปิดลบ มีแรงขายทำกำไรกดดัน ต้องจับตาแนวรับถัดไปอย่างใกล้ชิด"
else:
    c5_status = "❌ ไม่ผ่าน"
    c5_desc = f"วอลุ่มต่ำกว่าเกณฑ์ ({vol_ratio:.2f}x) การเคลื่อนไหวของราคาขาดแรงหนุนจากสถาบัน มักมีความเปราะบางและแกว่งตัวไซด์เวย์"

# ข้อ 6
if risk_pct:
    if risk_pct <= 5.0:
        c6_desc = f"กรอบความเสี่ยงแคบมากเพียง -${stop_dollar_diff:.2f} (-{risk_pct:.2f}%) เหมาะกับการวาง Position Sizing เต็มขนาดความเสี่ยง และให้ Risk/Reward ที่คุ้มค่าสูง"
    elif risk_pct <= 8.0:
        c6_desc = f"ความเสี่ยงระดับปกติของ Swing Trading อยู่ที่ -${stop_dollar_diff:.2f} (-{risk_pct:.2f}%) มีพื้นที่ปลอดภัยจากความผันผวนของราคา (2x ATR)"
    else:
        c6_desc = f"กรอบความเสี่ยงค่อนข้างกว้าง -${stop_dollar_diff:.2f} (-{risk_pct:.2f}%) ความผันผวนสูง ควรแบ่งไม้เข้าหรือลดขนาด Position Size (Half Position)"
else:
    c6_desc = "ไม่มีข้อมูลคำนวณ Stop Loss"

analysis_items = [
    {
        "หมวดหมู่การวิเคราะห์": "1. แนวโน้มระยะสั้น (Short-term)",
        "ตัวชี้วัด / เงื่อนไข": "ราคาปิด ยืนเหนือ EMA 20",
        "ค่าปัจจุบัน": f"Close: ${curr_c:.2f} | EMA20: ${curr_e20:.2f} ({diff_e20_dollar:+.2f}$ / {diff_e20_pct:+.2f}%)",
        "สถานะ": c1_status,
        "คำอธิบาย / นัยสำคัญ": c1_desc
    },
    {
        "หมวดหมู่การวิเคราะห์": "2. แนวโน้มระยะกลาง (Mid-term)",
        "ตัวชี้วัด / เงื่อนไข": "EMA 20 อยู่เหนือ EMA 50",
        "ค่าปัจจุบัน": f"EMA20: ${curr_e20:.2f} | EMA50: ${curr_e50:.2f} ({diff_e20_e50_dollar:+.2f}$ / {diff_e20_e50_pct:+.2f}%)",
        "สถานะ": c2_status,
        "คำอธิบาย / นัยสำคัญ": c2_desc
    },
    {
        "หมวดหมู่การวิเคราะห์": "3. แนวโน้มระยะยาว (Long-term)",
        "ตัวชี้วัด / เงื่อนไข": "EMA 50 ยืนเหนือ SMA 200",
        "ค่าปัจจุบัน": f"EMA50: ${curr_e50:.2f} | SMA200: " + (f"${curr_s200:.2f} ({diff_s200_dollar:+.2f}$ / {diff_s200_pct:+.2f}%)" if curr_s200 else "N/A"),
        "สถานะ": c3_status,
        "คำอธิบาย / นัยสำคัญ": c3_desc
    },
    {
        "หมวดหมู่การวิเคราะห์": "4. ทิศทางเส้นฐานใหญ่ (Trend Slope)",
        "ตัวชี้วัด / เงื่อนไข": "SMA 200 ชันขึ้นเทียบกับ 20 วันก่อน",
        "ค่าปัจจุบัน": f"SMA200 Slope: {s200_diff_dollar:+.2f}$ ({s200_diff_pct:+.2f}%)",
        "สถานะ": c4_status,
        "คำอธิบาย / นัยสำคัญ": c4_desc
    },
    {
        "หมวดหมู่การวิเคราะห์": "5. แรงผลักดันวอลุ่ม (Volume Spike)",
        "ตัวชี้วัด / เงื่อนไข": "Volume วันล่าสุด > เฉลี่ย 20 วัน (เกิน 5%)",
        "ค่าปัจจุบัน": f"Volume Ratio: {target_info['Vol_Ratio']:.2f}x ({vol_diff_pct:+.1f}%)",
        "สถานะ": c5_status,
        "คำอธิบาย / นัยสำคัญ": c5_desc
    },
    {
        "หมวดหมู่การวิเคราะห์": "6. การบริหารความเสี่ยง (Risk / Stop Loss)",
        "ตัวชี้วัด / เงื่อนไข": "จุดตัดขาดทุนแนะนำ (Trailing 2x ATR)",
        "ค่าปัจจุบัน": (f"${stop_val:.2f} (ห่าง -${stop_dollar_diff:.2f} / -{risk_pct:.2f}%)" if stop_val else "N/A"),
        "สถานะ": "🛡️ แนะนำระดับ Stop",
        "คำอธิบาย / นัยสำคัญ": c6_desc
    }
]

df_analysis = pd.DataFrame(analysis_items)

def color_status(val):
    if "✅ ผ่าน" in str(val):
        return 'color: #00e676; font-weight: bold;'
    elif "❌ ไม่ผ่าน" in str(val):
        return 'color: #ff5252; font-weight: bold;'
    elif "🛡️" in str(val):
        return 'color: #40c4ff; font-weight: bold;'
    return 'color: #ffab40;'

if hasattr(df_analysis.style, 'map'):
    styled_analysis = df_analysis.style.map(color_status, subset=['สถานะ'])
else:
    styled_analysis = df_analysis.style.applymap(color_status, subset=['สถานะ'])

st.dataframe(
    styled_analysis,
    use_container_width=True,
    hide_index=True
)
