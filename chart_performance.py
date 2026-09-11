"""Cumulative return for the selected chart period, not the last-bar change.

Uses exactly the first/last close of the requested window from the chart's
normalized records. Earlier indicator warm-up bars, quote prices and scoring
history never enter this calculation. No provider calls or annualization.
"""
from __future__ import annotations
from collections.abc import Mapping
from datetime import datetime, timezone
from html import escape
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASIS = 'first-visible-close-to-last-close'


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def period_performance(payload: Mapping) -> dict:
    """Return JSON-safe observations; missing/invalid data is never a 0% return."""
    result = dict(percent=None, amount=None, start_price=None, end_price=None,
                  start_time=None, end_time=None, observations=0,
                  full_window=payload.get('full_window') is True, basis=BASIS,
                  reason='ข้อมูลราคาไม่เพียงพอ')
    records = payload.get('records', [])
    start = payload.get('visibleStart')
    if (not isinstance(records, (list, tuple)) or not records
            or isinstance(start, bool) or not isinstance(start, int)
            or not 0 <= start < len(records) or payload.get('demo')):
        return result
    first, last = records[start], records[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return result
    count = len(records) - start
    initial, final = _positive(first.get('close')), _positive(last.get('close'))
    result.update(start_price=initial, end_price=final,
                  start_time=first.get('time'), end_time=last.get('time'),
                  observations=count)
    if count < 2 or first.get('time') is None or last.get('time') is None or first['time'] == last['time']:
        return result
    if initial is None or final is None:
        result['reason'] = 'ราคาเริ่มต้นหรือราคาสิ้นสุดไม่สมบูรณ์'
        return result
    percent, amount = (final / initial - 1) * 100, final - initial
    if not math.isfinite(percent) or not math.isfinite(amount):
        result['reason'] = 'ไม่สามารถคำนวณจากราคาที่มี'
        return result
    result.update(percent=percent, amount=amount, reason='')
    return result


def format_return(percent):
    if percent is None or not math.isfinite(percent):
        return '—'
    return '0.00%' if abs(percent) < .005 else f'{percent:+,.2f}%'


def _date_label(value, zone):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            try:
                tz = ZoneInfo(zone)
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                tz = timezone.utc
            return datetime.fromtimestamp(value, tz).strftime('%Y-%m-%d %H:%M %Z')
        except (ValueError, OverflowError, OSError):
            return '—'
    return str(value) if value is not None else '—'


def performance_card(payload):
    perf = period_performance(payload)
    period = str(payload.get('period', 'ช่วงที่เลือก'))
    title = 'ผลตอบแทนสะสม · ' + period
    if not perf['full_window']:
        title = 'ผลตอบแทนข้อมูลที่มี · เลือก ' + period
    percent = perf['percent']
    direction = 'up' if percent is not None and percent > 0 else 'down' if percent is not None and percent < 0 else 'flat'
    try:
        precision = max(2, min(8, int(payload.get('precision', 2))))
    except (TypeError, ValueError):
        precision = 2
    if percent is None:
        prices = perf['reason']
    else:
        prices = f"Close {perf['start_price']:,.{precision}f} → {perf['end_price']:,.{precision}f}"
    start, end = (_date_label(perf[k], payload.get('timezone', 'UTC')) for k in ('start_time', 'end_time'))
    note = 'Close แรก → ล่าสุดในช่วงที่เลือก · ราคาปรับแล้ว · ไม่ใช่ CAGR'
    if not perf['full_window']:
        note += ' · ประวัติไม่ครบช่วง'
    attr = '' if percent is None else repr(percent)
    return (f'<div id="range-return" class="range-return-card {direction}" data-period="{escape(period, quote=True)}">'
            f'<div id="range-return-label">{escape(title)}</div>'
            f'<div id="range-return-value" data-value="{attr}">{format_return(percent)}</div>'
            f'<div id="range-return-prices">{escape(prices)}</div>'
            f'<div id="range-return-dates">{escape(start)} → {escape(end)}</div>'
            f'<div id="range-return-basis">{escape(note)}</div></div>')


_STYLE = '''
.range-return-card{border-left:1px solid #303b4d;padding-left:18px;max-width:100%;font-variant-numeric:tabular-nums}
#range-return-label{font-size:12px;color:#a7b7ce;font-weight:600}
#range-return-value{font-size:26px;font-weight:700;line-height:1.4}
.range-return-card.up #range-return-value{color:#26a69a}
.range-return-card.down #range-return-value{color:#ef5350}
#range-return-prices{font-size:12px;color:#dde3ef}
#range-return-dates,#range-return-basis{font-size:10px;color:#94a3bb;margin-top:3px;overflow-wrap:anywhere}
@media(max-width:620px){.range-return-card{border-left:0;border-top:1px solid #303b4d;padding:10px 0 0;width:100%}#range-return-value{font-size:23px}}
'''


def with_performance(html: str, payload: Mapping) -> str:
    """Enhance the existing chart header without touching chart JS or price data."""
    anchor = '<div class="tag" id="status">'
    if html.count(anchor) != 1 or '</style>' not in html:
        raise ValueError('Chart header template changed; performance insertion needs review')
    return html.replace('</style>', _STYLE + '</style>', 1).replace(anchor, performance_card(payload) + anchor, 1)
