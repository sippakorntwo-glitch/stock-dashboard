"""Explain absent data without changing numeric values, scoring or table filters."""
from __future__ import annotations
import inspect
import pandas as pd
import streamlit as st
from data_quality import LABELS, STOCK_FIELDS, ETF_FIELDS, present, industry_value


def placeholder_options():
    return {'placeholder':'—'} if 'placeholder' in inspect.signature(st.dataframe).parameters else {}


def snapshot_quality(cache):
    quality,_=cache.get('remote:quality',request_remote=False)
    # Version 2 adds company metrics; old snapshots remain readable during rollout.
    return quality if isinstance(quality,dict) and quality.get('version') in (1,2) else {}


def industry_display(frame,quality):
    result=frame.copy();symbols=quality.get('symbols',{})
    if 'Industry' not in result:return result
    result['Industry']=result.apply(lambda r:r['Industry'] if present(r['Industry']) else
            LABELS.get(symbols.get(str(r['Ticker']),{}).get('industry_state'),'ยังไม่มีข้อมูลในชุดที่อ่าน'),axis=1)
    return result


def profile_field_state(info,key):
    if present(info.get(key)):return 'มีข้อมูล'
    return 'แหล่งข้อมูลไม่รายงาน' if info else 'รอโหลดข้อมูลพื้นฐาน'


def profile_value(raw,info):
    return raw if present(raw) else ('แหล่งข้อมูลไม่รายงาน' if info else 'รอโหลดข้อมูลพื้นฐาน')


def profile_unit(info,key):
    if key in ('operatingCashflow','freeCashflow','totalCash','totalDebt'):
        return info.get('financialCurrency') or 'ยังไม่ระบุสกุลของงบ'
    if key in ('marketCap','totalAssets','targetMeanPrice','navPrice'):
        return info.get('currency') or 'ยังไม่ระบุสกุลราคา'
    return ''


def render_family_counts(cache):
    quality=snapshot_quality(cache);n=quality.get('counts',{})
    if n:
        total=n.get('universe',0)
        st.caption(f"ความครบแยกประเภท: ประวัติราคา {n.get('histories',0):,}/{total:,} · พื้นฐาน {n.get('info',0):,}/{total:,} · Industry/หมวด ETF {n.get('industry',0):,}/{total:,} · ตรวจปันผลแล้ว {n.get('dividends_checked',0):,}/{total:,}")
        st.caption('จำนวนข้อมูลที่โหลดสำเร็จไม่ใช่ความครบทุกฟิลด์ และไม่ใช่จำนวนหุ้นที่ควรซื้อ')


def render_symbol_quality(ticker,cache,history,info):
    quality=snapshot_quality(cache);r=quality.get('symbols',{}).get(ticker,{})
    with st.expander('ตรวจข้อมูลที่ขาดของ '+ticker):
        if not r:
            st.info('ยังไม่มีรายงานความครบของหุ้นนี้ใน snapshot; ไม่สรุปจากแคชเฉพาะหุ้นว่าข้อมูลทั้งตลาดครบ')
        else:
            h=r.get('history',{})
            rows=[{'ส่วน':'Industry / หมวด ETF','สถานะ':LABELS.get(r.get('industry_state'),'ยังไม่ทราบ'),'รายละเอียด':'ใช้ industry สำหรับหุ้น และ category สำหรับ ETF ไม่เดาจากชื่อบริษัท'},
                  {'ส่วน':'ข้อมูลพื้นฐาน','สถานะ':LABELS.get(r.get('info_state'),'ยังไม่ทราบ'),'รายละเอียด':'ดึงสำเร็จ '+str(r.get('info_fetched_at') or 'ยังไม่เคยโหลด')},
                  {'ส่วน':'กราฟ / ความเสี่ยง / เปรียบเทียบ','สถานะ':'มีประวัติ' if h.get('valid') else 'รอประวัติราคา','รายละเอียด':f"{h.get('bars',0):,} แท่ง · {h.get('first') or '—'} ถึง {h.get('last') or '—'}"},
                  {'ส่วน':'ปันผล','สถานะ':LABELS.get(r.get('dividend_state'),'ยังไม่ทราบ'),'รายละเอียด':str(r.get('dividend_coverage_start') or '—')+' ถึง '+str(r.get('dividend_coverage_end') or '—')}]
            rows.extend({'ส่วน':key,'สถานะ':LABELS.get(state,state),'รายละเอียด':'ไม่เติมศูนย์ และไม่สร้างแท่งย้อนหลังให้หุ้นใหม่'} for key,state in r.get('missing_metrics',{}).items())
            st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch',**placeholder_options())
        etf=r.get('asset_type')=='ETF' or info.get('quoteType')=='ETF'
        missing=[key for key in (ETF_FIELDS if etf else STOCK_FIELDS) if not present(info.get(key))]
        if missing:
            st.caption(('ฟิลด์ที่แหล่งข้อมูลยังไม่รายงาน: ' if info else 'ยังต้องโหลดข้อมูลพื้นฐานก่อนประเมินฟิลด์: ')+', '.join(missing))
        st.caption('กราฟ 1–7 วันและ 5/10 ปีโหลดเฉพาะช่วงที่เลือก; หุ้นอายุสั้นไม่มีประวัติย้อนหลังครบ 10 ปีโดยธรรมชาติ ค่า P/E/เป้าหมายที่ผู้ให้ข้อมูลไม่รายงานจะไม่ถูกสร้างขึ้นจากการเดา')
        st.caption('ข้อมูลราคาสด เงื่อนไขซื้อ ข่าว และความเหมาะสมกับพอร์ตเป็นคนละเรื่องกับความครบของข้อมูลที่โหลดสำเร็จ')


