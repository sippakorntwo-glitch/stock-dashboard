"""Thai presentation of canonical company observations, without changing values.

Metric keys, policy decisions and availability states stay in company_metrics.
Translations use those keys and complete messages, never partial replacements.
"""
from __future__ import annotations

from company_metrics import METRICS, evaluate, metric_observations, DIVIDEND_YIELD_SOURCE_DISAGREEMENT


GROUP_LABELS = {
    'Valuation': 'มูลค่าและความถูกแพง',
    'Profitability & Returns': 'ความสามารถทำกำไรและผลตอบแทน',
    'Growth': 'การเติบโต',
    'Income Statement': 'งบกำไรขาดทุน',
    'Financial Strength': 'ความแข็งแกร่งทางการเงิน',
    'Balance Sheet': 'งบฐานะการเงิน',
    'Cash Flow': 'กระแสเงินสด',
    'Shareholder Returns': 'ผลตอบแทนแก่ผู้ถือหุ้น',
    'Analyst Expectations': 'ประมาณการของนักวิเคราะห์',
}

# Label and definition share the stable financial metric key.
METRIC_TEXT = {
    'marketCap': ('มูลค่าหลักทรัพย์ตามราคาตลาด', 'ราคาหุ้นคูณจำนวนหุ้นที่ออกและถืออยู่ ขนาดของบริษัทไม่ได้บอกคุณภาพของกิจการโดยลำพัง'),
    'enterpriseValue': ('มูลค่ากิจการ', 'มูลค่ากิจการตามผู้ให้ข้อมูล รวมมูลค่าหุ้นตามราคาตลาดและภาระที่มีลักษณะคล้ายหนี้ แล้วหักเงินสด ควรตรวจสอบวิธีคำนวณของผู้ให้ข้อมูล'),
    'trailingPE': ('ราคาต่อกำไรย้อนหลัง', 'ราคาหุ้นหารกำไรต่อหุ้นย้อนหลัง หากกำไรเป็นศูนย์หรือติดลบ อัตราส่วนนี้จะตีความไม่ได้ ค่า P/E ต่ำอาจสะท้อนความเสี่ยงได้เช่นกัน'),
    'forwardPE': ('ราคาต่อกำไรคาดการณ์', 'ราคาหุ้นหารกำไรต่อหุ้นที่คาดการณ์ ประมาณการของนักวิเคราะห์เปลี่ยนแปลงได้และยังไม่ใช่กำไรที่เกิดขึ้นจริง'),
    'priceToBook': ('ราคาต่อมูลค่าทางบัญชี', 'ราคาหุ้นหารมูลค่าทางบัญชีต่อหุ้น หรือ P/BV หากส่วนของผู้ถือหุ้นติดลบ อัตราส่วนนี้จะตีความไม่ได้ ธุรกิจที่ใช้สินทรัพย์น้อยและธนาคารควรใช้บริบทเปรียบเทียบต่างกัน'),
    'priceToSales': ('ราคาต่อยอดขาย', 'มูลค่าหุ้นตามราคาตลาดเทียบกับยอดขายย้อนหลัง ยอดขายเพียงอย่างเดียวไม่ได้บอกความสามารถทำกำไร'),
    'evRevenue': ('มูลค่ากิจการต่อรายได้', 'มูลค่ากิจการเทียบกับรายได้ ควรเปรียบเทียบธุรกิจที่มีอัตรากำไร การเติบโต และนโยบายบัญชีใกล้เคียงกัน'),
    'evEbitda': ('มูลค่ากิจการต่อกำไรก่อนดอกเบี้ย ภาษี ค่าเสื่อมและค่าตัดจำหน่าย', 'มูลค่ากิจการหารกำไรก่อนดอกเบี้ย ภาษี ค่าเสื่อมราคาและค่าตัดจำหน่าย EBITDA ยังไม่หักรายจ่ายลงทุนและความต้องการเงินทุนหมุนเวียน จึงไม่ใช่กระแสเงินสดอิสระ'),
    'grossMargins': ('อัตรากำไรขั้นต้น', 'กำไรขั้นต้นหารรายได้ การจัดประเภทต้นทุนและรูปแบบธุรกิจมีผลมากต่อการเปรียบเทียบ'),
    'operatingMargins': ('อัตรากำไรจากการดำเนินงาน', 'กำไรจากการดำเนินงานหารรายได้ ก่อนต้นทุนทางการเงินและภาษี ควรเทียบกับอดีตของบริษัทและบริษัทในอุตสาหกรรมเดียวกัน'),
    'profitMargins': ('อัตรากำไรสุทธิ', 'กำไรสุทธิหารรายได้ รายการครั้งเดียว ภาษี และต้นทุนทางการเงินอาจทำให้อัตราส่วนนี้เปลี่ยนแปลงมาก'),
    'returnOnEquity': ('ผลตอบแทนต่อส่วนของผู้ถือหุ้น', 'กำไรสุทธิหารส่วนของผู้ถือหุ้นเฉลี่ยเมื่อมีงบที่ตรงกัน หากไม่มีจะใช้ ROE จากผู้ให้ข้อมูล การซื้อหุ้นคืน หนี้สูง หรือฐานทุนเล็กอาจทำให้ ROE สูงขึ้น'),
    'returnOnAssets': ('ผลตอบแทนต่อสินทรัพย์', 'กำไรสุทธิหารสินทรัพย์เฉลี่ยเมื่อมีงบที่ตรงกัน หากไม่มีจะใช้ ROA จากผู้ให้ข้อมูล ควรเทียบธุรกิจที่ใช้สินทรัพย์มากน้อยใกล้เคียงกัน'),
    'roic': ('ผลตอบแทนต่อเงินลงทุน', 'กำไรจากการดำเนินงานหลังภาษีหารเงินลงทุนเฉลี่ย ในที่นี้เงินลงทุนคือส่วนของผู้ถือหุ้นบวกหนี้ที่มีดอกเบี้ย แล้วหักเงินสดและเงินลงทุนระยะสั้น ใช้อัตราภาษีที่รายงานจริงเฉพาะเมื่ออยู่ในช่วง 0–100% ค่าประมาณนี้อาจต่างจาก ROIC ที่นักวิเคราะห์ปรับปรุง ควรเทียบกับต้นทุนเงินทุนถัวเฉลี่ยถ่วงน้ำหนักของบริษัท (WACC) โดยระบบไม่ได้สมมติ WACC'),
    'revenueGrowth': ('การเติบโตของรายได้จากผู้ให้ข้อมูล', 'อัตราเติบโตที่ผู้ให้ข้อมูลรายงาน โดยทั่วไปเป็นการเทียบรายไตรมาสกับปีก่อน ควรตรวจสอบรอบบัญชี ไม่ได้หมายถึงการเติบโตทั้งปีหรือการคาดการณ์โดยอัตโนมัติ'),
    'earningsGrowth': ('การเติบโตของกำไรจากผู้ให้ข้อมูล', 'อัตราเติบโตของกำไรที่ผู้ให้ข้อมูลรายงาน การขาดทุน ฐานกำไรใกล้ศูนย์ และรายการพิเศษอาจทำให้การเปรียบเทียบเป็นร้อยละบิดเบือน'),
    'revenueGrowthFY': ('การเติบโตของรายได้ทั้งปีบัญชี', 'รายได้ทั้งปีบัญชีล่าสุดหารรายได้ทั้งปีบัญชีก่อน แล้วลบหนึ่ง ใช้ตัวเลขทั้งสองปีจากงบกำไรขาดทุน'),
    'netIncomeGrowthFY': ('การเติบโตของกำไรสุทธิทั้งปีบัญชี', 'กำไรสุทธิทั้งปีบัญชีล่าสุดหารกำไรสุทธิทั้งปีบัญชีก่อน แล้วลบหนึ่ง หากปีก่อนมีกำไรเป็นศูนย์หรือขาดทุนจะแสดงว่าตีความไม่ได้ ไม่แสดงเป็นอัตราเติบโตตามปกติ'),
    'epsGrowthFY': ('การเติบโตของกำไรต่อหุ้นปรับลดทั้งปี', 'กำไรต่อหุ้นปรับลดทั้งปีบัญชีล่าสุดหารค่าของปีก่อน แล้วลบหนึ่ง ไม่ประเมินอัตราเติบโตเมื่อฐานปีก่อนเป็นศูนย์หรือติดลบ'),
    'revenue': ('รายได้', 'ยอดขายที่รายงานสำหรับรอบบัญชีที่ระบุ รายได้ไม่ใช่เงินสดที่รับแล้ว และขนาดรายได้เพียงอย่างเดียวไม่ได้บอกคุณภาพของกิจการ'),
    'grossProfit': ('กำไรขั้นต้น', 'รายได้หักต้นทุนรายได้ที่รายงาน ใช้ข้อมูลจากงบกำไรขาดทุน โดยไม่สมมติให้รายจ่ายที่ไม่ทราบค่าเป็นศูนย์'),
    'operatingIncome': ('กำไรจากการดำเนินงาน', 'กำไรจากการดำเนินงานก่อนต้นทุนทางการเงินและภาษี แสดงแยกจาก EBIT เพราะรายการนอกการดำเนินงานอาจทำให้ตัวเลขต่างกัน'),
    'ebit': ('กำไรก่อนดอกเบี้ยและภาษี', 'กำไรก่อนดอกเบี้ยและภาษีที่รายงาน ไม่ใช้ EBITDA แทนและไม่ประมาณจากอัตรากำไร'),
    'ebitda': ('กำไรก่อนดอกเบี้ย ภาษี ค่าเสื่อมและค่าตัดจำหน่าย', 'กำไรก่อนดอกเบี้ย ภาษี ค่าเสื่อมราคาและค่าตัดจำหน่าย EBITDA ที่เป็นบวกไม่ได้รับประกันว่าจะสร้างเงินสดเป็นบวก'),
    'netIncome': ('กำไรสุทธิ', 'กำไรหลังหักค่าใช้จ่ายและภาษีสำหรับงวดที่ระบุ หากมีเฉพาะข้อมูลสรุปบริษัท จะใช้กำไรสุทธิส่วนที่เป็นของผู้ถือหุ้นสามัญ'),
    'dilutedEPS': ('กำไรต่อหุ้นปรับลด', 'กำไรต่อจำนวนหุ้นถัวเฉลี่ยถ่วงน้ำหนักแบบปรับลด ใช้ EPS รายปีที่รายงานโดยตรง ไม่บวก EPS รายไตรมาสเพื่อสร้างตัวเลขรายปี'),
    'debtToEquity': ('หนี้ที่มีดอกเบี้ยต่อส่วนของผู้ถือหุ้น', 'หนี้ที่มีดอกเบี้ยรวมหารส่วนของผู้ถือหุ้น แสดงหน่วยเป็นเท่า ค่า debtToEquity ในข้อมูลสรุปของ Yahoo เป็นร้อยละ จึงหาร 100 ก่อนแสดง ต่างจากหนี้สินรวมต่อส่วนของผู้ถือหุ้น หากส่วนของผู้ถือหุ้นเป็นศูนย์หรือติดลบจะตีความไม่ได้'),
    'liabilitiesToEquity': ('หนี้สินรวมต่อส่วนของผู้ถือหุ้น', 'หนี้สินทั้งหมดที่รายงานหารส่วนของผู้ถือหุ้น รวมภาระผูกพันที่ไม่ใช่หนี้ที่มีดอกเบี้ยด้วย จึงต่างจากรายการ D/E'),
    'currentRatio': ('อัตราส่วนเงินทุนหมุนเวียน', 'สินทรัพย์หมุนเวียนหารหนี้สินหมุนเวียน ค่าต่ำกว่า 1 อาจสะท้อนแรงกดดันด้านสภาพคล่อง แต่ค่าสูงไม่ได้หมายถึงประสิทธิภาพที่สูงเสมอ เกณฑ์นี้ไม่เหมาะกับธนาคาร'),
    'quickRatio': ('อัตราส่วนสภาพคล่องหมุนเร็ว', 'ในที่นี้คือเงินสด รายการเทียบเท่าเงินสด เงินลงทุนระยะสั้น และลูกหนี้ หารหนี้สินหมุนเวียน หากใช้ค่าจากผู้ให้ข้อมูล นิยามสินทรัพย์หมุนเร็วอาจต่างกัน ควรตรวจสอบแหล่งข้อมูล'),
    'cashRatio': ('อัตราส่วนเงินสด', 'เงินสด รายการเทียบเท่าเงินสด และเงินลงทุนระยะสั้น หารหนี้สินหมุนเวียน เป็นมุมมองสภาพคล่องที่จำกัดรายการมากกว่าอัตราส่วนเงินทุนหมุนเวียน'),
    'interestCoverage': ('ความสามารถชำระดอกเบี้ย', 'EBIT หารดอกเบี้ยจ่ายที่รายงานในงวดเดียวกัน หากดอกเบี้ยจ่ายเป็นศูนย์ จะไม่มีอัตราส่วนที่เป็นจำนวนจำกัด กรณีนี้ไม่ใช่ข้อมูลเสียและไม่ใช่คะแนนอนันต์'),
    'totalAssets': ('สินทรัพย์รวม', 'ทรัพยากรที่รับรู้ในงบฐานะการเงิน ณ วันที่แสดง ไม่ใช่มูลค่าสินทรัพย์ภายใต้การบริหารของ ETF'),
    'totalLiabilities': ('หนี้สินรวม', 'ภาระผูกพันที่รับรู้ ณ วันที่ในงบฐานะการเงิน รวมทั้งหนี้สินจากการดำเนินงานและการจัดหาเงินทุน'),
    'stockholdersEquity': ('ส่วนของผู้ถือหุ้น', 'ส่วนของทุนที่เป็นของผู้ถือหุ้นตามที่รายงาน หากติดลบควรตรวจสอบสาเหตุ และการเปรียบเทียบ ROE, P/B และ D/E ตามปกติจะไม่น่าเชื่อถือ'),
    'cash': ('เงินสดและเงินลงทุนระยะสั้น', 'เงินสด รายการเทียบเท่าเงินสด และเงินลงทุนระยะสั้นที่รายงาน ไม่ใช่กระแสเงินสดจากการดำเนินงาน และไม่ได้เป็นเงินสดส่วนเกินทั้งหมดเสมอไป'),
    'totalDebt': ('หนี้ที่มีดอกเบี้ยรวม', 'หนี้ที่มีดอกเบี้ยตามผู้ให้ข้อมูล ณ วันที่ในงบฐานะการเงิน การรวมภาระหนี้จากสัญญาเช่าอาจต่างกันระหว่างผู้ให้ข้อมูล'),
    'netDebt': ('หนี้สุทธิ', 'หนี้ที่มีดอกเบี้ยรวมหักเงินสดและเงินลงทุนระยะสั้น ณ วันเดียวกัน ค่าติดลบหมายถึงมีเงินสดสุทธิ'),
    'currentAssets': ('สินทรัพย์หมุนเวียน', 'สินทรัพย์ที่คาดว่าจะเปลี่ยนเป็นเงินสดหรือใช้ภายในรอบดำเนินงานหรือภายในหนึ่งปี'),
    'currentLiabilities': ('หนี้สินหมุนเวียน', 'ภาระผูกพันที่คาดว่าจะชำระภายในรอบดำเนินงานหรือภายในหนึ่งปี'),
    'workingCapital': ('เงินทุนหมุนเวียนสุทธิ', 'สินทรัพย์หมุนเวียนหักหนี้สินหมุนเวียน ณ วันเดียวกัน ธุรกิจค้าปลีกและบริการแบบสมาชิกบางแห่งสามารถดำเนินงานด้วยเงินทุนหมุนเวียนสุทธิติดลบได้อย่างต่อเนื่อง'),
    'operatingCashflow': ('กระแสเงินสดจากการดำเนินงาน', 'เงินสดที่ได้มาหรือใช้ไปจากการดำเนินงานในงวดที่ระบุ ควรตรวจสอบการเปลี่ยนแปลงเงินทุนหมุนเวียนและแยกผลที่เกิดประจำออกจากผลชั่วคราว'),
    'capex': ('รายจ่ายลงทุน', 'เงินสดที่จ่ายเพื่อลงทุนในสินทรัพย์ระยะยาว แสดงรายจ่ายเป็นค่าบวก หากไม่มีข้อมูลเงินสดจ่ายต้นทางจะไม่ถือว่าเป็นศูนย์'),
    'freeCashflow': ('กระแสเงินสดอิสระ', 'กระแสเงินสดอิสระที่รายงาน หรือกระแสเงินสดจากการดำเนินงานหักรายจ่ายลงทุนเมื่อข้อมูลทั้งสองตรงงวดกัน ไม่ได้เป็นเงินสดที่สามารถจ่ายให้ผู้ถือหุ้นได้ทั้งหมดโดยอัตโนมัติ'),
    'fcfMargin': ('อัตรากระแสเงินสดอิสระต่อรายได้', 'กระแสเงินสดอิสระหารรายได้ในรอบบัญชีเดียวกัน ระดับการลงทุนในสินทรัพย์ของธุรกิจมีผลต่อระดับอัตราส่วนที่เหมาะสม'),
    'cashConversion': ('การเปลี่ยนกำไรเป็นเงินสด', 'กระแสเงินสดจากการดำเนินงานหารกำไรสุทธิที่เป็นบวกในงวดเดียวกัน หากต่ำกว่า 1 อย่างต่อเนื่องควรตรวจสอบ แต่จังหวะเงินทุนหมุนเวียนอาจทำให้ผันผวนชั่วคราวได้'),
    'stockBasedCompensation': ('ค่าตอบแทนโดยใช้หุ้น', 'ค่าตอบแทนพนักงานที่ไม่ใช่เงินสดและรายงานในงบกระแสเงินสด การบวกกลับรายการนี้ในกระแสเงินสดไม่ได้ลบผลกระทบจากสัดส่วนถือหุ้นที่ลดลง'),
    'dividendYield': ('อัตราผลตอบแทนเงินปันผลย้อนหลัง', 'อัตราเงินปันผลย้อนหลังหนึ่งปีจากผู้ให้ข้อมูล แสดงเป็นร้อยละ ไม่ใช่อัตราผลตอบแทนเงินปันผลคาดการณ์หรือผลตอบแทนรวม และไม่ได้รับประกันการจ่ายในอนาคต'),
    'payoutRatio': ('อัตราการจ่ายเงินปันผลต่อกำไร', 'เงินปันผลเทียบกับกำไรตามผู้ให้ข้อมูล ค่าสูงกว่า 100% อาจไม่ยั่งยืน และตีความไม่ได้เมื่อกำไรเป็นศูนย์หรือติดลบ REIT ควรใช้ FFO/AFFO ประกอบการวิเคราะห์'),
    'dividendsPaid': ('เงินสดจ่ายปันผล', 'เงินสดที่จ่ายปันผลในงวดบัญชีที่ระบุ แสดงรายจ่ายเป็นค่าบวก ต่างจากประวัติเงินปันผลต่อหุ้นตามวันขึ้นเครื่องหมายไม่ได้สิทธิรับปันผล (XD)'),
    'buybacks': ('เงินสดซื้อหุ้นคืน', 'เงินสดรวมที่ใช้ซื้อหุ้นคืน ไม่ใช่ผลตอบแทนจากการซื้อหุ้นคืนสุทธิ เพราะการออกหุ้นใหม่และค่าตอบแทนโดยใช้หุ้นอาจหักล้างผลดังกล่าว'),
    'targetMeanPrice': ('ราคาเป้าหมายเฉลี่ยของนักวิเคราะห์', 'ราคาเป้าหมายเฉลี่ยที่ผู้ให้ข้อมูลรายงาน ประมาณการที่นำมารวมอาจจัดทำต่างวันกัน และไม่ใช่ราคาที่รับประกันว่าจะเกิดขึ้น'),
    'analystCount': ('จำนวนความเห็นของนักวิเคราะห์', 'จำนวนความเห็นนักวิเคราะห์ที่ใช้ในประมาณการรวมของผู้ให้ข้อมูล จำนวนความเห็นที่มากขึ้นไม่ได้รับประกันความแม่นยำ'),
    'forwardEps': ('กำไรต่อหุ้นคาดการณ์', 'กำไรต่อหุ้นคาดการณ์จากผู้ให้ข้อมูล เป็นประมาณการซึ่งต่างจากกำไรต่อหุ้นปรับลดทั้งปีบัญชีที่รายงานจริง'),
}

