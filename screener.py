import yfinance as yf
import pandas as pd
import numpy as np
import requests

def get_sp500_tickers():
    """ดึงรายชื่อ S&P 500 จาก DataHub"""
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
        df = pd.read_csv(url)
        return df['Symbol'].str.replace('.', '-', regex=False).dropna().tolist()
    except Exception:
        return []

def get_nasdaq100_tickers():
    """ดึงรายชื่อ Nasdaq 100 จาก GitHub Repo"""
    try:
        url = "https://raw.githubusercontent.com/fja05680/sp500/master/nasdaq100.csv"
        df = pd.read_csv(url)
        col = 'Symbol' if 'Symbol' in df.columns else 'Ticker'
        return df[col].str.replace('.', '-', regex=False).dropna().tolist()
    except Exception:
        return []

def get_dividend_assets():
    """รายชื่อ Dividend ETFs, Covered Call ETFs และ REITs"""
    return [
        # Dividend & Covered Call ETFs
        "SCHD", "VYM", "VIG", "DGRO", "HDV", "SPYD", "NOBL", "COWZ", "SDY", "DVY",
        "PEY", "FDVV", "FDL", "DHS", "RDIV", "DON", "DES", "DLN", "DGRW", "DGRS",
        "JEPI", "JEPQ", "DIVO", "IDVO", "GPIX", "GPIQ", "QYLD", "XYLD", "RYLD", "SPYI",
        "QQQI", "IWMI", "SVOL", "FEPI", "AIPI", "BALI", "ISPY", "QDTE", "XDTE", "RDTE",
        "VNQ", "SCHH", "XLRE", "IYR", "VNQI", "MORT", "REM", "KBWY", "RIET", "PSR",
        # Equity REITs & mREITs
        "O", "NNN", "WPC", "VICI", "GLPI", "ADC", "EPRT", "SRC", "KIM", "REG",
        "FRT", "PLD", "STAG", "EGP", "FR", "TRNO", "AMT", "CCI", "SBAC", "EQIX",
        "DLR", "IRM", "WELL", "VTR", "OHI", "HR", "NHI", "DOC", "LTC", "AVB",
        "EQR", "MAA", "UDR", "CPT", "INVH", "AMH", "ESS", "PSA", "EXR", "CUBE",
        "BXP", "ARE", "SLG", "VNO", "LAMR", "OUT", "WY", "HST", "RHP", "SHO",
        "AGNC", "NLY", "BXMT", "STWD", "ABR", "RITM", "TWO", "ARI", "DX", "CIM"
    ]

def get_accurate_dividend_yield(ticker_obj, current_price):
    """คำนวณ % Dividend Yield ย้อนหลัง 12 เดือน (TTM) จากยอดเงินปันผลจริง"""
    try:
        if current_price <= 0:
            return 0.0
        div_history = ticker_obj.dividends
        if div_history is not None and not div_history.empty:
            one_year_ago = pd.Timestamp.now(tz=div_history.index.tz) - pd.Timedelta(days=365)
            recent_divs = div_history[div_history.index >= one_year_ago]
            if not recent_divs.empty:
                calc_yield = (recent_divs.sum() / current_price) * 100
                return round(float(calc_yield), 2)

        info = ticker_obj.info
        raw_yield = info.get('dividendYield') or info.get('trailingAnnualDividendYield') or 0.0
        if 0 < raw_yield <= 1.0:
            raw_yield = raw_yield * 100
        return round(float(raw_yield), 2)
    except Exception:
        return 0.0

