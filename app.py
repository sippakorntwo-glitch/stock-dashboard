import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import os
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Ultimate Trend Terminal", page_icon="📈", layout="wide")
count = st_autorefresh(interval=300 * 1000, key="data_refresher_5min")

CSV_FILE = "daily_watchlist.csv"

def get_file_mtime():
    if os.path.exists(CSV_FILE): return os.path.getmtime(CSV_FILE)
    return 0

@st.cache_data(ttl=60)
def load_data(file_mtime):
    if not os.path.exists(CSV_FILE): return pd.DataFrame()
    return pd.read_csv(CSV_FILE)

current_mtime = get_file_mtime()
last_updated_str = "ไม่พบข้อมูลเวลา"

if current_mtime > 0:
    tz_bkk = timezone(timedelta(hours=7))
    updated_dt = datetime.fromtimestamp(current_mtime, tz=timezone.utc).astimezone(tz_bkk)
    last_updated_str = updated_dt.strftime("%d/%m/%Y %H:%M:%S (เวลาไทย)")

header_col1, header_col2 = st.columns([3, 2])
with header_col1:
    st.title("📈 Ultimate Trend Trading Terminal")
    st.caption("ระบบวิเคราะห์หุ้นสหรัฐฯ 4,500 ตัว พร้อม Fundamental, Risk Management และ Custom Filters")

with header_col2:
    st.markdown("<div style='text-align: right; padding-top: 15px;'>", unsafe_allow_html=True)
    st.info(f"🕒 **อัปเดตล่าสุดเมื่อ:** `{last_updated_str}`\n\n🔄 *รีเฟรชทุก 5 นาที (รอบ: {count})*")
    st.markdown("</div>", unsafe_allow_html=True)

df_all = load_data(current_mtime)
if df_all.empty:
    st.warning("⚠️ ยังไม่พบข้อมูล กรุณารอการรันสคริปต์สแกน")
    st.stop()

# ==========================================
# 🎛️ โซนตัวกรองข้อมูล (Filters)
# ==========================================
st.markdown("### 🎛️ Data Filters (ระบบคัดกรองข้อมูล)")
col1, col2, col3 = st.columns([2, 2, 2])
with col1:
    asset_types = ["ทั้งหมด (All Assets)"] + sorted(list(df_all['Asset_Type'].dropna().unique()))
    asset_type_filter = st.selectbox("🏷️ ประเภทสินทรัพย์:", asset_types)
with col2:
    status_filter = st.radio("⚡ สถานะแนวโน้ม:", ["ทั้งหมด", "เฉพาะที่ผ่านเกณฑ์ (PASS Only)"], horizontal=True)
with col3:
    search_query = st.text_input("🔍 ค้นหา Ticker (พิมพ์ชื่อหุ้น):", "").strip().upper()

with st.expander("🛠️ ตัวกรองขั้นสูง (Advanced Custom Filters) - คลิกเพื่อเปิด/ปิด", expanded=False):
    adv_c1, adv_c2, adv_c3 = st.columns(3)
    
    with adv_c1:
        st.markdown("**1. ช่วงราคา (Price Range)**")
        min_price = st.number_input("ราคาขั้นต่ำ ($)", min_value=0.0, value=0.0, step=1.0)
        max_price = st.number_input("ราคาสูงสุด ($)", min_value=0.1, value=5000.0, step=1.0)

    with adv_c2:
        st.markdown("**2. โมเมนตัม (RSI 14)**")
        rsi_range = st.slider("เลือกช่วง RSI (ต่ำกว่า 30 = Oversold)", 0, 100, (0, 100))

    with adv_c3:
        st.markdown("**3. ผลตอบแทนย้อนหลัง 1 ปี (1Y Return %)**")
        min_return = st.number_input("ผลตอบแทนขั้นต่ำ (%)", value=-100.0, step=10.0)

df_filtered = df_all.copy()

if asset_type_filter != "ทั้งหมด (All Assets)": 
    df_filtered = df_filtered[df_filtered['Asset_Type'] == asset_type_filter]
if status_filter == "เฉพาะที่ผ่านเกณฑ์ (PASS Only)": 
    df_filtered = df_filtered[df_filtered['Status'] == 'PASS']
if search_query: 
    df_filtered = df_filtered[df_filtered['Ticker'].astype(str).str.contains(search_query, na=False)]

df_filtered = df_filtered[(df_filtered['Close'] >= min_price) & (df_filtered['Close'] <= max_price)]

if 'RSI_14' in df_filtered.columns:
    df_filtered = df_filtered[
        (df_filtered['RSI_14'].isna()) | 
        ((df_filtered['RSI_14'] >= rsi_range[0]) & (df_filtered['RSI_14'] <= rsi_range[1]))
    ]

