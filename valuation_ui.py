"""Thai, editable research scenarios with source and unit gates."""
from __future__ import annotations

from datetime import date
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from valuation import MODEL_LABELS, price_scenario, sensitivity, valuation_basis, verified_basis


def _remember(ticker, field, widget_key):
    st.session_state.setdefault(f'valuation_saved_{ticker}', {})[field] = st.session_state[widget_key]


def _input(ticker, field, method, label, default, **kwargs):
    """Durable per-symbol assumptions survive widget cleanup after ticker changes."""
    saved = st.session_state.setdefault(f'valuation_saved_{ticker}', {})
    key = f'valuation_{ticker}_{field}'
    if key not in st.session_state:
        st.session_state[key] = saved.get(field, default)
    return method(label, key=key, on_change=_remember, args=(ticker, field, key), **kwargs)


def _price(value, currency):
    return '—' if value is None else f'{value:,.2f} {currency or "(ไม่ระบุสกุลเงิน)"}'


def render_valuation(ticker, info, row, bundle=None):
    st.subheader('ประเมินราคาหลายสถานการณ์', anchor='valuation-scenarios')
    st.caption('ปรับสมมติฐานเพื่อดูช่วงราคา ไม่ใช่คำแนะนำซื้อขายหรือราคาที่รับประกัน '
               'คำนวณจากราคาปลายงวดแล้วคิดลดกลับมา ไม่ใช่ DCF และไม่รวมปันผล ภาษี หรือค่าธรรมเนียม')
    original = valuation_basis(ticker, info, row, bundle)
    if original['state'] == 'not_applicable':
        st.info(original['reason'])
        return
    model = original['model']
    st.write('แบบจำลอง: **' + MODEL_LABELS[model] + '**')
    if original.get('value') is not None:
        st.caption(f"ฐานจากแหล่งข้อมูล: {_price(original['value'], original.get('currency'))}/หุ้น · "
                   f"รอบ {original.get('period') or 'ไม่ระบุ'} · {original.get('source') or 'ไม่ระบุแหล่งข้อมูล'}")
    if original['state'] != 'available':
        st.info(original['reason'])
    basis = original
    label = {'eps': 'EPS', 'book': 'BVPS', 'ffo': 'FFO ต่อหุ้น'}[model]
    manual = _input(ticker, 'manual_enabled', st.checkbox,
                    f'ใช้ {label} ที่ตรวจสอบจากรายงานด้วยตนเอง', model != 'eps',
                    help='เป็นข้อมูลที่ผู้ใช้กรอกสำหรับแบบจำลองเท่านั้น ไม่แก้ตัวเลขจากแหล่งข้อมูลในตารางการเงิน')
    if manual:
        with st.expander('ฐานต่อหุ้นที่ผู้ใช้ตรวจสอบ', expanded=True):
            if model == 'ffo':
                st.caption('ใช้ FFO ต่อหุ้นที่ REIT รายงานและตรวจตารางกระทบยอดกับกำไรสุทธิ '
                           'อย่าใช้ EPS หรือกระแสเงินสดดำเนินงานแทน FFO และอย่าปะปน FFO กับ AFFO')
            if model == 'book':
                st.caption('ใช้มูลค่าตามบัญชีต่อหุ้น ณ วันที่รายงาน โดยให้จำนวนหุ้นและส่วนของผู้ถือหุ้นเป็นวันเดียวกัน '
                           'P/B ไม่สะท้อนคุณภาพสินเชื่อหรือความเพียงพอของเงินกองทุนโดยตัวมันเอง')
            cols = st.columns(3)
            with cols[0]:
                value = _input(ticker, 'manual_value', st.number_input, f'{label} ต่อหุ้น',
                               float(original.get('value') or 0.0), format='%.4f')
            with cols[1]:
                currency = _input(ticker, 'manual_currency', st.text_input, 'สกุลเงินของฐานต่อหุ้น',
                                  str(original.get('currency') or ''), max_chars=3)
            with cols[2]:
                period = _input(ticker, 'manual_period', st.text_input, 'วันสิ้นงวด / วันที่ฐาน (YYYY-MM-DD)',
                                '', help='EPS / FFO ต้องเป็นทั้งปีหรือ TTM ที่ตรวจสอบแล้ว ไม่คูณไตรมาสเดียวเป็นทั้งปี')
            source = _input(ticker, 'manual_source', st.text_input, 'แหล่งอ้างอิง / ชื่อรายงานและหน้าที่ใช้', '')
            confirmed = _input(ticker, 'manual_confirmed', st.checkbox,
                               'ตรวจสอบค่า รอบบัญชี สกุลเงิน และหน่วยต่อหุ้นจากรายงานแล้ว', False)
            basis = verified_basis(original, value=value, currency=currency, period=period,
                                   source=source, confirmed=confirmed)
            if basis['state'] != 'available':
                st.info(basis['reason'])
                return
            st.caption(f'กำลังใช้ข้อมูลที่ผู้ใช้กรอก: {source} · วันที่ {period} · {_price(value, currency)}/หุ้น')
    if basis['state'] != 'available':
        return
    share_units = _input(ticker, 'share_units', st.checkbox,
                         'ยืนยันว่าฐานต่อหุ้นเป็นหน่วยเดียวกับหุ้น / ADR ที่ซื้อขาย เพื่อเทียบกับราคา', False,
                         help='ADR อาจแทนหุ้นสามัญหลายหุ้น ต้องตรวจอัตราส่วนต่อ ADR และสกุลเงินก่อนเปรียบเทียบ')
    st.caption(f"ราคาตลาดอ้างอิง: {_price(basis['quote_price'], basis.get('quote_currency'))} · "
               f"วันที่ {basis.get('quote_as_of') or 'ไม่ระบุ'} · ใช้ราคาปิดจากชุดข้อมูล ไม่ใช่ราคา tick ล่าสุด")
    controls = st.columns(2)
    with controls[0]:
        years = _input(ticker, 'years', st.number_input, 'ระยะประมาณการ (ปี)', 5,
                       min_value=1, max_value=15, step=1)
    with controls[1]:
        required = _input(ticker, 'required_return', st.number_input, 'ผลตอบแทนจากราคาที่ต้องการต่อปี (%)',
                          10.0, min_value=0.0, max_value=100.0, step=0.5)
    use_margin = False
    if basis.get('margin') is not None:
        use_margin = _input(ticker, 'margin_mode', st.checkbox,
                            'จำลองจากการเติบโตของรายได้และอัตรากำไรสุทธิปลายงวด', True)
        st.caption(f"อัตรากำไรสุทธิฐาน {basis['margin'] * 100:,.2f}% · รายได้ กำไร และ EPS "
                   f"มาจากปีบัญชีเดียวกัน {basis['period']} · สมมติสัดส่วนกำไรที่เป็นของหุ้นสามัญคงเดิม")
    elif model == 'eps':
        st.caption('ไม่มีรายได้ กำไร และ EPS ปีเดียวกันครบ จึงใช้การเติบโตของกำไรรวมโดยไม่ประมาณอัตรากำไรที่ขาด')
    growth_label = 'รายได้' if use_margin else {'eps': 'กำไรรวม', 'book': 'ส่วนของผู้ถือหุ้นรวม', 'ffo': 'FFO รวม'}[model]
    multiple_label = {'eps': 'P/E', 'book': 'P/B', 'ffo': 'P/FFO'}[model]
    st.caption('สมมติฐานเริ่มต้นเป็นตัวอย่างสำหรับทดลอง ไม่ใช่ประมาณการบริษัทหรือค่าเฉลี่ยอุตสาหกรรม '
               'การเปลี่ยนจำนวนหุ้น: ค่าบวก = เพิ่มจำนวนหุ้น / เจือจาง; ค่าลบ = จำนวนหุ้นลดลงสุทธิ '
               'กรณีแย่–ฐาน–ดีเป็นชื่อชุดสมมติฐานที่แก้ไขได้ ไม่มีการกำหนดโอกาสเกิดให้เอง')
    configs, outputs = [], []
    defaults = [('แย่ (Bear)', -5.0, 0.8), ('ฐาน (Base)', 5.0, 1.0), ('ดี (Bull)', 12.0, 1.2)]
    for index, (column, (name, default_growth, scale)) in enumerate(zip(st.columns(3), defaults)):
        with column:
            st.markdown(f'**{name}**')
            growth = _input(ticker, f's{index}_growth', st.number_input,
                            f'{growth_label}เติบโตต่อปี (%) · {name}', default_growth,
                            min_value=-95.0, max_value=300.0, step=1.0)
            multiple = _input(ticker, f's{index}_{model}_multiple', st.number_input,
                              f'{multiple_label} ปลายงวด (เท่า) · {name}',
                              (1.2 if model == 'book' else 15.0) * scale,
                              min_value=0.1, max_value=300.0, step=0.5)
            dilution = _input(ticker, f's{index}_dilution', st.number_input,
                              f'จำนวนหุ้นเปลี่ยนต่อปี (%) · {name}', 0.0,
                              min_value=-90.0, max_value=300.0, step=0.5)
            margin = None
            if use_margin:
                margin = _input(ticker, f's{index}_margin', st.number_input,
                                f'อัตรากำไรสุทธิปลายงวด (%) · {name}', basis['margin'] * 100 * scale,
                                min_value=0.01, step=0.5) / 100
            config = dict(growth=growth / 100, multiple=multiple, dilution=dilution / 100,
                          required_return=required / 100, years=years, terminal_margin=margin)
            output = price_scenario(basis, **config, share_unit_confirmed=share_units)
            configs.append(config)
            outputs.append(output)
    valid = [value['present_price'] for value in outputs if value['state'] == 'available']
    if not valid:
        st.info(outputs[0]['reason'])
        return
    if not outputs[1]['comparable']:
        st.info(outputs[1]['reason'] + ' — ยังดูราคาจำลองในสกุลของฐานต่อหุ้นได้')
    rows = []
    for (name, _, _), output in zip(defaults, outputs):
        rows.append({'กรณี': name, 'ราคาปลายงวด': output['terminal_price'],
                     'ราคาคิดลด ณ วันนี้': output['present_price'],
                     'ส่วนต่างราคาคิดลด (%)': output['price_gap'] * 100 if output['price_gap'] is not None else None,
                     'ผลตอบแทนราคาต่อปี (%)': output['price_cagr'] * 100 if output['price_cagr'] is not None else None})
    st.caption(f"หน่วยราคา: {basis.get('currency') or 'ไม่ระบุสกุลเงิน'} ต่อหุ้น · "
               'ส่วนต่าง = ราคาคิดลด ÷ ราคาตลาดอ้างอิง − 1; ไม่ใช่ผลตอบแทนที่รับประกัน')
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch',
                 column_config={name: st.column_config.NumberColumn(name, format='%.2f')
                                for name in rows[0] if name != 'กรณี'},
                 key=f'valuation_results_{ticker}')
    base = outputs[1]
    if base['implied_growth'] is not None:
        st.info(f"ภายใต้จำนวนหุ้น อัตรากำไร และ {multiple_label} ของกรณีฐาน ราคาตลาดอ้างอิงต้องอาศัย"
                f"{growth_label}เติบโตเฉลี่ย {base['implied_growth'] * 100:,.2f}% ต่อปี "
                f"ตลอด {years} ปี เพื่อให้ได้ผลตอบแทนจากราคา {required:,.1f}% ต่อปีตามสมมติฐานนี้")
    present_prices = [o['present_price'] for o in outputs]
    if all(v is not None for v in present_prices) and present_prices != sorted(present_prices):
        st.caption('ค่าที่แก้ไขทำให้ราคากรณีแย่–ฐาน–ดีไม่เรียงกัน โปรดพิจารณาสมมติฐานของแต่ละกรณี')
    with st.expander('ความไวของราคาและวิธีคำนวณ', expanded=False):
        config = configs[1]
        growths = sorted(set(max(-0.95, min(3.0, config['growth'] + offset)) for offset in (-0.10, -0.05, 0, 0.05, 0.10)))
        multiples = [config['multiple'] * scale for scale in (0.6, 0.8, 1.0, 1.2, 1.4)]
        grid = sensitivity(basis, growths=growths, multiples=multiples,
                           required_return=config['required_return'], years=years,
                           dilution=config['dilution'], terminal_margin=config['terminal_margin'])
        matrix = [[next(item['present_price'] for item in grid if item['growth'] == g and item['multiple'] == m)
                   for m in multiples] for g in growths]
        fig = go.Figure(go.Heatmap(z=matrix, x=[f'{m:.2f}×' for m in multiples],
                                  y=[f'{g * 100:.1f}%' for g in growths],
                                  texttemplate='%{z:.2f}', colorscale='Blues',
                                  colorbar=dict(title=basis.get('currency') or 'ราคา'),
                                  hovertemplate='การเติบโต %{y}<br>Multiple %{x}<br>ราคาคิดลด %{z:.2f}<extra></extra>'))
        fig.update_layout(height=330, margin=dict(l=20, r=20, t=25, b=20),
                          xaxis_title=f'{multiple_label} ปลายงวด', yaxis_title=f'{growth_label}เติบโตต่อปี')
        st.plotly_chart(fig, width='stretch', key=f'valuation_sensitivity_{ticker}')
        st.write('ฐานต่อหุ้นปลายงวด = ฐานต่อหุ้นเริ่มต้น × [(1 + การเติบโต) ÷ (1 + การเปลี่ยนจำนวนหุ้น)] ^ จำนวนปี '
                 'เมื่อใช้โหมดอัตรากำไร ให้คูณอัตรากำไรปลายงวด ÷ อัตรากำไรฐานเพิ่มเติม')
        st.write('ราคาปลายงวด = ฐานต่อหุ้นปลายงวด × Multiple ปลายงวด · '
                 'ราคาคิดลด = ราคาปลายงวด ÷ (1 + ผลตอบแทนที่ต้องการ) ^ จำนวนปี '
                 'แบบจำลองนี้ไม่รวมเงินปันผลระหว่างทางและไม่หักหนี้ซ้ำจากกำไรสุทธิหรือ BVPS')
        st.caption('สำหรับธุรกิจการเงิน P/B ต้องพิจารณาร่วมกับ ROE คุณภาพสินทรัพย์ และเงินกองทุน '
                   'สำหรับ REIT ค่า FFO ไม่ใช่เงินสดอิสระที่จ่ายผู้ถือหุ้นได้ทั้งหมด')
        st.link_button('วิธีอ่านงบการเงิน — SEC', 'https://www.sec.gov/investor/pubs/begfinstmtguide.htm')
        st.link_button('ความหมายของ FFO — Nareit', 'https://www.reit.com/news/blog/nareit-media/first-quarter-2018-funds-operations-ffo-reits-rose-6-percent-year-over-year')
    document = dict(schema=1, model=MODEL_LABELS[model], ticker=ticker, basis=basis,
                    scenario_names=[d[0] for d in defaults], assumptions=configs, results=outputs,
                    excluded=['interim dividends', 'fees', 'taxes'],
                    exported_at=date.today().isoformat())
    st.download_button('ดาวน์โหลดสมมติฐานและผลจำลอง (JSON)',
                       json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8'),
                       file_name=f'{ticker}_valuation_scenarios.json', mime='application/json',
                       key=f'valuation_export_{ticker}', on_click='ignore')
