"""One-time, guarded fix for duplicate summaries observed on production."""
from pathlib import Path

p=Path('chart_ranges.py');s=p.read_text()
start=s.index('@st.fragment(run_every=60)\ndef render_chart(')
end=s.index('\n\ndef first_chart_load_finished',start)
replacement='''@st.fragment(run_every=60)
def render_chart(ticker,daily_history):
    if st.session_state.get('selected_ticker',ticker) != ticker:
        return
    # Allocate every sibling before provider/cache spinners or optional messages.
    # Fixed empty slots replace their old payload instead of leaving a previous
    # period's iframe/commentary behind when a fragment child count changes.
    controls=st.container(key='chart_controls')
    notices=st.container(key='chart_notices')
    chart_slot=st.empty()
    commentary_slot=st.empty()
    with controls:
        period=st.radio('ช่วงเวลาแสดงกราฟ',PERIODS,index=PERIODS.index('1 ปี'),horizontal=True,key='chart_period',
            help='ช่วงย้อนหลัง ไม่ใช่ขนาดแท่ง: 1/3/5/7 วันใช้ 5 นาทีและนับวันซื้อขายล่าสุดที่มีข้อมูล; เดือน/ปีใช้แท่งรายวัน')
    try:
        with notices:
            short=period.endswith('วัน');long=period in ('5 ปี','10 ปี')
            service=get_chart_service()
            history,meta=a.get_data_cache().history(ticker,'5m' if short else '1d')
            kind='5m' if short else 'long';message=''
            st.session_state.pop('_chart_first_load_waiting',None)
            if short or long:
                extra,extra_meta=service.read(ticker,kind)
                if extra is not None and (short or not covers_years(history,int(period.split()[0]))):history,meta=extra,extra_meta
                need=short or not covers_years(history,int(period.split()[0]))
                if extra is not None and long:need=True
                if need:
                    if chart_requests_enabled():
                        first_load=history is None or (long and extra is None and not covers_years(history,int(period.split()[0])))
                        if first_load:st.session_state['_chart_first_load_waiting']=ticker
                        message=service.request(ticker,kind)
                    elif history is None:message='เจ้าของระบบปิดการดึงกราฟเพิ่มเติม จึงยังไม่มีข้อมูลช่วงนี้'
            if message:
                (st.warning if any(word in message for word in ('ไม่สำเร็จ','จำกัด','พัก','เต็ม','ปิด')) else st.info)(message)
            if short:
                st.caption('1 วัน / 3 วัน = 1 / 3 วันซื้อขายล่าสุดที่มีข้อมูล ไม่ใช่ 24 / 72 ชั่วโมง · แท่ง 5 นาที เฉพาะเวลาตลาดปกติ · ตรวจใหม่ประมาณทุก 1 นาที; แท่งยังเป็น 5 นาที และผู้ให้ข้อมูลอาจล่าช้า ไม่ใช่ราคาสตรีมสด')
            elif long:
                st.caption('5 ปี / 10 ปีใช้แท่งรายวัน ดึงประวัติเฉพาะหุ้นที่เลือกเมื่อจำเป็นและเก็บแคช 24 ชั่วโมง; หุ้นเข้าตลาดใหม่อาจมีไม่ครบช่วง')
            if history is None or history.empty:
                st.info('ยังไม่มีประวัติจริงสำหรับช่วงที่เลือก ไม่ใช้แท่งรายวันแทนแท่งระหว่างวัน และไม่เติมราคาจำลอง')
                return
            payload=range_payload(history,ticker,period,'5m' if short else '1d',meta.get('fetched_at',''))
            st.caption('ผลตอบแทนสะสม = (Close ล่าสุด / Close แรกในช่วงที่เลือก − 1) × 100; ใช้ราคาปรับแล้ว ไม่บวกปันผลซ้ำ ไม่ใช่ CAGR หรือผลตอบแทนสุทธิหลังค่าธรรมเนียม/ภาษี และไม่เปลี่ยนตามการลากหรือซูมกราฟ')
            if not payload['full_window']:st.warning('ประวัติที่มีสั้นกว่าช่วงที่เลือก แสดงเฉพาะข้อมูลจริงที่มี ไม่ถือว่าครบช่วง')
            first=history.index[min(payload['visibleStart'],len(history)-1)];last=history.index[-1]
            st.caption(f'ช่วงข้อมูลที่แสดงจริง: {first:%Y-%m-%d} ถึง {last:%Y-%m-%d} · ดึงสำเร็จ {a.thai_time(meta.get("fetched_at"))}')
            if short and (pd.Timestamp.now(tz=last.tz).date()-last.date()).days>4:st.warning('แท่งระหว่างวันล่าสุดเกิน 4 วันปฏิทิน อาจเป็นวันหยุดหรือข้อมูลเก่า ไม่ใช่ราคา ณ ขณะนี้')
            html=with_inspector(with_performance(a.build_chart_html(payload),payload))
        with chart_slot.container():
            if hasattr(st,'iframe'):st.iframe(html,height=900)
            else:components.html(html,height=900,scrolling=False)
        from chart_commentary import commentary_html
        commentary_slot.markdown(commentary_html(payload),unsafe_allow_html=True)
    except (ValueError,TypeError,KeyError) as exc:
        chart_slot.empty();commentary_slot.empty()
        with notices:
            st.warning(f'แสดงกราฟไม่ได้ ({type(exc).__name__}) ไม่เปลี่ยนข้อมูลให้คะแนนรายวัน')
'''
p.write_text(s[:start]+replacement+s[end:])
for name in ('app.py','dashboard_runtime.py','tests/test_chart_commentary.py'):
    p=Path(name);s=p.read_text();assert '2026-09-12.26' in s
    p.write_text(s.replace('2026-09-12.26','2026-09-13.27'))
p=Path('production_smoke.py');s=p.read_text()
old="        page.on('pageerror',lambda e:print('JAVASCRIPT_ERROR:',str(e)[:1000],flush=True))"
assert s.count(old)==1
s=s.replace(old,"        javascript_errors=[]\n        page.on('pageerror',lambda e:(javascript_errors.append(str(e)),print('JAVASCRIPT_ERROR:',str(e)[:1000],flush=True)))")
old="            report['result']='passed'";assert s.count(old)==1
s=s.replace(old,"            report['javascript_errors']=javascript_errors\n            if javascript_errors:raise RuntimeError('Browser JavaScript errors: '+str(javascript_errors[:5]))\n"+old)
p.write_text(s)
p=Path('enhanced_smoke.py');s=p.read_text();old='    return report';assert s.count(old)==1
s=s.replace(old,"    from chart_stability_smoke import verify_chart_stability\n    report['chart_refresh_stability']=verify_chart_stability(page,app)\n"+old);p.write_text(s)
Path(__file__).unlink()
print('Chart slots replaced atomically; numerical logic, data sources and polling budgets unchanged.')
