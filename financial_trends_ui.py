"""Thai financial trend charts from dated, validated statement observations."""
from __future__ import annotations

from html import escape
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from financial_trends import (LABELS, PERCENT_KEYS, STATE_LABELS,
                              build_financial_trends, export_trends)

BASIS_LABELS = {'FY': 'รายปี (FY)', 'Q': 'รายไตรมาส (Q)', 'TTM': 'ย้อนหลัง 12 เดือน (TTM)'}
TOPICS = {
    'การเติบโตและเงินสด': ('revenue', 'netIncome', 'operatingCashflow', 'freeCashflow'),
    'อัตรากำไร': ('grossMargins', 'operatingMargins', 'profitMargins', 'fcfMargin'),
    'หนี้และเงินสด': ('totalDebt', 'cash', 'netDebt'),
    'ผู้ถือหุ้นและการซื้อหุ้นคืน': ('buybacks', 'issuanceOfCapitalStock', 'netBuybackCash', 'stockBasedCompensation'),
}
COLORS = ('#63b3ed', '#b794f4', '#38d9a9', '#ffca66')


def format_trend_value(key, item, currency):
    if item.get('state') != 'available' or item.get('value') is None:
        return '—'
    value = item['value']
    if key in PERCENT_KEYS:
        return f'{value * 100:,.2f}%'
    if key == 'cashConversion':
        return f'{value:,.2f} เท่า'
    unit = 'หุ้น' if key in ('ordinarySharesNumber', 'dilutedAverageShares') else currency
    divisor, suffix = next(((n, s) for n, s in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'))
                            if abs(value) >= n), (1, ''))
    return f'{value / divisor:,.2f}{suffix} {unit}'


def trend_figure(rows, keys, currency, *, percent=False, shares=False):
    """One unit per chart, explicit date labels, and no interpolated data gaps."""
    fig = go.Figure()
    dates = [row['end'] for row in rows]
    for index, key in enumerate(keys):
        items = [row['metrics'][key] for row in rows]
        values = [item['value'] * (100 if percent else 1)
                  if item['state'] == 'available' else None for item in items]
        if not any(value is not None for value in values):
            continue
        custom = [[escape(STATE_LABELS.get(item['state'], item['state'])),
                   escape(item['basis'] or ''), escape(item['formula'] or ''),
                   escape(', '.join(item['period_ends']))] for item in items]
        unit = '%' if percent else 'หุ้น' if shares else escape(currency)
        common = dict(name=LABELS[key], x=dates, y=values, customdata=custom,
                      marker_color=COLORS[index % len(COLORS)],
                      hovertemplate='%{x}<br>%{y:,.2f} '+unit+
                      '<br>%{customdata[1]} · %{customdata[0]}<br>%{customdata[2]}'
                      '<br>วันสิ้นงวดที่ใช้: %{customdata[3]}<extra>%{fullData.name}</extra>')
        if percent or shares:
            fig.add_trace(go.Scatter(**common, mode='lines+markers', connectgaps=False))
        else:
            fig.add_trace(go.Bar(**common))
    fig.update_layout(template='plotly_dark', height=350, barmode='group',
                      margin=dict(l=15, r=15, t=25, b=30), hovermode='x unified',
                      legend=dict(orientation='h', y=-.24, font=dict(size=11)),
                      yaxis_title='ร้อยละ (%)' if percent else 'จำนวนหุ้น' if shares else currency,
                      xaxis=dict(title='วันสิ้นงวด (ค.ศ.)', type='category', categoryorder='array',
                                 categoryarray=dates), uirevision='financial-trends')
    return fig


def trend_insights(rows, currency):
    """Describe matched observations without producing an investment score."""
    if not rows:
        return []
    metrics = rows[-1]['metrics']

    def value(key):
        item = metrics[key]
        return item['value'] if item['state'] == 'available' else None

    messages = []
    if value('revenueGrowth') is not None:
        change = value('revenueGrowth') * 100
        messages.append(f'รายได้เทียบงวดเดียวกันปีก่อน {change:+.2f}% · '
                        f'งวดเทียบ {metrics["revenueGrowth"].get("comparison_end")}')
    if value('netIncome') is not None and value('operatingCashflow') is not None and metrics['cashConversion']['state'] != 'period_mismatch':
        if value('netIncome') > 0 and value('operatingCashflow') < 0:
            messages.append('กำไรสุทธิเป็นบวกแต่ OCF ติดลบ ควรอ่านการเปลี่ยนแปลงลูกหนี้ สินค้าคงเหลือ และเจ้าหนี้ประกอบ')
        elif value('cashConversion') is not None:
            messages.append(f'OCF / กำไรสุทธิ = {value("cashConversion"):.2f} เท่า · '
                            'ควรดูหลายงวดร่วมกับเงินทุนหมุนเวียนและรายการครั้งเดียว')
    if value('sbcToRevenue') is not None:
        messages.append(f'SBC เท่ากับ {value("sbcToRevenue") * 100:.2f}% ของรายได้ · '
                        'ค่าใช้จ่ายนี้ไม่ใช่เงินสดซื้อหุ้นคืนและไม่บอกจำนวนหุ้นเพิ่มโดยตรง')
    if value('shareCountGrowth') is not None:
        change = value('shareCountGrowth') * 100
        messages.append(f'หุ้นสามัญ ณ วันสิ้นงวดเปลี่ยน {change:+.2f}% เทียบปีก่อน · '
                        'อ่านหมายเหตุการออกหุ้น ซื้อคืน และแตกหุ้นก่อนสรุปผลต่อผู้ถือหุ้น')
    if value('netBuybackCash') is not None:
        amount = format_trend_value('netBuybackCash', metrics['netBuybackCash'], currency)
        messages.append(f'เงินสดซื้อคืนหักเงินรับออกหุ้น = {amount} · '
                        'เป็นกระแสเงินสด ไม่ใช่จำนวนหุ้นที่ลดลง และไม่หัก SBC ซ้ำเป็นเงินสด')
    return messages