# Use established abbreviations where useful, otherwise the canonical English
# metric name. Growth periods describe the metric, not an invented acronym.
METRIC_ALIASES = {metric.key: metric.label for metric in METRICS}
METRIC_ALIASES.update({
    'marketCap': 'Market Cap', 'enterpriseValue': 'EV', 'trailingPE': 'P/E',
    'forwardPE': 'Forward P/E', 'priceToBook': 'P/B', 'priceToSales': 'P/S',
    'evRevenue': 'EV/Revenue', 'evEbitda': 'EV/EBITDA',
    'grossMargins': 'GPM', 'operatingMargins': 'OPM', 'grossProfit': 'GP',
    'revenueGrowth': 'Revenue Growth — Provider', 'earningsGrowth': 'Earnings Growth — Provider',
    'revenueGrowthFY': 'Revenue Growth — FY', 'netIncomeGrowthFY': 'Net Income Growth — FY',
    'epsGrowthFY': 'Diluted EPS Growth — FY', 'debtToEquity': 'D/E',
    'operatingCashflow': 'OCF', 'capex': 'CapEx', 'freeCashflow': 'FCF',
    'cashConversion': 'OCF / Net Income', 'dividendYield': 'Dividend Yield — Trailing',
})
STATEMENT_ALIASES = METRIC_ALIASES | {
    'interestExpense': 'Interest Expense', 'pretaxIncome': 'Pretax Income',
    'taxProvision': 'Tax Provision', 'receivables': 'Receivables', 'inventory': 'Inventory',
}