def render_quality_report(cache,frame):
    quality=snapshot_quality(cache)
    st.subheader('รายงานความครบของข้อมูลทุกส่วน')
    if not quality:
        st.info('รอรายงานจากงานอัปเดตข้อมูลรุ่นใหม่ ไม่ได้หมายความว่าข้อมูลครบแล้ว');return
    rows=[]
    for field,states in quality.get('columns',{}).items():
        row={'ข้อมูล / ฟิลด์':field,'ทั้งหมดที่ใช้ฟิลด์นี้':sum(states.values())}
        row.update({label:states.get(code,0) for code,label in LABELS.items()})
        rows.append(row)
    report=pd.DataFrame(rows)
    st.dataframe(report,hide_index=True,height=360,width='stretch',**placeholder_options())
    st.download_button('ดาวน์โหลดรายงานความครบทุกฟิลด์',report.to_csv(index=False).encode('utf-8-sig'),'dashboard_field_coverage.csv','text/csv',key='download_quality_fields')
    gaps=[]
    for t,r in quality.get('symbols',{}).items():
        h=r.get('history',{})
        gaps.append({'Ticker':t,'Asset_Type':r.get('asset_type'),'Industry_Status':LABELS.get(r.get('industry_state')),
                     'Fundamentals_Status':LABELS.get(r.get('info_state')),'Dividend_Status':LABELS.get(r.get('dividend_state')),
                     'History_Bars':h.get('bars'),'History_First':h.get('first'),'History_Last':h.get('last'),
                     'Missing_Price_Metrics':'; '.join(k+': '+LABELS.get(v,v) for k,v in r.get('missing_metrics',{}).items()),
                     'Provider_Fields_Not_Reported':'; '.join(r.get('missing_info_fields',[])),
                     'Info_Fetched_At':r.get('info_fetched_at'),'Dividend_Checked_At':r.get('dividend_fetched_at')})
    export=pd.DataFrame(gaps)
    st.download_button('ดาวน์โหลดสถานะข้อมูลครบทุกหุ้น',export.to_csv(index=False).encode('utf-8-sig'),'dashboard_all_symbol_status.csv','text/csv',key='download_quality_symbols')
    st.caption('รายงานนี้มาจาก snapshot ทั้งทะเบียน ไม่ใช่แค่หุ้นที่เคยคลิกหรือหน้าตารางปัจจุบัน; ไม่รวม private portfolio หรือไฟล์ CSV ที่อัปโหลดในเซสชัน')
    st.caption('มีข้อมูล = ฟิลด์มีค่าที่ใช้ได้; แหล่งข้อมูลไม่รายงาน ≠ ศูนย์; ไม่พบปันผล = ตรวจรายการในช่วงข้อมูลสำเร็จแต่ไม่มีการจ่าย; ประวัติไม่ยาวพอ ≠ โหลดล้มเหลว')
