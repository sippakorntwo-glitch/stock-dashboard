"""Thai column/row tooltips; presentation only, never a change to scoring.
Background: Fidelity's Technical Indicator Guide and the existing formulas in
analytics.py and dashboard_core.py. HTML values are always escaped.
"""
from __future__ import annotations
from html import escape
from collections.abc import Mapping
import pandas as pd
import streamlit as st

_DEFINITIONS = [
('Ticker','สัญลักษณ์ซื้อขาย เช่น AAPL หรือ SPY คลิกแถวเพื่อเลือกหุ้นสำหรับรายละเอียดด้านล่าง'),
('Security_Name','ชื่อบริษัทหรือกองทุนจากทะเบียนรายชื่อ ไม่ใช่คำแนะนำลงทุน'),
('Industry|industry','หุ้น: อุตสาหกรรม; ETF: หมวดกองทุน อัปเดตแยกจากราคา ช่องว่างคือยังไม่มีข้อมูล'),
('Asset_Type','Common Stock คือหุ้นสามัญ; ETF คือกองทุนซื้อขายในตลาดซึ่งอาจถือหลายสินทรัพย์'),
('Status|Trend / Screener','การสแกนใหม่ PASS เมื่อราคาปิด > EMA20 > EMA50; FAIL เมื่อไม่ผ่าน CSV เก่าอาจใช้เกณฑ์เดิม ไม่ใช่คะแนนซื้อ 100 จุด'),
('Close','ราคาปิดรายวันปรับแล้วหรือราคาจาก CSV ในสกุลสินทรัพย์ ดูวันที่ราคาและแหล่งข้อมูล ไม่ใช่ราคาสตรีมสด'),
('Return_1D','ผลตอบแทนของราคาปิดปรับแล้ว 2 แท่งรายวัน: (ราคาล่าสุด / ราคาก่อนหน้า − 1) × 100 ไม่ใช่การเปลี่ยนแปลงระหว่างวัน'),
('Return_1M','ผลตอบแทนสะสม 1 เดือนจากราคาปรับแล้ว ไม่ใช่ CAGR ว่างเมื่อประวัติไม่ครบ'),
('Return_3M|ผลตอบแทน 3 เดือน','ผลตอบแทนสะสม 3 เดือน: (ราคาปรับแล้วล่าสุด / ราคาเริ่มช่วง − 1) × 100 ไม่ใช่ผลตอบแทนต่อปี'),
('Return_6M','ผลตอบแทนสะสม 6 เดือนจากราคาปรับแล้ว ไม่ใช่ CAGR ต้องมีข้อมูลครอบคลุมช่วง'),
('Historical_Return','ผลตอบแทนสะสม 1 ปีจากราคาปรับแล้ว ใช้วันซื้อขายแรกตั้งแต่วันเริ่มช่วง ว่างเมื่อประวัติไม่ครบ ไม่ใช่ CAGR'),
('Return_2Y','ผลตอบแทนสะสม 2 ปีจากราคาปรับแล้ว ไม่ใช่ผลตอบแทนเฉลี่ยต่อปี ว่างเมื่อประวัติไม่ครบ'),
('Return_3Y','ผลตอบแทนสะสม 3 ปีจากราคาปรับแล้ว ไม่ใช่ผลตอบแทนเฉลี่ยต่อปี ว่างเมื่อประวัติไม่ครบ'),
('RSI_14|RSI 14|RSI (14)','RSI แบบ Wilder 14 แท่ง วัดสมดุลการขึ้นและลง ช่วง 0–100 สูงกว่า 70/ต่ำกว่า 30 เป็นเขตซื้อมาก/ขายมาก ไม่รับประกันการกลับตัว'),
('EMA20|EMA 20 / EMA 50','EMA20 และ EMA50 เป็นค่าเฉลี่ยราคาปิดที่ให้น้ำหนักกับข้อมูลใหม่ ระยะ 20 และ 50 แท่ง ในตารางวิเคราะห์ใช้รายวัน'),
('EMA50','ค่าเฉลี่ยราคาปิดแบบเอ็กซ์โพเนนเชียล 50 แท่ง ในตารางใช้รายวัน ในกราฟใช้ขนาดแท่งที่แสดง'),
('SMA200|SMA 200','ค่าเฉลี่ยธรรมดาของราคาปิด 200 แท่ง แต่ละแท่งน้ำหนักเท่ากัน ต้องมีอย่างน้อย 200 แท่ง'),
('MACD|MACD > Signal|MACD / Signal','MACD = EMA12 − EMA26 ของราคาปิด; Signal = EMA9 ของ MACD หน่วยเดียวกับราคา ใช้เทียบโมเมนตัม ไม่ใช่สัญญาณซื้อโดยลำพัง'),
('MACD_Signal','เส้น Signal = EMA9 ของ MACD ไม่ใช่ค่าเฉลี่ยราคาปิดโดยตรง'),
('Vol_Ratio|Volume Ratio','Volume ของแท่งรายวันล่าสุด / ค่าเฉลี่ย Volume 20 แท่งก่อนหน้า เช่น 1.5 เท่า = มากกว่าค่าเฉลี่ย 50%'),
('ATR|ATR (14)','ATR14 คือค่าเฉลี่ย True Range 14 แท่ง รวมช่วง High−Low และช่องว่างจาก Close ก่อนหน้า หน่วยราคา วัดความผันผวน ไม่บอกทิศทาง'),
('ATR_Pct|ATR / ราคา','ATR14 / ราคาปิด × 100 คือขนาดความผันผวนเทียบราคา ไม่ใช่ความน่าจะเป็นขาดทุน'),
('Volatility_20D','ส่วนเบี่ยงเบนมาตรฐานตัวอย่างของผลตอบแทน 20 จุดรายวัน × √252 × 100 เป็นค่าปรับรายปี ต้องมีอย่างน้อย 21 แท่งราคา'),
('Dollar_Volume_20D','ค่าเฉลี่ย 20 แท่งของราคาปรับแล้ว × Volume ในสกุลสินทรัพย์ ใช้ประมาณสภาพคล่อง ไม่ใช่มูลค่าซื้อขายจริงที่ตลาดรายงาน'),
('Drawdown_52W','(ราคาล่าสุด / ราคาปิดสูงสุดใน 252 แท่งล่าสุด − 1) × 100 ต้องมีอย่างน้อย 252 แท่ง'),
('Suggested_Stop|Suggested Stop','จุดหยุดขาดทุนที่แหล่ง Watchlist เสนอ ตรวจสูตรและวันอ้างอิง ไม่รับประกันว่าจะขายได้ที่ราคานี้'),
('Price_AsOf','วันที่ของแท่งราคาที่ใช้คำนวณ ไม่ใช่วันที่เปิดเว็บหรือเวลาตรวจข้อมูล'),
('Data_Time','เวลาที่ดึงข้อมูลสำเร็จ ไม่ใช่เวลาที่เกิดการซื้อขาย'),
('Data_Status','สถานะการโหลดข้อมูล การโหลดใหม่ล้มเหลวอาจยังแสดงราคาเก่าที่เคยสำเร็จ'),
('Data_Source|แหล่งข้อมูล|ข้อมูลอ้างอิง','ที่มาและช่วงเวลาของข้อมูล เช่น CSV หรือ Yahoo Finance แต่ละชุดอาจมีความสดไม่เท่ากัน'),
('หมวด','กลุ่มของปัจจัย เช่น แนวโน้ม โมเมนตัม พื้นฐาน หรือความเสี่ยง'),
('เกณฑ์','กติกาที่ระบบใช้ให้คะแนน ชี้ที่ชื่อแถวเพื่อดูนิยาม คะแนนไม่ใช่ความน่าจะเป็นกำไร'),
('ค่าปัจจุบัน|ค่าล่าสุด','ค่าที่ใช้ประเมินจากชุดข้อมูลล่าสุดที่โหลดสำเร็จ ไม่รับรองว่าเป็นข้อมูลขณะนี้'),
('ช่วง / คะแนน','ช่วงค่ากับคะแนนที่โมเดลกำหนดไว้ล่วงหน้า ไม่ใช่เกณฑ์สากลสำหรับหุ้นทุกธุรกิจ'),
('ได้','คะแนนที่เกณฑ์นี้ได้รับ ว่างคือประเมินไม่ได้ ไม่ได้ถือว่าผ่าน'),
('เต็ม','น้ำหนักสูงสุดของเกณฑ์นี้ ผลรวมทุกเกณฑ์เต็ม 100 คะแนน'),
('ผล','เต็ม/บางส่วน/ไม่ผ่าน/ไม่มีข้อมูล เป็นผลเทียบกติกาในตาราง ไม่ใช่คำสั่งซื้อขาย'),
('ช่วงคะแนน','ช่วงคะแนนรวมของโมเดล แม้ได้ 80–100 ยังต้องผ่านเงื่อนไขราคา ความเสี่ยง และอายุข้อมูล'),
('ความหมาย|การแปลผล','การอ่านค่าตามกติกาในโปรแกรม ไม่ใช่ผลทดสอบย้อนหลังหรือการรับรองกำไร'),
('ปัจจัย|มิติ','ชื่อตัวชี้วัดหรือข้อมูลพื้นฐาน ชี้ที่ชื่อแถวเพื่อดูความหมาย สูตร และข้อจำกัด'),
('ค่า','ค่าที่ผู้ให้ข้อมูลส่งกลับมา หน่วยและช่วงบัญชีขึ้นกับฟิลด์ ว่างคือยังไม่มีข้อมูล ไม่ใช่ศูนย์'),
('ฟิลด์ต้นทาง','ชื่อฟิลด์ Yahoo/yfinance สำหรับตรวจที่มาของค่าบนหน้านี้'),
('observations','จำนวนรายการที่มีข้อมูลเพียงพอในกลุ่ม/ตัวอย่าง ไม่ใช่จำนวนรายชื่อทั้งหมดเสมอ'),
('median_return_3m','มัธยฐานผลตอบแทน 3 เดือนของรายการที่ผ่านตัวกรองและมีข้อมูลในกลุ่ม ไม่ใช่ผลตอบแทนดัชนีหรือพอร์ต'),
('Return (%)','ผลตอบแทนสะสมในวันที่ร่วมกัน: (ราคาปลายช่วง / ราคาต้นช่วง − 1) × 100'),
('Volatility (%)','ส่วนเบี่ยงเบนมาตรฐานผลตอบแทนรายวันในช่วงเปรียบเทียบ × √252 × 100 ไม่ใช่ขีดจำกัดความเสียหาย'),
('Max drawdown (%)','การลดลงสูงสุดจากยอดสะสมภายในช่วงตัวอย่าง ค่าติดลบหรือศูนย์ อนาคตอาจลดลงมากกว่าอดีต'),
('Beta vs SPY','Covariance(ผลตอบแทนหุ้น, SPY) / Variance(SPY) ใช้อย่างน้อย 60 จุดในวันที่ร่วมกัน ไม่ใช่ Beta ที่ Yahoo รายงาน'),
('วันขึ้น XD / Ex-dividend|Ex_Date','วันเริ่มซื้อขายโดยผู้ซื้อใหม่ไม่ได้สิทธิปันผลรอบนั้น ไม่ใช่วันจ่ายเงินเข้าบัญชี'),
('Dividend_Per_Share','จำนวนเงินปันผลต่อหุ้น/หน่วย อาจปรับตามการแตกหุ้น ไม่ได้แยกภาษีหรือคืนทุนของ ETF'),
('ปี','ปีปฏิทินของวัน Ex-dividend ปีปัจจุบันเป็นยอดตั้งแต่ต้นปี ไม่ใช่ประมาณการเต็มปี'),
('รวมต่อหน่วย','ผลรวมปันผลต่อหน่วยในช่วงที่เลือก ไม่หักภาษีหรือค่าธรรมเนียม'),
('จำนวนครั้ง','จำนวนรายการปันผลที่พบในช่วง ไม่ใช่ความถี่ในอนาคตที่รับประกัน'),
('ช่วงข้อมูล','แยกยอดสะสมปีนี้ (YTD) ออกจากข้อมูลในปีและช่วงที่เลือก'),
('ข้อมูล','ชื่อค่าตรวจสุขภาพระบบ ชี้ที่ชื่อแถวเพื่อดูความหมาย'),
('จำนวน','จำนวนรายการใน snapshot ขณะเผยแพร่ ไม่รับประกันว่าทุกรายการสดหรือครบทุกฟิลด์'),
('universe|total','จำนวนรายชื่อในทะเบียน/ตาราง ไม่ใช่จำนวนที่มีข้อมูลครบทุกชนิด'),
('prices|priced','จำนวนรายการที่มีราคาที่ใช้ได้ อาจรวมราคาเก่า ต้องดูวันที่ประกอบ'),
('checked_today','จำนวนสรุปที่ผ่านเกณฑ์ตรวจความเป็นปัจจุบันของระบบ ไม่ใช่จำนวนราคาซื้อขายวันนี้หรือราคาเรียลไทม์'),
('info','จำนวนรายการที่มีข้อมูลพื้นฐานบันทึกไว้ ไม่รับรองว่าทุกฟิลด์ครบ'),
('dividends','จำนวนรายการที่ดึงประวัติปันผลสำเร็จ อาจรวมประวัติว่างของหุ้นที่ไม่จ่ายปันผล'),
('return_1y','จำนวนรายการที่คำนวณผลตอบแทน 1 ปีได้'),
('return_2y','จำนวนรายการที่คำนวณผลตอบแทน 2 ปีได้'),
('return_3y','จำนวนรายการที่คำนวณผลตอบแทน 3 ปีได้'),
('recent','จำนวนราคาที่ระบุวันและอายุ 0–4 วันปฏิทิน ไม่ใช่วันทำการตลาด วันหยุดยาวอาจเกินเกณฑ์'),
('unknown_time','มีราคาที่ใช้ได้ แต่ไม่ระบุวันที่ จึงยืนยันความสดไม่ได้'),
('old_or_future','ราคามีวันที่ แต่เก่ากว่าเกณฑ์หรือเป็นวันในอนาคต ต้องตรวจแหล่งข้อมูล'),
('ราคา > EMA20 > EMA50','ราคาปิดสูงกว่า EMA20 และ EMA20 สูงกว่า EMA50 เป็นการเรียงตัวขาขึ้นตามกติกา ใช้แท่งรายวัน ไม่รับประกันแนวโน้มต่อเนื่อง'),
('ราคา > SMA200','ราคาปิดเหนือค่าเฉลี่ยธรรมดา 200 แท่งรายวัน ใช้ประกอบการดูแนวโน้มระยะยาว'),
('Upside ราคาเป้าหมาย','(ราคาเป้าหมายเฉลี่ยนักวิเคราะห์ / ราคาอ้างอิง − 1) × 100 เป็นประมาณการ ไม่ใช่ผลตอบแทนที่จะได้แน่นอน'),
('ผลตอบแทน 3 เดือนเทียบ SPY','ผลตอบแทน 3 เดือนลบผลตอบแทน SPY ในวันที่ร่วมกัน หน่วยจุดเปอร์เซ็นต์ ไม่ใช่อัตราส่วน'),
('forwardPE|Forward P/E','ราคาหุ้นเทียบกำไรต่อหุ้นคาดการณ์ หน่วยเท่า ควรเทียบธุรกิจคล้ายกัน กำไรประมาณการอาจผิด และค่าติดลบอาจตีความไม่ได้'),
('trailingPE|Trailing P/E','ราคาหุ้นเทียบกำไรต่อหุ้นย้อนหลัง หน่วยเท่า ไม่รับประกันกำไรในอนาคต'),
('priceToBook|Price / Book','มูลค่าหุ้นเทียบมูลค่าทางบัญชี หน่วยเท่า ความเหมาะสมต่างกันตามธุรกิจ'),
('enterpriseToEbitda|EV / EBITDA','Enterprise Value / EBITDA หน่วยเท่า เทียบมูลค่ากิจการก่อนดอกเบี้ย ภาษี และค่าเสื่อม ไม่ใช่กระแสเงินสดอิสระ'),
('marketCap|Market cap','มูลค่าตลาดของหุ้นทั้งหมด โดยทั่วไปคือราคาคูณจำนวนหุ้น ไม่ใช่มูลค่ากิจการรวมภาระหนี้'),
('sector|Sector','กลุ่มธุรกิจระดับกว้าง เช่น Technology กว้างกว่าอุตสาหกรรมย่อย'),
('country|ประเทศ','ประเทศที่ผู้ให้ข้อมูลระบุสำหรับบริษัท ไม่ใช่สัดส่วนรายได้ตามประเทศ'),
('revenueGrowth','การเติบโตของรายได้ตามฟิลด์ต้นทาง แสดงสัดส่วนคูณ 100 ตรวจช่วงเปรียบเทียบจากงบ ไม่ใช่ประมาณการอนาคตโดยอัตโนมัติ'),
('earningsGrowth','การเติบโตของกำไรตามผู้ให้ข้อมูล แสดงเปอร์เซ็นต์ ฐานกำไรต่ำ/ติดลบอาจทำให้ตีความยาก'),
('profitMargins','อัตรากำไรสุทธิเทียบรายได้ตามผู้ให้ข้อมูล แสดงเปอร์เซ็นต์'),
('operatingMargins','อัตรากำไรดำเนินงานเทียบรายได้ ไม่ใช่อัตรากำไรสุทธิ'),
('returnOnEquity','ROE: กำไรเทียบส่วนผู้ถือหุ้น แสดงเปอร์เซ็นต์ หนี้สูงหรือทุนติดลบอาจทำให้ตีความคลาดเคลื่อน'),
('returnOnAssets','ROA: กำไรเทียบสินทรัพย์ แสดงเปอร์เซ็นต์ ควรเทียบธุรกิจลักษณะใกล้เคียงกัน'),
('operatingCashflow','กระแสเงินสดจากกิจกรรมดำเนินงานในช่วงที่ผู้ให้ข้อมูลรายงาน หน่วยตามงบ ไม่ใช่ยอดเงินสดคงเหลือ'),
('freeCashflow','กระแสเงินสดอิสระตามฟิลด์ต้นทาง โดยทั่วไปคือกระแสเงินสดดำเนินงานหักรายจ่ายลงทุน ตรวจช่วงบัญชีและนิยามต้นทาง'),
('totalCash','เงินสดและรายการที่ผู้ให้ข้อมูลรวมในยอดเงินสด หน่วยตามงบ ไม่ใช่กำไร'),
('totalDebt','ยอดหนี้ตามผู้ให้ข้อมูล หน่วยตามงบ ไม่ใช่หนี้สุทธิหลังหักเงินสด'),
('targetMeanPrice|Target Price','ราคาเป้าหมายเฉลี่ยนักวิเคราะห์ ไม่รับประกันว่าจะถึงเป้าหมายหรือเป็นประมาณการ ณ วันเดียวกัน'),
('numberOfAnalystOpinions','จำนวนนักวิเคราะห์ที่ถูกรวมในประมาณการที่รายงาน ไม่ใช่คะแนนความแม่นยำ'),
('category','หมวดกลยุทธ์การลงทุนของกองทุน ไม่ใช่อุตสาหกรรมบริษัทเดียว'),
('fundFamily','กลุ่มบริษัทจัดการหรือครอบครัวกองทุนตามผู้ให้ข้อมูล'),
('totalAssets','สินทรัพย์รวมของกองทุนที่รายงาน ไม่ใช่มูลค่าตลาดหุ้นบริษัท'),
('navPrice','มูลค่าสินทรัพย์สุทธิต่อหน่วย ราคาซื้อขาย ETF อาจสูงหรือต่ำกว่า NAV'),
('beta3Year','Beta 3 ปีจากผู้ให้ข้อมูล อาจใช้ benchmark/ความถี่ต่างจาก Beta vs SPY ที่คำนวณบนหน้านี้'),
('Beta','ความไวของผลตอบแทนเทียบ benchmark ตามผู้ให้ข้อมูล มากกว่า 1 ไม่ได้แปลว่าจะขึ้นมากกว่าตลาดเสมอ'),
('Dividend Yield','ปันผลย้อนหลัง / ราคาอ้างอิง × 100 ไม่รับประกันการจ่ายครั้งต่อไป และไม่ใช่ผลตอบแทนรวม'),
('80–100','ผ่านระดับคะแนนของโมเดล ยังต้องผ่านเงื่อนไขราคา R:R และอายุข้อมูล'),
('60–79','คะแนนยังไม่ถึงเกณฑ์เข้า 80 ของโมเดล ใช้เฝ้าดู ไม่ใช่คำสั่งซื้อ'),
('40–59|0–39','ยังไม่ผ่านเกณฑ์คะแนนเข้าในโมเดล ไม่ได้หมายความว่าราคาจะลงหรือบริษัทไม่มีคุณภาพทุกมิติ'),
]
HELP={alias:description for aliases,description in _DEFINITIONS for alias in aliases.split('|')}
HELP.update({
    'Portfolio P/E':'Reported valuation of the underlying equity holdings, not corporate earnings per fund unit. Not applicable to physical gold, bond or currency funds. Not reported is different from N/A.',
    'Portfolio Trailing P/E':'Holdings-level trailing valuation reported by the fund data provider, not corporate earnings per ETF unit. Definitions can differ between providers.',
    'Portfolio Forward P/E':'Forward valuation of underlying equity holdings if reported. It is not a forecast of earnings per ETF unit.',
    'Beta (3Y, provider)':'Three-year beta reported by the fund data provider; not a guarantee of future sensitivity.'})
