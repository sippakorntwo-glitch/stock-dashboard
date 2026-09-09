from io import BytesIO
import inspect
from pathlib import Path
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

WATCHLIST_FILE = Path(__file__).resolve().parent / "daily_watchlist.csv"
NUMERIC_COLUMNS = ["Close", "Historical_Return", "Vol_Ratio", "RSI_14", "MACD",
                   "MACD_Signal", "ATR", "Suggested_Stop", "EMA20", "EMA50", "SMA200"]
# === ETF SETTINGS — ค่าที่ปรับเองได้ ===
ETF_BATCH_SIZE = 25       # จำนวน Ticker ต่อคำขอชุดหนึ่ง แนะนำ 25
ETF_EXTRA_TICKERS = ()   # เพิ่มเองได้ เช่น ("DIVO", "DGRO") หรือใช้ช่องเพิ่ม ETF บนหน้าแอป
ETF_CATALOG_AS_OF = "2026-09-09"
ETF_CATALOG_SOURCE = "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs"
CORE_ETFS = ("SPY", "QQQ", "VOO", "VTI", "DIA", "IWM", "SCHD", "VYM", "DVY", "HDV",
                "JEPI", "JEPQ", "VNQ", "GLD", "IAU", "SLV", "TLT", "IEF", "SHY", "AGG",
                "BND", "LQD", "HYG", "EEM", "VEA", "EFA", "XLK", "XLF", "XLV", "XLE", "SMH", "SOXX")

