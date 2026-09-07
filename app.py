import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import os

st.set_page_config(
    page_title="Personal Daily Trend Terminal",
    page_icon="📈",
    layout="wide"
)

st.title("📈 In-House Daily Trend Trading Terminal")
st.caption("ระบบมอนิเตอร์และวิเคราะห์หุ้น S&P 500, Nasdaq 100 และ US Dividend ETFs/REITs")

CSV_FILE = "daily_watchlist.csv"

if not os.path.exists(CSV_FILE):
    st.warning("⚠️ ยังไม่พบไฟล์ 'daily_watchlist.csv' กรุณาสั่งรัน screener.py ใน Terminal ก่อน")
    st.stop()

df_all = pd.read_csv(CSV_FILE)

if df_all.empty:
    st.error("ไฟล์ daily_watchlist.csv ว่างเปล่า กรุณาสั่งรัน screener.py ใหม่อีกครั้ง")
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
                "Asset_Type": st.column_config.Column("Asset Type", help="Common Stock (หุ้นสามัญ) หรือ Dividend Asset (กองทุนปันผล/REITs)"),
                "Status": st.column_config.Column("Status", help="PASS คือผ่านเกณฑ์ครบทุกข้อ / FAIL คือไม่ผ่านเกณฑ์"),
                "Close": st.column_config.Column("Close ($)", help="ราคาปิดล่าสุด (USD)"),
                "Return_Display": st.column_config.Column("Historical Return", help="ผลตอบแทนย้อนหลัง: (3Y)=3ปี, (2Y)=2ปี, (1Y)=1ปี, (<1Y)=ตั้งแต่เข้าตลาด"),
                "Div_Yield": st.column_config.Column("Div Yield (%)", help="อัตราปันผลตอบแทนต่อปี (TTM) 12 เดือนล่าสุด"),
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

# --- ตารางวิเคราะห์ทางเทคนิครายตัว (Deep-Dive Analysis Table) ---
st.subheader(f"🔍 เจาะลึกผลวิเคราะห์เชิงเทคนิค: {selected_ticker}")

curr_c = float(df_chart['Close'].iloc[-1])
curr_e20 = float(df_chart['EMA20'].iloc[-1])
curr_e50 = float(df_chart['EMA50'].iloc[-1])
curr_s200 = float(df_chart['SMA200'].iloc[-1]) if pd.notnull(df_chart['SMA200'].iloc[-1]) else None

s200_slope = None
if curr_s200 is not None and len(df_chart) >= 20 and pd.notnull(df_chart['SMA200'].iloc[-20]):
    s200_slope = curr_s200 > float(df_chart['SMA200'].iloc[-20])

stop_val = target_info.get('Suggested_Stop')
risk_pct = round(((curr_c - float(stop_val)) / curr_c) * 100, 2) if pd.notnull(stop_val) else None