def bilingual_label(key, thai_label):
    """Combine separately stored labels once, shared by tables and exports."""
    return f'{thai_label} ({STATEMENT_ALIASES[key]})'


METRIC_TEXT = {key: (bilingual_label(key, label), definition)
               for key, (label, definition) in METRIC_TEXT.items()}

STATE_VALUES = {
    'available': 'มีข้อมูล', 'not_applicable': 'N/A — ไม่ใช้กับหลักทรัพย์ประเภทนี้',
    'not_meaningful': 'N/M — ตีความอัตราส่วนไม่ได้', 'pending': 'รอเก็บงบการเงิน',
    'missing_inputs': 'ข้อมูลสำหรับคำนวณไม่เพียงพอ', 'invalid': 'ค่าต้นทางผิดปกติ',
    'not_reported': 'ไม่มีข้อมูลรายงาน',
}
STATE_ASSESSMENTS = {
    'pending': 'รอข้อมูล', 'not_applicable': 'ไม่ใช้กับหลักทรัพย์ประเภทนี้',
    'not_meaningful': 'ตีความไม่ได้', 'invalid': 'ต้องตรวจสอบแหล่งข้อมูล',
    'missing_inputs': 'ข้อมูลสำหรับคำนวณไม่เพียงพอ', 'not_reported': 'ไม่มีข้อมูลรายงาน',
}
PERIOD_LABELS = {
    'TTM (4 reported quarters)': 'ย้อนหลัง 12 เดือน (TTM: 4 ไตรมาสที่รายงาน)',
    'FY': 'ปีบัญชี (FY)', 'FY vs prior FY': 'ปีบัญชีล่าสุดเทียบปีก่อน',
    'Balance sheet': 'งบฐานะการเงิน ณ วันที่', 'Provider period': 'รอบข้อมูลตามผู้ให้ข้อมูล',
    'Not reported': 'ไม่ระบุรอบข้อมูล',
}
SOURCE_LABELS = {
    'Yahoo Finance profile': 'ข้อมูลสรุปบริษัทจาก Yahoo Finance',
    'Yahoo Finance financial statements': 'งบการเงินจาก Yahoo Finance',
    'Financial statements': 'งบการเงิน',
}

