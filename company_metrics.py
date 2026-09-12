"""Display-only research definitions. Guides are NOT universal fair values.

All amounts have no size-independent ideal. Special sectors are not assessed by
industrial-company debt/cash-flow shortcuts. Never changes Top 10 scoring.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Metric:
    key:str
    group:str
    label:str
    provider:str|None
    unit:str
    policy:str
    guide:str
    definition:str
    industrial:bool=False


def m(key,group,label,provider,unit,policy,guide,definition,industrial=False):
    return Metric(key,group,label,provider,unit,policy,guide,definition,industrial)

METRICS=(
 m('revenue','Income Statement','Revenue','totalRevenue','money','context','No universal amount; compare YoY and margins','รายได้รวมก่อนหักต้นทุน ไม่ใช่กำไร บริษัทใหญ่ไม่ได้ดีกว่าเสมอ ต้องอ่านงวดและการเติบโตประกอบ'),
 m('cost_of_revenue','Income Statement','Cost of Revenue',None,'money','context','Compare with revenue in the same period','ต้นทุนสินค้าและบริการที่สัมพันธ์กับรายได้ ไม่ใช่ค่าใช้จ่ายทั้งหมด'),
 m('gross_profit','Income Statement','Gross Profit','grossProfits','money','earnings','Positive; assess Gross Margin and trend','กำไรขั้นต้น = รายได้ − ต้นทุนขาย ค่าเป็นจำนวนเงิน ต้องดูอัตรากำไรและลักษณะธุรกิจร่วมด้วย',True),
 m('operating_income','Income Statement','Operating Income',None,'money','earnings','Positive recurring operating income','กำไรจากการดำเนินงานหลังค่าใช้จ่ายดำเนินงาน; ไม่เท่ากับ EBIT ทุกกรณี เพราะอาจมีรายการนอกการดำเนินงาน',True),
 m('ebit','Income Statement','EBIT',None,'money','earnings','Positive; compare margin and interest coverage','Earnings Before Interest and Taxes คำนวณจากกำไรก่อนภาษีบวกดอกเบี้ยจ่ายของงวดเดียวกัน ไม่ใช้ EBITDA แทน',True),
 m('ebitda','Income Statement','EBITDA','ebitda','money','earnings','Positive; not a substitute for cash flow','EBIT บวกค่าเสื่อมและค่าตัดจำหน่าย ไม่ใช่เงินสดจริงและยังไม่หัก CAPEX; ค่าจากงบเป็น proxy ไม่ใช่ Adjusted EBITDA ของฝ่ายบริหาร',True),
 m('pretax_income','Income Statement','Pretax Income',None,'money','earnings','Positive; inspect exceptional items','กำไรก่อนภาษีของบริษัททั้งกิจการ ห้ามใช้กำไรเฉพาะประเทศแทนยอดรวม'),
 m('tax_expense','Income Statement','Income Tax Expense',None,'money','context','Compare with pretax income; benefits can be negative','ค่าใช้จ่ายภาษีในงวด อาจติดลบจากสิทธิประโยชน์ภาษี ไม่ควรสมมติอัตราภาษี 21% ให้ทุกบริษัท'),
 m('net_income','Income Statement','Net Income','netIncomeToCommon','money','earnings','Positive recurring net income','กำไรสุทธิหลังต้นทุน ดอกเบี้ย และภาษี; provider netIncomeToCommon เป็นกำไรของหุ้นสามัญ ซึ่งอาจมีขอบเขตต่างจาก SEC NetIncomeLoss'),
 m('eps','Income Statement','Diluted EPS (reported)','trailingEps','per_share','earnings','Positive; compare same share/ADR basis','กำไรต่อหุ้นย้อนหลังที่แหล่งข้อมูลรายงาน หุ้นแตกพาร์และ ADR อาจใช้หน่วยต่างกัน ไม่หารกำไรทั้งบริษัทด้วยจำนวนหุ้นที่ต่างงวด'),
 m('gross_margin','Profitability & Capital Efficiency','Gross Margin','grossMargins','percent','higher_margin','Guide: ≥40% high; 20–40% middle; <20% low; industry-dependent','กำไรขั้นต้น ÷ รายได้ × 100 ธุรกิจค้าปลีกและซอฟต์แวร์มีโครงสร้างต่างกัน เกณฑ์นี้เป็นเพียง screening guide',True),
 m('operating_margin','Profitability & Capital Efficiency','Operating Margin','operatingMargins','percent','operating_margin','Guide: ≥15% strong; 5–15% moderate; <5% thin','กำไรดำเนินงาน ÷ รายได้ × 100 ดูกำไรจากธุรกิจหลักก่อนผลของโครงสร้างเงินทุน',True),
 m('net_margin','Profitability & Capital Efficiency','Net Margin','profitMargins','percent','net_margin','Guide: ≥10% strong; 0–10% positive; <0% loss','กำไรสุทธิ ÷ รายได้ × 100 รายการพิเศษอาจทำให้สูงชั่วคราว ควรเทียบอุตสาหกรรมและหลายปี'),
 m('roe','Profitability & Capital Efficiency','ROE','returnOnEquity','percent','roe','Guide: ≥15% strong; 8–15% moderate; <8% weak; equity must be positive','Return on Equity = กำไรสุทธิ ÷ ส่วนผู้ถือหุ้นเฉลี่ยต้นงวด-ปลายงวด × 100; ทุนต่ำจากซื้อหุ้นคืนหรือหนี้สูงอาจดัน ROE โดยไม่ได้สะท้อนคุณภาพที่ดีขึ้น'),
 m('roa','Profitability & Capital Efficiency','ROA','returnOnAssets','percent','roa','Guide: ≥5% strong; 2–5% moderate; <2% low','Return on Assets = กำไรสุทธิ ÷ สินทรัพย์เฉลี่ย × 100 ประเมินการใช้สินทรัพย์; ต้องเทียบรูปแบบธุรกิจ',True),
 m('nopat','Profitability & Capital Efficiency','NOPAT',None,'money','earnings','Positive after-tax operating profit','Net Operating Profit After Tax = Operating Income × (1 − effective tax rate); คำนวณเฉพาะกำไรก่อนภาษีบวกและอัตราภาษีระหว่าง 0–100%',True),
 m('roic','Profitability & Capital Efficiency','ROIC',None,'percent','roic','ROIC > WACC; no value-creation verdict without WACC','NOPAT ÷ ทุนลงทุนเฉลี่ย × 100; ทุนลงทุน = ส่วนผู้ถือหุ้น + หนี้มีดอกเบี้ย − เงินสด; รวม goodwill ไม่ปรับ R&D/lease เพิ่มเอง ไม่รับรองมูลค่าถ้าไม่ทราบ WACC',True),
 m('asset_turnover','Profitability & Capital Efficiency','Asset Turnover',None,'multiple','context','Compare industry and historical trend','รายได้ ÷ สินทรัพย์เฉลี่ย ยอดขายต่อหน่วยสินทรัพย์ ไม่ควรใช้เกณฑ์เดียวกับธุรกิจบริการและโรงงาน',True),
 m('inventory_turnover','Profitability & Capital Efficiency','Inventory Turnover',None,'multiple','context','Compare industry; excessive turnover can imply stock shortages','ต้นทุนขาย ÷ สินค้าคงเหลือเฉลี่ยต้นงวด-ปลายงวด ธุรกิจไม่มีสินค้าคงคลังอาจไม่เหมาะกับตัวชี้วัดนี้',True),
 m('revenue_growth','Growth','Revenue Growth (provider)','revenueGrowth','percent','growth','Guide: >10% expanding; 0–10% modest; <0% contraction','การเติบโตของรายได้ที่ provider รายงาน; อาจอิงไตรมาส ห้ามเรียก YoY ทั้งปีถ้าไม่ทราบงวด'),
 m('earnings_growth','Growth','Earnings Growth (provider)','earningsGrowth','percent','growth','Positive growth; inspect loss/low-base effects','การเติบโตกำไรที่แหล่งข้อมูลรายงาน ฐานติดลบหรือใกล้ศูนย์ทำให้เปอร์เซ็นต์หลอกตา ไม่ใช่กำไรที่รับประกันในอนาคต'),
 m('revenue_growth_fy','Growth','Revenue Growth (FY YoY)',None,'percent','growth','Guide: >10% expanding; 0–10% modest; <0% contraction','(รายได้ปีล่าสุด ÷ รายได้ปีก่อน − 1) × 100 ต้องเป็นปีที่ต่อเนื่อง สกุลเงินเดียวกัน และฐานมากกว่าศูนย์'),
 m('net_income_growth_fy','Growth','Net Income Growth (FY YoY)',None,'percent','growth','Positive recurring growth; prior earnings must be positive','(กำไรสุทธิปีล่าสุด ÷ กำไรปีก่อน − 1) × 100 ไม่คำนวณ growth ทั่วไปจากฐานกำไรศูนย์หรือติดลบ'),
 m('assets','Balance Sheet & Leverage','Total Assets',None,'money','context','No universal target','สินทรัพย์รวม ณ วันสิ้นงวด เป็นยอดคงเหลือ ไม่ใช่กระแสเงินในช่วงเวลา'),
 m('liabilities','Balance Sheet & Leverage','Total Liabilities',None,'money','context','Compare obligations, assets and cash flow','หนี้สินรวมรวมเจ้าหนี้และภาระอื่นด้วย จึงไม่เท่ากับหนี้ที่มีดอกเบี้ย'),
 m('equity','Balance Sheet & Leverage','Shareholders Equity',None,'money','equity','Positive equity; inspect buybacks and accumulated losses','ส่วนผู้ถือหุ้นตามงบดุล หากเป็นศูนย์หรือติดลบ ROE, P/B และ D/E อาจตีความไม่ได้ ไม่จัดว่าหนี้ต่ำเพราะ ratio ติดลบ'),
 m('cash','Balance Sheet & Leverage','Cash & Equivalents','totalCash','money','context','Compare obligations and operating needs','ยอดเงินสด; SEC ใช้ cash and equivalents ส่วน provider totalCash อาจรวม short-term investments ดูแหล่งและนิยามก่อนเทียบ'),
 m('debt','Balance Sheet & Leverage','Interest-bearing Debt','totalDebt','money','context','Compare cash flow, maturities and equity','หนี้มีดอกเบี้ย ไม่ใช่หนี้สินทั้งหมด; SEC ต้องมีส่วน current maturities, noncurrent debt และ short-term borrowings ครบ ไม่แทนส่วนที่ไม่รายงานด้วยศูนย์',True),
 m('net_debt','Balance Sheet & Leverage','Net Debt',None,'money','net_debt','≤0 indicates net cash; positive debt needs coverage analysis','หนี้มีดอกเบี้ย − เงินสดตามงวดเดียวกัน ค่าเป็นลบหมายถึงเงินสดมากกว่าหนี้ ไม่ได้หมายความว่ากิจการไม่มีภาระอื่น',True),
 m('de','Balance Sheet & Leverage','D/E Ratio','debtToEquity','multiple','de','Guide: <0.5x low; 0.5–1.5x moderate; >1.5x leveraged','Interest-bearing Debt ÷ Equity; provider debtToEquity แสดงแบบเปอร์เซ็นต์จึงหาร 100 เพื่อแสดงเท่า; ไม่สับสนกับ Total Liabilities/Equity',True),
 m('liabilities_equity','Balance Sheet & Leverage','Liabilities / Equity',None,'multiple','context','Different definition from interest-bearing D/E','หนี้สินรวม ÷ ส่วนผู้ถือหุ้น รวมภาระที่ไม่ใช่เงินกู้ด้วย; ดูทั้งนิยามและธุรกิจ'),
 m('net_debt_ebitda','Balance Sheet & Leverage','Net Debt / EBITDA',None,'multiple','net_debt_ebitda','Guide: <2x lower; 2–3x watch; >3x elevated','หนี้สุทธิ ÷ EBITDA ของงวดเดียวกัน ใช้เฉพาะ EBITDA บวก; ไม่แทน EBITDA ด้วย EBIT หรือกระแสเงินสด',True),
 m('interest_expense','Balance Sheet & Leverage','Interest Expense',None,'money','context','Inspect refinancing costs and debt maturity','ดอกเบี้ยจ่ายในปี ไม่ใช่ดอกเบี้ยสุทธิที่อาจรวมรายรับแล้ว',True),
 m('interest_coverage','Balance Sheet & Leverage','Interest Coverage',None,'multiple','interest','Guide: ≥5x stronger; 2–5x watch; <2x weak','EBIT ÷ ดอกเบี้ยจ่าย ต้องเป็นงวดเดียวกัน ถ้าดอกเบี้ยไม่รายงานหรือเป็นศูนย์ไม่แสดง Infinity ว่าปลอดภัย',True),
 m('current_ratio','Liquidity','Current Ratio','currentRatio','multiple','current','Guide: ≥1.5x cushion; 1–1.5x watch; <1x shortfall','สินทรัพย์หมุนเวียน ÷ หนี้สินหมุนเวียน เกณฑ์โรงงานทั่วไปไม่เหมาะกับธนาคารหรือบางธุรกิจที่มี working capital ติดลบตามปกติ',True),
 m('quick_ratio','Liquidity','Quick Ratio','quickRatio','multiple','quick','Guide: ≥1x cushion; <1x watch','(เงินสด + เงินลงทุนระยะสั้น + ลูกหนี้) ÷ หนี้สินหมุนเวียน ไม่รวม inventory/prepayments; สูตร provider อาจต่างกัน',True),
 m('cash_ratio','Liquidity','Cash Ratio',None,'multiple','context','Compare business cash cycle; no universal minimum','เงินสดและเทียบเท่าเงินสด ÷ หนี้สินหมุนเวียน ไม่รวม inventory และลูกหนี้',True),
 m('working_capital','Liquidity','Working Capital',None,'money','context','Positive buffer is useful; negative can be structural','สินทรัพย์หมุนเวียน − หนี้สินหมุนเวียน ยอดติดลบต้องวิเคราะห์วงจรรับจ่ายและอำนาจต่อรอง ไม่ตัดสินว่าแย่เสมอ',True),
 m('ocf','Cash Flow & Earnings Quality','Operating Cash Flow','operatingCashflow','money','earnings','Positive and repeatable operating cash flow','เงินสดจากกิจกรรมดำเนินงาน ไม่ใช่กำไรบัญชีหรือยอดเงินสดที่ถืออยู่',True),
 m('capex','Cash Flow & Earnings Quality','Capital Expenditure',None,'money','context','Compare reinvestment with sustainable operating cash flow','เงินสดจ่ายซื้อ PP&E แสดงจำนวนบวกก่อนนำไปหัก OCF; ไม่ได้รวม acquisition หรือ intangible investment ทุกประเภท',True),
 m('fcf','Cash Flow & Earnings Quality','Free Cash Flow','freeCashflow','money','earnings','Positive across a business cycle; growth capex can depress it','OCF − CAPEX ตามนิยามที่ระบุ ไม่หักรายจ่ายที่ไม่ทราบเอง และไม่คำนวณจากข้อมูลคนละงวด',True),
 m('fcf_margin','Cash Flow & Earnings Quality','FCF Margin',None,'percent','net_margin','Guide: ≥10% robust; 0–10% positive; <0% outflow','Free Cash Flow ÷ รายได้ × 100 ใช้ตัวเลขงวดเดียวกัน สะท้อนเงินสดหลังลงทุนต่อยอดขาย',True),
 m('ocf_ni','Cash Flow & Earnings Quality','Cash Conversion (OCF / NI)',None,'multiple','conversion','Guide: ≥1x supports earnings; <1x investigate','OCF ÷ กำไรสุทธิ ใช้เฉพาะกำไรสุทธิบวกและงวดเดียวกัน; working capital และรายการไม่ใช่เงินสดทำให้ ratio ผันผวน',True),
 m('sbc','Cash Flow & Earnings Quality','Share-based Compensation',None,'money','context','Review dilution and recurring nature','ค่าตอบแทนหุ้น อาจถูกบวกกลับใน OCF แต่มีต้นทุนต่อผู้ถือหุ้นผ่าน dilution ไม่ใช่เงินทุนฟรี'),
 m('sbc_revenue','Cash Flow & Earnings Quality','SBC / Revenue',None,'percent','context','Lower dilution burden, but compare sector practice','ค่าตอบแทนหุ้น ÷ รายได้ × 100; ใช้ดูภาระค่าตอบแทนหุ้นร่วมกับจำนวนหุ้นเพิ่มและการซื้อหุ้นคืน'),
 m('market_cap','Valuation','Market Capitalization','marketCap','quote_money','context','Size is not quality or fair value','มูลค่าตลาดของหุ้นทั้งหมด ไม่รวมภาระหนี้ของบริษัท ไม่ใช้ขนาดใหญ่ตัดสินว่าราคาถูก'),
 m('forward_pe','Valuation','Forward P/E','forwardPE','multiple','pe','Guide: 0–25x lower; 25–40x premium; >40x high expectations','ราคาหุ้น ÷ กำไรต่อหุ้นประมาณการ; การประมาณการอาจผิด ค่าเกณฑ์เป็นแนวคัดกรอง ไม่ใช่มูลค่ายุติธรรมของทุกอุตสาหกรรม'),
 m('trailing_pe','Valuation','Trailing P/E','trailingPE','multiple','pe','Positive earnings required; compare peers and cycle','ราคาหุ้น ÷ EPS ย้อนหลัง ไม่ใช้ P/E ต่ำเป็นคำสั่งซื้อ และไม่ประเมิน P/E เมื่อกำไรไม่เป็นบวก'),
 m('price_book','Valuation','Price / Book (P/B)','priceToBook','multiple','pb','<1x below book; 1–3x mid; >3x premium — not a quality verdict','P/B หรือ P/BV = ราคาต่อหุ้น ÷ มูลค่าทางบัญชีต่อหุ้น; ใช้ชื่อมาตรฐานแทน P/BE ที่ระบุมา; ทุนติดลบทำให้ไม่มีความหมายและธุรกิจสินทรัพย์เบาอาจซื้อขายสูงกว่า book มาก'),
 m('price_sales','Valuation','Price / Sales','priceToSalesTrailing12Months','multiple','context','Compare peers with similar margins and growth','มูลค่าตลาด ÷ รายได้ย้อนหลัง Ratio ต่ำอาจสะท้อน margin ต่ำ ห้ามใช้ตัวเลขเดียวกันตัดสินทุกธุรกิจ'),
 m('ev_ebitda','Valuation','EV / EBITDA','enterpriseToEbitda','multiple','ev','Guide: <10x lower; 10–15x middle; >15x premium','มูลค่ากิจการ ÷ EBITDA ไม่ใช่กำไรสุทธิหรือ FCF; มูลค่านี้ไม่เหมาะกับการเงินและต้องดู leases/adjustments',True),
 m('ev_sales','Valuation','EV / Sales','enterpriseToRevenue','multiple','context','Compare industry margins, growth and accounting basis','มูลค่ากิจการ ÷ รายได้ Ratio ต่ำไม่รับรองความถูกหากกิจการทำกำไรไม่ได้',True),
 m('dividend_yield','Shareholder Distributions','Dividend Yield (trailing)','trailingAnnualDividendYield','percent','context','Yield is not total return; assess coverage and continuity','อัตราปันผลย้อนหลังที่ provider รายงานเป็นสัดส่วนจึงคูณ 100 ไม่ใช่ผลตอบแทนรวม และไม่รับประกันการจ่ายงวดถัดไป'),
 m('payout','Shareholder Distributions','Dividend Payout Ratio','payoutRatio','percent','payout','Guide: 0–60% retained cushion; 60–100% watch; >100% above earnings','ปันผล ÷ กำไร ใช้เป็นตัวชี้วัดความครอบคลุมเท่านั้น ไม่รับประกันปันผลในอนาคต; REIT ต้องดู FFO/AFFO แทนกำไร GAAP',True),
 m('dividends_paid','Shareholder Distributions','Cash Dividends Paid',None,'money','context','Compare FCF and sustainable payout','เงินสดปันผลที่จ่ายในงวด ไม่ใช่ dividend yield หรือปันผลต่อหุ้น'),
 m('buybacks','Shareholder Distributions','Share Repurchases',None,'money','context','Compare FCF, debt funding and share-count change','เงินสดซื้อหุ้นคืนรวม ไม่ใช่ net buyback yield; ต้องดูหุ้นออกใหม่และ SBC ร่วมด้วย'),
 m('target','Analyst Expectations','Target Price','targetMeanPrice','quote_money','context','Analyst estimate, not intrinsic value or a guaranteed outcome','ราคาเป้าหมายเฉลี่ยนักวิเคราะห์ เวลาประมาณการอาจไม่ตรงกับราคาปัจจุบัน ไม่เปลี่ยนเป็นผลตอบแทนที่รับประกัน'),
 m('analysts','Analyst Expectations','Analyst Count','numberOfAnalystOpinions','count','context','Coverage count is not prediction accuracy','จำนวนนักวิเคราะห์ที่รวมในประมาณการ จำนวนมากไม่ได้รับรองความถูกต้อง'),
)
BY_KEY={m.key:m for m in METRICS}
GROUPS=tuple(dict.fromkeys(m.group for m in METRICS))
SOURCES={
 'Financial statements and ratio context':'https://www.sec.gov/about/reports-publications/beginners-guide-financial-statements',
 'SEC filed-facts definitions':'https://www.sec.gov/search-filings/edgar-application-programming-interfaces',
 'ROIC and cost-of-capital context':'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/articles/ROICrules.html',
}
GUIDE_NOTE='Illustrative screening guides, not universal targets. Compare sector, accounting basis, business cycle and history. A high ratio can be a warning, not automatically good.'