if 'Historical_Return' in df_filtered.columns:
    df_filtered = df_filtered[
        (df_filtered['Historical_Return'].isna()) | 
        (df_filtered['Historical_Return'] >= min_return)
    ]

st.divider()

# ==========================================
# 📊 โซนแสดงผลและกราฟ (UI หลัก)
# ==========================================
col_table, col_panel = st.columns([2.5, 1.5])

with col_table:
    st.subheader(f"📋 รายการสินทรัพย์ที่ผ่านเงื่อนไข ({len(df_filtered):,} ตัว)")
    if not df_filtered.empty:
        formatted_df = df_filtered.copy()
        if 'Historical_Return' in formatted_df.columns:
            formatted_df['Return_Display'] = formatted_df.apply(lambda r: f"{r['Historical_Return']:+.2f}%" if pd.notnull(r['Historical_Return']) else "-", axis=1)
        
        show_cols = ['Ticker', 'Asset_Type', 'Status', 'Close', 'Return_Display', 'Vol_Ratio', 'RSI_14']
        render_cols = [c for c in show_cols if c in formatted_df.columns]

        # สร้าง Styler เบื้องต้น
        styled_df = formatted_df[render_cols].style.format({
            "Close": "${:.2f}",
            "Vol_Ratio": "{:.2f}x",
            "RSI_14": "{:.2f}"
        })

        # 🌟 แก้ไข Error Applymap/Map (ดักจับเวอร์ชัน Pandas)
        if 'RSI_14' in render_cols:
            def rsi_color(val):
                if pd.notnull(val) and val > 70: return 'color: #ef5350'
                elif pd.notnull(val) and val < 30: return 'color: #26a69a'
                return ''
                
            if hasattr(styled_df, "map"):
                styled_df = styled_df.map(rsi_color, subset=['RSI_14'])
            else:
                styled_df = styled_df.applymap(rsi_color, subset=['RSI_14'])

        st.dataframe(styled_df, use_container_width=True, height=450, hide_index=True)
    else:
        st.warning("ไม่พบสินทรัพย์ที่ตรงกับเงื่อนไขการกรองของคุณ ปรับช่วงราคาหรือ RSI ให้กว้างขึ้นครับ")