# Snapshot: Nasdaq nasdaqlisted.txt + otherlisted.txt, ETF=Y, Test Issue=N.
# Nine issuer families + the existing core list; ETNs excluded. Not an AUM ranking.
# File Creation Time from the source: 0909202611:01 (source timezone unspecified).
ETF_CATALOG_TSV = """AAXJ	iShares MSCI All Country Asia ex Japan ETF
ACWI	iShares MSCI ACWI ETF
ACWV	iShares MSCI Global Min Vol Factor ETF
ACWX	iShares MSCI ACWI ex U.S. ETF
AFK	VanEck Africa Index ETF
AGG	iShares Core U.S. Aggregate Bond ETF
AGGM	iShares 1-10 Year U.S. Aggregate Bond ETF
AGGY	WisdomTree Yield Enhanced U.S. Aggregate Bond Fund
AGNG	Global X Aging Population ETF
AGZ	iShares  Agency Bond ETF
AGZD	WisdomTree Interest Rate Hedged U.S. Aggregate Bond Fund
AIA	iShares Asia 50 ETF
AIQ	Global X Artificial Intelligence & Technology ETF
AIVI	WisdomTree International AI Enhanced Value Fund
AIVL	WisdomTree U.S. AI Enhanced Value Fund
ALTY	Global X Alternative Income ETF
ANGL	VanEck Fallen Angel High Yield Bond ETF
AOA	iShares Core 80/20 Aggressive Allocation ETF
AOK	iShares Core 30/70 Conservative Allocation ETF
AOM	iShares Core 40/60 Moderate Allocation ETF
AOR	iShares Core 60/40 Balanced Allocation ETF
AQLT	iShares MSCI Global Quality Factor ETF
AQWA	Global X Clean Water ETF
ARGT	Global X MSCI Argentina ETF
ARTY	iShares Future AI & Tech ETF
ASEA	Global X FTSE Southeast Asia ETF
AUAU	Global X Gold Miners ETF
AUSF	Global X Adaptive U.S. Factor ETF
BAB	Invesco Taxable Municipal Bond ETF
BAI	iShares A.I. Innovation and Tech Active ETF
BALI	iShares U.S. Large Cap Premium Income Active ETF
BALQ	iShares Nasdaq Premium Income Active ETF
BBAG	JPMorgan BetaBuilders U.S. Aggregate Bond ETF
BBAX	JPMorgan BetaBuilders Developed Asia Pacific-ex Japan ETF
BBCA	JPMorgan BetaBuilders Canada ETF
BBCB	JPMorgan BetaBuilders USD Investment Grade Corporate Bond ETF
BBEM	JPMorgan BetaBuilders Emerging Markets Equity ETF
BBEU	JPMorgan BetaBuilders Europe ETF
BBH	VanEck Biotech ETF
BBHY	JPMorgan BetaBuilders USD High Yield Corporate Bond ETF
BBIB	JPMorgan BetaBuilders U.S. Treasury Bond 3-10 Year ETF
BBIN	JPMorgan BetaBuilders International Equity ETF
BBJP	JPMorgan BetaBuilders Japan ETF
BBLB	JPMorgan BetaBuilders U.S. Treasury Bond 20+ Year ETF
BBMC	JPMorgan BetaBuilders U.S. Mid Cap Equity ETF
BBRE	JPMorgan BetaBuilders MSCI U.S. REIT ETF
BBSB	JPMorgan BetaBuilders U.S. Treasury Bond 1-3 Year ETF
BBSC	JPMorgan BetaBuilders U.S. Small Cap Equity ETF
BBUS	JPMorgan BetaBuilders U.S. Equity ETF
BCCC	Global X Bitcoin Covered Call ETF
BCLO	iShares BBB-B CLO Active ETF
BDVL	iShares Disciplined Volatility Equity Active ETF
BDYN	iShares Dynamic Equity Active ETF
BEMB	iShares J.P. Morgan Broad USD Emerging Markets Bond ETF
BFLX	iShares Flexible Equity Active ETF
BGRN	iShares USD Green Bond ETF
BGRO	iShares Large Cap Growth Active ETF
BIDD	iShares International Dividend Active ETF
BIL	State Street SPDR Bloomberg 1-3 Month T-Bill ETF
BILS	State Street SPDR Bloomberg 3-12 Month T-Bill ETF
BILT	iShares Infrastructure Active ETF
BINC	iShares Flexible Income Active ETF
BITA	iShares Bitcoin Premium Income ETF
BITS	Global X Blockchain & Bitcoin Strategy ETF
BIV	Vanguard Intermediate-Term Bond ETF
BIZD	VanEck BDC Income ETF
BKCH	Global X Blockchain ETF
BKF	iShares MSCI BIC ETF
BKLN	Invesco Senior Loan ETF
BLCR	iShares Large Cap Core Active ETF
BLCV	iShares Large Cap Value Active ETF
BLV	Vanguard Long-Term Bond ETF
BMED	iShares Health Innovation Active ETF
BMVP	Invesco Bloomberg MVP Multi-factor ETF
BND	Vanguard Total Bond Market ETF
BNDP	Vanguard Core-Plus Bond Index ETF
BNDW	Vanguard Total World Bond ETF
BNDX	Vanguard Total International Bond ETF
BOTZ	Global X Robotics & Artificial Intelligence ETF
BPAY	iShares FinTech Active ETF
BRAZ	Global X Brazil Active ETF
BREM	iShares Emerging Markets Bond Active ETF
BRF	VanEck Brazil Small-Cap ETF
BRHY	iShares High Yield Active ETF
BRLN	iShares Floating Rate Loan Active ETF
BRTR	iShares Total Return Active ETF
BSCA	Invesco BulletShares 2036 Corporate Bond ETF
BSCQ	Invesco BulletShares 2026 Corporate Bond ETF
BSCR	Invesco BulletShares 2027 Corporate Bond ETF
BSCS	Invesco BulletShares 2028 Corporate Bond ETF
BSCT	Invesco BulletShares 2029 Corporate Bond ETF
BSCU	Invesco BulletShares 2030 Corporate Bond ETF
BSCV	Invesco BulletShares 2031 Corporate Bond ETF
BSCW	Invesco BulletShares 2032 Corporate Bond ETF
BSCX	Invesco BulletShares 2033 Corporate Bond ETF
BSCY	Invesco BulletShares 2034 Corporate Bond ETF
BSCZ	Invesco BulletShares 2035 Corporate Bond ETF
BSGR	Invesco BulletShares 2027 Treasury Bond ETF
BSGT	Invesco BulletShares 2029 Treasury Bond ETF
BSJQ	Invesco BulletShares 2026 High Yield Corporate Bond ETF
BSJR	Invesco BulletShares 2027 High Yield Corporate Bond ETF
BSJS	Invesco BulletShares 2028 High Yield Corporate Bond ETF
BSJT	Invesco BulletShares 2029 High Yield Corporate Bond ETF
BSJU	Invesco BulletShares 2030 High Yield Corporate Bond ETF
BSJV	Invesco BulletShares 2031 High Yield Corporate Bond ETF
BSJW	Invesco BulletShares 2032 High Yield Corporate Bond ETF
BSJX	Invesco BulletShares 2033 High Yield Corporate Bond ETF
BSJY	Invesco BulletShares 2034 High Yield Corporate Bond ETF
BSMQ	Invesco BulletShares 2026 Municipal Bond ETF
BSMR	Invesco BulletShares 2027 Municipal Bond ETF
BSMS	Invesco BulletShares 2028 Municipal Bond ETF
BSMT	Invesco BulletShares 2029 Municipal Bond ETF
BSMU	Invesco BulletShares 2030 Municipal Bond ETF
BSMV	Invesco BulletShares 2031 Municipal Bond ETF
BSMW	Invesco BulletShares 2032 Municipal Bond ETF
BSMY	Invesco BulletShares 2034 Municipal Bond ETF
BSMZ	Invesco BulletShares 2035 Municipal Bond ETF
BSSX	Invesco BulletShares 2033 Municipal Bond ETF
BSTS	Invesco BulletShares 2028 Treasury Bond ETF
BSTU	Invesco BulletShares 2030 Treasury Bond ETF
BSTV	Invesco BulletShares 2031 Treasury Bond ETF
BSV	Vanguard Short-Term Bond ETF
BTCO	Invesco Galaxy Bitcoin ETF 
BTCW	WisdomTree Bitcoin Fund 
BTOT	iShares Total USD Fixed Income Market ETF
BTRN	Global X Bitcoin Trend Strategy ETF
BUG	Global X Cybersecurity ETF
BUZZ	VanEck Social Sentiment ETF
BWX	State Street SPDR Bloomberg International Treasury Bond ETF
BWZ	State Street SPDR Bloomberg Short Term International Treasury Bond ETF
BYLD	iShares Yield Optimized Bond ETF
CALI	iShares Short-Term California Muni Active ETF
CATH	Global X S&P 500 Catholic Values ETF
CBON	VanEck China Bond ETF
CEFA	Global X S&P Catholic Values Developed ex-U.S. ETF
CEMB	iShares J.P. Morgan EM Corporate Bond ETF
CERY	State Street SPDR Bloomberg Enhanced Roll Yield Commodity Strategy No K-1 ETF
CEW	WisdomTree Emerging Currency Strategy Fund
CGW	Invesco S&P Global Water Index ETF
CHIQ	Global X MSCI China Consumer Discretionary ETF
CHPX	Global X AI Semiconductor & Quantum ETF
CHRI	Global X S&P 500 Christian Values ETF
CLIP	Global X 1-3 Month T-Bill ETF
CLOA	iShares AAA CLO Active ETF
CLOB	VanEck AA-BB CLO ETF
CLOI	VanEck CLO ETF
CLOU	Global X Cloud Computing ETF
CMBS	iShares CMBS Bond ETF
CMCI	VanEck CMCI Commodity Strategy ETF
CMDY	iShares Bloomberg Roll Select Commodity Strategy ETF
CMF	iShares California Muni Bond ETF
CNRG	State Street SPDR S&P Kensho Clean Power ETF
CNXT	VanEck ChiNext Innovators ETF
CNYA	iShares MSCI China A ETF
COLO	Global X MSCI Colombia ETF
COMD	Global X Commodity Strategy ETF
COMT	iShares GSCI Commodity Dynamic Roll Strategy ETF
COPX	Global X Copper Miners ETF
CORO	iShares International Country Rotation Active ETF
CPTL	Global X Morningstar Capital Allocation Leaders ETF
CQQQ	Invesco China Technology ETF
CRAK	VanEck Oil Refiners ETF
CRBN	iShares Low Carbon Optimized MSCI ACWI ETF
CSD	Invesco S&P Spin-Off ETF
CSHP	iShares Dynamic Short-Term Active ETF
CSTK	Invesco Comstock Contrarian Equity ETF
CTEC	Global X ClimateTech ETF
CUT	Invesco MSCI Global Timber ETF
CVY	Invesco Zacks Multi-Asset Income ETF
CWB	State Street SPDR Bloomberg Convertible Securities ETF
CWI	State Street SPDR MSCI ACWI ex-US ETF
CXSE	WisdomTree China ex-State-Owned Enterprises Fund
CZA	Invesco Zacks Mid-Cap ETF
DAPP	VanEck Digital Transformation ETF
DAX	Global X DAX Germany ETF
DBA	Invesco DB Agriculture Fund
DBB	Invesco DB Base Metals Fund
DBC	Invesco DB Commodity Index Tracking Fund
DBE	Invesco DB Energy Fund
DBO	Invesco DB Oil Fund
DBP	Invesco DB Precious Metals Fund
DDLS	WisdomTree Dynamic International SmallCap Equity Fund
DDWM	WisdomTree Dynamic International Equity Fund
DEM	WisdomTree Emerging Markets High Dividend Fund
DES	WisdomTree U.S. SmallCap Dividend Fund
DESK	VanEck Office and Commercial REIT ETF
DEW	WisdomTree Global High Dividend Fund
DFE	WisdomTree Europe SmallCap Dividend Fund
DFJ	WisdomTree Japan SmallCap Fund
DGIN	VanEck Digital India ETF
DGRE	WisdomTree Emerging Markets Quality Dividend Growth Fund
DGRO	iShares Core Dividend Growth ETF
DGRS	WisdomTree U.S. SmallCap Quality Dividend Growth Fund
DGRW	WisdomTree U.S. Quality Dividend Growth Fund
DGS	WisdomTree Emerging Market SmallCap Fund
DGT	State Street SPDR Global Dow ETF
DHS	WisdomTree U.S. High Dividend Fund
DIA	State Street SPDR Dow Jones Industrial Average ETF Trust
DIM	WisdomTree International MidCap Dividend Fund
DIV	Global X Super Dividend ETF
DIVB	iShares Core Dividend ETF
DIVG	Invesco S&P 500 High Dividend Growers ETF
DJD	Invesco Dow Jones Industrial Average Dividend ETF
DJIA	Global X Dow 30 Covered Call ETF
DLN	WisdomTree U.S. LargeCap Dividend Fund
DLS	WisdomTree International SmallCap Fund
DMAX	iShares Large Cap Max Buffer Dec ETF
DMXF	iShares ESG Advanced MSCI EAFE ETF
DNL	WisdomTree Global ex-U.S. Quality Growth Fund
DOL	WisdomTree True Developed International Fund
DON	WisdomTree U.S. MidCap Dividend Fund
DRIV	Global X Autonomous & Electric Vehicles ETF
DSI	iShares ESG MSCI KLD 400 ETF
DTCR	Global X Data Center & Digital Infrastructure ETF
DTD	WisdomTree U.S. Total Dividend Fund
DTH	WisdomTree International High Dividend Fund
DURA	VanEck Durable High Dividend ETF
DVVY	Invesco Diversified Dividend Opportunities ETF
DVY	iShares Select Dividend ETF
DVYA	iShares Asia / Pacific Dividend 30 Index Fund Exchange Traded Fund
DVYE	iShares Emerging Markets Dividend Index Fund Exchange Traded Fund
DWAS	Invesco Dorsey Wright SmallCap Momentum ETF
DWM	WisdomTree International Equity Fund
DWMF	WisdomTree International Multifactor Fund
DWX	State Street SPDR S&P International Dividend ETF
DXJ	WisdomTree Japan Hedged Equity Fund
DYLG	Global X Dow 30 Covered Call & Growth ETF
DYNF	iShares U.S. Equity Factor Rotation Active ETF
EAGG	iShares ESG Aware U.S. Aggregate Bond ETF
EART	Global X Rare Earth & Critical Materials ETF
EBIZ	Global X E-commerce ETF
EBND	State Street SPDR Bloomberg Emerging Markets Local Bond ETF
ECH	iShares MSCI Chile ETF
ECNS	iShares MSCI China Small-Cap ETF
EDEN	iShares MSCI Denmark ETF
EDGQ	Global X Nasdaq-100 Income Edge ETF
EDGX	Global X U.S. 500 Income Edge ETF
EDIV	State Street SPDR S&P Emerging Markets Dividend ETF
EDV	Vanguard Extended Duration Treasury ETF
EELV	Invesco S&P Emerging Markets Low Volatility ETF
EEM	iShares MSCI Emerging Index Fund
EEMA	iShares MSCI Emerging Markets Asia ETF
EEMO	Invesco S&P Emerging Markets Momentum ETF
EEMS	iShares MSCI Emerging Markets Small Cap ETF
EEMV	iShares MSCI Emerging Markets Min Vol Factor ETF
EEMX	State Street SPDR MSCI Emerging Markets Fossil Fuel Reserves Free ETF
EES	WisdomTree U.S. SmallCap Fund
EFA	iShares MSCI EAFE ETF
EFAA	Invesco MSCI EAFE Income Advantage ETF
EFAS	Global X MSCI SuperDividend EAFE ETF
EFAV	iShares MSCI EAFE Min Vol Factor ETF
EFAX	State Street SPDR MSCI EAFE Fossil Fuel Reserves Free ETF
EFG	iShares MSCI EAFE Growth ETF
EFIV	State Street SPDR S&P 500 ESG ETF
EFNL	iShares MSCI Finland ETF
EFRA	iShares Environmental Infrastructure and Industrials ETF
EFV	iShares MSCI EAFE Value ETF
EGLE	Global X S&P 500 U.S. Revenue Leaders ETF
EGUS	iShares ESG Aware MSCI USA Growth ETF
EHCC	Global X Ethereum Covered Call ETF
EIDO	iShares MSCI Indonesia ETF
EINC	VanEck Energy Income ETF
EIRL	iShares MSCI Ireland ETF
EIS	iShares MSCI Israel ETF
ELD	WisdomTree Emerging Markets Local Debt Fund
EMB	iShares J.P. Morgan USD Emerging Markets Bond ETF
EMBD	Global X Emerging Markets Bond ETF
EMBX	VanEck Emerging Markets Bond ETF
EMC	Global X Emerging Markets Great Consumer ETF
EMCB	WisdomTree Emerging Markets Corporate Bond Fund
EMET	VanEck Copper and Electrification Metals ETF
EMGF	iShares Emerging Markets Equity Factor ETF
EMHC	State Street SPDR Bloomberg Emerging Markets USD Bond ETF
EMHY	iShares J.P. Morgan EM High Yield Bond ETF
EMIF	iShares Emerging Markets Infrastructure ETF
EMLC	VanEck J. P. Morgan EM Local Currency Bond ET
EMM	Global X Emerging Markets ex-China ETF
EMMF	WisdomTree Emerging Markets Multifactor Fund
EMXC	iShares MSCI Emerging Markets ex China ETF
EMXF	iShares ESG Advanced MSCI EM ETF
ENHI	iShares Enhanced International Active ETF
ENHU	iShares Enhanced Large Cap Core Active ETF
ENOR	iShares MSCI Norway ETF
ENZL	iShares MSCI New Zealand ETF
EPHE	iShares MSCI Philippines ETF
EPI	WisdomTree India Earnings Fund
EPOL	iShares MSCI Poland ETF
EPP	iShares MSCI Pacific Ex-Japan Index Fund
EPS	WisdomTree U.S. LargeCap Fund
EPU	iShares MSCI Peru and Global Exposure ETF
EQAL	Invesco Russell 1000 Equal Weight ETF
EQLT	iShares MSCI Emerging Markets Quality Factor ETF
EQWL	Invesco S&P 100 Equal Weight ETF
ERET	iShares Environmentally Aware Real Estate ETF
ERTH	Invesco MSCI Sustainable Future ETF
ESGD	iShares ESG Aware MSCI EAFE ETF
ESGE	iShares ESG Aware MSCI EM ETF
ESGU	iShares ESG Aware MSCI USA ETF
ESGV	Vanguard ESG U.S. Stock ETF
ESML	iShares ESG Aware MSCI USA Small-Cap ETF
ESMV	iShares ESG Optimized MSCI USA Min Vol Factor ETF
ESPO	VanEck Video Gaming and eSports ETF
ETEC	iShares Breakthrough Environmental Solutions ETF
ETHA	iShares Ethereum Trust ETF
ETHB	iShares Staked Ethereum Trust ETF
ETHV	VanEck Ethereum ETF
EUDG	WisdomTree Europe Quality Dividend Growth Fund
EUFN	iShares MSCI Europe Financials ETF
EUHY	iShares Euro High Yield Corporate Bond USD Hedged ETF
EUIG	iShares Euro Investment Grade Corporate Bond USD Hedged ETF
EUSA	iShares MSCI USA Equal Weighted ETF
EUSB	iShares ESG Advanced Universal USD Bond ETF
EVLU	iShares MSCI Emerging Markets Value Factor ETF
EVMT	Invesco Electric Vehicle Metals Commodity Strategy No K-1 ETF
EVUS	iShares ESG Aware MSCI USA Value ETF
EVX	VanEck Environmental Services ETF
EWA	iShares MSCI Australia Index Fund
EWC	iShares MSCI Canada Index Fund
EWD	iShares MSCI Sweden ETF
EWG	iShares MSCI Germany Index Fund
EWH	iShares MSCI Hong Kong Index Fund
EWI	iShares MSCI Italy ETF
EWJ	iShares MSCI Japan Index Fund
EWJV	iShares MSCI Japan Value ETF
EWK	iShares MSCI Belgium ETF
EWL	iShares MSCI Switzerland ETF
EWM	iShares MSCI Malaysia Index Fund
EWN	iShares MSCI Netherlands Index Fund
EWO	iShares MSCI Austria ETF
EWP	iShares MSCI Spain ETF
EWQ	iShares MSCI France Index Fund
EWS	iShares MSCI Singapore ETF
EWT	iShares MSCI Taiwan ETF
EWU	iShares MSCI United Kingdom ETF
EWUS	iShares MSCI United Kingdom Small Cap ETF
EWW	iShares MSCI Mexico ETF
EWX	State Street SPDR S&P Emerging Markets Small Cap ETF
EWY	iShares MSCI South Korea ETF
EWZ	iShares MSCI Brazil ETF
EWZS	iShares MSCI Brazil Small-Cap ETF
EXI	iShares Global Industrials ETF
EZA	iShares MSCI South Africa Index Fund
EZM	WisdomTree U.S. MidCap Fund
EZU	iShares MSCI Eurozone ETF
FALN	iShares Fallen Angels USD Bond ETF
FDIQ	Invesco Bloomberg Financial Data Providers ETF
FEZ	State Street SPDR EURO STOXX 50 ETF
FINX	Global X FinTech ETF
FITE	State Street SPDR S&P Kensho Future Security ETF
FLAG	Global X S&P 500 U.S. Market Leaders Top 50 ETF
FLOT	iShares Floating Rate Bond ETF
FLOW	Global X U.S. Cash Flow Kings 100 ETF
FLRN	State Street SPDR Bloomberg Investment Grade Floating Rate ETF
FLTR	VanEck IG Floating Rate ETF
FLXI	Invesco Flexible Income ETF
FNDA	Schwab Fundamental U.S. Small Company ETF
FNDB	Schwab Fundamental U.S. Broad Market ETF
FNDC	Schwab Fundamental International Small Equity ETF
FNDE	Schwab Fundamental Emerging Markets Equity ETF
FNDF	Schwab Fundamental International Equity ETF
FNDX	Schwab Fundamental U.S. Large Company ETF
FXA	Invesco CurrencyShares Australian Dollar Trust
FXB	Invesco CurrencyShares British Pound Sterling Trust
FXC	Invesco CurrencyShares Canadian Dollar Trust
FXE	Invesco CurrencyShares Euro Currency Trust
FXF	Invesco CurrencyShares Swiss Franc Trust
FXI	iShares China Large-Cap ETF
FXY	Invesco CurrencyShares Japanese Yen Trust
GARP	iShares MSCI USA Quality GARP ETF
GCC	WisdomTree EnhancedContinuous Commodity Index Fund
GDE	WisdomTree Efficient Gold Plus Equity Strategy Fund
GDMN	WisdomTree Efficient Gold Plus Gold Miners Strategy Fund
GDT	WisdomTree Efficient TIPS Plus Gold Fund
GDX	VanEck Gold Miners ETF
GDXJ	VanEck Junior Gold Miners ETF
GENZ	VanEck Digital Native Economy ETF
GGME	Invesco Next Gen Media and Gaming ETF
GGOV	iShares Global Government Bond USD Hedged Active ETF
GHYG	iShares US & Intl High Yield Corp Bond ETF
GII	State Street SPDR S&P Global Infrastructure ETF
GLD	SPDR Gold Shares
GLDM	SPDR Gold MiniShares Trust
GLIN	VanEck India Growth Leaders ETF
GLOF	iShares Global Equity Factor ETF
GMF	State Street SPDR S&P Emerging Asia Pacific ETF
GMMF	iShares Government Money Market ETF
GNMA	iShares GNMA Bond ETF
GNOM	Global X Genomics & Biotechnology ETF
GNR	State Street SPDR S&P Global Natural Resources ETF
GOEX	Global X Gold Explorers ETF
GOVI	Invesco Equal Weight 0-30 Year Treasury ETF
GOVM	iShares 1-10 Year Treasury Bond ETF
GOVT	iShares U.S. Treasury Bond ETF
GOVZ	iShares 25  Year Treasury STRIPS Bond ETF
GPZ	VanEck Alternative Asset Manager ETF
GREK	Global X MSCI Greece ETF
GRNB	VanEck Green Bond ETF
GRPM	Invesco S&P MidCap 400 GARP ETF
GRPZ	Invesco S&P SmallCap 600 GARP ETF
GSG	iShares GSCI Commodity-Indexed Trust Fund
GSY	Invesco Ultra Short Duration ETF
GTO	Invesco Total Return Bond ETF
GTOC	Invesco Core Fixed Income ETF
GTOH	Invesco Short Duration High Yield ETF
GTOQ	Invesco High Yield Systematic Bond ETF
GTOS	Invesco Short Duration Total Return Bond ETF
GTR	WisdomTree Target Range Fund
GURU	Global X Guru Index ETF
GVI	iShares Intermediate Government/Credit Bond ETF
GWX	State Street SPDR S&P International Small Cap ETF
GXC	State Street SPDR S&P China ETF
GXDW	Global X Dorsey Wright Thematic ETF
GXIG	Global X Investment Grade Corporate Bond ETF
GXLC	Global X U.S. 500 ETF
GXPC	Global X PureCap MSCI Communication Services ETF
GXPD	Global X PureCap MSCI Consumer Discretionary ETF
GXPE	Global X PureCap MSCI Energy ETF
GXPS	Global X PureCap MSCI Consumer Staples ETF
GXPT	Global X PureCap MSCI Information Technology ETF
HAIL	State Street SPDR S&P Kensho Smart Mobility ETF
HAP	VanEck Natural Resources ETF
HAWX	iShares Currency Hedged MSCI ACWI ex U.S. ETF
HBRD	Invesco U.S. Hybrid Bond ETF
HDV	iShares Core High Dividend ETF
HEAL	Global X HealthTech ETF
HEDJ	WisdomTree Europe Hedged Equity Fund
HEEM	iShares Currency Hedged MSCI Emerging Markets ETF
HEFA	iShares Currency Hedged MSCI EAFE ETF
HELO	JPMorgan Hedged Equity Laddered Overlay ETF
HEQQ	JPMorgan Nasdaq Hedged Equity Laddered Overlay ETF
HERO	Global X Video Games & Esports ETF
HEWJ	iShares Currency Hedged MSCI Japan ETF
HEZU	iShares Currency Hedged MSCI Eurozone ETF
HIMU	iShares High Yield Muni Active ETF
HODL	VanEck Bitcoin Trust 
HOLA	JPMorgan International Hedged Equity Laddered Overlay ETF
HSCZ	iShares Currency Hedged MSCI EAFE Small-Cap ETF
HYBB	iShares BB Rated Corporate Bond ETF
HYD	VanEck High Yield Muni ETF
HYDB	iShares High Yield Systematic Bond ETF
HYDR	Global X Hydrogen ETF
HYEM	VanEck Emerging Markets High Yield Bond ETF
HYG	iShares iBoxx $ High Yield Corporate Bond ETF
HYGH	iShares Interest Rate Hedged High Yield Bond ETF
HYGW	iShares High Yield Corporate Bond BuyWrite Strategy ETF
HYIN	WisdomTree Private Credit and Alternative Income Fund
HYMB	State Street SPDR Nuveen ICE High Yield Municipal Bond ETF
HYXF	iShares ESG Advanced High Yield Corporate Bond ETF
HYZD	WisdomTree Interest Rate Hedged High Yield Bond Fund
IAGG	iShares International Aggregate Bond Fund
IAI	iShares U.S. Broker-Dealers & Securities Exchanges ETF
IAK	iShares U.S. Insurance ETF
IALT	iShares Systematic Alternatives Active ETF
IAT	iShares U.S. Regional Banks ETF
IAU	iShares Gold Trust Shares
IAUM	iShares Gold Trust Micro Shares
IBAT	iShares Energy Storage & Materials ETF
IBB	iShares Biotechnology ETF
IBBQ	Invesco Nasdaq Biotechnology ETF
IBCA	iShares iBonds Dec 2035 Term Corporate ETF
IBCB	iShares iBonds Dec 2036 Term Corporate ETF
IBDR	iShares iBonds Dec 2026 Term Corporate ETF
IBDS	iShares iBonds Dec 2027 Term Corporate ETF
IBDT	iShares iBonds Dec 2028 Term Corporate ETF
IBDU	iShares iBonds Dec 2029 Term Corporate ETF
IBDV	iShares iBonds Dec 2030 Term Corporate ETF
IBDW	iShares iBonds Dec 2031 Term Corporate ETF
IBDX	iShares iBonds Dec 2032 Term Corporate ETF
IBDY	iShares iBonds Dec 2033 Term Corporate ETF
IBDZ	iShares iBonds Dec 2034 Term Corporate ETF
IBGA	iShares iBonds Dec 2044 Term Treasury ETF
IBGB	iShares iBonds Dec 2045 Term Treasury ETF
IBGC	iShares iBonds Dec 2046 Term Treasury ETF
IBGK	iShares iBonds Dec 2054 Term Treasury ETF
IBGL	iShares iBonds Dec 2055 Term Treasury ETF
IBGM	iShares iBonds Dec 2056 Term Treasury ETF
IBHF	iShares iBonds 2026 Term High Yield and Income ETF
IBHG	iShares iBonds 2027 Term High Yield and Income ETF
IBHH	iShares iBonds 2028 Term High Yield and Income ETF
IBHI	iShares iBonds 2029 Term High Yield and Income ETF
IBHJ	iShares iBonds 2030 Term High Yield and Income ETF
IBHK	iShares iBonds 2031 Term High Yield and Income ETF
IBHL	iShares iBonds 2032 Term High Yield and Income ETF
IBHM	iShares iBonds 2033 Term High Yield and Income ETF
IBIC	iShares iBonds Oct 2026 Term TIPS ETF
IBID	iShares iBonds Oct 2027 Term TIPS ETF
IBIE	iShares iBonds Oct 2028 Term TIPS ETF
IBIF	iShares iBonds Oct 2029 Term TIPS ETF
IBIG	iShares iBonds Oct 2030 Term TIPS ETF
IBIH	iShares iBonds Oct 2031 Term TIPS ETF
IBII	iShares iBonds Oct 2032 Term TIPS ETF
IBIJ	iShares iBonds Oct 2033 Term TIPS ETF
IBIK	iShares iBonds Oct 2034 Term TIPS ETF
IBIL	iShares iBonds Oct 2035 Term TIPS ETF
IBIM	iShares iBonds Oct 2036 Term TIPS ETF
IBIT	iShares Bitcoin Trust ETF
IBLC	iShares Blockchain and Tech ETF
IBMO	iShares iBonds Dec 2026 Term Muni Bond ETF
IBMP	iShares iBonds Dec 2027 Term Muni Bond ETF
IBMQ	iShares iBonds Dec 2028 Term Muni Bond ETF
IBMR	iShares iBonds Dec 2029 Term Muni Bond ETF
IBMS	iShares iBonds Dec 2030 Term Muni Bond ETF
IBMT	iShares iBonds Dec 2031 Term Muni Bond ETF
IBMU	iShares iBonds Dec 2032 Term Muni Bond ETF
IBMV	iShares iBonds Dec 2033 Term Muni Bond ETF
IBMW	iShares iBonds Dec 2034 Term Muni Bond ETF
IBMX	iShares iBonds Dec 2035 Term Muni Bond ETF
IBND	State Street SPDR Bloomberg International Corporate Bond ETF
IBOT	VanEck Robotics ETF
IBRN	iShares Neuroscience and Healthcare ETF
IBTG	iShares iBonds Dec 2026 Term Treasury ETF
IBTH	iShares iBonds Dec 2027 Term Treasury ETF
IBTI	iShares iBonds Dec 2028 Term Treasury ETF
IBTJ	iShares iBonds Dec 2029 Term Treasury ETF
IBTK	iShares iBonds Dec 2030 Term Treasury ETF
IBTL	iShares iBonds Dec 2031 Term Treasury ETF
IBTM	iShares iBonds Dec 2032 Term Treasury ETF
IBTO	iShares iBonds Dec 2033 Term Treasury ETF
IBTP	iShares iBonds Dec 2034 Term Treasury ETF
IBTQ	iShares iBonds Dec 2035 Term Treasury ETF
IBTR	iShares iBonds Dec 2036 Term Treasury ETF
ICF	iShares Select U.S. REIT ETF
ICLN	iShares Global Clean Energy ETF
ICLO	Invesco AAA CLO Floating Rate Note ETF
ICOP	iShares Copper and Metals Mining ETF
ICPI	iShares 0-1 Year TIPS Bond ETF
ICSH	iShares Ultra Short Duration Bond Active ETF
ICVT	iShares Convertible Bond ETF
IDEF	iShares Defense Industrials and Tech Active ETF
IDEV	iShares Core MSCI International Developed Markets ETF
IDGT	iShares U.S. Digital Infrastructure and Real Estate ETF
IDHQ	Invesco S&P International Developed Quality ETF
IDLV	Invesco S&P International Developed Low Volatility ETF
IDMO	Invesco S&P International Developed Momentum ETF
IDNA	iShares Genomics Immunology and Healthcare ETF
IDRV	iShares Self-Driving EV and Tech ETF
IDU	iShares U.S. Utilities ETF
IDV	iShares International Select Dividend ETF
IDX	VanEck Indonesia Index ETF
IDYN	iShares International Equity Factor Rotation Active ETF
IEF	iShares 7-10 Year Treasury Bond ETF
IEFA	iShares Core MSCI EAFE ETF
IEI	iShares 3-7 Year Treasury Bond ETF
IEMG	iShares Core MSCI Emerging Markets ETF
IEO	iShares U.S. Oil & Gas Exploration & Production ETF
IETC	iShares U.S. Tech Independence Focused ETF
IEUR	iShares Core MSCI Europe ETF
IEUS	iShares MSCI Europe Small-Cap ETF
IEV	iShares Europe ETF
IEZ	iShares U.S. Oil Equipment & Services ETF
IFGL	iShares International Developed Real Estate ETF
IFLN	Invesco Bloomberg Enhanced Fallen Angels ETF
IFRA	iShares U.S. Infrastructure ETF
IGBH	iShares Interest Rate Hedged Long-Term Corporate Bond ETF
IGE	iShares North American Natural Resources ETF
IGEB	iShares Investment Grade Systematic Bond ETF
IGF	iShares Global Infrastructure ETF
IGIB	iShares 5-10 Year Investment Grade Corporate Bond ETF
IGLB	iShares 10  Year Investment Grade Corporate Bond ETF
IGM	iShares Expanded Tech Sector ETF
IGOV	iShares International Treasury Bond ETF
IGPT	Invesco AI and Next Gen Software ETF
IGRO	iShares International Dividend Growth ETF
IGSB	iShares 1-5 Year Investment Grade Corporate Bond ETF
IGV	iShares Expanded Tech-Software Sector ETF
IHAK	iShares Cybersecurity and Tech ETF
IHDG	WisdomTree International Hedged Quality Dividend Growth Fund
IHE	iShares U.S. Pharmaceutical ETF
IHF	iShares U.S. Health Care Providers ETF
IHI	iShares U.S. Medical Devices ETF
IHY	VanEck International High Yield Bond ETF
IIGD	Invesco Investment Grade Defensive ETF
IJH	iShares Core S&P Mid-Cap ETF
IJJ	iShares S&P Mid-Cap 400 Value ETF
IJK	iShares S&P Mid-Cap 400 Growth ETF
IJR	iShares Core S&P Small-Cap ETF
IJS	iShares S&P SmallCap 600 Value ETF
IJT	iShares S&P SmallCap 600 Growth ETF
ILCB	iShares Morningstar Large-Cap ETF
ILCG	iShares Morningstar Large-Cap Growth ETF
ILCV	iShares Morningstar Large-Cap  Value ETF
ILF	iShares Latin America 40 ETF
ILIT	iShares Lithium Miners and Producers ETF
ILTB	iShares Core 10  Year USD Bond ETF
IMCB	iShares Morningstar Mid-Cap ETF
IMCG	iShares Morningstar Mid-Cap Growth ETF
IMCV	iShares Morningstar Mid-Cap Value ETF
IMF	Invesco Managed Futures Strategy ETF
IMFL	Invesco International Developed Dynamic Multifactor ETF
IMTB	iShares Core 5-10 Year USD Bond ETF
IMTG	Invesco Agency MBS ETF
IMTM	iShares MSCI Intl Momentum Factor ETF
IMVP	Invesco India ETF
INDA	iShares MSCI India ETF
INDH	WisdomTree India Hedged Equity Fund
INDY	iShares India 50 ETF
INDZ	VanEck India Select ETF
INMU	iShares Intermediate Muni Income Active ETF
INRO	iShares U.S. Industry Rotation Active ETF
INTF	iShares International Equity Factor ETF
INTM	Invesco Intermediate Municipal ETF
IOO	iShares Global 100 ETF
IPAC	iShares Core MSCI Pacific ETF
IPAV	Global X Infrastructure Development ex-U.S. ETF
IPKW	Invesco International BuyBack Achievers ETF
IQDG	WisdomTree International Quality Dividend Growth Fund
IQLT	iShares MSCI Intl Quality Factor ETF
IQQ	iShares Nasdaq 100 ETF
IQSZ	Invesco Global Equity Net Zero ETF
IROC	Invesco Rochester High Yield Municipal ETF
IRTR	iShares LifePath Retirement ETF
IRVH	Global X Interest Rate Volatility & Inflation Hedge ETF
ISCB	iShares Morningstar Small-Cap ETF
ISCF	iShares International Small-Cap Equity Factor ETF
ISCG	iShares Morningstar Small-Cap Growth ETF
ISCV	iShares Morningstar Small-Cap Value ETF
ISHG	iShares 1-3 Year International Treasury Bond ETF
ISMF	iShares Managed Futures Active ETF
ISRA	VanEck Israel ETF
ISTB	iShares Core 1-5 Year USD Bond ETF
ISTM	iShares Strategic Metals ETF
ISVL	iShares International Developed Small Cap Value Factor ETF
ITA	iShares U.S. Aerospace & Defense ETF
ITB	iShares U.S. Home Construction ETF
ITDB	iShares LifePath Target Date 2030 ETF
ITDC	iShares LifePath Target Date 2035 ETF
ITDD	iShares LifePath Target Date 2040 ETF
ITDE	iShares LifePath Target Date 2045 ETF
ITDF	iShares LifePath Target Date 2050 ETF
ITDG	iShares LifePath Target Date 2055 ETF
ITDH	iShares LifePath Target Date 2060 ETF
ITDI	iShares LifePath Target Date 2065 ETF
ITDJ	iShares LifePath Target Date 2070 ETF
ITM	VanEck Intermediate Muni ETF
ITOT	iShares Core S&P Total U.S. Stock Market ETF
IUS	Invesco RAFI Strategic US ETF
IUSB	iShares Core Universal USD Bond ETF
IUSG	iShares Core S&P U.S. Growth ETF
IUSV	iShares Core S&P U.S. Value ETF
IVE	iShares S&P 500 Value ETF
IVLU	iShares MSCI Intl Value Factor ETF
IVOG	Vanguard S&P Mid-Cap 400 Growth ETF
IVOO	Vanguard S&P Mid-Cap 400 ETF
IVOV	Vanguard S&P Mid-Cap 400 Value ETF
IVV	iShares Core S&P 500 ETF
IVVB	iShares Large Cap Deep Quarterly Laddered ETF
IVVM	iShares Large Cap Moderate Quarterly Laddered ETF
IVVW	iShares S&P 500 BuyWrite ETF
IVW	iShares S&P 500 Growth ETF
IWB	iShares Russell 1000 ETF
IWC	iShares Microcap ETF
IWD	iShares Russell 1000 Value ETF
IWF	iShares Russell 1000 Growth Fund
IWL	iShares Russell Top 200 ETF
IWM	iShares Russell 2000 Index Fund
IWMW	iShares Russell 2000 BuyWrite ETF
IWN	iShares Russell 2000 Value ETF
IWO	iShares Russell 2000 Growth Fund
IWP	iShares Russell Midcap Growth ETF
IWR	iShares Russell Mid-Cap ETF
IWS	iShares Russell Mid-Cap Value ETF
IWV	iShares Russell 3000 Fund
IWX	iShares Russell Top 200 Value ETF
IWY	iShares Russell Top 200 Growth ETF
IXC	iShares Global Energy ETF
IXG	iShares Global Financial ETF
IXJ	iShares Global Healthcare ETF
IXN	iShares Global Tech ETF
IXP	iShares Global Comm Services ETF
IXUS	iShares Core MSCI Total International Stock ETF
IYC	iShares U.S. Consumer Discretionary ETF
IYE	iShares U.S. Energy ETF
IYF	iShares U.S. Financial ETF
IYG	iShares U.S. Financial Services ETF
IYH	iShares U.S. Healthcare ETF
IYJ	iShares U.S. Industrials ETF
IYK	iShares U.S. Consumer Staples ETF
IYLD	iShares Morningstar Multi-Asset Income ETF
IYM	iShares U.S. Basic Materials ETF
IYR	iShares U.S. Real Estate ETF
IYT	iShares U.S. Transportation ETF
IYW	iShares U.S. Technology ETF
IYY	iShares Dow Jones U.S. ETF
IYZ	iShares U.S. Telecommunications ETF
JADE	JPMorgan Active Developing Markets Equity ETF
JAVA	JPMorgan Active Value ETF
JBND	JPMorgan Active Bond ETF
JCAL	JPMorgan California Tax Free Bond ETF
JCHI	JPMorgan Active China ETF
JCPB	JPMorgan Core Plus Bond ETF
JCPI	JPMorgan Inflation Managed Bond ETF
JDIV	JPMorgan Dividend Leaders ETF
JDOC	JPMorgan Healthcare Leaders ETF
JEMA	JPMorgan ActiveBuilders Emerging Markets Equity ETF
JEPI	JPMorgan Equity Premium Income ETF
JEPQ	JPMorgan Nasdaq Equity Premium Income ETF
JFLI	JPMorgan Flexible Income ETF
JFLX	JPMorgan Flexible Debt ETF
JGLO	JPMorgan Global Select Equity ETF
JGRO	JPMorgan Active Growth ETF
JIDE	JPMorgan International Dynamic ETF
JIG	JPMorgan International Growth ETF
JIRE	JPMorgan International Research Enhanced Equity ETF
JIVE	JPMorgan International Value ETF
JLVP	JPMorgan U.S. Large Cap Value Plus ETF
JMEE	JPMorgan Small & Mid Cap Enhanced Equity ETF
JMHI	JPMorgan High Yield Municipal ETF
JMMF	JPMorgan 100% U.S. Treasury Securities Money Market ETF
JMOM	JPMorgan U.S. Momentum Factor ETF
JMSI	JPMorgan Sustainable Municipal Income ETF
JMST	JPMorgan Ultra-Short Municipal Income ETF
JMTG	JPMorgan Mortgage-Backed Securities ETF
JMUB	JPMorgan Municipal ETF
JNK	State Street SPDR Bloomberg High Yield Bond ETF
JOYT	JPMorgan Equity and Options Total Return ETF
JPEF	JPMorgan Equity Focus ETF
JPEM	JPMorgan Diversified Return Emerging Markets Equity ETF
JPFP	JPMorgan Managed Futures Plus ETF
JPHY	JPMorgan Active High Yield ETF
JPIB	JPMorgan International Bond Opportunities ETF
JPIE	JPMorgan Income ETF
JPIN	JPMorgan Diversified Return International Equity ETF
JPLD	JPMorgan Limited Duration Bond ETF
JPMB	JPMorgan USD Emerging Markets Sovereign Bond ETF
JPME	JPMorgan Diversified Return U.S. Mid Cap Equity ETF
JPRE	JPMorgan Realty Income ETF
JPRF	JPMorgan Preferred and Income Securities ETF
JPSE	JPMorgan Diversified Return U.S. Small Cap Equity ETF
JPST	JPMorgan Ultra-Short Income ETF
JPSV	JPMorgan Active Small Cap Value ETF
JPUS	JPMorgan Diversified Return U.S. Equity ETF
JPXN	iShares JPX-Nikkei 400 ETF
JQUA	JPMorgan U.S. Quality Factor ETF
JSCP	JPMorgan Short Duration Core Plus ETF
JTEK	JPMorgan U.S. Tech Leaders ETF
JTNY	JPMorgan New York Tax Free Bond ETF
JULV	VanEck U.S. Equity Buffer ETF - July
JUSA	JPMorgan U.S. Research Enhanced Large Cap ETF
JVAL	JPMorgan U.S. Value Factor ETF
JXI	iShares Global Utilities ETF
KBE	State Street SPDR S&P Bank ETF
KBWB	Invesco KBW Bank ETF
KBWD	Invesco KBW High Dividend Yield Financial ETF
KBWP	Invesco KBW Property & Casualty Insurance ETF
KBWY	Invesco KBW Premium Yield Equity REIT ETF
KCE	State Street SPDR S&P Capital Markets ETF
KIE	State Street SPDR S&P Insurance ETF
KLMN	Invesco MSCI North America Climate ETF
KLMT	Invesco MSCI Global Climate 500 ETF
KNCT	Invesco Next Gen Connectivity ETF
KOMP	State Street SPDR S&P Kensho New Economies Composite ETF
KRE	State Street SPDR S&P Regional Banking ETF
KROP	Global X AgTech & Food Innovation ETF
KSA	iShares MSCI Saudi Arabia ETF
KWT	iShares MSCI Kuwait ETF
KXI	iShares Global Consumer Staples ETF
LCDS	JPMorgan Fundamental Data Science Large Core ETF
LCTD	iShares World ex U.S. Carbon Transition Readiness Aware Active ETF
LCTU	iShares U.S. Carbon Transition Readiness Aware Active ETF
LDEM	iShares ESG MSCI EM Leaders ETF
LDRC	iShares iBonds 1-5 Year Corporate Ladder ETF
LDRH	iShares iBonds 1-5 Year High Yield and Income Ladder ETF
LDRI	iShares iBonds 1-5 Year TIPS Ladder ETF
LDRT	iShares iBonds 1-5 Year Treasury Ladder ETF
LEMB	iShares J.P. Morgan EM Local Currency Bond
LFEQ	VanEck Long/Flat Trend ETF
LGDS	JPMorgan Fundamental Data Science Large Growth ETF
LGLV	State Street SPDR US Large Cap Low Volatility Index ETF
LIT	Global X Lithium & Battery Tech ETF
LLDR	Global X Long-Term Treasury Ladder ETF
LMUB	iShares Long-Term National Muni Bond ETF
LNGX	Global X U.S. Natural Gas ETF
LQD	iShares iBoxx $ Investment Grade Corporate Bond ETF
LQDB	iShares BBB Rated Corporate Bond ETF
LQDH	iShares Interest Rate Hedged Corporate Bond ETF
LQDI	iShares Inflation Hedged Corporate Bond ETF
LQDW	iShares Investment Grade Corporate Bond BuyWrite Strategy ETF
LRGF	iShares U.S. Equity Factor ETF
LVDS	JPMorgan Fundamental Data Science Large Value ETF
LVLN	State Street SPDR S&P Leveraged Loan ETF
MADE	iShares U.S. Manufacturing ETF
MAXJ	iShares Large Cap Max Buffer Jun ETF
MBB	iShares MBS ETF
MBBA	iShares Mortgage-Backed Securities Active ETF
MBBB	VanEck Moody's Analytics BBB Corporate Bond ETF
MCDS	JPMorgan Fundamental Data Science Mid Core ETF
MCHI	iShares MSCI China ETF
MDY	State Street SPDR S&P MIDCAP 400 ETF Trust
MDYG	State Street SPDR S&P 400 Mid Cap Growth ETF
MDYV	State Street SPDR S&P 400 Mid Cap Value ETF
MEAR	iShares Short Maturity Municipal Bond Active ETF
MGC	Vanguard Morningstar Mega Cap ETF
MGK	Vanguard Morningstar Mega Cap Growth ETF
MGV	Vanguard Morningstar Mega Cap Value ETF
MIG	VanEck Moody's Analytics IG Corporate Bond ETF
MILN	Global X Millennial Consumer ETF
MLDR	Global X Intermediate-Term Treasury Ladder ETF
MLN	VanEck Long Muni ETF
MLPA	Global X MLP ETF
MLPD	Global X MLP & Energy Infrastructure Covered Call ETF
MLPX	Global X MLP & Energy Infrastructure ETF
MMAX	iShares Large Cap Max Buffer Mar ETF
MMTM	State Street SPDR S&P 1500 Momentum Tilt ETF
MOAT	VanEck Morningstar Wide Moat ETF
MOO	VanEck Agribusiness ETF
MORT	VanEck Mortgage REIT Income ETF
MOTG	VanEck Morningstar Global Wide Moat ETF
MOTI	VanEck Morningstar International Moat ETF
MTGP	WisdomTree Mortgage Plus Bond Fund
MTRA	Invesco International Growth Focus ETF
MTUM	iShares MSCI USA Momentum Factor ETF
MUB	iShares National Muni Bond ETF
MUNY	Vanguard New York Tax-Exempt Bond ETF
MVAL	VanEck Morningstar Wide Moat Value ETF
MXI	iShares Global Materials ETF
NANR	State Street SPDR S&P North American Natural Resources ETF
NDIA	Global X India Active ETF
NEAR	iShares Short Duration Bond Active ETF
NLR	VanEck Uranium and Nuclear ETF
NODE	VanEck Onchain Economy ETF
NORW	Global X MSCI Norway ETF
NTSD	WisdomTree Efficient U.S. Plus International Equity Fund
NTSE	WisdomTree Emerging Markets Efficient Core Fund
NTSI	WisdomTree International Efficient Core Fund
NTSX	WisdomTree U.S. Efficient Core Fund
NYF	iShares New York Muni Bond ETF
NYSX	Global X NYSE 100 ETF
NZAC	State Street SPDR MSCI ACWI Climate Paris Aligned ETF
OEF	iShares S&P 100 Fund
OIH	VanEck Oil Services ETF
OMFL	Invesco Russell 1000 Dynamic Multifactor ETF
OMFS	Invesco Russell 2000 Dynamic Multifactor ETF
ONEO	State Street SPDR Russell 1000 Momentum Focus ETF
ONEV	State Street SPDR Russell 1000 Low Volatility Focus ETF
ONEY	State Street SPDR Russell 1000 Yield Focus ETF
ONOF	Global X Adaptive U.S. Risk Management ETF
OPPE	WisdomTree European Opportunities Fund
OPPG	WisdomTree GeoAlpha Opportunities Fund
OPPJ	WisdomTree Japan Opportunities Fund
ORBX	Global X Space Tech ETF
OUNZ	VanEck Merk Gold ETF
PABD	iShares Paris-Aligned Climate Optimized MSCI World ex USA ETF
PABU	iShares Paris-Aligned Climate Optimized MSCI USA ETF
PAVE	Global X U.S. Infrastructure Development ETF
PBD	Invesco Global Clean Energy ETF
PBE	Invesco Biotechnology & Genome ETF
PBJ	Invesco Food & Beverage ETF
PBP	Invesco S&P 500 BuyWrite ETF
PBTP	Invesco 0-5 Yr US TIPS ETF
PBUS	Invesco MSCI USA ETF
PBW	Invesco WilderHill Clean Energy ETF
PCEF	Invesco CEF Income Composite ETF
PCY	Invesco Emerging Markets Sovereign Debt ETF
PDBA	Invesco Agriculture Commodity Strategy No K-1 ETF
PDBC	Invesco Optimum Yield Diversified Commodity Strategy No K-1 ETF
PDN	Invesco RAFI Developed Markets ex-U.S. Small-Mid ETF
PDP	Invesco Dorsey Wright Momentum ETF
PEJ	Invesco Leisure and Entertainment ETF
PEY	Invesco High Yield Equity Dividend Achievers ETF
PEZ	Invesco Dorsey Wright Consumer Cyclicals Momentum ETF
PFF	iShares Preferred and Income Securities ETF
PFFD	Global X U.S. Preferred ETF
PFFV	Global X Variable Rate Preferred ETF
PFI	Invesco Dorsey Wright Financial Momentum ETF
PFIG	Invesco Fundamental Investment Grade Corporate Bond  ETF
PFM	Invesco Dividend Achievers ETF
PFXF	VanEck Preferred Securities ex Financials ETF
PGF	Invesco Financial Preferred ETF
PGHY	Invesco Global ex-US High Yield Corporate Bond ETF
PGJ	Invesco Golden Dragon China ETF
PGX	Invesco Preferred ETF
PHDG	Invesco S&P 500 Downside Hedged ETF
PHO	Invesco Water Resources ETF
PICB	Invesco International Corporate Bond ETF
PICK	iShares MSCI Global Select Metals & Mining Producers Fund
PID	Invesco International Dividend Achievers ETF
PIE	Invesco Dorsey Wright Emerging Markets Momentum ETF
PIO	Invesco Global Water ETF
PIPE	Invesco SteelPath MLP & Energy Infrastructure ETF
PIT	VanEck Commodity Strategy ETF
PIZ	Invesco Dorsey Wright Developed Markets Momentum ETF
PJP	Invesco Pharmaceuticals ETF
PKB	Invesco Building & Construction ETF
PKW	Invesco BuyBack Achievers ETF
PMMF	iShares Prime Money Market ETF
PNQI	Invesco Nasdaq Internet ETF
POWA	Invesco Bloomberg Pricing Power ETF
POWR	iShares U.S. Power Infrastructure ETF
PPA	Invesco Aerospace & Defense ETF
PPH	VanEck Pharmaceutical ETF
PRF	Invesco RAFI US 1000 ETF
PRFZ	Invesco RAFI US 1500 Small-Mid ETF
PRN	Invesco Dorsey Wright Industrials Momentum ETF
PSCC	Invesco S&P SmallCap Consumer Staples ETF
PSCD	Invesco S&P SmallCap Consumer Discretionary ETF
PSCE	Invesco S&P SmallCap Energy ETF
PSCF	Invesco S&P SmallCap Financials ETF
PSCH	Invesco S&P SmallCap Health Care ETF
PSCI	Invesco S&P SmallCap Industrials ETF
PSCM	Invesco S&P SmallCap Materials ETF
PSCT	Invesco S&P SmallCap Information Technology ETF
PSCU	Invesco S&P SmallCap Utilities & Communication Services ETF
PSI	Invesco Semiconductors ETF
PSK	State Street SPDR ICE Preferred Securities ETF
PSL	Invesco Dorsey Wright Consumer Staples Momentum ETF
PSP	Invesco Global Listed Private Equity ETF
PSR	Invesco Active U.S. Real Estate Fund
PTF	Invesco Dorsey Wright Technology Momentum ETF
PTH	Invesco Dorsey Wright Healthcare Momentum ETF
PUI	Invesco Dorsey Wright Utilities Momentum ETF
PVI	Invesco Floating Rate Municipal Income ETF
PWB	Invesco Large Cap Growth ETF
PWV	Invesco Large Cap Value ETF
PWZ	Invesco California AMT-Free Municipal Bond Portfolio
PXE	Invesco Energy Exploration & Production ETF
PXF	Invesco RAFI Developed Markets ex-U.S. ETF
PXH	Invesco RAFI Emerging Markets ETF
PXI	Invesco Dorsey Wright Energy Momentum ETF
PXJ	Invesco Oil & Gas Services ETF
PYZ	Invesco Dorsey Wright Basic Materials Momentum ETF
PZA	Invesco National AMT-Free Municipal Bond ETFo
PZT	Invesco New York AMT-Free Municipal Bond ETF
QAT	iShares MSCI Qatar ETF
QBIG	Invesco Top QQQ ETF
QCLR	Global X NASDAQ 100 Collar 95-110 ETF
QDIV	Global X S&P 500 Quality Dividend ETF
QEFA	State Street SPDR MSCI EAFE StrategicFactors ETF
QEMM	State Street SPDR MSCI Emerging Markets StrategicFactors ETF
QETH	Invesco Galaxy Ethereum ETF
QEW	Invesco QQQ Equal Weight ETF
QGRW	WisdomTree U.S. Quality Growth Fund
QHY	WisdomTree U.S. High Yield Corporate Bond Fund
QIG	WisdomTree U.S. Corporate Bond Fund
QLTA	iShares Aaa A Rated Corporate Bond ETF
QMID	WisdomTree U.S. MidCap Quality Growth Fund
QNDX	State Street SPDR Portfolio Nasdaq 100 ETF
QNXT	iShares Nasdaq-100 ex Top 30 ETF
QOWZ	Invesco Nasdaq Free Cash Flow Achievers ETF
QQA	Invesco QQQ Income Advantage ETF
QQHG	Invesco QQQ Hedged Advantage ETF
QQLV	Invesco QQQ Low Volatility ETF
QQMG	Invesco ESG NASDAQ 100 ETF
QQQ	Invesco QQQ Trust, Series 1
QQQJ	Invesco NASDAQ Next Gen 100 ETF
QQQM	Invesco NASDAQ 100 ETF
QQQS	Invesco NASDAQ Future Gen 200 ETF
QRMI	Global X NASDAQ 100 Risk Managed Income ETF
QSIG	WisdomTree U.S. Short Term Corporate Bond Fund
QSML	WisdomTree U.S. SmallCap Quality Growth Fund
QSOL	Invesco Galaxy Solana ETF
QTOP	iShares Nasdaq Top 30 Stocks ETF
QTR	Global X NASDAQ 100 Tail Risk ETF
QUAL	iShares MSCI USA Quality Factor ETF
QUS	State Street SPDR MSCI USA StrategicFactors ETF
QVML	Invesco S&P 500 QVM Multi-factor ETF
QVMM	Invesco S&P MidCap 400 QVM Multi-factor ETF
QVMS	Invesco S&P SmallCap 600 QVM Multi-factor ETF
QVMT	Invesco S&P 500 Concentrated QVM ETF
QWLD	State Street SPDR MSCI World StrategicFactors ETF
QYLD	Global X NASDAQ 100 Covered Call ETF
QYLG	Global X Nasdaq 100 Covered Call & Growth ETF
RAAX	VanEck Real Assets ETF
RACK	VanEck Data Center Supply Chain ETF
RDIV	Invesco S&P Ultra Dividend Revenue ETF
REET	iShares Global REIT ETF
REM	iShares Mortgage Real Estate ETF
REMX	VanEck Rare Earth and Strategic Metals ETF
REZ	iShares Residential and Multisector Real Estate ETF
RFG	Invesco S&P MidCap 400 Pure Growth ETF
RFV	Invesco S&P MidCap 400 Pure Value ETF
RING	iShares MSCI Global Gold Miners ETF
RMHY	Global X Adaptive Risk Managed Yield ETF
RNRG	Global X Renewable Energy Producers ETF
ROCQ	JPMorgan Nasdaq Equity Premium Yield ETF
ROCY	JPMorgan Equity Premium Yield ETF
ROKT	State Street SPDR S&P Kensho Final Frontiers ETF
RPG	Invesco S&P 500 Pure Growth ETF
RPV	Invesco S&P 500 Pure Value ETF
RSP	Invesco S&P 500 Equal Weight ETF
RSPA	Invesco S&P 500 Equal Weight Income Advantage ETF
RSPC	Invesco S&P 500 Equal Weight Communication Services ETF
RSPD	Invesco S&P 500 Equal Weight Consumer Discretionary ETF
RSPE	Invesco ESG S&P 500 Equal Weight ETF
RSPF	Invesco S&P 500 Equal Weight Financial ETF
RSPG	Invesco S&P 500 Equal Weight Energy ETF
RSPH	Invesco S&P 500 Equal Weight Health Care ETF
RSPM	Invesco S&P 500 Equal Weight Materials ETF
RSPN	Invesco S&P 500 Equal Weight Industrials Portfolio
RSPR	Invesco S&P 500 Equal Weight Real Estate ETF
RSPS	Invesco S&P 500 Equal Weight Consumer Staples ETF
RSPT	Invesco S&P 500 Equal Weight Technology ETF
RSPU	Invesco S&P 500 Equal Weight Utilities ETF
RSSL	Global X Russell 2000 ETF
RTH	VanEck Retail ETF
RWJ	Invesco S&P SmallCap 600 Revenue ETF
RWK	Invesco S&P MidCap 400 Revenue ETF
RWL	Invesco S&P 500 Revenue ETF
RWO	State Street SPDR Dow Jones Global Real Estate ETF
RWR	State Street SPDR Dow Jones REIT ETF
RWX	State Street SPDR Dow Jones International Real Estate ETF
RXI	iShares Global Consumer Discretionary ETF
RYLD	Global X Russell 2000 Covered Call ETF
RYLG	Global X Russell 2000 Covered Call & Growth ETF
RZG	Invesco S&P SmallCap 600 Pure Growth ETF
RZV	Invesco S&P SmallCap 600 Pure Value ETF
SATO	Invesco Alerian Galaxy Crypto Economy ETF
SCCR	Schwab Core Bond ETF
SCDS	JPMorgan Fundamental Data Science Small Core ETF
SCHA	Schwab U.S. Small-Cap ETF
SCHB	Schwab U.S. Broad Market ETF
SCHC	Schwab International Small-Cap Equity ETF
SCHD	Schwab US Dividend Equity ETF
SCHE	Schwab Emerging Markets Equity ETF
SCHF	Schwab International Equity ETF
SCHG	Schwab U.S. Large-Cap Growth ETF
SCHH	Schwab U.S. REIT ETF
SCHI	Schwab 5-10 Year Corporate Bond ETF
SCHJ	Schwab 1-5 Year Corporate Bond ETF
SCHK	Schwab 1000 Index ETF
SCHM	Schwab U.S. Mid Cap ETF
SCHO	Schwab Short-Term U.S. Treasury ETF
SCHP	Schwab U.S. TIPS ETF
SCHQ	Schwab Long-Term U.S. Treasury ETF
SCHR	Schwab Intermediate-Term U.S. Treasury ETF
SCHV	Schwab U.S. Large-Cap Value ETF
SCHX	Schwab U.S. Large-Cap ETF
SCHY	Schwab International Dividend Equity ETF
SCHZ	Schwab US Aggregate Bond ETF
SCJ	iShares MSCI Japan Sm Cap
SCMB	Schwab Municipal Bond ETF
SCUS	Schwab Ultra-Short Income ETF
SCYB	Schwab High Yield Bond ETF
SCZ	iShares MSCI EAFE Small-Cap ETF
SDEM	Global X MSCI SuperDividend Emerging Markets ETF
SDG	iShares MSCI Global Sustainable Development Goals ETF
SDIV	Global X SuperDividend ETF
SDY	State Street SPDR S&P Dividend ETF
SECU	iShares Securitized Income Active ETF
SGOV	iShares 0-3 Month Treasury Bond ETF
SGVT	Schwab Government Money Market ETF
SHAG	WisdomTree Yield Enhanced U.S. Short-Term Aggregate Bond Fund
SHE	State Street SPDR MSCI USA Gender Diversity ETF
SHLD	Global X Defense Tech ETF
SHM	State Street SPDR Nuveen ICE Short Term Municipal Bond ETF
SHV	iShares 0-1 Year Treasury Bond ETF
SHY	iShares 1-3 Year Treasury Bond ETF
SHYD	VanEck Short High Yield Muni ETF
SHYG	iShares 0-5 Year High Yield Corporate Bond ETF
SHYM	iShares Short Duration High Yield Muni Active ETF
SIL	Global X Silver Miners ETF
SIMS	State Street SPDR S&P Kensho Intelligent Structures ETF
SIZE	iShares MSCI USA Size Factor ETF
SJNK	State Street SPDR Bloomberg Short Term High Yield Bond ETF
SLDR	Global X Short-Term Treasury Ladder ETF
SLQD	iShares 0-5 Year Investment Grade Corporate Bond ETF
SLV	iShares Silver Trust
SLVP	iShares MSCI Global Silver and Metals Miners ETF
SLX	VanEck Steel ETF
SLYG	State Street SPDR S&P 600 Small Cap Growth ETF
SLYV	State Street SPDR S&P 600 Small Cap Value ETF
SMAX	iShares Large Cap Max Buffer Sep ETF
SMB	VanEck Short Muni ETF
SMBS	Schwab Mortgage-Backed Securities ETF
SMH	VanEck Semiconductor ETF
SMHC	VanEck China Semiconductor ETF
SMHX	VanEck Fabless Semiconductor ETF
SMIN	Ishares MSCI India Small Cap ETF
SMLF	iShares U.S. Small-Cap Equity Factor ETF
SMLV	State Street SPDR US Small Cap Low Volatility Index ETF
SMMD	iShares Russell 2500 ETF
SMMV	iShares MSCI USA Small-Cap Min Vol Factor ETF
SMOG	VanEck Low Carbon Energy ETF
SMOT	VanEck Morningstar SMID Moat ETF
SNSR	Global X Internet of Things ETF
SOCL	Global X Social Media ETF
SOXQ	Invesco PHLX Semiconductor ETF
SOXX	iShares PHLX SOX Semiconductor Sector Index Fund
SPAB	State Street SPDR Portfolio Aggregate Bond ETF
SPBO	State Street SPDR Portfolio Corporate Bond ETF
SPDG	State Street SPDR Portfolio S&P Sector Neutral Dividend ETF
SPDW	State Street SPDR Portfolio Developed World ex-US ETF
SPEM	State Street SPDR Portfolio Emerging Markets ETF
SPEU	State Street SPDR Portfolio Europe ETF
SPFF	Global X SuperIncome Preferred ETF
SPGM	State Street SPDR Portfolio MSCI Global Stock Market ETF
SPGP	Invesco S&P 500 GARP ETF
SPHB	Invesco S&P 500 High Beta ETF
SPHD	Invesco S&P 500 High Dividend Low Volatility ETF
SPHQ	Invesco S&P 500 Quality ETF
SPHY	State Street SPDR Portfolio High Yield Bond ETF
SPIB	State Street SPDR Portfolio Intermediate Term Corporate Bond ETF
SPIP	State Street SPDR Portfolio TIPS ETF
SPLB	State Street SPDR Portfolio Long Term Corporate Bond ETF
SPLV	Invesco S&P 500 Low Volatility ETF
SPMB	State Street SPDR Portfolio Mortgage Backed Bond ETF
SPMD	State Street SPDR Portfolio S&P 400 Mid Cap ETF
SPMO	Invesco S&P 500 Momentum ETF
SPSB	State Street SPDR Portfolio Short Term Corporate Bond ETF
SPSM	State Street SPDR Portfolio S&P 600 Small Cap ETF
SPTB	State Street SPDR Portfolio Treasury ETF
SPTI	State Street SPDR Portfolio Intermediate Term Treasury ETF
SPTL	State Street SPDR Portfolio Long Term Treasury ETF
SPTM	State Street SPDR Portfolio S&P 1500 Composite Stock Market ETF
SPTS	State Street SPDR Portfolio Short Term Treasury ETF
SPTU	State Street SPDR Portfolio Ultra Short T-Bill ETF
SPVM	Invesco S&P 500 Value with Momentum ETF
SPY	State Street SPDR S&P 500 ETF Trust
SPYD	State Street SPDR Portfolio S&P 500 High Dividend ETF
SPYG	State Street SPDR Portfolio S&P 500 Growth ETF
SPYM	State Street SPDR Portfolio S&P 500 ETF
SPYV	State Street SPDR Portfolio S&P 500 Value ETF
SPYX	State Street SPDR S&P 500 Fossil Fuel Reserves Free ETF
SQLT	iShares MSCI USA Small-Cap Quality Factor ETF
SRET	Global X SuperDividend REIT ETF
STCE	Schwab Crypto Thematic Natural Language Processing ETF
STEN	iShares Large Cap 10% Target Buffer Sep ETF
STIP	iShares 0-5 Year TIPS Bond ETF
SUB	iShares Short-Term National Muni Bond ETF
SUSA	iShares ESG Optimized MSCI USA ETF
SUSB	iShares ESG Aware 1-5 Year USD Corporate Bond ETF
SUSC	iShares ESG Aware USD Corporate Bond ETF
SUSL	iShares ESG MSCI USA Leaders ETF
SVAL	iShares US Small Cap Value Factor ETF
SYSB	iShares Systematic Bond ETF
TAN	Invesco Solar ETF
TBLL	Invesco Short Term Treasury ETF
TCHI	iShares MSCI China Multisector Tech ETF
TECB	iShares U.S. Tech Breakthrough Multisector ETF
TEK	iShares Technology Opportunities Active ETF
TEND	iShares Large Cap 10% Target Buffer Dec ETF
TENJ	iShares Large Cap 10% Target Buffer Jun ETF
TENM	iShares Large Cap 10% Target Buffer Mar ETF
TEXN	iShares Texas Equity ETF
TFI	State Street SPDR Nuveen ICE Municipal Bond ETF
TFLO	iShares Treasury Floating Rate Bond ETF
THD	iShares MSCI Thailand ETF
THRO	iShares U.S. Thematic Rotation Active ETF
TIP	iShares TIPS Bond ETF
TIPX	State Street SPDR Bloomberg 1a??10 Year TIPS ETF
TLH	iShares 10-20 Year Treasury Bond ETF
TLT	iShares 20+ Year Treasury Bond ETF
TLTW	iShares 20+ Year Treasury Bond BuyWrite Strategy ETF
TLTX	Global X Treasury Bond Enhanced Income ETF
TOK	iShares MSCI Kokusai ETF
TOPC	iShares S&P 500 3% Capped ETF
TOPT	iShares Top 20 U.S. Stocks ETF
TROT	Invesco MSCI Treasury Duration Rotation ETF
TRUC	VanEck Communication Services TruSector ETF
TRUD	VanEck Consumer Discretionary TruSector ETF
TRUF	VanEck Financials TruSector ETF
TRUH	VanEck Healthcare TruSector ETF
TRUI	VanEck Industrials TruSector ETF
TRUM	VanEck Materials TruSector ETF
TRUN	VanEck Energy TruSector ETF
TRUO	VanEck Consumer Staples TruSector ETF
TRUR	VanEck Real Estate TruSector ETF
TRUT	VanEck Technology TruSector ETF
TRUU	VanEck Utilities TruSector ETF
TUR	iShares MSCI Turkey ETF
TWOX	iShares Large Cap Accelerated Outcome ETF
TYLG	Global X Information Technology Covered Call & Growth ETF
UAE	iShares MSCI UAE ETF
UCBG	State Street SPDR UC Investments 90/10 Endowment Strategy Index ETF
UDN	Invesco DB USD Index Bearish ETF
UNIY	WisdomTree Voya Yield Enhanced USD Universal Bond Fund
UPGD	Invesco Bloomberg Analyst Rating Improvers ETF
URA	Global X Uranium ETF
URTH	iShares MSCI World ETF
USCL	iShares Climate Conscious & Transition MSCI USA ETF
USDU	WisdomTree Bloomberg U.S. Dollar Bullish Fund
USFR	WisdomTree Floating Rate Treasury Fund
USHY	iShares Broad USD High Yield Corporate Bond ETF
USIG	iShares Broad USD Investment Grade Corporate Bond ETF
USIN	WisdomTree 7-10 Year Laddered Treasury Fund
USLN	iShares Broad USD Floating Rate Loan ETF
USMF	WisdomTree U.S. Multifactor Fund
USMV	iShares MSCI USA Min Vol Factor ETF
USRT	iShares Core U.S. REIT ETF
USSH	WisdomTree 1-3 Year Laddered Treasury Fund
USXF	iShares ESG Advanced MSCI USA ETF
UUP	Invesco DB USD Index Bullish Fund ETF
VAVX	VanEck Avalanche ETF
VAW	Vanguard Materials ETF
VB	Vanguard Morningstar Small-Cap ETF
VBCA	Vanguard Target Maturity 2027 Corporate Bond ETF
VBCB	Vanguard Target Maturity 2028 Corporate Bond ETF
VBCC	Vanguard Target Maturity 2029 Corporate Bond ETF
VBCD	Vanguard Target Maturity 2030 Corporate Bond ETF
VBCE	Vanguard Target Maturity 2031 Corporate Bond ETF
VBCF	Vanguard Target Maturity 2032 Corporate Bond ETF
VBCG	Vanguard Target Maturity 2033 Corporate Bond ETF
VBCH	Vanguard Target Maturity 2034 Corporate Bond ETF
VBCI	Vanguard Target Maturity 2035 Corporate Bond ETF
VBCJ	Vanguard Target Maturity 2036 Corporate Bond ETF
VBIL	Vanguard 0-3 Month Treasury Bill ETF
VBK	Vanguard Morningstar Small-Cap Growth ETF
VBNB	VanEck BNB ETF
VBR	Vanguard Morningstar Small-Cap Value ETF
VCEB	Vanguard ESG U.S. Corporate Bond ETF
VCHY	Vanguard U.S. High-Yield Corporate Bond Index ETF
VCIT	Vanguard Intermediate-Term Corporate Bond ETF
VCLT	Vanguard Long-Term Corporate Bond ETF
VCR	Vanguard Consumer Discretion ETF
VCRB	Vanguard Core Bond ETF
VCRM	Vanguard Core Tax-Exempt Bond ETF
VCSH	Vanguard Short-Term Corporate Bond ETF
VDC	Vanguard Consumer Staples ETF
VDE	Vanguard Energy ETF
VDG	Vanguard Developed Markets ex-US Growth Index ETF
VDIG	Vanguard Wellington Dividend Growth Active ETF
VDV	Vanguard Developed Markets ex-US Value Index ETF
VEA	Vanguard FTSE Developed Markets ETF
VEFA	VanEck MSCI EAFE Analyst Sentiment ETF
VEGI	iShares MSCI Agriculture Producers ETF
VEU	Vanguard FTSE All World Ex US ETF
VEXC	Vanguard Emerging Markets Ex-China ETF
VFH	Vanguard Financials ETF
VFMF	Vanguard U.S. Multifactor ETF
VFMO	Vanguard U.S. Momentum Factor ETF
VFMV	Vanguard U.S. Minimum Volatility ETF
VFQY	Vanguard U.S. Quality Factor ETF
VFVA	Vanguard U.S. Value Factor ETF
VGHY	Vanguard High-Yield Active ETF
VGIT	Vanguard Intermediate-Term Treasury ETF
VGK	Vanguard FTSEEuropean ETF
VGLT	Vanguard Long-Term Treasury ETF
VGMS	Vanguard Multi-Sector Income Bond ETF
VGSH	Vanguard Short-Term Treasury ETF
VGT	Vanguard Information Tech ETF
VGUS	Vanguard Ultra-Short Treasury ETF
VGVT	Vanguard Government Securities Active ETF
VHT	Vanguard Health Care ETF
VIG	Vanguard Div Appreciation ETF
VIGI	Vanguard International Dividend Appreciation ETF
VIOG	Vanguard S&P Small-Cap 600 Growth ETF
VIOO	Vanguard S&P Small-Cap 600 ETF
VIOV	Vanguard S&P Small-Cap 600 Value ETF
VIS	Vanguard Industrials ETF
VLU	State Street SPDR S&P 1500 Value Tilt ETF
VLUE	iShares MSCI USA Value Factor ETF
VMBS	Vanguard Mortgage-Backed Securities ETF
VNAM	Global X MSCI Vietnam ETF
VNM	VanEck Vietnam ETF
VNQ	Vanguard Real Estate ETF
VNQI	Vanguard Global ex-U.S. Real Estate ETF
VO	Vanguard Morningstar Mid-Cap ETF
VOE	Vanguard Morningstar Mid-Cap Value ETF
VONE	Vanguard Russell 1000 ETF
VONG	Vanguard Russell 1000 Growth ETF
VONV	Vanguard Russell 1000 Value ETF
VOO	Vanguard S&P 500 ETF
VOOG	Vanguard S&P 500 Growth ETF
VOOV	Vanguard S&P 500 Value ETF
VOT	Vanguard Morningstar Mid-Cap Growth ETF
VOX	Vanguard Communication Services  ETF
VPL	Vanguard FTSE Pacific ETF
VPLS	Vanguard Core Plus Bond ETF
VPU	Vanguard Utilities ETF
VRIG	Invesco Variable Rate Investment Grade ETF
VRP	Invesco Variable Rate Preferred ETF
VSDB	Vanguard Short Duration Bond ETF
VSDM	Vanguard Short Duration Tax-Exempt Bond ETF
VSGX	Vanguard ESG International Stock ETF
VSOL	VanEck Solana ETF
VSS	Vanguard FTSE All-Wld ex-US SmCp Idx ETF
VT	Vanguard Total World Stock Index ETF
VTC	Vanguard Total Corporate Bond ETF
VTEB	Vanguard Tax-Exempt Bond ETF
VTEC	Vanguard California Tax-Exempt Bond ETF
VTEI	Vanguard Tax-Managed Funds Vanguard Intermediate-Term Tax-Exempt Bond ETF
VTEL	Vanguard Long-Term Tax-Exempt Bond ETF
VTES	Vanguard Wellington Fund Vanguard Short-Term Tax Exempt Bond ETF
VTG	Vanguard Total Treasury ETF
VTHR	Vanguard Russell 3000 ETF
VTI	Vanguard Morningstar Total Stock Market ETF
VTIP	Vanguard Short-Term Inflation-Protected Securities Index Fund ETF Shares
VTP	Vanguard Total Inflation-Protected Securities ETF
VTV	Vanguard Morningstar Value ETF
VTWG	Vanguard Russell 2000 Growth ETF
VTWO	Vanguard Russell 2000 ETF
VTWV	Vanguard Russell 2000 Value ETF
VUG	Vanguard Morningstar Growth ETF
VUSB	Vanguard Ultra-Short Bond ETF
VUSG	Vanguard Wellington U.S. Growth Active ETF
VUSV	Vanguard Wellington U.S. Value Active ETF
VV	Vanguard Morningstar Large-Cap ETF
VWO	Vanguard FTSE Emerging Markets ETF
VWOB	Vanguard Emerging Markets Government Bond ETF
VXF	Vanguard Extended Market ETF
VXUS	Vanguard Total International Stock ETF
VYM	Vanguard High Dividend Yield ETF
VYMI	Vanguard International High Dividend Yield ETF
WAMA	WisdomTree US Adaptive Moving Average Fund
WARP	VanEck Space ETF
WCBR	WisdomTree Cybersecurity Fund
WCLD	WisdomTree Cloud Computing Fund
WDAF	WisdomTree Asia Defense Fund
WDEF	WisdomTree Europe Defense Fund
WDGF	WisdomTree Global Defense Fund
WDIG	WisdomTree Efficient Rare Earth Plus Strategic Metals Fund
WDIV	State Street SPDR S&P Global Dividend ETF
WDNA	WisdomTree BioRevolution Fund
WDRN	WisdomTree Physical AI, Humanoids and Drones Fund
WIMA	WisdomTree International Adaptive Moving Average Fund
WIP	State Street SPDR FTSE International Government Inflation-Protected Bond ETF
WOOD	iShares Global Timber & Forestry ETF
WQTM	WisdomTree Quantum Computing Fund
WSML	iShares MSCI World Small-Cap ETF
WSPC	WisdomTree Space Economy Fund
WTAI	WisdomTree Artificial Intelligence and Innovation Fund
WTBN	WisdomTree Bianco Total Return Fund
WTIP	WisdomTree Inflation Plus Fund
WTLS	WisdomTree Efficient Long/Short U.S. Equity Fund
WTMF	WisdomTree Managed Futures Strategy Fund
WTMU	WisdomTree Core Laddered Municipal Fund
WTMY	WisdomTree High Income Laddered Municipal Fund
WTPI	WisdomTree Equity Premium Income Fund
WTRE	WisdomTree New Economy Real Estate Fund
WTV	WisdomTree U.S. Value Fund
XAR	State Street SPDR S&P Aerospace & Defense ETF
XBI	State Street SPDR S&P Biotech ETF
XC	WisdomTree True Emerging Markets Fund
XCLR	Global X S&P 500 Collar 95-110 ETF
XCNY	State Street SPDR S&P Emerging Markets ex-China ETF
XES	State Street SPDR S&P Oil & Gas Equipment & Services ETF
XHB	State Street SPDR S&P Homebuilders ETF
XHE	State Street SPDR S&P Health Care Equipment ETF
XHS	State Street SPDR S&P Health Care Services ETF
XITK	State Street SPDR FactSet Innovative Technology ETF
XJH	iShares ESG Select Screened S&P Mid-Cap ETF
XJR	iShares ESG Select Screened S&P Small-Cap ETF
XLB	State Street Materials Select Sector SPDR ETF
XLBI	State Street Materials Select Sector SPDR Premium Income ETF
XLC	State Street Communication Services Select Sector SPDR ETF
XLCI	State Street Communication Services Select Sector SPDR Premium Income ETF
XLE	State Street Energy Select Sector SPDR ETF
XLEI	State Street Energy Select Sector SPDR Premium Income ETF
XLF	State Street Financial Select Sector SPDR ETF
XLFI	State Street Financial Select Sector SPDR Premium Income ETF
XLG	Invesco S&P 500 Top 50 ETF
XLI	State Street Industrial Select Sector SPDR ETF
XLII	State Street Industrial Select Sector SPDR Premium Income ETF
XLK	State Street Technology Select Sector SPDR ETF
XLKI	State Street Technology Select Sector SPDR Premium Income ETF
XLP	State Street Consumer Staples Select Sector SPDR ETF
XLRE	State Street Real Estate Select Sector SPDR ETF
XLRI	State Street Real Estate Select Sector SPDR Premium Income ETF
XLSI	State Street Consumer Staples Select Sector SPDR Premium Income ETF
XLU	State Street Utilities Select Sector SPDR ETF
XLUI	State Street Utilities Select Sector SPDR Premium Income ETF
XLV	State Street Health Care Select Sector SPDR ETF
XLVI	State Street Health Care Select Sector SPDR Premium Income ETF
XLY	State Street Consumer Discretionary Select Sector SPDR ETF
XLYI	State Street Consumer Discretionary Select Sector SPDR Premium Income ETF
XME	State Street SPDR S&P Metals & Mining ETF
XMHQ	Invesco S&P MidCap Quality ETF
XMLV	Invesco S&P MidCap Low Volatility ETF
XMMO	Invesco S&P MidCap Momentum ETF
XMPT	VanEck CEF Muni Income ETF
XMVM	Invesco S&P MidCap Value with Momentum ETF
XNTK	State Street SPDR NYSE Technology ETF
XOEF	iShares S&P 500 ex S&P 100 ETF
XOP	State Street SPDR S&P Oil & Gas Exploration & Production ETF
XPH	State Street SPDR S&P Pharmaceuticals ETF
XRMI	Global X S&P 500 Risk Managed Income ETF
XRT	State Street SPDR S&P Retail ETF
XSD	State Street SPDR S&P Semiconductor ETF
XSHD	Invesco S&P SmallCap High Dividend Low Volatility ETF
XSHQ	Invesco S&P SmallCap Quality ETF
XSLV	Invesco S&P SmallCap Low Volatility ETF
XSMO	Invesco S&P SmallCap Momentum ETF
XSOE	WisdomTree Emerging Markets Ex-State Owned Enterprises Fund
XSVM	Invesco S&P SmallCap Value with Momentum ETF
XSW	State Street SPDR S&P Software & Services ETF
XT	iShares Future Exponential Technologies ETF
XTL	State Street SPDR S&P Telecom ETF
XTN	State Street SPDR S&P Transportation ETF
XTR	Global X S&P 500 Tail Risk ETF
XVV	iShares ESG Select Screened S&P 500 ETF
XYLD	Global X S&P 500 Covered Call ETF
XYLG	Global X S&P 500 Covered Call & Growth ETF
ZAP	Global X U.S. Electrification ETF
ZCBA	Global X Zero Coupon Bond 2030 ETF
ZCBB	Global X Zero Coupon Bond 2031 ETF
ZCBC	Global X Zero Coupon Bond 2032 ETF
ZCBE	Global X Zero Coupon Bond 2033 ETF
ZCBF	Global X Zero Coupon Bond 2034 ETF
ZCBG	Global X Zero Coupon Bond 2035 ETF"""
ETF_NAMES = dict(line.split("\t", 1) for line in ETF_CATALOG_TSV.splitlines() if line.strip())
DEFAULT_ETFS = tuple(dict.fromkeys((*CORE_ETFS, *ETF_NAMES)))