LABEL_COLUMNS=('เกณฑ์','ปัจจัย','มิติ','ข้อมูล','ช่วงคะแนน')
PRESENTATION_ONLY_HIDDEN_COLUMNS=frozenset(('ข้อมูลอ้างอิง','แหล่งข้อมูล','ฟิลด์ต้นทาง','สถานะข้อมูล'))


def field_help(name):
    from return_periods import return_help
    tip=return_help(name)
    if tip is not None:return tip
    name=str(name)
    if name.startswith('ปันผลต่อหน่วย'):return HELP['Dividend_Per_Share']
    return HELP.get(name,f'{name}: ค่าจากชุดข้อมูลที่แสดง ตรวจหน่วย วันที่ และแหล่งข้อมูลประกอบ ช่องว่างไม่ใช่ศูนย์')


def column_help(columns,existing=None,correlation=False):
    config=dict(existing or {})
    for col in columns:
        if col in config and config[col] is None:continue
        item=config.get(col)
        item=dict(item) if isinstance(item,Mapping) else {'label':item} if isinstance(item,str) else {}
        if not item.get('help'):
            item['help']=(f'Correlation ของผลตอบแทนรายวันเทียบ {col} ช่วง −1 ถึง +1 จากวันที่ร่วมกัน ไม่ใช่ผลตอบแทนหรือหลักประกันการกระจายความเสี่ยง' if correlation else field_help(col))
        config[col]=item
    return config