analysis_items = [
    {
        "หมวดหมู่การวิเคราะห์": "1. แนวโน้มระยะสั้น (Short-term)",
        "ตัวชี้วัด / เงื่อนไข": "ราคาปิด ยืนเหนือ EMA 20",
        "ค่าปัจจุบัน": f"Close: ${curr_c:.2f} | EMA20: ${curr_e20:.2f}",
        "สถานะ": "✅ ผ่าน" if curr_c > curr_e20 else "❌ ไม่ผ่าน",
        "คำอธิบาย / นัยสำคัญ": "สะท้อนแรงส่งของราคาในรอบ 1 เดือน หากยืนได้แสดงว่าโมเมนตัมฝั่งซื้อยังคุมอยู่"
    },
    {
        "หมวดหมู่การวิเคราะห์": "2. แนวโน้มระยะกลาง (Mid-term)",
        "ตัวชี้วัด / เงื่อนไข": "EMA 20 อยู่เหนือ EMA 50",
        "ค่าปัจจุบัน": f"EMA20: ${curr_e20:.2f} | EMA50: ${curr_e50:.2f}",
        "สถานะ": "✅ ผ่าน" if curr_e20 > curr_e50 else "❌ ไม่ผ่าน",
        "คำอธิบาย / นัยสำคัญ": "รอบการแกว่งตัว 1-2 เดือนเป็นขาขึ้น ต้นทุนผู้เล่นระยะสั้นสูงกว่าระยะกลาง"
    },
    {
        "หมวดหมู่การวิเคราะห์": "3. แนวโน้มระยะยาว (Long-term)",
        "ตัวชี้วัด / เงื่อนไข": "EMA 50 ยืนเหนือ SMA 200",
        "ค่าปัจจุบัน": f"EMA50: ${curr_e50:.2f} | SMA200: " + (f"${curr_s200:.2f}" if curr_s200 else "N/A"),
        "สถานะ": ("✅ ผ่าน" if (curr_s200 and curr_e50 > curr_s200) else ("❌ ไม่ผ่าน" if curr_s200 else "⚠️ ข้อมูลไม่พอ")),
        "คำอธิบาย / นัยสำคัญ": "Golden Cross ภาพใหญ่ ยืนยันวัฏจักร Bull Market ระยะยาว"
    },
    {
        "หมวดหมู่การวิเคราะห์": "4. ทิศทางเส้นฐานใหญ่ (Trend Slope)",
        "ตัวชี้วัด / เงื่อนไข": "SMA 200 ชันขึ้นเทียบกับ 20 วันก่อน",
        "ค่าปัจจุบัน": "SMA200 มีความชันขึ้น" if s200_slope else ("SMA200 ชี้ลง/ไซด์เวย์" if s200_slope is False else "N/A"),
        "สถานะ": ("✅ ผ่าน" if s200_slope else ("❌ ไม่ผ่าน" if s200_slope is False else "⚠️ ข้อมูลไม่พอ")),
        "คำอธิบาย / นัยสำคัญ": "ป้องกันการติดกับดัก False Breakout ในช่วงที่ภาพรวมตลาดยังเป็นขาลง"
    },
    {
        "หมวดหมู่การวิเคราะห์": "5. แรงผลักดันวอลุ่ม (Volume Spike)",
        "ตัวชี้วัด / เงื่อนไข": "Volume วันล่าสุด > เฉลี่ย 20 วัน (เกิน 5%)",
        "ค่าปัจจุบัน": f"Volume Ratio: {target_info['Vol_Ratio']:.2f}x",
        "สถานะ": "✅ ผ่าน" if target_info['Vol_Ratio'] >= 1.05 else "❌ ไม่ผ่าน",
        "คำอธิบาย / นัยสำคัญ": "ยืนยันการมีส่วนร่วมของสถาบันหรือผู้เล่นใหญ่ ไม่ใช่การเคลื่อนไหวแบบไร้วอลุ่ม"
    },
    {
        "หมวดหมู่การวิเคราะห์": "6. การบริหารความเสี่ยง (Risk / Stop Loss)",
        "ตัวชี้วัด / เงื่อนไข": "จุดตัดขาดทุนแนะนำ (Trailing 2x ATR)",
        "ค่าปัจจุบัน": (f"${stop_val:.2f} (ความเสี่ยง -{risk_pct:.2f}%)" if stop_val else "N/A"),
        "สถานะ": "🛡️ แนะนำระดับ Stop",
        "คำอธิบาย / นัยสำคัญ": "ระยะความปลอดภัยจากความผันผวน หากหลุดระดับนี้ควรลดสถานะหรือยอม Stop Loss"
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

# ตรวจสอบเมธอดสำหรับ Pandas 2.1+ (.map) และเวอร์ชันเดิม (.applymap)
if hasattr(df_analysis.style, 'map'):
    styled_analysis = df_analysis.style.map(color_status, subset=['สถานะ'])
else:
    styled_analysis = df_analysis.style.applymap(color_status, subset=['สถานะ'])

st.dataframe(
    styled_analysis,
    use_container_width=True,
    hide_index=True
)