def thai_time(value):
    if value is None or value == "":
        return "ยังไม่มีข้อมูล"
    try:
        stamp = pd.Timestamp(value, unit="s", tz="UTC") if isinstance(value,(int,float)) else pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        return stamp.tz_convert("Asia/Bangkok").strftime("%d/%m/%Y %H:%M:%S") + " น. (ไทย)"
    except (ValueError, TypeError):
        return "ไม่ทราบเวลา"


def completed_daily_history(history, now=None):
    """Conservatively exclude today's bar in the exchange timezone.

    This avoids comparing incomplete intraday volume with completed daily volume.
    After the close, today's candle is intentionally used from the next local day.
    """
    f = normalize_history(history)
    current = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    # Daily yf.download output for the US ETF basket can have a naive index.
    market_today = current.tz_convert(f.index.tz or "America/New_York").date()
    return f.loc[f.index.date < market_today]


def snapshot_return(history, months):
    if history is None or history.empty:
        return None
    start = history.index[-1] - pd.DateOffset(months=months)
    if history.index[0] > start:
        return None
    subset = history.loc[history.index >= start]
    first = number(subset.Close.iloc[0])
    return (float(subset.Close.iloc[-1])/first-1)*100 if len(subset)>1 and first and first>0 else None


def etf_directory_rows(tickers):
    """The full catalog is available without making any price requests."""
    return pd.DataFrame([{"Ticker":t,"Asset_Type":"ETF","ETF_Name":ETF_NAMES.get(t,t),
                          "Status":"ไม่มีข้อมูล","Data_Source":"ETF เพิ่มเติม","Data_Time":"",
                          "Price_AsOf":"","Data_Status":"ยังไม่โหลดราคา"} for t in dict.fromkeys(tickers)])