def fetch_and_scan(common_tickers, div_tickers):
    results = []
    ticker_dict = {}
    for t in common_tickers:
        ticker_dict[t] = "Common Stock"
    for t in div_tickers:
        ticker_dict[t] = "Dividend Asset"
        
    all_tickers = list(ticker_dict.keys())
    total = len(all_tickers)
    
    print(f"\n⚡ กำลังดาวน์โหลดข้อมูลราคาย้อนหลัง ({total} รายการ)...")
    data = yf.download(all_tickers, period="3y", interval="1d", group_by="ticker", threads=True, progress=True)

    print("\n🔍 กำลังประมวลผล Indicators และข้อมูลเงินปันผล...")

    for ticker in all_tickers:
        try:
            asset_type = ticker_dict[ticker]
            if ticker not in data.columns.levels[0]:
                continue
            df = data[ticker].dropna(subset=['Close', 'Volume'])

            if len(df) < 50:
                continue

            close = df['Close']
            volume = df['Volume']
            high = df['High']
            low = df['Low']

            # Technical Indicators
            df['EMA20'] = close.ewm(span=20, adjust=False).mean()
            df['EMA50'] = close.ewm(span=50, adjust=False).mean()
            df['SMA200'] = close.rolling(window=200).mean() if len(df) >= 200 else pd.Series(np.nan, index=df.index)
            df['VOL_SMA20'] = volume.rolling(window=20).mean()

            prev_close = close.shift(1)
            tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
            df['ATR'] = tr.rolling(window=14).mean()

            curr = df.iloc[-1]
            prev_20 = df.iloc[-20] if len(df) >= 20 else df.iloc[0]

            # ตรรกะ Multi-Period Return (3Y -> 2Y -> 1Y -> <1Y)
            n_bars = len(df)
            if n_bars >= 740:
                lookback = 756 if n_bars >= 756 else n_bars - 1
                period_remark = "3Y"
            elif n_bars >= 490:
                lookback = 504 if n_bars >= 504 else n_bars - 1
                period_remark = "2Y"
            elif n_bars >= 240:
                lookback = 252 if n_bars >= 252 else n_bars - 1
                period_remark = "1Y"
            else:
                lookback = n_bars - 1
                period_remark = "<1Y"

            past_price = close.iloc[-lookback - 1]
            pct_return = round(float(((curr['Close'] - past_price) / past_price) * 100), 2)

            # Trend Check
            if len(df) >= 200 and pd.notnull(curr['SMA200']) and pd.notnull(prev_20['SMA200']):
                trend_align = curr['Close'] > curr['EMA20'] > curr['EMA50'] > curr['SMA200']
                sma200_up = curr['SMA200'] > prev_20['SMA200']
                vol_expansion = curr['Volume'] > (curr['VOL_SMA20'] * 1.05) if curr['VOL_SMA20'] > 0 else False
                is_passed = trend_align and sma200_up and vol_expansion
                sma200_val = round(float(curr['SMA200']), 2)
            else:
                is_passed = False
                sma200_val = None

            stop_loss = curr['Close'] - (2 * curr['ATR']) if pd.notnull(curr['ATR']) else None
            vol_ratio = curr['Volume'] / curr['VOL_SMA20'] if (pd.notnull(curr['VOL_SMA20']) and curr['VOL_SMA20'] > 0) else 0

            # Dividend Yield
            div_yield = 0.0
            if asset_type == "Dividend Asset":
                t_obj = yf.Ticker(ticker)
                div_yield = get_accurate_dividend_yield(t_obj, curr['Close'])

            results.append({
                "Ticker": str(ticker),
                "Asset_Type": str(asset_type),
                "Status": "PASS" if is_passed else "FAIL",
                "Close": round(float(curr['Close']), 2),
                "Historical_Return": pct_return,
                "Return_Period": str(period_remark),
                "Div_Yield": round(float(div_yield), 2) if asset_type == "Dividend Asset" else None,
                "EMA20": round(float(curr['EMA20']), 2) if pd.notnull(curr['EMA20']) else None,
                "SMA200": sma200_val,
                "Vol_Ratio": round(float(vol_ratio), 2),
                "ATR": round(float(curr['ATR']), 2) if pd.notnull(curr['ATR']) else None,
                "Suggested_Stop": round(float(stop_loss), 2) if stop_loss is not None else None
            })
        except Exception:
            continue

    return pd.DataFrame(results)

if __name__ == "__main__":
    sp500 = get_sp500_tickers()
    nasdaq100 = get_nasdaq100_tickers()
    div_assets = get_dividend_assets()

    common_stocks = list(set(sp500 + nasdaq100) - set(div_assets))

    print(f"📊 สรุป Universe: Common Stocks {len(common_stocks)} ตัว | Dividend Assets {len(div_assets)} ตัว")
    df_results = fetch_and_scan(common_stocks, div_assets)
    df_results = df_results.sort_values(by=["Status", "Vol_Ratio"], ascending=[True, False])

    df_results.to_csv("daily_watchlist.csv", index=False)
    print(f"\n💾 บันทึกข้อมูล {len(df_results)} รายการลง 'daily_watchlist.csv' เรียบร้อยแล้ว")