SECTOR_LABELS = {
    'Basic Materials': 'วัสดุพื้นฐาน', 'Communication Services': 'บริการสื่อสาร',
    'Consumer Cyclical': 'สินค้าและบริการที่ขึ้นกับวัฏจักรเศรษฐกิจ',
    'Consumer Defensive': 'สินค้าอุปโภคบริโภคจำเป็น', 'Energy': 'พลังงาน',
    'Financial Services': 'บริการทางการเงิน', 'Financial': 'การเงิน',
    'Healthcare': 'สุขภาพ', 'Industrials': 'อุตสาหกรรม',
    'Real Estate': 'อสังหาริมทรัพย์', 'Technology': 'เทคโนโลยี', 'Utilities': 'สาธารณูปโภค',
}
INDUSTRY_LABELS = {
    'Advertising Agencies': 'ธุรกิจโฆษณา', 'Aerospace & Defense': 'การบินอวกาศและการป้องกันประเทศ',
    'Agricultural Inputs': 'ปัจจัยการผลิตทางการเกษตร', 'Airlines': 'สายการบิน',
    'Airports & Air Services': 'สนามบินและบริการการบิน', 'Aluminum': 'อะลูมิเนียม',
    'Apparel Manufacturing': 'การผลิตเครื่องแต่งกาย', 'Apparel Retail': 'ค้าปลีกเครื่องแต่งกาย',
    'Asset Management': 'การจัดการสินทรัพย์', 'Auto & Truck Dealerships': 'ตัวแทนจำหน่ายรถยนต์และรถบรรทุก',
    'Auto Manufacturers': 'ผู้ผลิตรถยนต์', 'Auto Parts': 'ชิ้นส่วนยานยนต์',
    'Banks - Diversified': 'ธนาคารที่ให้บริการหลากหลาย', 'Banks - Regional': 'ธนาคารระดับภูมิภาค',
    'Beverages - Brewers': 'เครื่องดื่มประเภทเบียร์', 'Beverages - Non-Alcoholic': 'เครื่องดื่มไม่มีแอลกอฮอล์',
    'Beverages - Wineries & Distilleries': 'ไวน์และสุรากลั่น', 'Biotechnology': 'เทคโนโลยีชีวภาพ',
    'Broadcasting': 'การแพร่ภาพและกระจายเสียง', 'Building Materials': 'วัสดุก่อสร้าง',
    'Building Products & Equipment': 'ผลิตภัณฑ์และอุปกรณ์อาคาร', 'Business Equipment & Supplies': 'อุปกรณ์และวัสดุสำหรับธุรกิจ',
    'Capital Markets': 'บริการตลาดทุน', 'Chemicals': 'เคมีภัณฑ์', 'Coking Coal': 'ถ่านหินสำหรับผลิตโค้ก',
    'Communication Equipment': 'อุปกรณ์สื่อสาร', 'Computer Hardware': 'ฮาร์ดแวร์คอมพิวเตอร์',
    'Confectioners': 'ขนมและผลิตภัณฑ์น้ำตาล', 'Conglomerates': 'กลุ่มธุรกิจหลากหลายประเภท',
    'Consulting Services': 'บริการที่ปรึกษา', 'Consumer Electronics': 'อุปกรณ์อิเล็กทรอนิกส์สำหรับผู้บริโภค',
    'Copper': 'ทองแดง', 'Credit Services': 'บริการสินเชื่อ', 'Department Stores': 'ห้างสรรพสินค้า',
    'Diagnostics & Research': 'การตรวจวินิจฉัยและการวิจัย', 'Discount Stores': 'ร้านค้าราคาประหยัด',
    'Drug Manufacturers - General': 'ผู้ผลิตยาทั่วไป',
    'Drug Manufacturers - Specialty & Generic': 'ผู้ผลิตยาเฉพาะทางและยาสามัญ',
    'Education & Training Services': 'บริการการศึกษาและฝึกอบรม',
    'Electrical Equipment & Parts': 'อุปกรณ์และชิ้นส่วนไฟฟ้า',
    'Electronic Components': 'ชิ้นส่วนอิเล็กทรอนิกส์',
    'Electronic Gaming & Multimedia': 'เกมอิเล็กทรอนิกส์และมัลติมีเดีย',
    'Electronics & Computer Distribution': 'จัดจำหน่ายอิเล็กทรอนิกส์และคอมพิวเตอร์',
    'Engineering & Construction': 'วิศวกรรมและก่อสร้าง', 'Entertainment': 'สื่อและความบันเทิง',
    'Farm & Heavy Construction Machinery': 'เครื่องจักรการเกษตรและก่อสร้างขนาดใหญ่',
    'Farm Products': 'ผลิตภัณฑ์การเกษตร', 'Financial Conglomerates': 'กลุ่มธุรกิจการเงินหลากหลายประเภท',
    'Financial Data & Stock Exchanges': 'ข้อมูลทางการเงินและตลาดหลักทรัพย์',
    'Food Distribution': 'การจัดจำหน่ายอาหาร', 'Footwear & Accessories': 'รองเท้าและเครื่องประดับแต่งกาย',
    'Furnishings, Fixtures & Appliances': 'เฟอร์นิเจอร์ อุปกรณ์ตกแต่ง และเครื่องใช้ภายในบ้าน',
    'Gambling': 'ธุรกิจการพนัน', 'Gold': 'ทองคำ', 'Grocery Stores': 'ร้านขายสินค้าอุปโภคบริโภค',
    'Healthcare Plans': 'แผนประกันและบริการสุขภาพ', 'Health Information Services': 'บริการข้อมูลสุขภาพ',
    'Home Improvement Retail': 'ค้าปลีกสินค้าปรับปรุงบ้าน',
    'Household & Personal Products': 'ผลิตภัณฑ์ครัวเรือนและของใช้ส่วนบุคคล',
    'Industrial Distribution': 'จัดจำหน่ายสินค้าอุตสาหกรรม',
    'Information Technology Services': 'บริการเทคโนโลยีสารสนเทศ',
    'Infrastructure Operations': 'การดำเนินงานโครงสร้างพื้นฐาน',
    'Insurance - Diversified': 'ธุรกิจประกันภัยหลากหลายประเภท', 'Insurance - Life': 'ประกันชีวิต',
    'Insurance - Property & Casualty': 'ประกันทรัพย์สินและวินาศภัย', 'Insurance - Reinsurance': 'ประกันภัยต่อ',
    'Insurance - Specialty': 'ประกันภัยเฉพาะทาง', 'Insurance Brokers': 'นายหน้าประกันภัย',
    'Integrated Freight & Logistics': 'ขนส่งสินค้าและโลจิสติกส์ครบวงจร',
    'Internet Content & Information': 'เนื้อหาและข้อมูลบนอินเทอร์เน็ต',
    'Internet Retail': 'ค้าปลีกออนไลน์', 'Leisure': 'สินค้าและบริการเพื่อการพักผ่อน',
    'Lodging': 'โรงแรมและที่พัก', 'Lumber & Wood Production': 'ไม้แปรรูปและผลิตภัณฑ์ไม้',
    'Luxury Goods': 'สินค้าหรูหรา', 'Marine Shipping': 'ขนส่งทางทะเล',
    'Medical Care Facilities': 'สถานพยาบาล', 'Medical Devices': 'เครื่องมือแพทย์',
    'Medical Distribution': 'จัดจำหน่ายผลิตภัณฑ์ทางการแพทย์',
    'Medical Instruments & Supplies': 'อุปกรณ์และวัสดุทางการแพทย์', 'Metal Fabrication': 'การแปรรูปโลหะ',
    'Mortgage Finance': 'สินเชื่อที่อยู่อาศัย', 'Oil & Gas Drilling': 'การขุดเจาะน้ำมันและก๊าซ',
    'Oil & Gas E&P': 'การสำรวจและผลิตน้ำมันและก๊าซ',
    'Oil & Gas Equipment & Services': 'อุปกรณ์และบริการน้ำมันและก๊าซ',
    'Oil & Gas Integrated': 'ธุรกิจน้ำมันและก๊าซครบวงจร', 'Oil & Gas Midstream': 'ขนส่งและจัดเก็บน้ำมันและก๊าซ',
    'Oil & Gas Refining & Marketing': 'กลั่นและจำหน่ายน้ำมันและก๊าซ',
    'Other Industrial Metals & Mining': 'โลหะอุตสาหกรรมและเหมืองแร่อื่น ๆ',
    'Other Precious Metals & Mining': 'โลหะมีค่าและเหมืองแร่อื่น ๆ',
    'Packaged Foods': 'อาหารบรรจุสำเร็จ', 'Packaging & Containers': 'บรรจุภัณฑ์และภาชนะ',
    'Paper & Paper Products': 'กระดาษและผลิตภัณฑ์กระดาษ', 'Personal Services': 'บริการส่วนบุคคล',
    'Pharmaceutical Retailers': 'ค้าปลีกยา', 'Pollution & Treatment Controls': 'ควบคุมและบำบัดมลพิษ',
    'Publishing': 'ธุรกิจสิ่งพิมพ์', 'Railroads': 'ขนส่งทางรถไฟ',
    'Real Estate - Development': 'พัฒนาอสังหาริมทรัพย์', 'Real Estate - Diversified': 'อสังหาริมทรัพย์หลากหลายประเภท',
    'Real Estate Services': 'บริการอสังหาริมทรัพย์',
    'Recreational Vehicles': 'ยานพาหนะเพื่อการพักผ่อน',
    'REIT - Diversified': 'REIT อสังหาริมทรัพย์หลากหลายประเภท', 'REIT - Healthcare Facilities': 'REIT สถานพยาบาล',
    'REIT - Hotel & Motel': 'REIT โรงแรมและที่พัก', 'REIT - Industrial': 'REIT อสังหาริมทรัพย์อุตสาหกรรม',
    'REIT - Mortgage': 'REIT สินเชื่อจำนอง', 'REIT - Office': 'REIT อาคารสำนักงาน',
    'REIT - Residential': 'REIT ที่อยู่อาศัย', 'REIT - Retail': 'REIT อสังหาริมทรัพย์ค้าปลีก',
    'REIT - Specialty': 'REIT อสังหาริมทรัพย์เฉพาะทาง', 'Rental & Leasing Services': 'บริการเช่าและลีสซิ่ง',
    'Residential Construction': 'ก่อสร้างที่อยู่อาศัย', 'Resorts & Casinos': 'รีสอร์ตและคาสิโน',
    'Restaurants': 'ร้านอาหาร', 'Scientific & Technical Instruments': 'เครื่องมือวิทยาศาสตร์และเทคนิค',
    'Security & Protection Services': 'บริการรักษาความปลอดภัย',
    'Semiconductor Equipment & Materials': 'อุปกรณ์และวัสดุผลิตเซมิคอนดักเตอร์',
    'Semiconductors': 'เซมิคอนดักเตอร์', 'Shell Companies': 'บริษัทที่ยังไม่มีธุรกิจดำเนินงานหลัก',
    'Silver': 'เงิน', 'Software - Application': 'ซอฟต์แวร์ประยุกต์',
    'Software - Infrastructure': 'ซอฟต์แวร์โครงสร้างพื้นฐาน', 'Solar': 'พลังงานแสงอาทิตย์',
    'Specialty Business Services': 'บริการธุรกิจเฉพาะทาง', 'Specialty Chemicals': 'เคมีภัณฑ์เฉพาะทาง',
    'Specialty Industrial Machinery': 'เครื่องจักรอุตสาหกรรมเฉพาะทาง', 'Specialty Retail': 'ค้าปลีกเฉพาะทาง',
    'Staffing & Employment Services': 'บริการจัดหาพนักงานและการจ้างงาน', 'Steel': 'เหล็ก',
    'Telecom Services': 'บริการโทรคมนาคม', 'Textile Manufacturing': 'การผลิตสิ่งทอ',
    'Thermal Coal': 'ถ่านหินเชื้อเพลิง', 'Tobacco': 'ยาสูบ', 'Tools & Accessories': 'เครื่องมือและอุปกรณ์ประกอบ',
    'Travel Services': 'บริการท่องเที่ยว', 'Trucking': 'ขนส่งทางรถบรรทุก', 'Uranium': 'ยูเรเนียม',
    'Utilities - Diversified': 'สาธารณูปโภคหลากหลายประเภท',
    'Utilities - Independent Power Producers': 'ผู้ผลิตไฟฟ้าอิสระ',
    'Utilities - Regulated Electric': 'กิจการไฟฟ้าภายใต้การกำกับ',
    'Utilities - Regulated Gas': 'กิจการก๊าซภายใต้การกำกับ',
    'Utilities - Regulated Water': 'กิจการน้ำภายใต้การกำกับ',
    'Utilities - Renewable': 'สาธารณูปโภคพลังงานหมุนเวียน', 'Waste Management': 'การจัดการขยะและของเสีย',
}
COUNTRY_LABELS = {
    'United States': 'สหรัฐอเมริกา', 'United Kingdom': 'สหราชอาณาจักร', 'Canada': 'แคนาดา',
    'China': 'จีน', 'Hong Kong': 'ฮ่องกง', 'Macau': 'มาเก๊า', 'Taiwan': 'ไต้หวัน', 'Japan': 'ญี่ปุ่น',
    'South Korea': 'เกาหลีใต้', 'Singapore': 'สิงคโปร์', 'Thailand': 'ไทย',
    'Malaysia': 'มาเลเซีย', 'Indonesia': 'อินโดนีเซีย', 'Vietnam': 'เวียดนาม', 'Cambodia': 'กัมพูชา',
    'Philippines': 'ฟิลิปปินส์', 'India': 'อินเดีย', 'Pakistan': 'ปากีสถาน',
    'Australia': 'ออสเตรเลีย', 'New Zealand': 'นิวซีแลนด์',
    'Germany': 'เยอรมนี', 'France': 'ฝรั่งเศส', 'Switzerland': 'สวิตเซอร์แลนด์',
    'Netherlands': 'เนเธอร์แลนด์', 'Ireland': 'ไอร์แลนด์', 'Belgium': 'เบลเยียม',
    'Luxembourg': 'ลักเซมเบิร์ก', 'Spain': 'สเปน', 'Italy': 'อิตาลี', 'Portugal': 'โปรตุเกส',
    'Denmark': 'เดนมาร์ก', 'Norway': 'นอร์เวย์', 'Sweden': 'สวีเดน', 'Finland': 'ฟินแลนด์',
    'Austria': 'ออสเตรีย', 'Greece': 'กรีซ', 'Cyprus': 'ไซปรัส', 'Malta': 'มอลตา',
    'Poland': 'โปแลนด์', 'Czech Republic': 'เช็ก', 'Hungary': 'ฮังการี', 'Russia': 'รัสเซีย',
    'Israel': 'อิสราเอล', 'Turkey': 'ตุรกี', 'Türkiye': 'ตุรกี',
    'United Arab Emirates': 'สหรัฐอาหรับเอมิเรตส์', 'Saudi Arabia': 'ซาอุดีอาระเบีย',
    'Qatar': 'กาตาร์', 'Jordan': 'จอร์แดน', 'Kazakhstan': 'คาซัคสถาน',
    'Brazil': 'บราซิล', 'Mexico': 'เม็กซิโก', 'Argentina': 'อาร์เจนตินา',
    'Chile': 'ชิลี', 'Colombia': 'โคลอมเบีย', 'Peru': 'เปรู', 'Uruguay': 'อุรุกวัย',
    'Panama': 'ปานามา', 'Costa Rica': 'คอสตาริกา', 'Puerto Rico': 'เปอร์โตริโก',
    'Bermuda': 'เบอร์มิวดา', 'Cayman Islands': 'หมู่เกาะเคย์แมน',
    'British Virgin Islands': 'หมู่เกาะบริติชเวอร์จิน', 'Marshall Islands': 'หมู่เกาะมาร์แชลล์',
    'Bahamas': 'บาฮามาส', 'Monaco': 'โมนาโก', 'Gibraltar': 'ยิบรอลตาร์',
    'Jersey': 'เจอร์ซีย์', 'Guernsey': 'เกิร์นซีย์', 'Isle of Man': 'ไอล์ออฟแมน',
    'South Africa': 'แอฟริกาใต้', 'Egypt': 'อียิปต์', 'Morocco': 'โมร็อกโก',
    'Nigeria': 'ไนจีเรีย', 'Ghana': 'กานา', 'Mauritius': 'มอริเชียส',
}