@st.cache_data(ttl=300, show_spinner=False)
def _load_etf_batch(tickers):
    """One bounded request, cached independently of other batches."""
    if len(tickers)>ETF_BATCH_SIZE:
        raise ValueError("จำนวน Ticker เกินขนาดชุดโหลด")
    rows = {row["Ticker"]:row for row in etf_directory_rows(tickers).to_dict("records")}
    errors, success_time = [], ""
    if not tickers:
        return pd.DataFrame(), success_time, errors
    try:
        batch = yf.download(list(tickers),period="2y",interval="1d",group_by="ticker",auto_adjust=True,
                            threads=4,progress=False,timeout=15)
        if batch is None or batch.empty:
            raise ValueError("แหล่งราคาไม่ส่งข้อมูล ETF กลับมา")
        stamp = datetime.now(timezone.utc).isoformat()
        for ticker in tickers:
            try:
                if isinstance(batch.columns,pd.MultiIndex):
                    f = batch[ticker] if ticker in batch.columns.get_level_values(0) else batch.xs(ticker,axis=1,level=1)
                elif len(tickers)==1:
                    f=batch
                else:
                    raise ValueError("ไม่พบคอลัมน์ราคา")
                f = completed_daily_history(f)
                if f.empty:
                    raise ValueError("ไม่พบแท่งวันที่สมบูรณ์")
                s = daily_snapshot(f)
                complete = all(s.get(k) is not None for k in ("Close","EMA20","EMA50"))
                rows[ticker].update(s)
                rows[ticker].update({"Status":("PASS" if s['Close']>s['EMA20']>s['EMA50'] else "FAIL") if complete else "ไม่มีข้อมูล",
                                     "Historical_Return":snapshot_return(f,12),"Data_Time":stamp,
                                     "Price_AsOf":s.get("Bar_Date",""),"Data_Status":"โหลดสำเร็จ"})
                success_time=stamp
            except Exception as exc:
                rows[ticker]["Data_Status"]="โหลดไม่สำเร็จ"
                errors.append(f"{ticker}: {exc}")
    except Exception as exc:
        for row in rows.values():
            row["Data_Status"]="โหลดไม่สำเร็จ"
        errors.append(str(exc))
    return pd.DataFrame(rows.values()),success_time,errors


