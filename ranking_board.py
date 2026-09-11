"""Compact read-only board: strict entries and watch candidates never share a label."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import requests
import streamlit as st
import dashboard_runtime as a
from dashboard_selection import set_selected
from github_store import checked_repo
from ranking_engine import SCHEMA, MODEL, fresh, utc, seconds, STALE_SECONDS
from ranking_policy import is_entry, entry_checks, UNASSESSED


def validate_payload(data):
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA or data.get('model')!=MODEL:
        raise ValueError('Unknown ranking format')
    if seconds(data.get('computed_at')) is None or not isinstance(data.get('counts'),dict):
        raise ValueError('Missing ranking time/coverage')
    items=data.get('items')
    if not isinstance(items,list) or len(items)>10: raise ValueError('Invalid Top 10 items')
    seen=set()
    for row in items:
        t=row.get('ticker','') if isinstance(row,dict) else ''
        if not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}',t) or t in seen: raise ValueError('Invalid symbol')
        seen.add(t)
        score,coverage=row.get('score'),row.get('coverage')
        if (not isinstance(score,(int,float)) or not isinstance(coverage,(int,float))
                or not 0<=score<=coverage<=100): raise ValueError('Invalid score')
        if not isinstance(row.get('ready_at_calculation'),bool) or not isinstance(row.get('qualified'),bool):
            raise ValueError('Invalid readiness')
    return data


@st.cache_data(ttl=60,show_spinner=False)
def read_ranking(repo,local_file=''):
    try:
        if local_file: data=json.loads(Path(local_file).read_text(encoding='utf-8'))
        else:
            repo=checked_repo(repo)
            # Minute cache-key avoids an older shared CDN object masking new publications.
            url=f'https://raw.githubusercontent.com/{repo}/dashboard-rankings/top10.json'
            with requests.Session() as session:
                session.trust_env=False
                with session.get(url,headers={'Authorization':None,'Accept':'application/json'},
                                 params={'minute':int(utc().timestamp()//60)},timeout=(3,8),stream=True) as response:
                    response.raise_for_status();parts=[];size=0
                    for chunk in response.iter_content(65536):
                        size+=len(chunk)
                        if size>1_000_000: raise ValueError('Ranking exceeds size budget')
                        parts.append(chunk)
                    data=json.loads(b''.join(parts))
        return validate_payload(data),''
    except (requests.RequestException,ValueError,OSError,TypeError,KeyError):
        return None,'อ่านอันดับรอบใหม่ไม่ได้ — คงข้อมูลเดิมและเวลาจริงไว้'


def consume_selection(cache):
    pending=st.session_state.pop('_ranking_pending',None)
    if not pending:return
    ticker,info,meta=pending
    if not re.fullmatch(r'[A-Z0-9.^=_-]{1,30}',ticker):return
    set_selected(st.session_state,ticker,reset_table=True)
    old,oldmeta=cache.get('info:'+ticker,request_remote=False)
    if isinstance(info,dict) and isinstance(meta,dict) and (seconds(meta.get('fetched_at')) or 0)>(seconds(oldmeta.get('fetched_at')) or 0):
        cache.put('info:'+ticker,info,meta)


def queue_selection(row):
    st.session_state['_ranking_pending']=(row['ticker'],row.get('info',{}),row.get('info_meta',{}))


def compact_number(value,digits=2):
    n=a.number(value)
    return '—' if n is None else f'{n:,.{digits}f}'


def split_entries(payload,now=None):
    entries=[];watch=[]
    for row in payload['items']:
        (entries if is_entry(row,payload,now) else watch).append(row)
    return entries,watch


def pick_buttons(rows,entry):
    for rank,row in enumerate(rows,1):
        label=f"{rank:02d} · {row['ticker']} · {row['score']}/100 · "+('ผ่าน ณ เวลาตรวจ' if entry else 'เฝ้าดู ไม่ใช่จุดซื้อ')
        st.button(label,key='ranking_pick_'+row['ticker'],width='stretch',on_click=queue_selection,args=(row,))


@st.fragment(run_every=60)
def render_board(cache):
    if st.session_state.get('_ranking_pending'):st.rerun()
    config=a.settings() or {};repo=config.get('DASHBOARD_DATA_REPO') or a.DEFAULT_REPO
    local=os.environ.get('DASHBOARD_RANKING_FILE','')
    payload,error=read_ranking(repo,local)
    key='ranking:last-good:'+repo+':'+local
    previous,_=cache.get(key,request_remote=False)
    if payload:
        if previous and (seconds(previous.get('computed_at')) or 0)>(seconds(payload['computed_at']) or 0):payload=previous
        elif not previous or previous.get('computed_at')!=payload['computed_at']:
            cache.put(key,payload,{'fetched_at':utc().isoformat()})
    elif previous:
        try:payload=validate_payload(previous)
        except ValueError:payload=None
    with st.container(border=True,height=560,key='ranking_board'):
        st.subheader('Top 10 · จังหวะเข้าซื้อ')
        st.caption('ผ่านโมเดล ณ เวลาตรวจ ไม่ใช่การรับประกันกำไร')
        if not payload:
            st.info('ยังไม่มีอันดับที่เผยแพร่สำเร็จ — ไม่แสดงรายชื่อสุ่ม')
            st.caption('รอบคำนวณทุก 30 นาที · ยังรอข้อมูลจริง');return
        now=utc();counts=payload['counts']
        entries,watch=split_entries(payload,now)
        st.caption('จัดอันดับ '+a.thai_time(payload['computed_at']))
        st.caption(f"ตรวจ {counts.get('scanned',0):,}/{counts.get('total',0):,} รายชื่อ · คำนวณโมเดลได้ {counts.get('evaluated',0):,}")
        st.caption(f"ผ่านเงื่อนไขซื้อขณะตรวจสอบสถานะ: {len(entries)} ตัว · ไม่เติมให้ครบ 10")
        if error:st.warning(error)
        if not fresh(payload['computed_at'],now,STALE_SECONDS):
            st.warning('อันดับเกิน 35 นาที — ไม่มีรายชื่อที่ยืนยันสถานะซื้อ')
        if not entries:
            st.info('ยังไม่มีหุ้นผ่านเงื่อนไขซื้อครบ ณ เวลานี้ รวมกรณีตลาดปิด ราคาเก่า หรือข้อมูลไม่ครบ')
        pick_buttons(entries,True)
        with st.expander('เฝ้าดู / รอยืนยัน — ยังไม่ใช่จุดซื้อ',expanded=not entries):
            if watch:pick_buttons(watch,False)
            else:st.caption('ไม่มีรายการเฝ้าดูเพิ่มเติมในอันดับรอบนี้')
        st.caption('คำนวณทุก 30 นาที · หน้าเว็บตรวจสถานะทุก 1 นาที')
        with st.expander('เหตุผล เงื่อนไข และอายุข้อมูล'):
            st.write('ตรวจทั้งทะเบียนจาก snapshot ไม่ขึ้นกับตัวกรองส่วนบุคคล; ราคา ≥1 USD สภาพคล่องประมาณ ≥1 ล้าน USD/วัน ประวัติ ≥200 แท่ง ราคาไม่เกิน 4 วัน และตัด Shell/ETF ทดหรือผกผันที่ตรวจพบ')
            st.write('รายชื่อซื้อ: คะแนน ≥80/100 และคะแนนครบ R:R ≥2 ราคายังอยู่ในโซน quote ไม่เกิน 15 นาที ในช่วงตลาดปกติ และผ่าน checklist เพิ่มเติมด้านกำไร กระแสเงินสด หนี้ สเปรด และวันประกาศกำไร ช่องที่ไม่ทราบจะไม่ถือว่าผ่าน; ETF ใช้เกณฑ์กองทุนแยก')
            st.write('เกณฑ์กระแสเงินสดเป็นแบบอนุรักษนิยม ไม่รับรองธุรกิจการเงิน/อสังหาริมทรัพย์ คะแนนครบ 100 ไม่ได้แปลว่าวิเคราะห์ครบทุกด้านของบริษัท')
            st.warning('ยังไม่ได้ตรวจ: '+'; '.join(UNASSESSED)+' — ต้องตรวจเพิ่มเติมก่อนตัดสินใจจริง')
            st.caption('Snapshot ต้นทาง '+a.thai_time(payload.get('source_published_at')))
            st.caption('รอบตามตารางถัดไป '+a.thai_time(payload.get('next_scheduled_at'))+' (อาจล่าช้าตาม GitHub Actions)')
            refresh=payload.get('quote_refresh',{})
            st.caption(f"ตรวจ quote เพิ่มเติม {refresh.get('success',0)}/{refresh.get('attempted',0)} ตัวในกลุ่มคัดเลือกสูงสุด {refresh.get('limit',20)} ตัว ไม่ใช่ราคาใหม่ทั้ง 4,900 ตัวทุก 30 นาที")
            st.write('เทคนิคใช้แท่งรายวันสมบูรณ์; ส่วนจังหวะใช้ quote และโซนเข้าซื้อ สถานะหมดอายุเมื่อ quote เกิน 15 นาที ไม่ค้างคำว่าซื้อได้จนครบรอบใหม่')
            for row in payload['items']:
                st.markdown('**'+row['ticker']+' · '+str(row.get('name',''))+'**')
                st.caption(f"คะแนน {row['score']}/100 · ความครบคะแนน {row['coverage']}/100 · R:R แผน {compact_number(row.get('rr'))}")
                st.caption('เหตุผล: '+'; '.join(row.get('reasons',[])))
                st.caption(f"โซน {compact_number(row.get('zone_low'))}–{compact_number(row.get('zone_high'))} · Stop {compact_number(row.get('stop'))} · เป้า {compact_number(row.get('target'))} USD")
                st.caption('ราคาปิดวันที่ '+str(row.get('price_asof') or '—')+' · Quote ณ '+a.thai_time(row.get('quote_time')))
                for check in entry_checks(row,now)['checks']:
                    st.caption(('✓ ' if check['passed'] else 'รอ: ')+check['check']+' — '+check['detail'])
                for blocker in row.get('blockers',[])[:5]:st.caption('เงื่อนไข: '+str(blocker))
            st.json({'coverage':counts,'excluded':payload.get('excluded',{})},expanded=False)