def profile_text_th(info):
    parts = []
    for key, label, catalog in (('sector', 'กลุ่มธุรกิจ', SECTOR_LABELS),
                                ('industry', 'อุตสาหกรรม', INDUSTRY_LABELS),
                                ('country', 'ประเทศ/เขตที่ตั้ง', COUNTRY_LABELS)):
        if info.get(key):
            original = str(info[key])
            translated = catalog.get(original)
            value = translated if translated else 'ตามข้อมูลต้นทาง (' + original + ')'
            parts.append(label + ': ' + value)
    return ' · '.join(parts)

TEXT = {
    DIVIDEND_YIELD_SOURCE_DISAGREEMENT: 'ผู้ให้ข้อมูลรายงานอัตราผลตอบแทนเงินปันผลย้อนหลังเป็นศูนย์ แต่ประวัติมีการจ่ายเงินสดเป็นบวกในช่วงหนึ่งปีย้อนหลังจากวันที่ข้อมูลบริษัท ยังยืนยันองค์ประกอบของเงินจ่ายและนิยามอัตราผลตอบแทนให้ตรงกันไม่ได้ จึงงดแสดงค่านี้',
    'Quote and reporting currencies differ; EV units or FX conversion are not verified': 'สกุลเงินราคาหุ้นต่างจากสกุลเงินรายงานงบ โดยยังไม่ได้ยืนยันหน่วยมูลค่ากิจการ (EV) หรือการแปลงอัตราแลกเปลี่ยน',
    'Review reported net revenue and accounting notes': 'ตรวจรายได้สุทธิและหมายเหตุประกอบงบ',
    'Negative net revenue': 'รายได้สุทธิติดลบ',
    'Negative net revenue can arise from investment losses or revenue reversals. Preserve the reported sign and inspect the filing; do not replace it with zero.': 'รายได้สุทธิติดลบอาจเกิดจากขาดทุนจากการลงทุนหรือการกลับรายการรายได้ ควรคงเครื่องหมายตามรายงานและตรวจสอบงบ ไม่แทนค่าด้วยศูนย์',
    'Industry-specific analysis': 'ใช้การวิเคราะห์เฉพาะอุตสาหกรรม',
    'Specialized comparison': 'ต้องใช้เกณฑ์เฉพาะธุรกิจ',
    'Generic operating-company bands are not applied to banks, insurers, credit businesses or REITs; use sector-specific capital and cash-flow measures.': 'ไม่ใช้ช่วงอ้างอิงของบริษัททั่วไปกับธนาคาร บริษัทประกัน ธุรกิจสินเชื่อ หรือ REIT ควรใช้ตัวชี้วัดเงินทุนและกระแสเงินสดที่เหมาะกับธุรกิจนั้น',
    'Illustrative: 0–25× / 25–40× / >40×': 'ตัวอย่างช่วงอ้างอิง: 0–25× / 25–40× / >40×',
    'Lower multiple': 'อัตราส่วนอยู่ในช่วงต่ำ', 'Elevated multiple': 'อัตราส่วนค่อนข้างสูง', 'High multiple': 'อัตราส่วนสูง',
    'Compare peers, growth and earnings quality; this band does not establish fair value.': 'เทียบกับธุรกิจใกล้เคียง การเติบโต และคุณภาพกำไร ช่วงอ้างอิงนี้ไม่ได้ระบุมูลค่ายุติธรรม',
    'Illustrative: <1× / 1–3× / >3×': 'ตัวอย่างช่วงอ้างอิง: <1× / 1–3× / >3×',
    'Below book': 'ต่ำกว่ามูลค่าทางบัญชี', '1–3× book': '1–3 เท่าของมูลค่าทางบัญชี', 'Premium to book': 'สูงกว่ามูลค่าทางบัญชีมาก',
    'A low P/B can reflect weak asset quality; high P/B is common in asset-light businesses.': 'P/B ต่ำอาจสะท้อนคุณภาพสินทรัพย์ที่อ่อนแอ ส่วน P/B สูงพบได้บ่อยในธุรกิจที่ใช้สินทรัพย์น้อย',
    'Illustrative: <8% / 8–15% / >15%': 'ตัวอย่างช่วงอ้างอิง: <8% / 8–15% / >15%',
    'Loss-making': 'ขาดทุน', 'Low return': 'ผลตอบแทนต่ำ', 'Moderate return': 'ผลตอบแทนปานกลาง',
    'High return; inspect equity base': 'ผลตอบแทนสูง ควรตรวจฐานทุน',
    'Review leverage and buybacks. A very small equity base can inflate ROE.': 'ตรวจระดับหนี้และการซื้อหุ้นคืน ฐานส่วนของผู้ถือหุ้นที่เล็กมากอาจทำให้ ROE สูงขึ้น',
    'Illustrative: <2% / 2–5% / >5%': 'ตัวอย่างช่วงอ้างอิง: <2% / 2–5% / >5%',
    'Higher return': 'ผลตอบแทนค่อนข้างสูง',
    'These are example bands, not norms for every industry; asset intensity matters.': 'เป็นช่วงตัวอย่าง ไม่ใช่ค่ามาตรฐานของทุกอุตสาหกรรม ควรพิจารณาระดับการใช้สินทรัพย์ของธุรกิจ',
    'Above company WACC; WACC not supplied': 'ควรสูงกว่า WACC ของบริษัท แต่ยังไม่มีข้อมูล WACC',
    'Negative operating return': 'ผลตอบแทนจากการดำเนินงานติดลบ', 'WACC comparison needed': 'ต้องเปรียบเทียบกับ WACC',
    'A positive ROIC alone does not establish value creation. Compare with a defensible company-specific cost of capital.': 'ROIC เป็นบวกเพียงอย่างเดียวไม่ได้ยืนยันว่าบริษัทสร้างมูลค่า ควรเทียบกับต้นทุนเงินทุนเฉพาะบริษัทที่มีข้อมูลรองรับ',
    'Illustrative: <0.5× / 0.5–1.5× / >1.5×': 'ตัวอย่างช่วงอ้างอิง: <0.5× / 0.5–1.5× / >1.5×',
    'Lower leverage': 'ภาระหนี้ค่อนข้างต่ำ', 'Moderate leverage': 'ภาระหนี้ปานกลาง', 'Higher leverage': 'ภาระหนี้ค่อนข้างสูง',
    'Debt maturity, interest coverage and cash-flow stability matter as much as the ratio.': 'กำหนดชำระหนี้ ความสามารถชำระดอกเบี้ย และความสม่ำเสมอของกระแสเงินสดสำคัญพอ ๆ กับอัตราส่วนนี้',
    'Illustrative: <1× / 1–2× / >2×': 'ตัวอย่างช่วงอ้างอิง: <1× / 1–2× / >2×',
    'Liquidity review': 'ควรตรวจสอบสภาพคล่อง', 'Positive coverage': 'สินทรัพย์หมุนเวียนครอบคลุมหนี้', 'High current assets': 'สินทรัพย์หมุนเวียนอยู่ในระดับสูง',
    'Inspect the quality and turnover of assets; a high value is not automatically more efficient.': 'ตรวจคุณภาพและการหมุนเวียนของสินทรัพย์ ค่าสูงไม่ได้แปลว่ามีประสิทธิภาพมากกว่าเสมอไป',
    'Illustrative: at least 1×': 'ตัวอย่างเกณฑ์อ้างอิง: อย่างน้อย 1×',
    'Below reference': 'ต่ำกว่าเกณฑ์อ้างอิง', 'At or above reference': 'เท่ากับหรือสูงกว่าเกณฑ์อ้างอิง',
    'Compare near-term obligations with realizable quick assets and sector working-capital patterns.': 'เปรียบเทียบภาระระยะสั้นกับสินทรัพย์หมุนเร็วที่เปลี่ยนเป็นเงินสดได้จริง และรูปแบบเงินทุนหมุนเวียนของอุตสาหกรรม',
    'EBIT below interest': 'EBIT ต่ำกว่าดอกเบี้ยจ่าย', 'Thin coverage': 'ส่วนเผื่อชำระดอกเบี้ยค่อนข้างน้อย', 'Higher coverage': 'ความสามารถชำระดอกเบี้ยค่อนข้างสูง',
    'Check debt repricing, maturities and recurring operating income; no guarantee of solvency.': 'ตรวจการปรับอัตราดอกเบี้ย กำหนดชำระหนี้ และกำไรดำเนินงานที่เกิดประจำ ค่านี้ไม่ได้รับประกันความสามารถชำระหนี้ทั้งหมด',
    'Illustrative: at least 1× over time': 'ตัวอย่างเกณฑ์อ้างอิง: อย่างน้อย 1× เมื่อพิจารณาหลายงวด',
    'Below net income': 'เงินสดดำเนินงานต่ำกว่ากำไรสุทธิ', 'At or above net income': 'เงินสดดำเนินงานเท่ากับหรือสูงกว่ากำไรสุทธิ',
    'One period can be distorted by working capital. Compare several years and review non-cash compensation.': 'งวดเดียวอาจได้รับผลจากเงินทุนหมุนเวียน ควรเทียบหลายปีและตรวจค่าตอบแทนที่ไม่ใช่เงินสด',
    'Illustrative: 0–60% / 60–100% / >100%': 'ตัวอย่างช่วงอ้างอิง: 0–60% / 60–100% / >100%',
    'More earnings retained': 'เก็บกำไรไว้ในกิจการมากกว่า', 'High payout': 'จ่ายปันผลในสัดส่วนสูง', 'Above reported earnings': 'จ่ายปันผลเกินกำไรที่รายงาน',
    'Review cash coverage, debt and the dividend policy. A zero payout can be a deliberate reinvestment choice.': 'ตรวจเงินสดรองรับการจ่าย หนี้ และนโยบายปันผล การไม่จ่ายปันผลอาจเป็นการเลือกนำเงินกลับไปลงทุน',
    'Positive growth; compare prior periods and peers': 'เติบโตเป็นบวก โดยเทียบกับอดีตและธุรกิจใกล้เคียง',
    'Contracting': 'หดตัว', 'Flat': 'ไม่เปลี่ยนแปลง', 'Growing': 'เติบโต',
    'Check base effects, acquisitions, currency effects and whether the accounting periods are comparable.': 'ตรวจผลจากฐานปีก่อน การซื้อกิจการ อัตราแลกเปลี่ยน และความเทียบเคียงกันของรอบบัญชี',
    'Positive and sustainable; compare history and peers': 'เป็นบวกและยั่งยืน โดยเทียบกับอดีตและธุรกิจใกล้เคียง',
    'Negative': 'ติดลบ', 'Break-even': 'เท่ากับศูนย์', 'Positive': 'เป็นบวก',
    'The sign alone is not a company-quality verdict; inspect recurring performance, scale and business model.': 'เครื่องหมายบวกหรือลบเพียงอย่างเดียวไม่ได้ตัดสินคุณภาพบริษัท ควรตรวจผลการดำเนินงานที่เกิดประจำ ขนาด และรูปแบบธุรกิจ',
    'Positive equity; inspect capital structure': 'ส่วนของผู้ถือหุ้นเป็นบวก พร้อมตรวจโครงสร้างเงินทุน',
    'Negative equity': 'ส่วนของผู้ถือหุ้นติดลบ', 'Zero equity': 'ส่วนของผู้ถือหุ้นเป็นศูนย์', 'Positive equity': 'ส่วนของผู้ถือหุ้นเป็นบวก',
    'Negative equity needs investigation; ordinary equity-denominator ratios are not meaningfully comparable.': 'ควรตรวจสอบสาเหตุของส่วนของผู้ถือหุ้นติดลบ อัตราส่วนที่ใช้ส่วนของผู้ถือหุ้นเป็นตัวหารจะเปรียบเทียบตามปกติไม่ได้',
    'Compare with recurring cash generation': 'เทียบกับความสามารถสร้างเงินสดอย่างต่อเนื่อง',
    'Net cash': 'มีเงินสดสุทธิ', 'No net debt': 'หนี้สุทธิเป็นศูนย์', 'Net debt': 'มีหนี้สุทธิ',
    'Net cash does not remove operating risk; restricted cash and debt maturities require separate review.': 'เงินสดสุทธิไม่ได้ลบความเสี่ยงในการดำเนินงาน ควรตรวจเงินสดที่มีข้อจำกัดการใช้และกำหนดชำระหนี้แยกต่างหาก',
    'Business-model-specific': 'ขึ้นอยู่กับรูปแบบธุรกิจ',
    'Negative working capital': 'เงินทุนหมุนเวียนสุทธิติดลบ', 'Non-negative working capital': 'เงินทุนหมุนเวียนสุทธิไม่ติดลบ',
    'Evaluate the operating cycle and liquidity; negative working capital can be normal for some businesses.': 'ประเมินรอบดำเนินงานและสภาพคล่อง เงินทุนหมุนเวียนสุทธิติดลบอาจเป็นลักษณะปกติของธุรกิจบางประเภท',
    'Sustainable payouts; no universal target': 'เน้นการจ่ายที่ยั่งยืน ไม่มีค่าเป้าหมายเดียวสำหรับทุกบริษัท',
    'Income context': 'ใช้ประกอบการพิจารณารายได้เงินปันผล',
    'A high yield can reflect a falling price or a distribution at risk; it is not a higher total-return forecast.': 'อัตราปันผลสูงอาจเกิดจากราคาหุ้นลดลงหรือการจ่ายปันผลที่มีความเสี่ยง ไม่ได้คาดการณ์ว่าผลตอบแทนรวมจะสูงกว่า',
    'Same-industry and historical comparison': 'เทียบกับอดีตและบริษัทในอุตสาหกรรมเดียวกัน',
    'Context only': 'ใช้ประกอบการวิเคราะห์',
    'No universal good/bad threshold applies to this amount or multiple.': 'ไม่มีเกณฑ์ดีหรือไม่ดีเพียงค่าเดียวที่ใช้ได้กับจำนวนเงินหรืออัตราส่วนนี้ในทุกบริษัท',
    'Corporate financial statements do not apply to this ETF / ETP.': 'งบการเงินบริษัทไม่ใช้กับ ETF / ETP นี้',
    'Unexpected negative source amount': 'จำนวนเงินต้นทางติดลบผิดจากลักษณะของรายการ',
    'Non-positive valuation denominator or multiple': 'ตัวหารหรืออัตราส่วนมูลค่าเป็นศูนย์หรือติดลบ',
    'Reported EBITDA is zero or negative': 'EBITDA ที่รายงานเป็นศูนย์หรือติดลบ',
    'Negative multiple without a verified positive EBITDA denominator': 'อัตราส่วนติดลบโดยไม่มีข้อมูลยืนยันว่า EBITDA ที่ใช้เป็นตัวหารเป็นบวก',
    'Negative equity-based debt multiple': 'อัตราส่วนหนี้ต่อส่วนของผู้ถือหุ้นติดลบ',
    'Unexpected negative liquidity ratio': 'อัตราส่วนสภาพคล่องติดลบผิดปกติ',
    'A count must be a whole number': 'ข้อมูลจำนวนต้องเป็นจำนวนเต็ม',
    'Trailing revenue is zero or negative; a sales multiple is not meaningful': 'รายได้ย้อนหลังเป็นศูนย์หรือติดลบ จึงตีความอัตราส่วนต่อยอดขายไม่ได้',
    'Non-positive reported revenue base; inspect statement periods before interpreting margins': 'ฐานรายได้ที่รายงานเป็นศูนย์หรือติดลบ ควรตรวจงวดบัญชีก่อนตีความอัตรากำไร',
    'Reported equity or book value is non-positive': 'ส่วนของผู้ถือหุ้นหรือมูลค่าทางบัญชีที่รายงานเป็นศูนย์หรือติดลบ',
    'Non-positive earnings or negative payout ratio': 'กำไรเป็นศูนย์หรือติดลบ หรืออัตราการจ่ายปันผลติดลบ',
    'Denominator is zero or negative': 'ตัวหารเป็นศูนย์หรือติดลบ',
    'Unexpected positive cash-outflow sign': 'รายการเงินสดจ่ายต้นทางมีเครื่องหมายบวกผิดปกติ',
    'Opening or closing capital is non-positive': 'ทุนต้นงวดหรือปลายงวดเป็นศูนย์หรือติดลบ',
    'Non-positive invested capital or tax rate outside 0–100%; no assumed tax rate used': 'เงินลงทุนเป็นศูนย์หรือติดลบ หรืออัตราภาษีอยู่นอกช่วง 0–100% โดยไม่ได้ใช้อัตราภาษีสมมติ',
    'Prior year is zero or a loss': 'ฐานปีก่อนเป็นศูนย์หรือขาดทุน',
}

