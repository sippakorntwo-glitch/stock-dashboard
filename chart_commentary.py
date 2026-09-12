"""Read-only chart commentary from the exact plotted payload; no provider calls.

Recent trend describes the last plotted bar, not the return over the entire
selected preset. All indicator periods count bars of the chart's interval.
No new trade score, predicted return, backtest claim, or price target is created.
"""
from __future__ import annotations
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from html import escape
import json
import math
from zoneinfo import ZoneInfo
from chart_performance import period_performance, format_return, _date_label

TITLE = 'สรุปแนวโน้มและวิเคราะห์กราฟ'
METHOD = 'chart-commentary-v1'


def number(value, *, positive=False, nonnegative=False):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or (positive and value <= 0) or (nonnegative and value < 0):
        return None
    return value


def instant(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def pct(current, previous):
    current, previous = number(current, positive=True), number(previous, positive=True)
    return number((current / previous - 1) * 100) if current and previous else None


def atr14(records):
    """Wilder average with 14-bar SMA seed, matching the existing daily helper."""
    ranges = []
    previous = None
    for row in records:
        high, low, close, opening = (number(row.get(k), positive=True) for k in ('high', 'low', 'close', 'open'))
        if any(v is None for v in (high, low, close, opening)) or not low <= min(opening, close) <= max(opening, close) <= high:
            return None
        ranges.append(max(high-low, abs(high-previous), abs(low-previous)) if previous else high-low)
        previous = close
    if len(ranges) < 14:
        return None
    value = math.fsum(ranges[:14]) / 14
    for true_range in ranges[14:]:
        value = (13 * value + true_range) / 14
    return number(value, nonnegative=True)


def summarize_chart(payload: Mapping, *, now=None) -> dict:
    """Deterministic price/indicator facts, with time used only for freshness."""
    output = {'method': METHOD, 'ticker': str(payload.get('ticker', '')), 'period': str(payload.get('period', '')),
              'interval': str(payload.get('interval', '')), 'available': False,
              'reason': 'ข้อมูลกราฟไม่พอสำหรับสรุป', 'warnings': []}
    records, start = payload.get('records'), payload.get('visibleStart')
    if (payload.get('demo') or not isinstance(records, (tuple, list)) or not records
            or isinstance(start, bool) or not isinstance(start, int) or not 0 <= start < len(records)
            or not all(isinstance(r, Mapping) for r in records)):
        return output
    interval = output['interval']
    if interval not in ('1d', '5m'):
        output['reason'] = 'ยังไม่รองรับการสรุปขนาดแท่งนี้'
        return output
    # Do not silently sort/drop bad rows and then attach different observations
    # to the original chart's dates or warm-up index.
    times = [r.get('time') for r in records]
    try:
        if any(t is None or isinstance(t, bool) for t in times) or any(a >= b for a, b in zip(times, times[1:])):
            return output
    except TypeError:
        return output
    last = records[-1]
    close = number(last.get('close'), positive=True)
    if close is None:
        output['reason'] = 'ราคาปิดแท่งล่าสุดไม่ใช่ค่าบวกที่ใช้ได้'
        return output
    precision = payload.get('precision', 2)
    if isinstance(precision, bool) or not isinstance(precision, int):
        precision = 2
    metric = {k: number(last.get(k), positive=k in ('ema20', 'ema50', 'sma200'))
              for k in ('ema20', 'ema50', 'sma200', 'rsi', 'macd', 'signal', 'hist')}
    # Respect warm-up even when a malformed external payload supplies a number.
    for k, minimum in {'ema20':20, 'ema50':50, 'sma200':200, 'rsi':15, 'macd':26, 'signal':34, 'hist':34}.items():
        if len(records) < minimum:
            metric[k] = None
    if metric['rsi'] is not None and not 0 <= metric['rsi'] <= 100:
        metric['rsi'] = None
    slopes = {key: pct(metric[key], records[-6].get(key)) if len(records) >= minimum else None
              for key, minimum in (('ema20',25), ('ema50',55))}
    ema20, ema50, sma = (metric[k] for k in ('ema20','ema50','sma200'))
    ordered_up = ema20 is not None and ema50 is not None and close > ema20 > ema50
    ordered_down = ema20 is not None and ema50 is not None and close < ema20 < ema50
    rising = all(v is not None and v > 0 for v in slopes.values())
    falling = all(v is not None and v < 0 for v in slopes.values())
    trend = ('insufficient' if ema20 is None or ema50 is None else
             'uptrend' if ordered_up and rising else
             'downtrend' if ordered_down and falling else 'mixed')
    regime = 'unknown' if sma is None else 'above' if close > sma else 'below' if close < sma else 'at'
    # The window's total return and its last-bar trend are deliberately separate.
    perf = period_performance(payload)
    prior_window = records[max(start, len(records)-21):-1]
    support = resistance = None
    if len(prior_window) >= 5:
        lows = [number(r.get('low'), positive=True) for r in prior_window]
        highs = [number(r.get('high'), positive=True) for r in prior_window]
        if all(v is not None for v in lows+highs) and all(lo <= hi for lo,hi in zip(lows,highs)):
            support, resistance = min(lows), max(highs)
    level_state = ('unknown' if support is None else 'breakout' if close > resistance else
                   'breakdown' if close < support else 'inside')
    volume = number(last.get('volume'), nonnegative=True)
    volumes = [number(r.get('volume'), nonnegative=True) for r in records[-21:-1]]
    average = math.fsum(volumes)/20 if len(volumes)==20 and all(v is not None for v in volumes) else None
    volume_ratio = number(volume/average, nonnegative=True) if volume is not None and average is not None and average>0 else None
    atr = atr14(records)
    previous_hist = number(records[-2].get('hist')) if len(records) >= 35 else None
    hist_delta = number(metric['hist']-previous_hist) if metric['hist'] is not None and previous_hist is not None else None
    observed = instant(times[-1]) if interval=='5m' else None
    acquired = instant(payload.get('fetchedAt'))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    effective = min(acquired, current) if acquired else None
    bar_state = 'unknown'
    if effective:
        if interval=='5m' and observed:
            bar_state = 'closed' if observed+timedelta(minutes=5)<=effective else 'provisional'
        elif interval=='1d':
            try:
                day = datetime.strptime(times[-1], '%Y-%m-%d').date()
                bar_state = 'closed' if day < effective.astimezone(ZoneInfo('America/New_York')).date() else 'provisional'
            except (TypeError, ValueError):
                pass
    warnings = output['warnings']
    if acquired and acquired > current + timedelta(seconds=60):
        warnings.append('เวลารับข้อมูลอยู่ในอนาคตเมื่อเทียบกับเวลาเซิร์ฟเวอร์ ต้องตรวจแหล่งข้อมูล')
        bar_state = 'unknown'
    if observed and observed > current + timedelta(seconds=60):
        warnings.append('เวลาแท่งราคาอยู่ในอนาคต ไม่ควรใช้สรุปเป็นจังหวะปัจจุบัน')
        bar_state = 'unknown'
    if bar_state!='closed':
        warnings.append('แท่งล่าสุดอาจยังไม่ปิดหรือยืนยันเวลาไม่ได้: การอ่านแนวโน้มและการทะลุกรอบยังเป็นเพียงชั่วคราว')
    if not perf['full_window']:
        warnings.append('ประวัติไม่ครบช่วงที่เลือก: ผลตอบแทนและแนวโน้มสะท้อนเฉพาะข้อมูลจริงที่มี')
    if interval=='5m':
        warnings.append('EMA/RSI/MACD/ATR นับแท่ง 5 นาที ไม่ใช่จำนวนวัน; Volume เทียบ 20 แท่งก่อนหน้าและไม่ได้ปรับฤดูกาลระหว่างวัน')
        if observed and (current-observed).total_seconds()>15*60:
            warnings.append('แท่ง 5 นาทีล่าสุดเก่ากว่า 15 นาที อาจเป็นช่วงปิดตลาดหรือข้อมูลล่าช้า ไม่ใช่ภาพราคาขณะนี้')
    else:
        try:
            if (current.astimezone(ZoneInfo('America/New_York')).date()-datetime.strptime(times[-1],'%Y-%m-%d').date()).days>4:
                warnings.append('ราคาล่าสุดเก่ากว่า 4 วันปฏิทิน อาจเป็นวันหยุดหรือข้อมูลล่าช้า')
        except (ValueError, TypeError):
            warnings.append('ตรวจอายุราคาจากวันที่ของแท่งไม่ได้')
    if trend=='insufficient':
        warnings.append('ข้อมูลยังไม่พอสำหรับ EMA20/EMA50 จึงยังสรุปแนวโน้มล่าสุดไม่ได้')
    output.update(available=True, reason='', precision=max(2,min(8,precision)),
                  latest_time=times[-1], close=close, metrics=metric, slopes_5bars=slopes,
                  trend=trend, regime=regime, distance_ema20_pct=pct(close,ema20),
                  return_window=perf, visible_bars=len(records)-start, available_bars=len(records),
                  levels={'support':support,'resistance':resistance,'bars':len(prior_window), 'state':level_state},
                  volume=volume, average_volume_20=average, volume_ratio=volume_ratio,
                  atr14=atr, atr_pct=number(atr/close*100) if atr is not None else None,
                  histogram_change=hist_delta, bar_state=bar_state,
                  timezone=str(payload.get('timezone') or 'UTC'), fetched_at=payload.get('fetchedAt',''))
    return output


STYLE = '''<style>
.chart-reading{border:1px solid #3d526d;border-top:3px solid #70d3e5;border-radius:14px;background:linear-gradient(125deg,#13223a,#151d31);padding:20px 22px;margin:12px 0 20px;color:#eaf2ff;overflow-wrap:anywhere}
.chart-reading h3{margin:0 0 8px!important;font-size:1.22rem!important;color:#c5edff!important}.chart-reading h4{margin:0 0 7px!important;font-size:1rem!important;color:#cfceff!important}
.chart-reading p{margin:5px 0 10px;line-height:1.65}.chart-reading .reading-meta,.chart-reading .reading-note{font-size:.82rem;color:#b5c7df;line-height:1.6}
.chart-reading .reading-lead{font-size:1.03rem;border-left:3px solid #c5b3ff;padding:9px 13px;background:#1b2b43;border-radius:5px}
.chart-reading .reading-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}.chart-reading .reading-cell{border:1px solid #354760;border-radius:10px;padding:14px;background:#101e32}
.chart-reading .reading-scenarios{border-top:1px solid #43526a;padding-top:12px}.chart-reading .reading-warning{color:#ffdaa0;background:#332d27;padding:8px 11px;border-radius:6px;font-size:.84rem;margin-top:8px}
.chart-reading .reading-badge{display:inline-block;border:1px solid #73809b;border-radius:18px;padding:3px 12px;font-weight:650;margin:0 0 7px;background:#24314b}.chart-reading .uptrend{color:#9df4d7;border-color:#598977}.chart-reading .downtrend{color:#ffb8bf;border-color:#985f6b}.chart-reading a{color:#a8e4ff;text-decoration:underline}
@media(max-width:720px){.chart-reading{padding:15px}.chart-reading .reading-grid{grid-template-columns:1fr}}
</style>'''


def commentary_html(payload: Mapping, *, now=None) -> str:
    data = summarize_chart(payload, now=now)
    esc = lambda text: escape(str(text), quote=True)
    tag = f'<section class="chart-reading" aria-label="{TITLE}" data-ticker="{esc(data["ticker"])}" data-period="{esc(data["period"])}" data-report="{esc(json.dumps(data,ensure_ascii=False,allow_nan=False))}">'
    heading = f'<h3>{TITLE} · {esc(data["ticker"])}</h3>'
    if not data['available']:
        return STYLE+tag+heading+f'<p>{esc(data["reason"])} ไม่เติมข้อสรุปจากราคาจำลอง</p></section>'
    precision = data['precision']
    fmt = lambda value, places=precision: '—' if value is None else f'{value:,.{places}f}'
    m, levels, perf = data['metrics'], data['levels'], data['return_window']
    bar = '1 วัน' if data['interval']=='1d' else '5 นาที'
    recent = {'uptrend':'ขาขึ้นตาม EMA', 'downtrend':'ขาลงตาม EMA', 'mixed':'สัญญาณผสม / ทิศทางยังไม่ชัด', 'insufficient':'ข้อมูลแนวโน้มยังไม่พอ'}[data['trend']]
    if data['trend']=='uptrend':
        lead = 'ราคาปิดอยู่เหนือ EMA20 และ EMA50 โดย EMA20 > EMA50 และทั้งสองเส้นสูงกว่าค่าเมื่อ 5 แท่งก่อน สะท้อนแนวโน้มล่าสุดที่เอนขึ้น'
    elif data['trend']=='downtrend':
        lead = 'ราคาปิดอยู่ต่ำกว่า EMA20 และ EMA50 โดย EMA20 < EMA50 และทั้งสองเส้นต่ำกว่าค่าเมื่อ 5 แท่งก่อน สะท้อนแนวโน้มล่าสุดที่เอนลง'
    elif data['trend']=='mixed':
        lead = 'การเรียงตัวของราคาและ EMA20/EMA50 หรือความชันย้อนหลัง 5 แท่งยังไม่สอดคล้องกัน จึงยังไม่ยืนยันขาขึ้นหรือขาลงชัดเจน; ไม่ได้แปลว่าเป็น Sideways แน่นอน'
    else:
        lead = 'ต้องมีข้อมูลอย่างน้อย 50 แท่งเพื่ออ่าน EMA ทั้งสอง และ 55 แท่งเพื่อเปรียบเทียบความชันครบ 5 แท่ง'
    regime = {'above':'ราคายืนเหนือ SMA200 เป็นโครงสร้างที่ดีกว่าการอยู่ใต้เส้นนี้', 'below':'ราคาอยู่ใต้ SMA200 โครงสร้าง 200 แท่งยังอ่อนกว่าระดับค่าเฉลี่ย', 'at':'ราคาอยู่ใกล้/เท่ากับ SMA200 ตามความละเอียดข้อมูล', 'unknown':'ยังไม่มี SMA200 ที่ใช้ได้ (ต้องมีอย่างน้อย 200 แท่ง)'}[data['regime']]
    overview = f'ช่วง {data["period"]}: ผลตอบแทนสะสม {format_return(perf["percent"])} จาก Close {fmt(perf["start_price"])} → {fmt(perf["end_price"])}'
    overview += f' · {_date_label(perf["start_time"],data["timezone"])} ถึง {_date_label(perf["end_time"],data["timezone"])}'
    rsi = m['rsi']
    rsi_text = ('ข้อมูล RSI14 ไม่พอ' if rsi is None else
                'อยู่ในโซนสูงกว่า 70: โมเมนตัมร้อนแรงและควรระวังการพักตัว แต่ไม่ใช่สัญญาณขายอัตโนมัติ' if rsi>70 else
                'อยู่ในโซนต่ำกว่า 30: แรงขายเด่น แต่ไม่ยืนยันว่าจะเด้งหรือเป็นจุดซื้อทันที' if rsi<30 else
                'อยู่ระหว่าง 50–70: โมเมนตัมเอนบวก แต่ยังต้องดูแนวโน้มและราคา' if rsi>50 else
                'อยู่ระหว่าง 30–50: โมเมนตัมเอนลบ แต่ยังต้องดูแนวโน้มและราคา' if rsi<50 else 'อยู่ที่ 50: แรงส่งยังสมดุลตามตัวชี้วัดนี้')
    macd_text = ('ข้อมูล MACD/Signal ไม่พอ' if m['macd'] is None or m['signal'] is None else
                 'MACD อยู่เหนือ Signal' if m['macd']>m['signal'] else
                 'MACD อยู่ใต้ Signal' if m['macd']<m['signal'] else 'MACD เท่ากับ Signal')
    if m['hist'] is not None:
        macd_text += f' · Histogram {fmt(m["hist"],4)}'
    if data['histogram_change'] is not None:
        delta = data['histogram_change']
        macd_text += ' สูงขึ้นจากแท่งก่อน' if delta>0 else ' ลดลงจากแท่งก่อน' if delta<0 else ' เท่าแท่งก่อน'
    volume_text = ('ยังเปรียบเทียบ Volume ไม่ได้ ต้องมีแท่งล่าสุดและ Volume ครบ 20 แท่งก่อนหน้าโดยค่าเฉลี่ยมากกว่าศูนย์' if data['volume_ratio'] is None else
                   f'Volume ล่าสุด {fmt(data["volume"],0)} เทียบค่าเฉลี่ย 20 แท่งก่อนหน้า {fmt(data["average_volume_20"],0)} = {fmt(data["volume_ratio"],2)}x; '+
                   ('สูงกว่าค่าเฉลี่ย' if data['volume_ratio']>1 else 'ต่ำกว่าค่าเฉลี่ย' if data['volume_ratio']<1 else 'เท่าค่าเฉลี่ย')+' ปริมาณซื้อขายไม่บอกทิศทางด้วยตัวมันเอง')
    level_text = ('ข้อมูลกรอบราคาไม่พอ ต้องมี High/Low ที่ใช้ได้อย่างน้อย 5 แท่งก่อนหน้าในช่วงที่เลือก' if levels['support'] is None else
                  f'กรอบ {levels["bars"]} แท่งก่อนหน้าภายในช่วงที่เลือก (ไม่รวมแท่งล่าสุด): Low {fmt(levels["support"])} / High {fmt(levels["resistance"])}; '+
                  {'inside':'ราคายังอยู่ในกรอบเดิม','breakout':'ราคาล่าสุดสูงกว่าขอบบนเดิม','breakdown':'ราคาล่าสุดต่ำกว่าขอบล่างเดิม'}[levels['state']])
    volatility = ('ATR14 ยังไม่มีค่าที่ใช้ได้' if data['atr14'] is None else f'ATR14 = {fmt(data["atr14"])} หรือ {fmt(data["atr_pct"],2)}% ของราคา เป็นขนาดความผันผวนต่อแท่ง ไม่ใช่เป้าราคาหรือโอกาสขาดทุน')
    if levels['support'] is None:
        scenarios = 'ยังไม่มีกรอบราคาที่พอสร้างเงื่อนไขติดตาม ไม่สร้างแนวรับ/แนวต้านขึ้นมาแทนข้อมูลที่ขาด'
    else:
        scenarios = (f'ด้านบวก: ติดตามการปิดแท่งเหนือกรอบอ้างอิง {fmt(levels["resistance"])} และดู Volume/โมเมนตัมประกอบ; '
                     f'ด้านลบ: การปิดแท่งต่ำกว่า {fmt(levels["support"])} เป็นเหตุให้ทบทวนความแข็งแรงของกรอบเดิม '
                     'ระดับเหล่านี้เป็น High/Low ย้อนหลังสำหรับเฝ้าดู ไม่ใช่แนวรับ/แนวต้านหรือราคาเป้าหมายที่รับประกัน')
    def cell(title, text):
        return f'<div class="reading-cell"><h4>{esc(title)}</h4><p>{esc(text)}</p></div>'
    ema_text = f'Close {fmt(data["close"])} · EMA20 {fmt(m["ema20"])} · EMA50 {fmt(m["ema50"])} · SMA200 {fmt(m["sma200"])}. {regime}.'
    if data['distance_ema20_pct'] is not None:
        ema_text += f' ราคาห่างจาก EMA20 {format_return(data["distance_ema20_pct"])}'
    meta = f'ช่วงที่เลือก {data["period"]} · แท่ง {bar} · อ้างอิงแท่ง {_date_label(data["latest_time"],data["timezone"])} · ข้อมูล {data["visible_bars"]:,} แท่งในช่วงนี้'
    body = heading+f'<p class="reading-meta">{esc(meta)}</p><span class="reading-badge {data["trend"]}">{recent}</span>'
    body += f'<p class="reading-lead">{esc(lead)}</p><p>{esc(overview)}</p><p class="reading-note">ผลตอบแทนทั้งช่วงอาจเป็นบวกแม้แนวโน้มล่าสุดเริ่มอ่อนตัว และกลับกัน จึงแยกสองมิตินี้ออกจากกัน</p>'
    body += '<div class="reading-grid">'+cell('แนวโน้มและเส้นค่าเฉลี่ย',ema_text)+cell('โมเมนตัม · RSI / MACD',f'RSI14 {fmt(rsi,2)}: {rsi_text}. MACD {fmt(m["macd"],4)} / Signal {fmt(m["signal"],4)}: {macd_text}.')+cell('แนวรับ–แนวต้านอ้างอิง',level_text)+cell('Volume และความผันผวน',volume_text+'. '+volatility)+'</div>'
    body += f'<div class="reading-scenarios"><h4>เงื่อนไขที่ควรติดตามจากกราฟ</h4><p>{esc(scenarios)}</p></div>'
    body += ''.join(f'<p class="reading-warning">{esc(warning)}</p>' for warning in data['warnings'])
    body += '<p class="reading-note">สรุปตามกติกาจากข้อมูลชุดเดียวกับกราฟ ไม่ใช่การวิเคราะห์ข่าว/งบหรือคำสั่งซื้อขาย และไม่เปลี่ยนคะแนนหรือบอร์ด Top 10 · ใช้ตัวชี้วัดทุกตัวข้างต้นแม้ซ่อนเส้นบนกราฟ · การชี้เมาส์ ลาก หรือซูมไม่เปลี่ยนข้อสรุปนี้</p>'
    body += '<details><summary>หลักการอ่านและขอบเขต</summary><p class="reading-note">EMA20/50 ต้องเรียงตัวพร้อมความชันย้อนหลัง 5 แท่งจึงเรียกขาขึ้น/ขาลง; SMA200 อธิบายโครงสร้าง 200 แท่ง ไม่ใช่ผลตอบแทนทั้งช่วง. กรอบราคาใช้ได้สูงสุด 20 แท่งก่อนหน้าในช่วงที่เลือก. ATR14 ใช้ Wilder average. เกณฑ์เป็นกติกาอธิบายกราฟ ไม่ใช่ความน่าจะเป็นกำไร และไม่ตรวจ divergence หรือรูปแบบแท่งเทียนอัตโนมัติ.</p><p class="reading-note">หลักการอินดิเคเตอร์: <a href="https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/" target="_blank" rel="noopener noreferrer">RSI</a> · <a href="https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/" target="_blank" rel="noopener noreferrer">ATR</a></p></details>'
    return STYLE+tag+body+'</section>'