with col_panel:
    st.subheader("⚡ Quick Viewer & Risk Manager")
    if not df_filtered.empty:
        selected_ticker = st.selectbox("เลือก Ticker เพื่อเจาะลึก:", df_filtered['Ticker'])
        target_info = df_filtered[df_filtered['Ticker'] == selected_ticker].iloc[0]
        
        with st.spinner("กำลังดึงข้อมูลพื้นฐาน (Fundamentals)..."):
            try:
                tkr = yf.Ticker(selected_ticker)
                info = tkr.info
                sector = info.get('sector', 'ETF / Not Available')
                fwd_pe = info.get('forwardPE', 'N/A')
                target_price = info.get('targetMeanPrice', None)
                div_yield = info.get('dividendYield', None)
            except:
                sector, fwd_pe, target_price, div_yield = "N/A", "N/A", None, None
            
            curr_c = target_info['Close']
            upside = f"{round(((target_price - curr_c)/curr_c)*100, 2)}%" if target_price else "N/A"
            div_pct = f"{round(div_yield * 100, 2)}%" if div_yield else "N/A"

        st.markdown(f"**Sector:** `{sector}` | **Type:** `{target_info['Asset_Type']}`")
        
        m_col1, m_col2 = st.columns(2)
        m_col1.metric("ราคาปัจจุบัน", f"${curr_c}")
        m_col2.metric("Target Price (Wall St.)", f"${target_price}" if target_price else "N/A", delta=upside if upside != "N/A" else None)
        
        m_col3, m_col4 = st.columns(2)
        m_col3.metric("Forward P/E", f"{round(fwd_pe,2)}x" if isinstance(fwd_pe, (int, float)) else "N/A")
        m_col4.metric("Dividend Yield", div_pct)

        st.divider()
        st.markdown("#### 💰 ระบบคำนวณหน้าตัก (Position Sizer)")
        port_size = st.number_input("ขนาดพอร์ตลงทุนรวม (USD):", value=10000, step=1000)
        risk_pct = st.slider("ความเสี่ยงต่อไม้ (% ของพอร์ต):", 0.5, 5.0, 1.0, 0.5)
        
        stop_val = target_info.get('Suggested_Stop')
        if pd.notnull(stop_val) and curr_c > stop_val:
            risk_amt = port_size * (risk_pct / 100)
            risk_per_share = curr_c - stop_val
            shares_to_buy = int(risk_amt // risk_per_share)
            capital_required = shares_to_buy * curr_c
            
            st.success(f"**คำแนะนำการเข้าซื้อ:**")
            st.write(f"• จุดตัดขาดทุน (Stop Loss): **${stop_val}**")
            st.write(f"• ซื้อได้สูงสุด: **{shares_to_buy} หุ้น**")
            st.write(f"• ใช้เงินลงทุน: **${capital_required:,.2f}**")
            st.write(f"• ขาดทุนสูงสุดหากโดน Stop: **-${risk_amt:,.2f}**")
        else:
            st.warning("ไม่มีข้อมูล Stop Loss หรือราคาต่ำกว่าจุด Stop")
    else:
        st.stop()

st.divider()

tab1, tab2 = st.tabs(["📊 Advanced Technical Chart", "🥊 Relative Strength (vs SPY)"])

with tab1:
    with st.spinner(f"กำลังวาดกราฟ {selected_ticker}..."):
        df_chart = yf.download(selected_ticker, period="1y", interval="1d", progress=False)
        if isinstance(df_chart.columns, pd.MultiIndex): df_chart.columns = df_chart.columns.get_level_values(0)

        df_chart['EMA20'] = df_chart['Close'].ewm(span=20, adjust=False).mean()
        df_chart['EMA50'] = df_chart['Close'].ewm(span=50, adjust=False).mean()
        df_chart['SMA200'] = df_chart['Close'].rolling(window=200).mean() if len(df_chart) >= 200 else np.nan
        
        df_chart['MACD'] = df_chart['Close'].ewm(span=12).mean() - df_chart['Close'].ewm(span=26).mean()
        df_chart['Signal'] = df_chart['MACD'].ewm(span=9).mean()
        df_chart['Hist'] = df_chart['MACD'] - df_chart['Signal']

        delta = df_chart['Close'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / avg_loss
        df_chart['RSI'] = 100 - (100 / (1 + rs))

        recent_90d = df_chart.iloc[-60:]
        res_level = recent_90d['High'].max()
        sup_level = recent_90d['Low'].min()

        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.15, 0.2, 0.15])
        
        fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name="Price"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA20'], line=dict(color='orange', width=1), name="EMA 20"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA50'], line=dict(color='blue', width=1), name="EMA 50"), row=1, col=1)
        if pd.notnull(df_chart['SMA200']).any(): fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA200'], line=dict(color='pink', width=2), name="SMA 200"), row=1, col=1)
        
        fig.add_hline(y=res_level, line_dash="dot", line_color="green", annotation_text="Auto Resistance", row=1, col=1)
        fig.add_hline(y=sup_level, line_dash="dot", line_color="red", annotation_text="Auto Support", row=1, col=1)
        
        if pd.notnull(stop_val):
            fig.add_hline(y=stop_val, line_dash="dash", line_color="red", annotation_text="Trailing Stop", row=1, col=1)

        vol_colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df_chart['Close'], df_chart['Open'])]
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=vol_colors, name="Volume"), row=2, col=1)

        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['MACD'], line=dict(color='blue', width=1.5), name="MACD"), row=3, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Signal'], line=dict(color='orange', width=1.5), name="Signal"), row=3, col=1)
        hist_colors = ['#26a69a' if val >= 0 else '#ef5350' for val in df_chart['Hist']]
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Hist'], marker_color=hist_colors, name="Histogram"), row=3, col=1)

        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['RSI'], line=dict(color='purple', width=1.5), name="RSI"), row=4, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=4, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=4, col=1)

        fig.update_layout(height=800, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=30, b=20), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader(f"🥊 ความแข็งแกร่งเทียบกับตลาดรวม ({selected_ticker} vs SPY)")
    with st.spinner("กำลังดึงข้อมูล S&P 500 (SPY)..."):
        spy_df = yf.download("SPY", period="1y", interval="1d", progress=False)
        if isinstance(spy_df.columns, pd.MultiIndex): spy_df.columns = spy_df.columns.get_level_values(0)
        
        stock_pct = (df_chart['Close'] / df_chart['Close'].iloc[0] - 1) * 100
        spy_pct = (spy_df['Close'] / spy_df['Close'].iloc[0] - 1) * 100
        
        fig_rs = go.Figure()
        fig_rs.add_trace(go.Scatter(x=df_chart.index, y=stock_pct, mode='lines', name=selected_ticker, line=dict(color='#2196F3', width=2.5)))
        fig_rs.add_trace(go.Scatter(x=spy_df.index, y=spy_pct, mode='lines', name="SPY (Market)", line=dict(color='#FFA500', width=2, dash='dash')))
        
        fig_rs.update_layout(height=400, yaxis_title="Performance (%)", hovermode="x unified")
        st.plotly_chart(fig_rs, use_container_width=True)