FORMULAS = {
    'Provider debtToEquity percentage / 100': 'ค่า D/E ที่ผู้ให้ข้อมูลรายงานเป็นร้อยละ ÷ 100',
    'Sum of 4 consecutive reported quarters': 'ผลรวมของ 4 ไตรมาสที่รายงานต่อเนื่องกัน',
    'Interest-bearing total debt / shareholders equity': 'หนี้ที่มีดอกเบี้ยรวม ÷ ส่วนของผู้ถือหุ้น',
    'Total liabilities / shareholders equity': 'หนี้สินรวม ÷ ส่วนของผู้ถือหุ้น',
    'Current assets / current liabilities': 'สินทรัพย์หมุนเวียน ÷ หนี้สินหมุนเวียน',
    'Cash, equivalents and short-term investments / current liabilities': '(เงินสด + รายการเทียบเท่าเงินสด + เงินลงทุนระยะสั้น) ÷ หนี้สินหมุนเวียน',
    '(Cash, equivalents, short-term investments + receivables) / current liabilities': '(เงินสด + รายการเทียบเท่าเงินสด + เงินลงทุนระยะสั้น + ลูกหนี้) ÷ หนี้สินหมุนเวียน',
    'Total debt - cash and short-term investments': 'หนี้ที่มีดอกเบี้ยรวม − เงินสดและเงินลงทุนระยะสั้น',
    'Current assets - current liabilities': 'สินทรัพย์หมุนเวียน − หนี้สินหมุนเวียน',
    'EBIT / reported interest expense': 'EBIT ÷ ดอกเบี้ยจ่ายที่รายงาน',
    'Operating cash flow / net income': 'กระแสเงินสดจากการดำเนินงาน ÷ กำไรสุทธิ',
    'Negative reported cash outflow displayed as spending': 'แสดงเงินสดจ่ายที่ต้นทางบันทึกเป็นค่าลบ ให้เป็นยอดรายจ่ายค่าบวก',
    'Operating cash flow - capital expenditure spending': 'กระแสเงินสดจากการดำเนินงาน − รายจ่ายลงทุน',
    'Free cash flow / revenue': 'กระแสเงินสดอิสระ ÷ รายได้',
    'Net income / average opening and closing stockholdersEquity': 'กำไรสุทธิ ÷ ส่วนของผู้ถือหุ้นเฉลี่ยต้นงวดและปลายงวด',
    'Net income / average opening and closing totalAssets': 'กำไรสุทธิ ÷ สินทรัพย์รวมเฉลี่ยต้นงวดและปลายงวด',
    'Operating income × (1 - tax provision / pretax income) / average (equity + debt - cash)': 'กำไรจากการดำเนินงาน × (1 − ค่าใช้จ่ายภาษี ÷ กำไรก่อนภาษี) ÷ ค่าเฉลี่ย (ส่วนของผู้ถือหุ้น + หนี้ที่มีดอกเบี้ย − เงินสด)',
}
for _key in ('grossProfit', 'operatingIncome', 'netIncome', 'freeCashflow'):
    FORMULAS[f'{_key} / revenue'] = METRIC_TEXT[_key][0] + ' ÷ รายได้'
