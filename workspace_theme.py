"""Scoped, accessible color accents without hiding controls or changing values."""
from __future__ import annotations
import streamlit as st

CSS = '''
<style id="workspace-theme-v22">
:root { --ws-cyan:#6cddf5; --ws-violet:#baadff; --ws-text:#eaf2ff; --ws-muted:#b4c5dc; }
.stApp { background:radial-gradient(ellipse at 12% 0%,#152340 0,transparent 48%),#090f1e; color:var(--ws-text); }
.block-container { padding-top:2rem; padding-bottom:3rem; max-width:1720px; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#101d35,#0c1427); border-right:1px solid #283c5b; }
h1 { color:#a6eaff !important; letter-spacing:-.04em; font-weight:760 !important; }
h2 { border-left:4px solid var(--ws-cyan); padding-left:.8rem !important; margin-top:1.2rem !important; }
h3 { color:#d6d0ff !important; }
[data-testid="stCaptionContainer"] { color:var(--ws-muted); }
[data-testid="stMetric"] { background:linear-gradient(130deg,#172844,#111c33); border:1px solid #344c70; border-top:3px solid #6cddf5; border-radius:15px; padding:15px 16px; box-shadow:0 7px 22px #00000020; }
[data-testid="stMetricValue"] { color:#e8f5ff; font-size:1.8rem; font-weight:700; }
[data-testid="stMetricLabel"] { color:#bed1eb; }
[data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] { border-top-color:#ad9bff; }
[data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"] { border-top-color:#70e4bd; }
[data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"] { border-top-color:#ffce80; }
[data-testid="stExpander"] { background:#101a2e; border-radius:12px; border-color:#354664; }
[data-testid="stExpander"] summary { color:#bcecf8; }
[data-testid="stTextInput"] input,[data-testid="stNumberInput"] input { border-radius:8px; }
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button { border:1px solid #4c638b; border-radius:9px; color:#e4efff; background:#192943; transition:background .15s,border-color .15s; }
[data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover { background:#253958; border-color:#74d6ec; color:#fff; }
button:focus-visible,a:focus-visible,input:focus-visible { outline:3px solid #ffdb8c !important; outline-offset:3px; }
.st-key-ranking_board { background:linear-gradient(150deg,#1a2344,#101b30); border:1px solid #6d6098 !important; border-radius:16px; }
.st-key-ranking_board [data-testid="stVerticalBlock"] { gap:.3rem; }
.st-key-ranking_board [data-testid="stButton"] button { min-height:2rem; padding:.22rem .6rem; text-align:left; }
.st-key-ranking_board [data-testid="stButton"] p { font-size:.84rem; }
.st-key-ranking_board h3 { font-size:1.18rem; }
.st-key-stock_picker_table { border:1px solid #354968; border-radius:12px; overflow:hidden; }
.st-key-overview_controls { background:#111c30; border:1px solid #304460; border-radius:14px; padding:16px; margin-top:10px; }
.st-key-minute_quote_panel { background:linear-gradient(110deg,#112d3c,#192441 62%,#282141); border:1px solid #477594 !important; border-radius:17px; padding:1rem 1.2rem; }
.quote-symbol { font-size:1.05rem; color:#a7ddeb; font-weight:650; letter-spacing:.06em; }
.quote-symbol span { color:#c3bddf; font-weight:400; padding-left:.5rem; }
.quote-price { font-size:2.7rem; color:#f3faff; font-variant-numeric:tabular-nums; font-weight:750; }
.quote-delta { font-size:1.1rem; padding-left:1rem; color:#cfdcf0; font-weight:500; }
.screener-ready { display:block; margin:.5rem 0; padding:.6rem .8rem; border-left:3px solid #70e4bd; border-radius:6px; background:#122c35; color:#c9f2e5; font-size:.8rem; }
.workspace-nav { display:flex; flex-wrap:wrap; gap:.6rem; margin:.6rem 0 1rem; }
.workspace-nav a { color:#d6eeff; background:#152541; border:1px solid #3e567a; border-radius:20px; padding:.38rem .85rem; text-decoration:none; font-size:.86rem; }
.workspace-nav a:hover { color:#fff; border-color:#9f9cf2; background:#273157; }
.workspace-help-table { border-radius:10px; }
.workspace-help-table th { background:#1e3150 !important; color:#d8efff !important; }
.workspace-help-table tr:nth-child(even) td { background:#101c2e; }
hr { border-color:#2b3c58 !important; }
@media(max-width:760px) { .block-container { padding:1.2rem .9rem; } h1 { font-size:1.7rem !important; } .quote-price { font-size:2rem; } .workspace-nav { gap:.4rem; } .workspace-nav a { padding:.35rem .65rem; } }
@media(prefers-reduced-motion:reduce) { * { transition:none !important; scroll-behavior:auto !important; } }
</style>
'''

def apply_theme():
    st.markdown(CSS,unsafe_allow_html=True)

def navigation():
    st.markdown('''<nav class="workspace-nav" aria-label="Research sections"><a href="#selected-stock">กราฟและราคา</a><a href="#fundamentals">พื้นฐานและปันผล</a><a href="#risk">ความเสี่ยง</a><a href="#comparison">เปรียบเทียบ</a><a href="#system-status">สถานะระบบ</a></nav>''',unsafe_allow_html=True)
