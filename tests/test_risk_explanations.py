"""Risk explanations follow selected observations and retain native help/charts."""
import pandas as pd
import pytest

from analytics import risk_metrics
from risk_explanations import (RISK_METRIC_HELP, drawdown_band, risk_summary,
                               volatility_band)


def close_series(values):
    return pd.Series(values, index=pd.date_range('2025-01-01', periods=len(values)), dtype=float)


@pytest.mark.parametrize('value,expected', [
    (None, 'ข้อมูลไม่พอ'), (float('nan'), 'ข้อมูลไม่พอ'), (-1, 'ข้อมูลไม่พอ'),
    (0, 'แกว่งน้อย'), (14.99, 'แกว่งน้อย'), (15, 'แกว่งปานกลาง'),
    (29.99, 'แกว่งปานกลาง'), (30, 'แกว่งมาก'),
    (29.999999999999996, 'แกว่งมาก'),
])
def test_volatility_bands_include_exact_boundaries(value, expected):
    assert volatility_band(value) == expected


@pytest.mark.parametrize('value,expected', [
    (None, 'ข้อมูลไม่พอ'), (float('inf'), 'ข้อมูลไม่พอ'), (1, 'ข้อมูลไม่พอ'),
    (0, 'ย่อตื้น'), (-9.99, 'ย่อตื้น'), (-10, 'ย่อปานกลาง'),
    (-19.99, 'ย่อปานกลาง'), (-20, 'ย่อลึก'),
    ((90 / 100 - 1) * 100, 'ย่อปานกลาง'),
])
def test_drawdown_bands_use_depth_not_signed_order(value, expected):
    assert drawdown_band(value) == expected


def test_observed_drawdown_dates_and_distribution_are_not_start_return():
    close = close_series([100, 120, 90, 110])
    stats = risk_metrics(close.to_frame('Close'))
    text = '\n'.join(risk_summary(close, stats))
    assert stats['return_pct'] == pytest.approx(10)
    assert 'ย่อลึกสุด -25.00%' in text
    assert 'จากยอดวันที่ 2025-01-02 ถึงวันที่ 2025-01-03' in text
    assert 'ล่าสุดอยู่ -8.33%' in text
    assert 'ดีที่สุด +22.22% (2025-01-04)' in text
    assert 'แย่ที่สุด -25.00% (2025-01-03)' in text
    assert '4 ราคาปิด / 3 ช่วงผลตอบแทน' in text
    assert 'อย่างน้อย 20 จุด' in text and 'ยังไม่ถึง 365 วัน' in text
    assert 'ไม่ใช่ความน่าจะเป็นในอนาคต' in text


def test_negative_returns_do_not_become_positive_best_day():
    close = close_series([100, 90, 80])
    text = '\n'.join(risk_summary(close, risk_metrics(close.to_frame('Close'))))
    assert 'ดีที่สุด -10.00% (2025-01-02)' in text
    assert 'แย่ที่สุด -11.11% (2025-01-03)' in text
    assert 'ย่อลึกสุด -20.00%' in text


@pytest.mark.parametrize('values', [[], [100]])
def test_insufficient_observations_are_missing_not_zero_risk(values):
    close = close_series(values)
    text = '\n'.join(risk_summary(close, risk_metrics(close.to_frame('Close'))))
    assert 'อย่างน้อย 2 วัน' in text and 'ไม่ใช่ความเสี่ยงเท่ากับศูนย์' in text
    assert '0.00%' not in text and 'ดีที่สุด' not in text


def test_no_drawdown_does_not_claim_no_risk():
    close = close_series([100, 110, 120])
    text = '\n'.join(risk_summary(close, risk_metrics(close.to_frame('Close'))))
    assert 'ยังไม่พบการย่อลง' in text and 'ไม่ได้แปลว่าไม่มีความเสี่ยง' in text
    assert 'แย่ที่สุด +9.09%' in text


def test_help_definitions_match_calculation_and_disclose_display_bands():
    assert set(RISK_METRIC_HELP) == {'return_pct', 'cagr_pct', 'volatility_pct', 'max_drawdown_pct'}
    assert '365.25' in RISK_METRIC_HELP['cagr_pct'] and '365 วัน' in RISK_METRIC_HELP['cagr_pct']
    assert 'ddof=1' in RISK_METRIC_HELP['volatility_pct'] and '√252' in RISK_METRIC_HELP['volatility_pct']
    for key in ('volatility_pct', 'max_drawdown_pct'):
        assert 'เกณฑ์ตัวอย่าง' in RISK_METRIC_HELP[key] and 'ไม่ใช่มาตรฐานสากล' in RISK_METRIC_HELP[key]
    assert 'ผลตอบแทนสูงไม่ได้แปลว่าความเสี่ยงต่ำ' in RISK_METRIC_HELP['return_pct']


def risk_app():
    import numpy as np
    import pandas as pd
    from dashboard_views import risk
    history = pd.DataFrame({'Close': 100 * np.exp(np.linspace(0, 0.6, 800) + np.sin(np.arange(800) / 11) / 20)},
                           index=pd.bdate_range(end='2025-12-31', periods=800))
    history = history.assign(Open=history.Close, High=history.Close + 1,
                             Low=history.Close - 1, Volume=1_000)
    risk('TEST', history)


def test_native_metric_tooltips_and_box_update_with_window_without_extra_charts():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(risk_app, default_timeout=30).run()
    assert not at.exception
    assert len(at.metric) == 4 and len(at.get('plotly_chart')) == 2
    assert [metric.proto.help for metric in at.metric] == list(RISK_METRIC_HELP.values())
    assert any('อ่านกราฟและความเสี่ยงของช่วงนี้' in item.value for item in at.markdown)
    initial = next(item.value for item in at.markdown if 'ช่วงที่นำมาอธิบาย' in item.value)
    assert '2024-12-31 ถึง 2025-12-31' in initial
    assert any('เกณฑ์ตัวอย่าง' in item.value for item in at.markdown)
    before_keys = [chart.proto.id for chart in at.get('plotly_chart')]
    assert before_keys[0].endswith('-drawdown') and before_keys[1].endswith('-daily_distribution')
    at.radio(key='risk_period').set_value('ทั้งหมด').run()
    assert not at.exception
    assert len(at.metric) == 4 and len(at.get('plotly_chart')) == 2
    changed = next(item.value for item in at.markdown if 'ช่วงที่นำมาอธิบาย' in item.value)
    assert '800 ราคาปิด / 799 ช่วงผลตอบแทน' in changed
    assert changed != initial
    assert at.metric[0].proto.help == RISK_METRIC_HELP['return_pct']