for _key in ('revenue', 'netIncome', 'dilutedEPS'):
    FORMULAS[f'{_key} / prior fiscal-year {_key} - 1'] = METRIC_TEXT[_key][0] + 'ปีล่าสุด ÷ ' + METRIC_TEXT[_key][0] + 'ปีก่อน − 1'

CSV_HEADERS = {
    'Group': 'หมวด', 'Metric': 'ตัวชี้วัด', 'Current Value': 'ค่าปัจจุบัน',
    'Reference / Benchmark': 'เกณฑ์อ้างอิง', 'Assessment': 'การประเมิน',
    'Interpretation': 'การตีความ', 'Period': 'รอบข้อมูล',
}


def format_value_th(metric, item, info):
    """Only presentation changes: preserve amounts, scaling, signs and currencies."""
    state, value = item['state'], item.get('value')
    if state != 'available' or value is None:
        return STATE_VALUES.get(state, STATE_VALUES['not_reported'])
    if metric.unit == '%':
        return f'{value*100:,.2f}%'
    if metric.unit == 'x':
        return f'{value:,.2f}×'
    if metric.unit == 'count':
        return f'{value:,.0f}'
    quote_unit = metric.unit in ('quote_money', 'quote_per_share') or (metric.unit == 'per_share' and item.get('source') == 'Yahoo Finance profile')
    currency = item.get('currency') or (info.get('currency') if quote_unit else info.get('financialCurrency')) or 'ไม่ระบุสกุลเงิน'
    if currency == 'Currency not reported':
        currency = 'ไม่ระบุสกุลเงิน'
    if metric.unit in ('per_share', 'quote_per_share'):
        return f'{value:,.2f} {currency}/หุ้น'
    for scale, label in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M')):
        if abs(value) >= scale:
            return f'{value/scale:,.2f}{label} {currency}'
    return f'{value:,.2f} {currency}'