def render_financial_trends(ticker, info, bundle):
    result = build_financial_trends(ticker, info, bundle)
    if result['state'] == 'not_applicable':
        return result
    with st.container(key='financial_trends'):
        st.markdown('#### แนวโน้มการเงินและคุณภาพกำไร')
        if result['state'] != 'available':
            st.info(result['reason'])
            return result
        bases = [basis for basis in BASIS_LABELS if result['periods'][basis]]
        basis = st.radio('รอบบัญชีของกราฟ', bases, format_func=BASIS_LABELS.get,
                         horizontal=True, key=f'financial_trend_basis_{ticker}')
        rows = result['periods'][basis]
        currency = result['currency']
        st.caption(f'{BASIS_LABELS[basis]} · สกุลเงินงบ {currency} · '
                   f'{len(rows)} งวดที่มีรายการรายงาน · ล่าสุด {rows[-1]["end"]} · '
                   f'ดึงงบเมื่อ {result["fetched_at"] or "ไม่ระบุ"}')
        st.caption('TTM รวมเฉพาะ 4 ไตรมาสต่อเนื่อง; หนี้ เงินสด และจำนวนหุ้นสามัญใช้ยอด ณ วันสิ้นงวด '
                   'ช่องว่างหมายถึงข้อมูลไม่ครบหรือพักใช้ ไม่แทนด้วยศูนย์ และไม่รวม EPS หรือหุ้นถัวเฉลี่ยเป็น TTM')
        keys = ('revenueGrowth', 'freeCashflow', 'cashConversion', 'shareCountGrowth')
        for column, key in zip(st.columns(4), keys):
            item = rows[-1]['metrics'][key]
            with column:
                st.metric(LABELS[key], format_trend_value(key, item, currency),
                          help=(f'วันสิ้นงวด {rows[-1]["end"]} · {STATE_LABELS.get(item["state"], item["state"])}\n'
                                f'{item["reason"] or item["formula"]}'))
        topic = st.selectbox('หัวข้อกราฟการเงิน', list(TOPICS), key=f'financial_trend_topic_{ticker}')
        fig = trend_figure(rows, TOPICS[topic], currency, percent=topic == 'อัตรากำไร')
        if fig.data:
            st.plotly_chart(fig, key=f'financial_trend_chart_{ticker}_{basis}',
                            width='stretch', config={'displaylogo': False})
        else:
            st.info('ยังไม่มีค่าที่ผ่านการตรวจสอบสำหรับหัวข้อนี้ในรอบบัญชีที่เลือก')
        if topic == 'ผู้ถือหุ้นและการซื้อหุ้นคืน':
            st.caption('ซื้อหุ้นคืนขั้นต้นและเงินรับออกหุ้นเป็นเงินสด; SBC เป็นค่าใช้จ่ายที่ไม่ใช่เงินสด '
                       'ต้องดูจำนวนหุ้นประกอบ จึงจะประเมินผลต่อผู้ถือหุ้นได้')
            shares = trend_figure(rows, ('ordinarySharesNumber', 'dilutedAverageShares'), currency, shares=True)
            if shares.data:
                st.plotly_chart(shares, key=f'financial_shares_chart_{ticker}_{basis}',
                                width='stretch', config={'displaylogo': False})
            st.caption('หุ้นสามัญคือยอด ณ วันสิ้นงวด ส่วนหุ้นปรับลดเป็นค่าเฉลี่ยถ่วงน้ำหนักของงวด '
                       'การเปลี่ยนแปลงอาจได้รับผลจากการแตกหุ้นหรือการปรับย้อนหลัง '
                       'ไม่ตีความเงินซื้อคืนหรือ SBC เป็นจำนวนหุ้นลด/เพิ่มโดยอัตโนมัติ '
                       'รายการที่แหล่งข้อมูลยังไม่ส่งมาจะแสดงเป็นไม่มีข้อมูลรายงาน')
        insights = trend_insights(rows, currency)
        if insights:
            st.markdown('**ประเด็นจากงวดล่าสุดที่ควรอ่านต่อ**')
            for message in insights:
                st.write('• '+message)
        if result['issues']:
            st.caption(f'พักใช้รายการที่มีปัญหา {len(result["issues"])} จุด; อ่านเหตุผลได้ในรายละเอียดข้อมูล')
        exported = pd.DataFrame(export_trends(result, basis))
        with st.expander('ตรวจตัวเลข สูตร และแหล่งข้อมูลของกราฟ'):
            st.caption('ค่าร้อยละในตารางและ CSV คูณ 100 แล้ว จำนวนเงินเป็นค่าจริงในสกุลเงินงบ '
                       'ข้อมูลหุ้นถัวเฉลี่ย หุ้นสามัญ และเงินรับออกหุ้นขึ้นอยู่กับงบที่แหล่งข้อมูลรายงาน')
            st.dataframe(exported, hide_index=True, width='stretch',
                         column_config={'ค่า': st.column_config.NumberColumn('ค่า', format='%.6f')})
            for issue in result['issues']:
                st.write(issue)
            st.caption('แหล่งข้อมูล: '+str(result['source']))
        st.download_button('ดาวน์โหลดแนวโน้มการเงินทุกงวด',
                           pd.DataFrame(export_trends(result)).to_csv(index=False).encode('utf-8-sig'),
                           f'{ticker}_financial_trends.csv', 'text/csv',
                           key=f'financial_trends_export_{ticker}', on_click='ignore')
    return result