def load_etf_watchlist(tickers):
    """Split requests so an expanded catalog never becomes one huge download."""
    tickers=tuple(dict.fromkeys(tickers))
    frames,stamp,errors=[],"",[]
    for start in range(0,len(tickers),ETF_BATCH_SIZE):
        frame,last,problems=_load_etf_batch(tickers[start:start+ETF_BATCH_SIZE])
        frames.append(frame)
        stamp=last or stamp
        errors.extend(problems)
    return pd.concat(frames,ignore_index=True) if frames else etf_directory_rows(()),stamp,errors


load_etf_watchlist.clear = _load_etf_batch.clear


def remember_etf_quotes(existing, incoming):
    """A failed retry keeps the last successful price and its original timestamp."""
    result={ticker:row.copy() for ticker,row in existing.items()}
    for row in incoming.to_dict("records"):
        ticker=row["Ticker"]
        if row.get("Data_Status")=="โหลดสำเร็จ" or ticker not in result:
            previous=result.get(ticker,{})
            if row.get("Data_Status")=="โหลดสำเร็จ" and previous.get("Data_Time") and row.get("Data_Time"):
                try:
                    if pd.Timestamp(previous["Data_Time"])>pd.Timestamp(row["Data_Time"]):
                        continue
                except (ValueError,TypeError):
                    pass
            result[ticker]=row
        else:
            result[ticker]["Data_Status"]="โหลดใหม่ไม่สำเร็จ — แสดงข้อมูลเดิมถ้ามี"
    return result


def prepare_etf_universe(tickers, saved=None):
    directory=etf_directory_rows(tickers)
    if directory.empty or not saved:
        return directory
    rows=[]
    for row in directory.to_dict("records"):
        rows.append({**row,**saved.get(row["Ticker"],{})})
    return pd.DataFrame(rows)


def pause_auto_refresh_for_scan():
    # The button callback runs before the next script execution, so a long
    # full-universe scan cannot be interrupted by the five-minute rerun timer.
    st.session_state["auto_refresh"]=False


def render_etf_loader(tickers, scan_next=False, scan_all=False, retry_failed=False):
    """Load core symbols automatically; full-universe requests require the scan button."""
    if "etf_quotes" not in st.session_state:
        st.session_state.etf_quotes={}
        st.session_state.etf_attempted=[]
    stored=st.session_state.etf_quotes
    attempted=set(st.session_state.etf_attempted)
    errors=[]
    first,_,problems=load_etf_watchlist(tuple(t for t in CORE_ETFS if t in tickers))
    stored=remember_etf_quotes(stored,first)
    attempted.update(first.Ticker if not first.empty else [])
    errors.extend(problems)
    remaining=[t for t in tickers if t not in attempted]
    if scan_all:
        pending=list(tickers)
    elif retry_failed:
        pending=[t for t in tickers if t in stored and stored[t].get("Data_Status")!="โหลดสำเร็จ"][:ETF_BATCH_SIZE]
    elif scan_next:
        pending=remaining[:ETF_BATCH_SIZE]
    else:
        pending=[]
    if scan_next and not pending:
        st.info("ครบทุกชุดแล้ว ใช้ปุ่มลองใหม่สำหรับตัวที่โหลดไม่สำเร็จ หรือรีเฟรชทั้งชุด")
    progress=st.progress(0,text=f"กำลังโหลดราคา ETF {len(pending):,} ตัว") if pending else None
    for start in range(0,len(pending),ETF_BATCH_SIZE):
        group=tuple(pending[start:start+ETF_BATCH_SIZE])
        incoming,_,problems=load_etf_watchlist(group)
        stored=remember_etf_quotes(stored,incoming)
        attempted.update(group)
        errors.extend(problems)
        # Checkpoint each chunk so previous results survive a interrupted scan.
        st.session_state.etf_quotes=stored
        st.session_state.etf_attempted=sorted(attempted)
        progress.progress(min(1,(start+len(group))/len(pending)),text=f"ลองโหลดแล้ว {start+len(group):,}/{len(pending):,} ตัว")
        if incoming.empty or not incoming.Data_Status.eq("โหลดสำเร็จ").any():
            st.warning("ชุดนี้โหลดราคาไม่ได้ทุกตัว จึงหยุดการโหลดรอบนี้ ข้อมูลที่สำเร็จก่อนหน้ายังอยู่ กดโหลดชุดถัดไปหรือลองใหม่ได้ภายหลัง")
            break
    if progress:
        progress.empty()
    st.session_state.etf_quotes=stored
    st.session_state.etf_attempted=sorted(attempted)
    frame=prepare_etf_universe(tickers,stored)
    times=[str(row.get("Data_Time")) for row in stored.values() if row.get("Data_Time")]
    return frame,max(times) if times else "",errors


def merge_etf_watchlist(frame, etfs):
    original=frame.copy()
    for col,default in [("Data_Source","CSV เดิม"),("Data_Status","จาก CSV"),("Data_Time",""),("Price_AsOf","")]:
        if col not in original:
            original[col]=default
        original[col]=original[col].fillna(default)
    original.loc[original.Ticker.isin(DEFAULT_ETFS),"Asset_Type"]="ETF"
    original["Asset_Type"]=original.Asset_Type.replace({"EQUITY":"Common Stock","Equity":"Common Stock","etf":"ETF"})
    if etfs is not None and not etfs.empty:
        original.loc[original.Ticker.isin(etfs.Ticker),"Asset_Type"]="ETF"
        # Refresh previously exported supplemental rows, while preserving scanner rows.
        for _,fresh in etfs.iterrows():
            mask=original.Ticker.eq(fresh.Ticker) & original.Data_Source.eq("ETF เพิ่มเติม")
            if mask.any():
                if fresh.get("Data_Status")=="โหลดสำเร็จ":
                    for col,value in fresh.items():
                        if col not in original:
                            original[col]=np.nan if col in NUMERIC_COLUMNS else ""
                        original.loc[mask,col]=value
                elif "ไม่สำเร็จ" in str(fresh.get("Data_Status","")):
                    original.loc[mask,"Data_Status"]="โหลดใหม่ไม่สำเร็จ — แสดงข้อมูลเดิมถ้ามี"
        # Existing scanner observations retain their original source and values.
        additions=etfs.loc[~etfs.Ticker.isin(original.Ticker)]
        original=pd.concat([original,additions],ignore_index=True)
    for col in NUMERIC_COLUMNS:
        if col not in original:
            original[col]=np.nan
        original[col]=pd.to_numeric(original[col],errors="coerce")
    if "ETF_Name" not in original:
        original["ETF_Name"]=""
    names=original.ETF_Name.astype("string")
    original["ETF_Name"]=names.where(names.ne(""),pd.NA).fillna(original.Ticker.map(ETF_NAMES)).fillna("")
    return original


def asset_is_etf(ticker, row, info):
    return info.get("quoteType")=="ETF" or ticker in DEFAULT_ETFS or "ETF" in str(row.get("Asset_Type","")).upper()


@st.cache_data(ttl=3600, show_spinner=False)
def load_dividend_history(ticker):
    try:
        # An explicit history request distinguishes missing data from zero dividends.
        f=yf.Ticker(ticker).history(period="max",interval="1d",actions=True,auto_adjust=False,timeout=20)
        if f is None or f.empty or "Dividends" not in f:
            raise ValueError("แหล่งข้อมูลไม่ได้ส่งประวัติปันผลกลับมา")
        cash=pd.to_numeric(f.Dividends,errors="coerce")
        if cash.notna().sum()==0:
            raise ValueError("คอลัมน์ปันผลไม่มีค่าที่ตรวจสอบได้ จึงยังสรุปว่าไม่มีปันผลไม่ได้")
        cash=cash.loc[cash.notna() & cash.gt(0)]
        dates=pd.DatetimeIndex(cash.index)
        if dates.tz is not None:
            dates=dates.tz_localize(None)
        dividends=pd.DataFrame({"Ex_Date":dates.normalize(),"Dividend_Per_Share":cash.to_numpy()})
        dividends=dividends.groupby("Ex_Date",as_index=False).Dividend_Per_Share.sum().sort_values("Ex_Date")
        return {"data":dividends,"fetched_at":datetime.now(timezone.utc).isoformat(),"error":None,
                "coverage_start":str(f.index[0].date()),"coverage_end":str(f.index[-1].date())}
    except Exception as exc:
        return {"data":None,"fetched_at":"","error":str(exc),"coverage_start":"","coverage_end":""}


def dividend_summary(result, price=None, now=None):
    if result.get("error") or result.get("data") is None:
        return {"total":None,"count":None,"yield":None,"last_date":None,"last_amount":None}
    today=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if today.tzinfo is not None:
        today=today.tz_convert("UTC").tz_localize(None)
    today=today.normalize()
    data=result["data"].loc[result["data"].Ex_Date.le(today)]
    ttm=data.loc[data.Ex_Date.gt(today-pd.DateOffset(years=1))]
    last=data.iloc[-1] if not data.empty else None
    value=float(ttm.Dividend_Per_Share.sum())
    return {"total":value,"count":len(ttm),"yield":value/price*100 if price and price>0 else None,
            "last_date":None if last is None else last.Ex_Date.strftime("%d/%m/%Y"),
            "last_amount":None if last is None else float(last.Dividend_Per_Share)}


def render_dividends(ticker, result, currency, price):
    st.subheader(f"ประวัติปันผล — {ticker}")
    if result.get("error"):
        st.warning(f"ยังโหลดประวัติปันผลไม่ได้: {result['error']}")
        return
    st.caption(f"ดึงสำเร็จล่าสุด {thai_time(result.get('fetched_at'))} · ข้อมูลครอบคลุม {result['coverage_start']} – {result['coverage_end']}")
    if result.get("coverage_start") and pd.Timestamp(result["coverage_start"])>pd.Timestamp.now(tz="UTC").tz_localize(None)-pd.DateOffset(years=1):
        st.info("ประวัติที่ผู้ให้ข้อมูลส่งกลับมาสั้นกว่า 12 เดือน ยอดและ Yield แสดงเฉพาะรายการที่มี ไม่ได้คูณประมาณให้เป็นรายปี")
    stats=dividend_summary(result,price)
    a,b,c,d=st.columns(4)
    a.metric(f"ปันผล 12 เดือน / หน่วย ({currency})",show_number(stats["total"],digits=4))
    b.metric("จำนวนครั้งใน 12 เดือน",str(stats["count"]))
    c.metric("Yield ย้อนหลัง 12 เดือน",show_number(stats["yield"],"%"))
    d.metric("Ex-dividend ล่าสุด",stats["last_date"] or "ไม่พบรายการ")
    years=st.radio("ช่วงประวัติปันผล",["1 ปี","3 ปี","5 ปี","10 ปี","ทั้งหมด"],index=2,horizontal=True,key="dividend_years")
    data=result["data"].copy()
    today=pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    data=data.loc[data.Ex_Date.le(today)]
    if years!="ทั้งหมด":
        data=data.loc[data.Ex_Date.gt(today-pd.DateOffset(years=int(years.split()[0])))]
    if data.empty:
        st.info("ไม่พบรายการปันผลในช่วงที่เลือกจากข้อมูลที่โหลดสำเร็จ")
    else:
        year=data.Ex_Date.dt.year
        yearly=data.assign(Year=year).groupby("Year").agg(Total=("Dividend_Per_Share","sum"),Payments=("Dividend_Per_Share","size")).reset_index()
        yearly["ช่วงข้อมูล"]=yearly.Year.map(lambda y:"สะสมปีนี้ (YTD)" if y==today.year else "ข้อมูลที่มีในช่วงเลือก")
        fig=go.Figure(go.Bar(x=yearly.Year.astype(str),y=yearly.Total,marker_color="#26a69a",hovertemplate="%{x}: %{y:.4f}<extra></extra>"))
        fig.update_layout(height=280,margin=dict(l=15,r=15,t=15,b=15),template="plotly_dark",yaxis_title=f"ปันผลต่อหน่วย ({currency})",xaxis_title="ปี (ปีปัจจุบันเป็น YTD)")
        st.plotly_chart(fig,**width_options(st.plotly_chart),key="dividend_chart")
        a,b=st.columns([1.4,1])
        displayed=data.sort_values("Ex_Date",ascending=False).rename(columns={"Ex_Date":"วันขึ้น XD / Ex-dividend","Dividend_Per_Share":f"ปันผลต่อหน่วย ({currency})"})
        a.dataframe(displayed,hide_index=True,**width_options(st.dataframe),height=300)
        b.dataframe(yearly.rename(columns={"Year":"ปี","Total":"รวมต่อหน่วย","Payments":"จำนวนครั้ง"}),hide_index=True,**width_options(st.dataframe),height=300)
        st.download_button("ดาวน์โหลดประวัติปันผล",data.to_csv(index=False).encode("utf-8-sig"),file_name=f"{ticker}_dividends.csv",mime="text/csv",key="download_dividends")
    st.caption("วันที่ในตารางเป็นวัน Ex-dividend ตามตลาด ไม่ใช่วันเงินเข้าบัญชี จำนวนเงินใช้ตามที่ผู้ให้ข้อมูลรายงาน อาจปรับตามการแตกหุ้น; การจ่ายของ ETF อาจมีองค์ประกอบอื่นนอกจากเงินปันผล และข้อมูลนี้ไม่ได้แยกภาษี/คืนทุน")


