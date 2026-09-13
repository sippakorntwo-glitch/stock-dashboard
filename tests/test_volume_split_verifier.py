"""Regressions for the real-browser verifier's independent numeric oracle."""
import math

import pytest

from volume_split import split_volume
from volume_split_smoke import verify_volume_payload


AAPL_2024_03_15 = {
    'time': '2024-03-15', 'open': 169.3240932528417,
    'high': 170.75845336914062, 'low': 168.45357838204507,
    'close': 170.75845336914062, 'volume': 121752700,
    'buy_volume_est': 121752700, 'sell_volume_est': 0,
    'unclassified_volume': 0,
}


def payload(record):
    return {'volumeSplitMethod': 'ohlc-close-position-estimate', 'records': [record]}


def test_verifier_accepts_real_close_at_high_without_a_negative_expected_sell():
    record = AAPL_2024_03_15
    old_expected = record['volume']*(record['close']-record['low'])/(record['high']-record['low'])
    assert old_expected > record['volume'], 'Fixture must reproduce the CI floating-point failure'
    assert verify_volume_payload(payload(record))['mixed_bars'] == 0


@pytest.mark.parametrize('boundary', ['high', 'low'])
@pytest.mark.parametrize('one_float_inside', [False, True])
def test_verifier_checks_zero_and_full_allocations_and_the_adjacent_float(boundary, one_float_inside):
    record = dict(AAPL_2024_03_15)
    other = 'low' if boundary == 'high' else 'high'
    record['close'] = (math.nextafter(record[boundary],record[other])
                       if one_float_inside else record[boundary])
    record.update(split_volume(record['volume'],record['high'],record['low'],record['close']))
    verify_volume_payload(payload(record))
    if not one_float_inside:
        assert record['sell_volume_est' if boundary == 'high' else 'buy_volume_est'] == 0


@pytest.mark.parametrize('boundary', ['high', 'low'])
def test_verifier_rejects_negative_boundary_parts_even_if_volume_is_conserved(boundary):
    record = dict(AAPL_2024_03_15, close=AAPL_2024_03_15[boundary])
    epsilon = math.ulp(float(record['volume']))
    record.update(buy_volume_est=record['volume']+epsilon if boundary == 'high' else -epsilon,
                  sell_volume_est=-epsilon if boundary == 'high' else record['volume']+epsilon)
    assert record['buy_volume_est']+record['sell_volume_est'] == record['volume']
    with pytest.raises(AssertionError):
        verify_volume_payload(payload(record))


def test_verifier_roundoff_budget_is_bounded_in_ulps_even_when_total_is_correct():
    record = dict(AAPL_2024_03_15)
    record['close'] = (record['high']+record['low'])/2
    record.update(split_volume(record['volume'],record['high'],record['low'],record['close']))
    verify_volume_payload(payload(record))
    epsilon = 8*math.ulp(float(record['volume']))
    record['buy_volume_est'] += epsilon
    record['sell_volume_est'] -= epsilon
    assert record['buy_volume_est']+record['sell_volume_est'] == record['volume']
    with pytest.raises(AssertionError):
        verify_volume_payload(payload(record))