def _plain(value):
    try:
        if value is None or pd.isna(value):return '—'
    except (TypeError,ValueError):pass
    return '—' if str(value).strip().casefold() in ('none','nan','null','n/a','') else str(value)


def table_html(frame,height=420):
    label=next((c for c in LABEL_COLUMNS if c in frame),None)
    def cell(tag,value,tip=None):
        if tip is None:return f'<{tag}>{escape(_plain(value))}</{tag}>'
        return f'<{tag}><abbr tabindex="0" title="{escape(tip,quote=True)}" aria-label="{escape(_plain(value)+": "+tip,quote=True)}">{escape(_plain(value))} <small>ⓘ</small></abbr></{tag}>'
    # Keep help ONLY on indicator/criterion names, not values or category/source cells.
    if label == 'ช่วงคะแนน':label = None
    columns=[col for col in frame.columns if col not in PRESENTATION_ONLY_HIDDEN_COLUMNS]
    tooltip_column = columns.index(label) if label in columns else -1
    headers=''.join(cell('th',col) for col in columns)
    rows=[];definitions=[]
    for _,row in frame.iterrows():
        key=row.get('ฟิลด์ต้นทาง',row.get(label,''))
        tip=field_help(key)
        if label=='ข้อมูล' and key=='industry':tip='จำนวนรายการที่มีอุตสาหกรรมหรือหมวดกองทุนที่ระบบรู้จัก'
        for extra in ['การแปลผล','ช่วง / คะแนน','ข้อมูลอ้างอิง']:
            if extra in row:tip+='\n'+extra+': '+_plain(row[extra])
        rows.append('<tr>'+''.join(cell('td',row[col],tip if col==label else None) for col in columns)+'</tr>')
        if label:definitions.append(f'<dt>{escape(_plain(row[label]))}</dt><dd>{escape(tip)}</dd>')
    css='''<style>.workspace-help-scroll{overflow:auto;border:1px solid #29384c;border-radius:8px}.workspace-help-table{border-collapse:collapse;width:100%;font:14px sans-serif;color:inherit}.workspace-help-table th,.workspace-help-table td{border-bottom:1px solid #29384c;padding:10px 12px;text-align:left;vertical-align:top}.workspace-help-table th{position:sticky;top:0;background:#142135;z-index:1}.workspace-help-table abbr{border:0;text-decoration:none;cursor:help}.workspace-help-table abbr:focus{outline:2px solid #34d399;outline-offset:3px}.workspace-help-table small{color:#91b8bf}.workspace-glossary{font:14px sans-serif;margin:8px 0 16px}.workspace-glossary summary{cursor:pointer}.workspace-glossary dt{font-weight:bold;margin-top:10px}.workspace-glossary dd{margin:4px 0 10px 12px;line-height:1.6;white-space:pre-line}</style>'''
    return css+f'<div class="workspace-help-scroll" style="max-height:{int(height or 420)}px"><table class="workspace-help-table" data-tooltip-column="{tooltip_column}"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'+f'<details class="workspace-glossary"><summary>ⓘ อ่านคำอธิบายแต่ละแถว (สำหรับมือถือหรือแป้นพิมพ์)</summary><dl>{"".join(definitions)}</dl></details>'


def help_table(data,*,height=420,hide_index=True,column_config=None,width='stretch',use_container_width=None,correlation=False,**kwargs):
    frame=data.data if hasattr(data,'data') and isinstance(data.data,pd.DataFrame) else data
    if isinstance(frame,pd.DataFrame) and len(frame)<=100 and any(c in frame for c in LABEL_COLUMNS) and not kwargs.get('on_select'):
        st.html(table_html(frame,height));return None
    columns=frame.columns if hasattr(frame,'columns') else []
    kwargs.setdefault('placeholder','—')
    return st.dataframe(data,height=height,hide_index=hide_index,column_config=column_help(columns,column_config,correlation),width=width,**kwargs)