def decision_context(history, info, benchmark=None, now=None):
    ctx={"history":None,"metrics":{},"quote":number(info.get("regularMarketPrice")),"quote_time":number(info.get("regularMarketTime"))}
    if history is None or history.empty:
        return ctx
    f=completed_daily_history(history,now)
    if f.empty:
        return ctx
    ctx["history"],ctx["metrics"]=f,daily_snapshot(f)
    ctx["return_3m"]=snapshot_return(f,3)
    ctx["relative_3m"]=None
    if benchmark is not None and not benchmark.empty:
        try:
            b=completed_daily_history(benchmark,now)
            aligned=align_comparison({"asset":f,"benchmark":b},"3 เดือน")
            # Both histories must cover the intended period, not just a short overlap.
            if snapshot_return(f,3) is not None and snapshot_return(b,3) is not None:
                ctx["relative_3m"]=float(aligned.asset.iloc[-1]-aligned.benchmark.iloc[-1])
        except (ValueError,IndexError):
            pass
    return ctx


def criteria_score(ctx, info, is_etf):
    m=ctx["metrics"]
    c,e20,e50,sma=(number(m.get(k)) for k in ("Close","EMA20","EMA50","SMA200"))
    rsi,macd,signal,volume,atr=(number(m.get(k)) for k in ("RSI_14","MACD","MACD_Signal","Vol_Ratio","ATR"))
    rows=[]
    def add(group,name,current,ranges,earned,maximum,source="แท่งรายวันก่อนวันปัจจุบัน"):
        rows.append({"หมวด":group,"เกณฑ์":name,"ค่าปัจจุบัน":current,"ช่วง / คะแนน":ranges,
                     "ได้":earned,"เต็ม":maximum,"ผล":"ไม่มีข้อมูล" if earned is None else "เต็ม" if earned==maximum else "บางส่วน" if earned>0 else "ไม่ผ่าน","ข้อมูลอ้างอิง":source})
    trend=None if any(x is None for x in (c,e20,e50)) else c>e20>e50
    add("แนวโน้ม","ราคา > EMA20 > EMA50",f"{show_number(c)} > {show_number(e20)} > {show_number(e50)}","เรียงตามเงื่อนไข = 20; อื่น ๆ = 0",None if trend is None else 20 if trend else 0,20)
    add("แนวโน้ม","ราคา > SMA200",f"ราคา {show_number(c)} / SMA200 {show_number(sma)}","ราคาเหนือ SMA200 = 10; อื่น ๆ = 0",None if c is None or sma is None else 10 if c>sma else 0,10)
    add("โมเมนตัม","RSI 14",show_number(rsi),"45–65 = 10; 35–<45 หรือ >65–70 = 5; อื่น ๆ = 0",None if rsi is None else 10 if 45<=rsi<=65 else 5 if 35<=rsi<45 or 65<rsi<=70 else 0,10)
    add("โมเมนตัม","MACD > Signal",f"{show_number(macd,digits=4)} / {show_number(signal,digits=4)}","เหนือ Signal = 10; ต่ำกว่าหรือเท่ากัน = 0",None if macd is None or signal is None else 10 if macd>signal else 0,10)
    add("วอลุ่ม","Volume Ratio",show_number(volume,"x"),">=1.20 = 15; 1.00–<1.20 = 8; 0.80–<1.00 = 4; <0.80 = 0",None if volume is None else 15 if volume>=1.2 else 8 if volume>=1 else 4 if volume>=.8 else 0,15)
    atr_pct=atr/c*100 if atr is not None and c and c>0 else None
    add("ความผันผวน","ATR / ราคา",show_number(atr_pct,"%"),"<=3% = 15; >3–6% = 8; >6–10% = 3; >10% = 0",None if atr_pct is None else 15 if atr_pct<=3 else 8 if atr_pct<=6 else 3 if atr_pct<=10 else 0,15)
    if is_etf:
        relative,ret=ctx.get("relative_3m"),ctx.get("return_3m")
        add("ETF","ผลตอบแทน 3 เดือนเทียบ SPY",show_number(relative," จุดเปอร์เซ็นต์"),">=0 = 10; <0 = 0",None if relative is None else 10 if relative>=0 else 0,10,"ราคาปรับแล้ว วันที่ร่วมกัน")
        add("ETF","ผลตอบแทน 3 เดือน",show_number(ret,"%"),">=0% = 10; <0% = 0",None if ret is None else 10 if ret>=0 else 0,10,"ราคาปรับแล้ว")
    else:
        pe=number(info.get("forwardPE"))
        target=number(info.get("targetMeanPrice"))
        quote=ctx.get("quote") or c
        upside=(target/quote-1)*100 if target is not None and quote and quote>0 else None
        add("พื้นฐาน","Forward P/E",show_number(pe,"x"),">0–25 = 10; >25–40 = 5; <=0 หรือ >40 = 0",None if pe is None else 10 if 0<pe<=25 else 5 if 25<pe<=40 else 0,10,"Yahoo Finance; ไม่ใช่มูลค่ายุติธรรมรายอุตสาหกรรม")
        add("พื้นฐาน","Upside ราคาเป้าหมาย",show_number(upside,"%"),">=10% = 10; 5–<10% = 5; <5% = 0",None if upside is None else 10 if upside>=10 else 5 if upside>=5 else 0,10,"ราคาเป้าหมายเฉลี่ยนักวิเคราะห์")
    score=sum(r["ได้"] for r in rows if r["ได้"] is not None)
    coverage=sum(r["เต็ม"] for r in rows if r["ได้"] is not None)
    return {"rows":pd.DataFrame(rows),"score":score,"coverage":coverage,"upper":score+100-coverage,"trend":trend}


def build_entry_plan(ctx, info, scored, is_etf, min_rr=2.0, now=None):
    """Transparent long pullback setup. This is a heuristic, not a forecast."""
    result={"zone_low":None,"zone_high":None,"entry":None,"stop":None,"target":None,"rr":None,"blockers":[],"status":"ข้อมูลไม่พอ", "ready":False}
    f,m=ctx.get("history"),ctx.get("metrics",{})
    ema,atr=number(m.get("EMA20")),number(m.get("ATR"))
    if f is None or len(f)<60 or ema is None or atr is None or atr<=0:
        result["blockers"].append("ต้องมีประวัติอย่างน้อย 60 แท่ง พร้อม EMA20 และ ATR14")
        return result
    low,high=ema-.25*atr,ema+.25*atr
    support=float(f.Low.tail(20).min())
    resistance=float(f.High.tail(60).max())
    stop=min(support-.25*atr,low-1.5*atr)
    analyst=number(info.get("targetMeanPrice")) if not is_etf else None
    target=min(resistance,analyst) if analyst is not None and analyst>0 else resistance
    result.update(zone_low=low,zone_high=high,entry=high,stop=stop,target=target,support=support,resistance=resistance)
    blockers=result["blockers"]
    if low<=0 or stop<=0 or stop>=high or target<=high:
        blockers.append("ระดับราคา/Stop/เป้าหมายไม่รองรับแผนซื้อที่สมเหตุผล")
    else:
        result["rr"]=(target-high)/(high-stop)
    if result["rr"] is None or result["rr"]<min_rr:
        blockers.append(f"Reward/Risk ต้อง >= {min_rr:.1f} (ปัจจุบัน {show_number(result['rr'])})")
    if scored["coverage"]<100:
        blockers.append(f"ข้อมูลให้คะแนนยังไม่ครบ ({scored['coverage']}/100 คะแนนที่ประเมินได้)")
    if scored["score"]<80:
        blockers.append(f"คะแนนต้อง >=80/100 (ปัจจุบัน {scored['score']}/100)")
    if scored["trend"] is not True:
        blockers.append("แนวโน้มต้องเป็น ราคา > EMA20 > EMA50")
    nowstamp=pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if nowstamp.tzinfo is None:
        nowstamp=nowstamp.tz_localize("UTC")
    last_date=f.index[-1].date()
    if (nowstamp.date()-last_date).days>7:
        blockers.append("แท่งราคาเก่าเกิน 7 วัน ต้องอัปเดตข้อมูลก่อน")
    quote,quote_time=ctx.get("quote"),ctx.get("quote_time")
    age=nowstamp.timestamp()-quote_time if quote_time is not None else None
    if age is None or not -60<=age<=900:
        blockers.append("ต้องยืนยันราคา quote ที่อัปเดตไม่เกิน 15 นาที")
    name=(str(info.get("shortName",""))+" "+str(info.get("longName",""))).lower()
    if is_etf and re.search(r"\b(2x|3x|inverse|leveraged|ultrapro|ultrashort)\b",name):
        blockers.append("ETF ทด/ผกผันอยู่นอกขอบเขตโมเดลนี้")
    if quote is None:
        blockers.append("ไม่มีราคา quote สำหรับยืนยันจุดเข้า")
    elif quote<low:
        blockers.append(f"ราคาต่ำกว่าโซน {low:.4f}; รอการยืนยันแนวรับใหม่")
    elif quote>high:
        blockers.append(f"รอราคาย่อลงสู่โซน {low:.4f}–{high:.4f}; ไม่ไล่ราคา")
    if not blockers:
        result.update(status="เข้าได้ตามเงื่อนไขของโมเดล",ready=True)
    elif scored["coverage"]<100:
        result["status"]="รอข้อมูลให้ครบ"
    elif scored["score"]<60 or scored["trend"] is False:
        result["status"]="ยังไม่ควรเข้าตามโมเดลนี้"
    else:
        result["status"]="รอจังหวะ / รอยืนยันเงื่อนไข"
    return result


def render_decision(ticker, ctx, info, scored, plan, is_etf, div_result, currency):
    st.subheader("เกณฑ์เข้าซื้อ — Trading Verdict (เต็ม 100)")
    a,b,c=st.columns(3)
    a.metric("คะแนนที่ได้",f"{scored['score']} / 100")
    b.metric("ความครบของข้อมูล",f"{scored['coverage']} / 100")
    c.metric("คะแนนต่ำสุด–สูงสุดที่เป็นไปได้",f"{scored['score']}–{scored['upper']}")
    st.dataframe(pd.DataFrame([
        {"ช่วงคะแนน":"80–100","ความหมาย":"ผ่านระดับคะแนนสำหรับพิจารณาเข้า ต้องผ่านเงื่อนไขราคา/ความเสี่ยงด้วย"},
        {"ช่วงคะแนน":"60–79","ความหมาย":"เฝ้าดู / รอจังหวะ ยังไม่ผ่านเกณฑ์เข้า"},
        {"ช่วงคะแนน":"40–59","ความหมาย":"ยังไม่ควรเข้าตามโมเดลนี้"},
        {"ช่วงคะแนน":"0–39","ความหมาย":"งดเข้าตามโมเดลนี้"}]),hide_index=True,**width_options(st.dataframe))
    st.caption(("โปรไฟล์ ETF: แทน P/E และราคาเป้าหมายด้วยผลตอบแทน 3 เดือนและความแข็งแกร่งเทียบ SPY" if is_etf else "โปรไฟล์หุ้น: รวมเงื่อนไขแนวโน้ม โมเมนตัม วอลุ่ม ความผันผวน P/E และราคาเป้าหมาย")+" · ข้อมูลที่ขาดไม่ถูกนับเป็นผ่าน และไม่มีการหารปรับให้คะแนนสูงขึ้น")
    st.dataframe(scored["rows"],hide_index=True,**width_options(st.dataframe),height=370,
                 column_config={"ช่วง / คะแนน":st.column_config.TextColumn(width="large")})
    bar=ctx.get("metrics",{}).get("Bar_Date","ไม่มีข้อมูล")
    st.caption(f"เกณฑ์เทคนิคใช้แท่งรายวันก่อนวันปัจจุบันตามตลาด ล่าสุด {bar} เพื่อไม่เทียบวอลุ่มระหว่างวันกับวอลุ่มเต็มวัน")
    st.subheader(f"แผนราคาเข้า — {ticker}")
    (st.success if plan["ready"] else st.warning)(plan["status"])
    m=ctx.get("metrics",{})
    trend_text="ยังไม่มีข้อมูลพอ" if scored["trend"] is None else "เรียงตัวเป็นขาขึ้นตามเกณฑ์" if scored["trend"] else "ยังไม่ผ่านการเรียงตัวขาขึ้น"
    st.write(f"**สรุปข้อมูลประกอบ:** ราคา quote {show_number(ctx.get('quote'),digits=4)} {currency}; แนวโน้ม {trend_text}; RSI {show_number(m.get('RSI_14'))}; MACD / Signal {show_number(m.get('MACD'),digits=4)} / {show_number(m.get('MACD_Signal'),digits=4)}; Volume Ratio {show_number(m.get('Vol_Ratio'),'x')}; ATR14 {show_number(m.get('ATR'),digits=4)} {currency}")
    if is_etf:
        st.write(f"**ผลตอบแทน ETF:** 3 เดือน {show_number(ctx.get('return_3m'),'%')} และต่างจาก SPY {show_number(ctx.get('relative_3m'),' จุดเปอร์เซ็นต์')} โดยใช้วันที่ร่วมกัน; เกณฑ์นี้วัดกลยุทธ์ตามแนวโน้ม ไม่ได้ตัดสินว่า ETF ตราสารหนี้หรือทองคำเหมาะกับพอร์ตหรือไม่")
    else:
        st.write(f"**พื้นฐาน:** Forward P/E {show_number(info.get('forwardPE'),'x')}; เป้าหมายเฉลี่ยนักวิเคราะห์ {show_number(info.get('targetMeanPrice'))} {currency}; Beta {show_number(info.get('beta'))} ใช้ประกอบความเสี่ยง โดยราคาเป้าหมายเป็นประมาณการ ไม่ใช่ราคาที่จะเกิดแน่นอน")
    if plan["entry"] is not None:
        a,b,c,d=st.columns(4)
        a.metric(f"โซนรอซื้อ ({currency})",f"{plan['zone_low']:,.4f}–{plan['zone_high']:,.4f}")
        b.metric("ราคาเข้าอ้างอิง",show_number(plan["entry"],digits=4))
        c.metric("Stop Loss",show_number(plan["stop"],digits=4))
        d.metric("เป้าทำกำไร / R:R",f"{show_number(plan['target'],digits=4)} / {show_number(plan['rr'])}")
        st.write("**ที่มาของราคา:** โซนซื้อ = EMA20 ± 0.25 ATR; ราคาเข้าอ้างอิง = ขอบบนของโซน; Stop = ค่าต่ำกว่าระหว่างแนวรับต่ำสุด 20 แท่งลบ 0.25 ATR กับขอบล่างโซนลบ 1.5 ATR")
        st.write("**เป้าหมาย:** แนวต้านสูงสุด 60 แท่ง"+(" โดยจำกัดไม่เกินราคาเป้าหมายนักวิเคราะห์เมื่อมีข้อมูล" if not is_etf else "")+"; R:R = (เป้าหมาย − ราคาเข้า) ÷ (ราคาเข้า − Stop)")
        if not plan["ready"]:
            st.caption("ตัวเลขนี้เป็นแผนรอเงื่อนไข ไม่ใช่สัญญาณให้ส่งคำสั่งซื้อทันที")
        if plan["stop"]>0 and plan["target"]>plan["entry"]:
            if st.button("นำราคาในแผนไปคำนวณจำนวนหุ้น",key="apply_entry_plan"):
                st.session_state[f"entry_{ticker}"]=float(plan["entry"])
                st.session_state[f"stop_{ticker}"]=float(plan["stop"])
    if plan["blockers"]:
        st.markdown("**เงื่อนไขที่ยังต้องรอ:**\n\n"+"\n".join("- "+reason for reason in plan["blockers"]))
    div=dividend_summary(div_result,ctx.get("quote"))
    st.write(f"**ปันผลประกอบการพิจารณา:** 12 เดือนย้อนหลัง {show_number(div['total'],digits=4)} {currency}/หน่วย; Yield {show_number(div['yield'],'%')}; ล่าสุด {div['last_date'] or 'ไม่มีข้อมูล'}")
    st.caption("ปันผลใช้ประกอบกระแสเงินสด ไม่เพิ่มคะแนนซื้ออัตโนมัติ และไม่ใช่การรับประกันการจ่ายครั้งต่อไป")
    st.caption("โมเดลนี้เป็นกติกาสำหรับซื้อเมื่อย่อในแนวโน้มขาขึ้น ยังไม่ผ่านการทดสอบย้อนหลัง ค่าคะแนน/ตัวคูณ ATR เป็นสมมติฐานของระบบ ไม่ใช่ความน่าจะเป็นกำไรหรือราคาที่รับประกัน")
    with st.expander("แหล่งอ้างอิงและขอบเขตของเกณฑ์"):
        st.markdown("[ATR และความผันผวน — Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr) · [ข้อมูลราคาและปันผล — yfinance](https://ranaroussi.github.io/yfinance/reference/index.html) · [ETF ทดและผกผัน — Investor.gov](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/sec)")
        st.write("แหล่งอ้างอิงอธิบายข้อมูลและอินดิเคเตอร์ ไม่ได้รับรองคะแนน 100 จุดหรือสูตรราคาเข้าของระบบนี้ กติกาเหมาะสำหรับเทียบสินทรัพย์ภายในกลยุทธ์เดียวกัน ไม่แทนการวิเคราะห์ข่าว ผลประกอบการ และความเหมาะสมกับพอร์ต")


def width_options(element):
    """Use the modern width API when present, retain older Streamlit support."""
    parameter = inspect.signature(element).parameters.get("width")
    return {"width": "stretch"} if parameter is not None and parameter.default == "stretch" else {"use_container_width": True}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def show_number(value, suffix="", digits=2):
    n = number(value)
    return f"{n:,.{digits}f}{suffix}" if n is not None else "ไม่มีข้อมูล"


def compact_number(value):
    n = number(value)
    if n is None:
        return "ไม่มีข้อมูล"
    for scale, label in [(1e12, "T"), (1e9, "B"), (1e6, "M")]:
        if abs(n) >= scale:
            return f"{n / scale:,.2f}{label}"
    return f"{n:,.0f}"


def parse_watchlist(data: bytes) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(data), encoding="utf-8-sig")
    frame.columns = frame.columns.astype(str).str.strip()
    if "Ticker" not in frame and "Symbol" in frame:
        frame = frame.rename(columns={"Symbol": "Ticker"})
    if "Ticker" not in frame:
        raise ValueError("ไฟล์ต้องมีคอลัมน์ Ticker หรือ Symbol")
    frame = frame.loc[frame.Ticker.notna()].copy()
    frame["Ticker"] = frame.Ticker.astype(str).str.strip().str.upper()
    frame = frame.loc[frame.Ticker.ne("")].drop_duplicates("Ticker", keep="last")
    if "Asset_Type" not in frame:
        frame["Asset_Type"] = "ไม่ระบุ"
    frame["Asset_Type"] = frame.Asset_Type.fillna("ไม่ระบุ").astype(str)
    if "Status" not in frame:
        frame["Status"] = "ไม่มีข้อมูล"
    frame["Status"] = frame.Status.fillna("ไม่มีข้อมูล").astype(str).str.strip().str.upper()
    for col in NUMERIC_COLUMNS:
        if col not in frame:
            frame[col] = np.nan
        elif not pd.api.types.is_numeric_dtype(frame[col]):
            frame[col] = pd.to_numeric(
                frame[col].astype(str).str.replace(",", "", regex=False)
                .str.replace("$", "", regex=False).str.replace("%", "", regex=False), errors="coerce")
        frame[col] = frame[col].replace([np.inf, -np.inf], np.nan)
    return frame.reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def read_watchlist(path: str, modified_ns: int, file_size: int) -> pd.DataFrame:
    # modified_ns and file_size invalidate the cache after the scanner writes.
    return parse_watchlist(Path(path).read_bytes())


def filter_watchlist(frame, asset_type, pass_only, query, low, high, rsi_range,
                     min_return, keep_missing):
    result = frame.copy()
    if asset_type != "ทั้งหมด":
        result = result.loc[result.Asset_Type.eq(asset_type)]
    if pass_only:
        result = result.loc[result.Status.eq("PASS")]
    if query:
        term=query.strip().upper()
        found=result.Ticker.str.contains(term,regex=False,na=False)
        if "ETF_Name" in result:
            found=found | result.ETF_Name.str.upper().str.contains(term,regex=False,na=False)
        result = result.loc[found]
    for col, mask in [("Close", result.Close.between(low, high)),
                      ("RSI_14", result.RSI_14.between(*rsi_range)),
                      ("Historical_Return", result.Historical_Return.ge(min_return))]:
        if keep_missing:
            mask = mask | result[col].isna()
        result = result.loc[mask.reindex(result.index, fill_value=False)]
    return result