def build_rows_th(ticker, info, bundle=None, *, is_etf=False):
    values = metric_observations(ticker, info, bundle, is_etf=is_etf)
    rows = []
    for metric in METRICS:
        item = values[metric.key]
        value, state = item.get('value'), item['state']
        if state == 'available' and value is not None:
            benchmark, assessment, meaning = evaluate(metric, value, info)
            benchmark, display_assessment, meaning = (TEXT.get(s, s) for s in (benchmark, assessment, meaning))
        else:
            benchmark = 'ต้องมีข้อมูลที่ใช้ได้และถูกต้องก่อนประเมิน'
            assessment = ''
            display_assessment = STATE_ASSESSMENTS.get(state, STATE_ASSESSMENTS['not_reported'])
            reason = item.get('reason')
            meaning = TEXT.get(reason, reason) if reason else 'ข้อมูลที่ขาดไม่ได้มีค่าเป็นศูนย์ และไม่ได้เป็นคะแนนว่าบริษัทอ่อนแอ'
        basis = item.get('basis') or 'Provider period'
        period = PERIOD_LABELS.get(basis, basis)
        if item.get('end'):
            period += ' · ' + item['end']
        label, tooltip = METRIC_TEXT[metric.key]
        if item.get('reason') == DIVIDEND_YIELD_SOURCE_DISAGREEMENT:
            tooltip += '\nการตรวจสอบแหล่งข้อมูล: ' + TEXT[item['reason']]
        formula = item.get('formula')
        if formula:
            tooltip += '\nวิธีคำนวณ: ' + FORMULAS.get(formula, formula)
        source = item['source']
        tooltip += '\nแหล่งข้อมูล: ' + SOURCE_LABELS.get(source, source) + '\nรอบข้อมูล: ' + period
        if value is not None:
            tooltip += f'\nค่าก่อนปัดเศษ: {value:.12g}' + (' (สัดส่วนก่อนคูณ 100 เพื่อแสดงเป็นร้อยละ)' if metric.unit == '%' else '')
        rows.append({'Group': metric.group, 'Metric': label, 'Current Value': format_value_th(metric, item, info),
                     'Reference / Benchmark': benchmark, 'Assessment': display_assessment,
                     'Interpretation': meaning, 'Period': period, '_key': metric.key,
                     '_state': state, '_value': value, '_help': tooltip, '_assessment': assessment})
    return rows


def export_rows_th(rows):
    export = []
    for row in rows:
        translated = {label: GROUP_LABELS[row[key]] if key == 'Group' else row[key]
                      for key, label in CSV_HEADERS.items()}
        translated['คำอธิบายและวิธีคำนวณ'] = row['_help']
        translated['สถานะข้อมูล'] = STATE_VALUES.get(row['_state'], STATE_VALUES['not_reported'])
        export.append(translated)
    return export


LEGACY_360_LABELS = {
    'Forward P/E': METRIC_TEXT['forwardPE'][0],
    'Trailing P/E': METRIC_TEXT['trailingPE'][0],
    'Target Price': METRIC_TEXT['targetMeanPrice'][0],
    'Dividend Yield': 'อัตราผลตอบแทนเงินปันผล (Dividend Yield)',
    'Portfolio P/E': 'P/E ของหลักทรัพย์ในกองทุน',
    'Portfolio Trailing P/E': 'P/E ย้อนหลังของหลักทรัพย์ในกองทุน',
    'Portfolio Forward P/E': 'P/E คาดการณ์ของหลักทรัพย์ในกองทุน',
    'Beta (3Y, provider)': 'เบตา 3 ปีจากผู้ให้ข้อมูล',
}
LEGACY_360_TEXT = {
    DIVIDEND_YIELD_SOURCE_DISAGREEMENT: TEXT[DIVIDEND_YIELD_SOURCE_DISAGREEMENT],
    'N/A — Not applicable': STATE_VALUES['not_applicable'],
    'N/M — Non-positive earnings': 'N/M — กำไรเป็นศูนย์หรือติดลบ',
    '— (invalid source value)': '— (ค่าต้นทางผิดปกติ)',
    'Not reported': STATE_VALUES['not_reported'], 'Awaiting data': 'รอข้อมูล',
    'Gold/bond/currency exposure has no underlying corporate earnings P/E.': 'การลงทุนในทองคำ ตราสารหนี้ หรือสกุลเงินไม่มี P/E จากกำไรบริษัทที่นำมาใช้กับกองทุนได้',
    'Corporate analyst target price does not apply to this fund; compare NAV, strategy, costs and risk.': 'ราคาเป้าหมายนักวิเคราะห์สำหรับบริษัทไม่ใช้กับกองทุนนี้ ควรเทียบมูลค่าสินทรัพย์สุทธิ (NAV) กลยุทธ์ ค่าใช้จ่าย และความเสี่ยง',
    'P/E is not meaningful with non-positive earnings; this is not a missing-data failure.': 'ตีความ P/E ไม่ได้เมื่อกำไรเป็นศูนย์หรือติดลบ กรณีนี้ไม่ใช่ความผิดพลาดจากข้อมูลที่ขาดหาย',
    'Source value failed validation; excluded from this displayed metric.': 'ค่าต้นทางไม่ผ่านการตรวจสอบ จึงไม่นำมาแสดงเป็นค่าที่ใช้ได้ของตัวชี้วัดนี้',
    'Holdings-level ratio reported by the provider, not earnings per ETF unit; methodology may differ between providers.': 'อัตราส่วนของหลักทรัพย์ที่กองทุนถือครองตามผู้ให้ข้อมูล ไม่ใช่กำไรต่อหน่วย ETF วิธีคำนวณอาจต่างกันระหว่างผู้ให้ข้อมูล',
    'Provider three-year beta; not a missing company beta or a prediction.': 'ค่าเบตา 3 ปีจากผู้ให้ข้อมูล ไม่ใช่กรณีข้อมูลเบตาของบริษัทขาดหายและไม่ใช่การคาดการณ์',
}


def localize_360_frame(frame):
    """Translate the legacy financial display after asset applicability is applied.

    Keep this outside asset_semantics: canonical states and numerical scoring
    callers still receive their original contracts. No numeric value is changed.
    """
    result = frame.copy(deep=True)
    if 'ปัจจัย' not in result:
        return result
    for label, translated in LEGACY_360_LABELS.items():
        mask = result['ปัจจัย'].eq(label)
        if not mask.any():
            continue
        result.loc[mask, 'ปัจจัย'] = translated
        for column in ('ค่าล่าสุด', 'การแปลผล'):
            if column in result:
                result.loc[mask, column] = result.loc[mask, column].map(lambda value: LEGACY_360_TEXT.get(value, value))
    return result