@st.cache_data(ttl=300, show_spinner=False)
def load_fundamentals(ticker):
    result = yf.Ticker(ticker).get_info()
    if not isinstance(result, dict) or not result:
        raise ValueError("แหล่งข้อมูลไม่ได้ส่งข้อมูลพื้นฐานกลับมา")
    return {**result, "_Fetched_At_UTC":datetime.now(timezone.utc).isoformat()}


def daily_snapshot(history):
    if history is None or history.empty:
        return {}
    payload = build_payload(history, "", "1 เดือน", "1d")
    row = payload["records"][-1]
    f = normalize_history(history)
    previous = f.Close.shift(1)
    true_range = pd.concat([f.High-f.Low, (f.High-previous).abs(), (f.Low-previous).abs()], axis=1).max(axis=1)
    atr = None
    if len(true_range) >= 14:
        atr = float(true_range.iloc[:14].mean())
        for value in true_range.iloc[14:]:
            atr = (atr * 13 + float(value)) / 14
    average_vol = number(f.Volume.iloc[-21:-1].mean()) if len(f) >= 21 else None
    volume = number(f.Volume.iloc[-1])
    ratio = volume / average_vol if average_vol and volume is not None else None
    return {"Close": row["close"], "EMA20": row["ema20"], "EMA50": row["ema50"],
            "SMA200": row["sma200"], "RSI_14": row["rsi"], "MACD": row["macd"],
            "MACD_Signal": row["signal"], "ATR": atr, "Vol_Ratio": ratio,
            "Bar_Date": f.index[-1].strftime("%Y-%m-%d")}


def build_analysis(snapshot, selected_row, info):
    metrics, sources = {}, {}
    for col in NUMERIC_COLUMNS:
        fresh = number(snapshot.get(col))
        old = number(selected_row.get(col))
        metrics[col] = fresh if fresh is not None else old
        sources[col] = "กราฟรายวัน" if fresh is not None else str(selected_row.get("Data_Source") or "CSV") if old is not None else "—"
    # Use a quote from the fundamentals response for target-price comparison.
    quote = number(info.get("regularMarketPrice"))
    if quote is None:
        quote = number(info.get("currentPrice"))
    price = quote if quote is not None else metrics["Close"]
    metrics["Quote"] = price
    pe = number(info.get("forwardPE"))
    trailing_pe = number(info.get("trailingPE"))
    target = number(info.get("targetMeanPrice"))
    upside = (target / price - 1) * 100 if target is not None and price and price > 0 else None
    # Explicitly use the trailing annual rate/yield; do not guess dividendYield units.
    dividend_rate = number(info.get("trailingAnnualDividendRate"))
    raw_yield = number(info.get("trailingAnnualDividendYield"))
    dividend_pct = dividend_rate / price * 100 if dividend_rate is not None and price and price > 0 else (
        raw_yield * 100 if raw_yield is not None else None)
    beta = number(info.get("beta"))
    current, ema20, ema50 = metrics["Close"], metrics["EMA20"], metrics["EMA50"]
    trend = None if any(x is None for x in (current, ema20, ema50)) else current > ema20 > ema50
    rsi, macd, signal, volume_ratio, atr = (metrics[k] for k in ["RSI_14", "MACD", "MACD_Signal", "Vol_Ratio", "ATR"])
    status = str(selected_row.get("Status", "ไม่มีข้อมูล"))
    rows = []

    def add(group, metric, value, meaning, source):
        rows.append({"หมวด": group, "ปัจจัย": metric, "ค่าล่าสุด": value,
                     "การแปลผล": meaning, "แหล่งข้อมูล": source})

    pe_text = "ไม่มีประมาณการกำไร" if pe is None else "กำไรประมาณการไม่เป็นบวก" if pe <= 0 else "อยู่ในช่วง >0–25 เท่า (เกณฑ์เต็ม 10)" if pe <= 25 else "อยู่ในช่วง >25–40 เท่า (เกณฑ์ 5)" if pe <= 40 else "มากกว่า 40 เท่า (เกณฑ์ 0)"
    add("พื้นฐาน", "Forward P/E", show_number(pe, "x"), pe_text+"; ควรเทียบธุรกิจกลุ่มเดียวกัน", "Yahoo Finance")
    add("พื้นฐาน", "Trailing P/E", show_number(trailing_pe, "x"), "ราคาเทียบกำไรย้อนหลัง", "Yahoo Finance")
    add("พื้นฐาน", "Target Price", show_number(target), "ไม่มีราคาเป้าหมาย" if upside is None else f"ต่างจากราคาอ้างอิง {upside:+.2f}%", "นักวิเคราะห์ผ่าน Yahoo")
    add("พื้นฐาน", "Dividend Yield", show_number(dividend_pct, "%"), "อัตราปันผลย้อนหลังเทียบราคาอ้างอิง" if dividend_pct is not None else "ไม่มีข้อมูลปันผล", "Yahoo Finance")
    add("เทคนิค", "Trend / Screener", status, "สถานะของแหล่ง Watchlist; คะแนน 100 คำนวณจากข้อมูลใหม่ด้านล่าง", str(selected_row.get("Data_Source") or "CSV") if selected_row else "—")
    add("เทคนิค", "EMA 20 / EMA 50", f"{show_number(ema20)} / {show_number(ema50)}", "ข้อมูลไม่พอ" if trend is None else "ราคา > EMA20 > EMA50" if trend else "ยังไม่เรียงตัวตามเงื่อนไข ราคา > EMA20 > EMA50", sources["EMA20"])
    add("เทคนิค", "SMA 200", show_number(metrics["SMA200"]), "ค่าเฉลี่ย 200 แท่งรายวัน", sources["SMA200"])
    add("เทคนิค", "MACD / Signal", f"{show_number(macd, digits=4)} / {show_number(signal, digits=4)}", "ข้อมูลไม่พอ" if macd is None or signal is None else "MACD อยู่เหนือ Signal" if macd > signal else "MACD อยู่ต่ำกว่าหรือเท่ากับ Signal", sources["MACD"])
    add("เทคนิค", "RSI (14)", show_number(rsi), "ข้อมูลไม่พอ" if rsi is None else "สูงกว่า 70" if rsi > 70 else "ต่ำกว่า 30" if rsi < 30 else "อยู่ในช่วง 30–70", sources["RSI_14"])
    add("สภาพคล่อง", "Volume Ratio", show_number(volume_ratio, "x"), "ปริมาณล่าสุดเทียบค่าเฉลี่ย 20 แท่งก่อนหน้า" if sources["Vol_Ratio"] == "กราฟรายวัน" else "อัตราวอลุ่มจากไฟล์สแกน", sources["Vol_Ratio"])
    add("ความเสี่ยง", "Beta", show_number(beta), "ไม่มีข้อมูล" if beta is None else "Beta มากกว่า 1" if beta > 1 else "Beta ต่ำกว่าหรือเท่ากับ 1", "Yahoo Finance")
    add("ความเสี่ยง", "ATR (14)", show_number(atr), "ขนาด True Range เฉลี่ยรายวัน ในหน่วยราคา", sources["ATR"])
    add("ความเสี่ยง", "Suggested Stop", show_number(selected_row.get("Suggested_Stop")), "จุด Stop จากไฟล์สแกนเดิม", "CSV" if number(selected_row.get("Suggested_Stop")) is not None else "—")
    checks = [
        ("Screener = PASS", None if status not in ("PASS", "FAIL") else status == "PASS", 2),
        ("Forward P/E มากกว่า 0 และต่ำกว่า 25", None if pe is None else 0 < pe < 25, 1),
        ("Upside มากกว่า 5%", None if upside is None else upside > 5, 1),
        ("MACD > Signal", None if macd is None or signal is None else macd > signal, 1),
        ("RSI อยู่ระหว่าง 30–65", None if rsi is None else 30 <= rsi <= 65, 1),
        ("Volume Ratio มากกว่า 1.1", None if volume_ratio is None else volume_ratio > 1.1, 1)]
    return pd.DataFrame(rows), metrics, {"pe": pe, "target": target, "upside": upside,
                                        "dividend_pct": dividend_pct, "beta": beta, "checks": checks}


def position_size(capital, risk_pct, entry, stop):
    values = [number(v) for v in (capital, risk_pct, entry, stop)]
    if any(v is None for v in values):
        raise ValueError("กรุณากรอกตัวเลขให้ครบ")
    if capital <= 0 or not 0 < risk_pct <= 100 or entry <= 0 or stop < 0 or stop >= entry:
        raise ValueError("ราคาเข้าต้องมากกว่า Stop Loss และเงินลงทุนต้องมากกว่า 0")
    budget = capital * risk_pct / 100
    per_share = entry - stop
    by_risk = math.floor(budget / per_share)
    by_cash = math.floor(capital / entry)
    shares = min(by_risk, by_cash)
    return {"shares": shares, "capital_used": shares * entry, "planned_loss": shares * per_share,
            "risk_budget": budget, "cash_limited": by_cash < by_risk}


def render_position_sizer(ticker, selected_row, metrics, currency):
    st.subheader("วางแผนการซื้อ — Position Sizer")
    st.caption(f"กรอกพอร์ตและราคาเป็นสกุลเดียวกัน ({currency})")
    current = number(metrics.get("Quote"))
    csv_stop = number(selected_row.get("Suggested_Stop"))
    if current is not None and current > 0:
        entry_default = current
    else:
        entry_default = 0.0
    stop_default = max(0.0, csv_stop) if csv_stop is not None else 0.0
    if csv_stop is not None:
        st.caption(f"Stop จาก CSV: {csv_stop:,.4f} — แก้ไขได้ตามแผนของคุณ")
    else:
        st.caption("ไม่มี Suggested_Stop ใน CSV กรุณากรอกจุด Stop ของคุณ")
    a, b = st.columns(2)
    capital = a.number_input(f"เงินลงทุน ({currency})", min_value=0.0, value=10000.0, step=1000.0, key="port_size")
    risk = b.slider("ความเสี่ยงต่อไม้ (% ของพอร์ต)", .5, 5.0, 1.0, .5, key="risk_pct")
    a, b = st.columns(2)
    if f"entry_{ticker}" not in st.session_state:
        st.session_state[f"entry_{ticker}"]=float(entry_default)
    if f"stop_{ticker}" not in st.session_state:
        st.session_state[f"stop_{ticker}"]=float(stop_default)
    entry = a.number_input("ราคาเข้าซื้อ", min_value=0.0, step=.01, format="%.4f", key=f"entry_{ticker}")
    stop = b.number_input("Stop Loss", min_value=0.0, step=.01, format="%.4f", key=f"stop_{ticker}")
    if stop == 0:
        st.info("กรอก Stop Loss มากกว่า 0 เพื่อคำนวณจำนวนหุ้น")
        return
    try:
        plan = position_size(capital, risk, entry, stop)
    except ValueError as exc:
        st.warning(str(exc))
        return
    a, b, c = st.columns(3)
    a.metric("จำนวนหุ้น", f"{plan['shares']:,}")
    b.metric(f"เงินที่ใช้ ({currency})", f"{plan['capital_used']:,.2f}")
    c.metric(f"ขาดทุนตามแผน ({currency})", f"{plan['planned_loss']:,.2f}")
    if plan["cash_limited"]:
        st.caption("จำนวนหุ้นถูกจำกัดด้วยเงินลงทุนที่กรอก")
    st.caption("คำนวณที่ราคา Stop ที่ระบุ ยังไม่รวมค่าธรรมเนียมและส่วนต่างราคาซื้อขายจริง")


def align_comparison(histories: dict, period: str):
    series = []
    for ticker, frame in histories.items():
        f = normalize_history(frame)
        s = f.Close.copy()
        s.index = s.index.tz_localize(None).normalize() if s.index.tz is not None else s.index.normalize()
        s = s.loc[~s.index.duplicated(keep="last")]
        series.append(s.rename(ticker))
    common = pd.concat(series, axis=1, join="inner").dropna()
    if common.empty:
        raise ValueError("หุ้นที่เลือกไม่มีวันที่มีข้อมูลตรงกัน")
    n, unit = period.split()
    begin = common.index[-1] - (pd.DateOffset(months=int(n)) if unit == "เดือน" else pd.DateOffset(years=int(n)))
    common = common.loc[common.index >= begin]
    if len(common) < 2 or (common.iloc[0] <= 0).any():
        raise ValueError("ข้อมูลร่วมกันไม่พอสำหรับเปรียบเทียบ")
    return (common / common.iloc[0] - 1) * 100


def render_comparison(first, second, period, key):
    first, second = first.strip().upper(), second.strip().upper()
    if not all(re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}", t) for t in (first, second)):
        st.info("กรุณาระบุ Ticker ให้ครบสองตัว")
        return
    if first == second:
        st.info("เลือกหุ้นคนละตัวเพื่อเปรียบเทียบ")
        return
    try:
        histories = {t: load_chart_history(t, "1d")[0] for t in (first, second)}
        performance = align_comparison(histories, period)
    except Exception as exc:
        st.warning(f"ยังเปรียบเทียบไม่ได้: {exc}")
        return
    fig = go.Figure()
    for ticker, color in zip((first, second), ("#5b9cf6", "#f3b34c")):
        fig.add_trace(go.Scatter(x=performance.index, y=performance[ticker], mode="lines", name=ticker,
                                line=dict(color=color, width=2.5), hovertemplate="%{y:+.2f}%<extra>%{fullData.name}</extra>"))
    fig.add_hline(y=0, line_color="#526075", line_dash="dot")
    fig.update_layout(height=480, template="plotly_dark", paper_bgcolor="#10141d", plot_bgcolor="#10141d",
                      font=dict(size=14), margin=dict(l=15,r=15,t=35,b=15), hovermode="x unified", dragmode="pan",
                      yaxis=dict(title="ผลตอบแทน (%)", side="right", fixedrange=False),
                      xaxis=dict(title=None, rangeslider_visible=False), legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, **width_options(st.plotly_chart), key=key, config={"scrollZoom": True, "displaylogo": False})
    a,b,c = st.columns(3)
    end = performance.iloc[-1]
    a.metric(first, f"{end[first]:+.2f}%")
    b.metric(second, f"{end[second]:+.2f}%")
    c.metric("ส่วนต่างผลตอบแทน", f"{end[first]-end[second]:+.2f} จุดเปอร์เซ็นต์")
    st.caption(f"เริ่มทั้งคู่ที่ 0% บนวันที่มีข้อมูลร่วมกัน: {performance.index[0]:%d/%m/%Y} – {performance.index[-1]:%d/%m/%Y} · ใช้ราคาปรับแล้วในสกุลของแต่ละสินทรัพย์")


def render_filters(frame):
    st.subheader("ตัวกรองข้อมูล — Data Filters")
    a,b,c = st.columns([1,1,1.4])
    asset = a.selectbox("ประเภทสินทรัพย์", ["ทั้งหมด"]+sorted(frame.Asset_Type.unique().tolist()), key="asset_filter")
    status = b.radio("สถานะจาก Screener", ["ทั้งหมด", "PASS เท่านั้น"], horizontal=True, key="status_filter")
    query = c.text_input("ค้นหา Ticker / ชื่อ ETF", key="search_ticker", help="เช่น SCHD, Vanguard, Treasury หรือ Dividend")
    with st.expander("ตัวกรองขั้นสูง", expanded=False):
        a,b,c = st.columns(3)
        low = a.number_input("ราคาต่ำสุด", min_value=0.0, value=0.0, step=1.0, key="min_price")
        # Start with a bound that retains every finite price in the user's CSV.
        max_seen = number(frame.Close.max())
        high_default = max(5000.0, max_seen or 0.0)
        high = a.number_input("ราคาสูงสุด", min_value=0.0, value=high_default, step=10.0, key="max_price")
        rsi = b.slider("ช่วง RSI (14)", 0, 100, (0,100), key="rsi_filter")
        ret = c.number_input("ผลตอบแทน 1 ปีขั้นต่ำ (%)", value=-100.0, step=10.0, key="return_filter")
        keep = st.checkbox("แสดงแถวที่บางคอลัมน์ยังไม่มีข้อมูลด้วย", value=True, key="keep_missing")
    if high < low:
        st.warning("ราคาสูงสุดต้องไม่น้อยกว่าราคาต่ำสุด")
        return frame.iloc[0:0]
    return filter_watchlist(frame, asset, status == "PASS เท่านั้น", query, low, high, rsi, ret, keep)


def render_watchlist_table(frame):
    columns = ["Ticker", "ETF_Name", "Asset_Type", "Status", "Close", "Historical_Return", "Vol_Ratio", "RSI_14", "MACD", "Data_Source", "Data_Status", "Price_AsOf", "Data_Time"]
    table = frame[columns].copy()
    table["Data_Time"] = table.Data_Time.map(lambda value: thai_time(value) if pd.notna(value) and value else "ไม่ระบุ")
    def rsi_style(value):
        n = number(value)
        return "" if n is None else "color: #ef5350" if n > 70 else "color: #26a69a" if n < 30 else ""
    styled = table.style.format({"Close":"{:,.2f}", "Historical_Return":"{:+.2f}%", "Vol_Ratio":"{:.2f}x", "RSI_14":"{:.2f}", "MACD":"{:.4f}"}, na_rep="—")
    styled = styled.map(rsi_style, subset=["RSI_14"]) if hasattr(styled,"map") else styled.applymap(rsi_style, subset=["RSI_14"])
    st.dataframe(styled, height=500, **width_options(st.dataframe), hide_index=True, column_config={
        "Ticker":st.column_config.TextColumn("Ticker",help="สัญลักษณ์หุ้นหรือกองทุน"),
        "ETF_Name":st.column_config.TextColumn("ชื่อ ETF",help="ชื่อจากทะเบียน Nasdaq ณ วันที่ในส่วน ETF"),
        "Asset_Type":st.column_config.TextColumn("ประเภท"),
        "Status":st.column_config.TextColumn("Status",help="CSV ใช้ผลสแกนเดิม; ETF เพิ่มเติมใช้ Close > EMA20 > EMA50 ไม่ใช่คะแนนซื้อ 100 จุด"),
        "Close":st.column_config.NumberColumn("ราคา Watchlist",help="CSV ใช้ราคาที่บันทึก; ETF เพิ่มเติมใช้ราคาปรับแล้วของแท่งก่อนวันปัจจุบันตามตลาด"),
        "Historical_Return":st.column_config.NumberColumn("1Y Return (%)",help="CSV ใช้ค่าเดิม; ETF เพิ่มเติมคำนวณราคาปรับแล้วช่วง 12 เดือน"),
        "Vol_Ratio":st.column_config.NumberColumn("Vol Ratio",help="ETF เพิ่มเติม: วอลุ่มรายวัน / ค่าเฉลี่ย 20 แท่งก่อนหน้า; CSV ใช้ค่าเดิม"),
        "RSI_14":st.column_config.NumberColumn("RSI (14)"),
        "MACD":st.column_config.NumberColumn("MACD"),
        "Data_Source":st.column_config.TextColumn("แหล่งข้อมูล"),
        "Data_Status":st.column_config.TextColumn("สถานะข้อมูล"),
        "Price_AsOf":st.column_config.TextColumn("วันที่ราคา"),
        "Data_Time":st.column_config.TextColumn("ดึงข้อมูลสำเร็จ (ไทย)")})
    st.download_button("ดาวน์โหลดรายการที่กรองแล้ว", frame.to_csv(index=False).encode("utf-8-sig"),
                       file_name="filtered_watchlist.csv", mime="text/csv", key="download_watchlist")


def main():
    st.set_page_config(page_title="Ultimate Trend Trading Terminal", page_icon="📈", layout="wide")
    st.markdown("""<style>
    .block-container {padding-top:2rem;padding-bottom:3rem;max-width:1800px}
    [data-testid="stMetricValue"]{font-size:1.65rem}
    [data-testid="stDataFrame"]{border:1px solid #334155;border-radius:7px}
    </style>""", unsafe_allow_html=True)
    head, settings = st.columns([4,1])
    head.title("Ultimate Trend Trading Terminal")
    head.caption("คัดกรองหุ้น · วิเคราะห์พื้นฐานและเทคนิค · วางแผนความเสี่ยง · เปรียบเทียบผลตอบแทน")
    if "auto_refresh" not in st.session_state:
        st.session_state["auto_refresh"]=True
    auto = settings.checkbox("รีเฟรชหน้าทุก 5 นาที", key="auto_refresh")
    if auto:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=300_000, key="dashboard_refresh_5m")
        except ImportError:
            settings.caption("ใช้ปุ่มโหลดข้อมูลใหม่เพื่อรีเฟรช")
    if settings.button("รีเฟรชข้อมูลหน้าวิเคราะห์", key="refresh_all"):
        load_chart_history.clear()
        load_fundamentals.clear()
        read_watchlist.clear()
        load_etf_watchlist.clear()
        load_dividend_history.clear()
    st.caption(f"หน้ารีเฟรชล่าสุด: {thai_time(datetime.now(timezone.utc))}")
    with st.expander("แหล่งข้อมูล Watchlist / อัปโหลด CSV", expanded=not WATCHLIST_FILE.exists()):
        upload = st.file_uploader("เลือก daily_watchlist.csv เดิม", type=["csv"], key="watchlist_upload")
        st.caption("อ่านไฟล์ในโฟลเดอร์แอปอัตโนมัติ หรือเลือกอัปโหลดเพื่อใช้ในรอบนี้")
    with st.expander(f"ETF เพิ่มเติม — {len(DEFAULT_ETFS):,} ตัว / จัดการการโหลด",expanded=True):
        include_etfs = st.checkbox("รวม ETF เพิ่มเติมเข้ากับ Watchlist เดิม",value=True,key="include_etfs")
        st.caption(f"รายชื่อยืนยันจากทะเบียน Nasdaq ณ {ETF_CATALOG_AS_OF}: {len(DEFAULT_ETFS):,} ตัว จาก iShares, Vanguard, SPDR, Schwab, Invesco, Global X, VanEck, JPMorgan และ WisdomTree รวมชุดเดิม · ไม่ใช่การจัดอันดับความน่าซื้อหรือรายชื่อ ETF ทั้งตลาด")
        st.caption(f"แสดงรายชื่อครบตั้งแต่เปิดหน้า โหลดราคาชุดหลัก {len(CORE_ETFS)} ตัวอัตโนมัติ; กองอื่นเลือกวิเคราะห์ได้ทันที หรือโหลดราคาเข้าตารางครั้งละ {ETF_BATCH_SIZE} ตัว")
        c1,c2,c3=st.columns(3)
        scan_next=c1.button(f"โหลด ETF ชุดถัดไป ({ETF_BATCH_SIZE} ตัว)",key="scan_etfs_next",disabled=not include_etfs)
        scan_all=c2.button("โหลด / รีเฟรช ETF ทั้งหมด",key="scan_etfs_all",disabled=not include_etfs,on_click=pause_auto_refresh_for_scan)
        retry_failed=c3.button("ลองใหม่รายการที่โหลดไม่สำเร็จ",key="retry_etfs_failed",disabled=not include_etfs)
        st.caption("การโหลดทั้งหมดใช้เวลาหลายนาทีและจะปิดรีเฟรชอัตโนมัติระหว่างสแกน มีแถบความคืบหน้าและเก็บผลที่สำเร็จไว้ หากชุดใดล้มเหลวทั้งหมดจะหยุดให้ลองใหม่ภายหลัง เมื่อเสร็จแล้วเปิดรีเฟรชทุก 5 นาทีคืนได้")
        st.markdown(f"[ที่มารายชื่อและคำอธิบายประเภทสินทรัพย์ — Nasdaq]({ETF_CATALOG_SOURCE})")
        st.download_button("ดาวน์โหลดทะเบียนรายชื่อ ETF",etf_directory_rows(DEFAULT_ETFS)[["Ticker","ETF_Name","Asset_Type"]].to_csv(index=False).encode("utf-8-sig"),file_name="etf_catalog.csv",mime="text/csv",key="download_etf_catalog")
        if "extra_etfs" not in st.session_state:
            st.session_state.extra_etfs=[]
        with st.form("add_etfs_form"):
            requested=st.text_input("เพิ่ม Ticker ของ ETF คั่นด้วยจุลภาค (ครั้งละไม่เกิน 25 ตัว)",key="extra_etf_input",placeholder="เช่น VT, DGRO, DIVO")
            add_etfs=st.form_submit_button("ตรวจประเภทและเพิ่ม ETF")
        if add_etfs:
            candidates=list(dict.fromkeys(t.upper() for t in re.split(r"[,\s]+",requested.strip()) if t))
            if len(candidates)>25:
                st.warning("เพิ่มได้ครั้งละไม่เกิน 25 ตัว")
            else:
                for symbol in candidates:
                    if not re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}",symbol):
                        st.warning(f"ชื่อ Ticker ไม่ถูกต้อง: {symbol}")
                        continue
                    try:
                        details=load_fundamentals(symbol)
                        if str(details.get("quoteType","")).upper()!="ETF":
                            st.warning(f"ยังยืนยันว่า {symbol} เป็น ETF ไม่ได้ จึงยังไม่เพิ่ม")
                        elif symbol not in st.session_state.extra_etfs and symbol not in DEFAULT_ETFS:
                            st.session_state.extra_etfs.append(symbol)
                    except Exception as exc:
                        st.warning(f"ตรวจ {symbol} ไม่สำเร็จ: {exc}")
        if st.session_state.extra_etfs:
            st.caption("ETF ที่เพิ่มในรอบนี้: "+", ".join(st.session_state.extra_etfs))
        st.caption("ดาวน์โหลดรายการที่กรองแล้วและใช้เป็น CSV ครั้งหน้าเพื่อเก็บรายชื่อที่เพิ่มไว้; การรีเฟรชหน้าไม่รัน screener.py เพื่อเขียน CSV ใหม่")
    frame = pd.DataFrame(columns=["Ticker","Asset_Type","Status"]+NUMERIC_COLUMNS)
    source_label = "ยังไม่มีไฟล์ Watchlist"
    csv_time = "ไม่ทราบเวลาข้อมูลในไฟล์"
    try:
        if upload is not None:
            frame = parse_watchlist(upload.getvalue())
            source_label = f"ไฟล์ที่อัปโหลด: {upload.name}"
        elif WATCHLIST_FILE.exists():
            stat = WATCHLIST_FILE.stat()
            frame = read_watchlist(str(WATCHLIST_FILE), stat.st_mtime_ns, stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).astimezone(ZoneInfo("Asia/Bangkok"))
            source_label = f"CSV แก้ไขล่าสุด {modified:%d/%m/%Y %H:%M} เวลาไทย"
            csv_time = thai_time(modified)
        else:
            st.info("ยังไม่พบ daily_watchlist.csv ให้วางไฟล์เดิมไว้ข้าง app.py หรืออัปโหลดด้านบน เพื่อแสดงรายชื่อหุ้นทั้งหมด")
    except Exception as exc:
        st.error(f"อ่าน Watchlist ไม่สำเร็จ: {exc}")
    st.caption(source_label+" · เวลาไฟล์ไม่ใช่เวลาของราคาสตรีมสด")
    etfs,etf_stamp,etf_errors=pd.DataFrame(),"",[]
    if include_etfs:
        with st.spinner("โหลดราคาชุดหลักและเตรียมรายชื่อ ETF…"):
            saved_etfs=frame.loc[frame.get("Data_Source",pd.Series(index=frame.index,dtype=str)).eq("ETF เพิ่มเติม"),"Ticker"].tolist()
            configured=[str(t).strip().upper() for t in ETF_EXTRA_TICKERS if re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}",str(t).strip().upper())]
            universe=tuple(dict.fromkeys((*DEFAULT_ETFS,*configured,*st.session_state.extra_etfs,*saved_etfs)))
            if scan_all:
                load_etf_watchlist.clear()
            etfs,etf_stamp,etf_errors=render_etf_loader(universe,scan_next,scan_all,retry_failed)
    frame=merge_etf_watchlist(frame,etfs)
    if include_etfs:
        priced=int(etfs.Data_Status.eq("โหลดสำเร็จ").sum()) if not etfs.empty else 0
        untried=int(etfs.Data_Status.eq("ยังไม่โหลดราคา").sum())
        st.caption(f"ETF เพิ่มเติม: {len(etfs):,} รายชื่อ · โหลดราคาสำเร็จ {priced:,} ตัว · ยังไม่โหลด {untried:,} ตัว · ดึงสำเร็จล่าสุด {thai_time(etf_stamp)} · PASS = Close > EMA20 > EMA50")
        st.caption("ช่องราคาที่ยังว่างไม่ได้แปลว่ากองทุนหาย ใช้ปุ่มโหลด ETF หรือเลือก Ticker เพื่อดูราคา กราฟ ปันผล และแผนเข้า; เวลาแต่ละแถวอาจต่างกัน ตัวกรอง PASS/ราคาใช้ได้เฉพาะแถวที่มีข้อมูลตามเงื่อนไข")
        if etf_errors:
            st.warning("ETF บางตัวโหลดราคาไม่ได้ รายชื่อยังอยู่และเก็บราคาเดิมเมื่อมี; ใช้ปุ่มลองใหม่รายการที่โหลดไม่สำเร็จ")
            with st.expander("รายละเอียดการโหลด ETF"):
                st.text("\n".join(etf_errors))
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("สินทรัพย์ใน Watchlist", f"{len(frame):,}")
    c2.metric("PASS ตามแหล่ง Watchlist", f"{int(frame.Status.eq('PASS').sum()):,}")
    c3.metric("ประเภทสินทรัพย์", f"{frame.Asset_Type.nunique():,}")
    c4.metric("ETF ใน Watchlist",f"{int(frame.Asset_Type.eq('ETF').sum()):,}")
    filtered = render_filters(frame)
    st.divider()
    a,b = st.columns([1,1])
    with a:
        st.subheader(f"รายการสินทรัพย์ ({len(filtered):,} ตัว)")
        render_watchlist_table(filtered)
        if filtered.empty and not frame.empty:
            st.info("ไม่พบหุ้นตามตัวกรอง ลองปรับเงื่อนไขหรือค้นชื่อหุ้นด้านขวา")
    with b:
        st.subheader("เลือกหุ้นเพื่อวิเคราะห์")
        options = filtered.Ticker.tolist()
        if options:
            if st.session_state.get("selected_watchlist") not in options:
                st.session_state["selected_watchlist"] = options[0]
            chosen = st.selectbox("Ticker จากรายการที่กรอง", options, key="selected_watchlist")
            manual = st.text_input("หรือพิมพ์ Ticker อื่น", value="", key="manual_ticker")
            ticker = manual.strip().upper() or chosen
        else:
            ticker = st.text_input("Ticker สำหรับวิเคราะห์", value="AAPL", key="manual_fallback").strip().upper()
        valid_ticker = bool(re.fullmatch(r"[A-Z0-9.^=/_-]{1,30}",ticker))
        matches = frame.loc[frame.Ticker.eq(ticker)]
        selected_row = matches.iloc[0].to_dict() if not matches.empty else {}
        info, history, snapshot, history_stamp = {}, None, {}, ""
        div_result={"data":None,"fetched_at":"","error":"ยังไม่มี Ticker ที่ถูกต้อง","coverage_start":"","coverage_end":""}
        if valid_ticker:
            try:
                info = load_fundamentals(ticker)
            except Exception as exc:
                st.warning(f"ข้อมูลพื้นฐานยังโหลดไม่ได้: {exc}")
            try:
                history, history_stamp = load_chart_history(ticker,"1d")
                snapshot = daily_snapshot(completed_daily_history(history))
            except Exception as exc:
                st.warning(f"ราคาย้อนหลังยังโหลดไม่ได้ ใช้ค่าที่มีใน CSV: {exc}")
            with st.spinner("โหลดประวัติปันผล…"):
                div_result=load_dividend_history(ticker)
        else:
            st.info("กรุณาระบุ Ticker ให้ถูกต้อง")
        analysis, metrics, facts = build_analysis(snapshot, selected_row, info)
        is_etf=asset_is_etf(ticker,selected_row,info)
        if include_etfs and is_etf and snapshot and history_stamp:
            known=etf_directory_rows((ticker,)).iloc[0].to_dict()
            known.update(snapshot)
            trend_ready=all(snapshot.get(k) is not None for k in ("Close","EMA20","EMA50"))
            known.update({"Status":("PASS" if snapshot["Close"]>snapshot["EMA20"]>snapshot["EMA50"] else "FAIL") if trend_ready else "ไม่มีข้อมูล",
                          "Data_Time":history_stamp,"Price_AsOf":snapshot.get("Bar_Date",""),"Data_Status":"โหลดสำเร็จ",
                          "Historical_Return":snapshot_return(completed_daily_history(history),12)})
            st.session_state.etf_quotes=remember_etf_quotes(st.session_state.get("etf_quotes",{}),pd.DataFrame([known]))
            st.session_state.etf_attempted=sorted(set(st.session_state.get("etf_attempted",[])) | {ticker})
        currency = str(info.get("currency") or selected_row.get("Currency") or "สกุลราคาหุ้น")
        div_stats=dividend_summary(div_result,metrics["Quote"])
        facts["dividend_pct"]=div_stats["yield"]
        div_mask=analysis["ปัจจัย"].eq("Dividend Yield")
        analysis.loc[div_mask,"ค่าล่าสุด"]=show_number(div_stats["yield"],"%")
        analysis.loc[div_mask,"แหล่งข้อมูล"]="ประวัติปันผลที่โหลดสำเร็จ" if not div_result["error"] else "ไม่มีข้อมูล"
        analysis.loc[div_mask,"การแปลผล"]="ยอดปันผลต่อหน่วย 12 เดือน / ราคาอ้างอิง" if not div_result["error"] else "โหลดประวัติไม่ได้ ไม่ตีความว่าไม่มีปันผล"
        st.markdown(f"**{ticker or '—'} — {info.get('shortName') or info.get('longName') or ''}**")
        st.caption(f"Sector: {info.get('sector') or 'ไม่มีข้อมูล'} · Industry: {info.get('industry') or 'ไม่มีข้อมูล'}")
        c1,c2,c3 = st.columns(3)
        c1.metric(f"ราคาอ้างอิง ({currency})",show_number(metrics["Quote"]))
        c2.metric("Target Price",show_number(facts["target"]),
                  delta=f"{facts['upside']:+.2f}%" if facts["upside"] is not None else None)
        c3.metric("ขนาดสินทรัพย์กองทุน" if is_etf else "Market Cap",compact_number(info.get("totalAssets") if is_etf else info.get("marketCap")))
        c1,c2,c3 = st.columns(3)
        if is_etf:
            c1.metric("ประเภทสินทรัพย์","ETF")
        else:
            c1.metric("Forward P/E",show_number(facts["pe"],"x"),help="ราคาเทียบประมาณการกำไรต่อหุ้น")
        c2.metric("Dividend Yield (12 เดือน)",show_number(facts["dividend_pct"],"%"),help="รวมปันผลจากประวัติ 12 เดือน หารด้วยราคาอ้างอิง")
        c3.metric("Beta",show_number(facts["beta"]),help="ค่าความสัมพันธ์ของความเคลื่อนไหวกับตลาดจากผู้ให้ข้อมูล")
        if snapshot:
            st.caption(f"อินดิเคเตอร์ใช้แท่งก่อนวันปัจจุบันตามตลาด ล่าสุด {snapshot['Bar_Date']} · ราคา Watchlist อาจอัปเดตคนละเวลา ดูคอลัมน์แหล่งข้อมูล")
        st.caption(f"ราคาจากผู้ให้ข้อมูล ณ {thai_time(info.get('regularMarketTime'))}")
    with st.expander("เวลาอัปเดตข้อมูลล่าสุด — เวลาไทย (UTC+7)",expanded=True):
        st.dataframe(pd.DataFrame([
            {"ข้อมูล":"Quote / ข้อมูลพื้นฐานของ "+ticker,"ดึงสำเร็จล่าสุด (ไทย)":thai_time(info.get("_Fetched_At_UTC")),"เวลาที่ข้อมูลอ้างถึง":thai_time(info.get("regularMarketTime"))},
            {"ข้อมูล":"ราคาย้อนหลังรายวัน","ดึงสำเร็จล่าสุด (ไทย)":thai_time(history_stamp),"เวลาที่ข้อมูลอ้างถึง":"แท่งเทคนิคล่าสุด "+str(snapshot.get("Bar_Date","ไม่มีข้อมูล"))+" (วันที่ตลาด)"},
            {"ข้อมูล":"ประวัติปันผล","ดึงสำเร็จล่าสุด (ไทย)":thai_time(div_result.get("fetched_at")),"เวลาที่ข้อมูลอ้างถึง":str(div_result.get("coverage_start") or "—")+" ถึง "+str(div_result.get("coverage_end") or "—")},
            {"ข้อมูล":"ชุด ETF เพิ่มเติม","ดึงสำเร็จล่าสุด (ไทย)":thai_time(etf_stamp),"เวลาที่ข้อมูลอ้างถึง":"ดูวันที่ราคาแต่ละตัวใน Watchlist" if include_etfs else "ปิดชุดเพิ่มเติม"},
            {"ข้อมูล":"CSV เดิม","ดึงสำเร็จล่าสุด (ไทย)":"ไม่ทราบเวลาสแกนจากไฟล์","เวลาที่ข้อมูลอ้างถึง":"เวลาแก้ไขไฟล์: "+csv_time}]),hide_index=True,**width_options(st.dataframe))
        st.caption("เวลารีเฟรชหน้าไม่ใช่เวลาราคา: ราคาหุ้นที่เลือก/ข้อมูลพื้นฐาน/ชุดหลัก ETF เก็บแคช 5 นาที; ปันผล 1 ชั่วโมง ใช้ปุ่มรีเฟรชข้อมูลหน้าวิเคราะห์เพื่อดึงใหม่ ETF ที่โหลดเป็นชุดเก็บราคาตามเวลาแต่ละแถว ใช้ปุ่มโหลด / รีเฟรช ETF ทั้งหมดเพื่ออัปเดตทั้งรายชื่อ ปุ่มเหล่านี้ไม่รัน screener.py เพื่อเขียน CSV ใหม่ และเวลาราคาอาจล่าช้าหรือเป็นราคาตลาดปิด")
    st.divider()
    st.subheader("ตารางวิเคราะห์ 360° — พื้นฐาน เทคนิค และความเสี่ยง")
    st.dataframe(analysis, **width_options(st.dataframe), hide_index=True, height=500,
                 column_config={"การแปลผล":st.column_config.TextColumn(width="large"),
                                "แหล่งข้อมูล":st.column_config.TextColumn(help="ค่าแต่ละส่วนอาจอัปเดตคนละเวลา")})
    benchmark=None
    if is_etf and valid_ticker:
        try:
            benchmark=history if ticker=="SPY" else load_chart_history("SPY","1d")[0]
        except Exception as exc:
            st.warning(f"ยังโหลด SPY สำหรับประเมิน ETF ไม่ได้: {exc}")
    ctx=decision_context(history,info,benchmark)
    scored=criteria_score(ctx,info,is_etf)
    min_rr=st.number_input("Reward/Risk ขั้นต่ำสำหรับให้ผ่านแผนซื้อ",min_value=2.0,max_value=10.0,value=2.0,step=.5,key="minimum_rr",help="กำไรตามเป้าหมายต้องไม่น้อยกว่าความเสี่ยงตาม Stop กี่เท่า ยังไม่รวมค่าธรรมเนียม")
    entry_plan=build_entry_plan(ctx,info,scored,is_etf,min_rr)
    render_decision(ticker,ctx,info,scored,entry_plan,is_etf,div_result,currency)
    st.divider()
    render_position_sizer(ticker or "UNKNOWN", selected_row, metrics, currency)
    st.divider()
    render_dividends(ticker,div_result,currency,metrics["Quote"])
    st.divider()
    tab1,tab2,tab3 = st.tabs(["กราฟเทคนิค", "Relative Strength เทียบ SPY", "เปรียบเทียบหุ้น 2 ตัว"])
    with tab1:
        st.subheader(f"กราฟเทคนิค — {ticker or 'เลือกหุ้น'}")
        if valid_ticker:
            render_trading_chart(ticker)
    with tab2:
        st.subheader("ผลตอบแทนเทียบตลาด — SPY")
        rs_period = st.radio("ช่วงเวลาเทียบตลาด",["1 เดือน","3 เดือน","6 เดือน","1 ปี","2 ปี","3 ปี"],index=3,horizontal=True,key="rs_period")
        if valid_ticker:
            render_comparison(ticker,"SPY",rs_period,"rs_chart")
    with tab3:
        st.subheader("เปรียบเทียบผลตอบแทนหุ้น 2 ตัว")
        c1,c2 = st.columns(2)
        c1.text_input("หุ้นตัวที่ 1 (หุ้นที่เลือก)",value=ticker,disabled=True,key=f"comp_first_{ticker}")
        second = c2.text_input("หุ้นตัวที่ 2",value="MSFT" if ticker == "AAPL" else "AAPL",key="comp_second").strip().upper()
        comp_period = st.radio("ช่วงเวลาเปรียบเทียบ",["1 เดือน","3 เดือน","6 เดือน","1 ปี","2 ปี","3 ปี"],index=3,horizontal=True,key="comp_period")
        if valid_ticker:
            render_comparison(ticker,second,comp_period,"comparison_chart")


if __name__ == "__main__":
    main()
