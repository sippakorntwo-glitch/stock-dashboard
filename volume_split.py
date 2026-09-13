"""Explicit OHLC range-position proxy; never classified exchange trade volume.

Yahoo's prepared bars only contain total volume. These allocations describe the
closing price's position within that bar, not observed buyer/seller initiation.
Missing volume stays missing; a flat price range stays unclassified.
"""
from __future__ import annotations
import math

METHOD = 'ohlc-close-position-estimate'


def split_volume(volume, high, low, close):
    result = {'buy_volume_est': None, 'sell_volume_est': None,
              'unclassified_volume': None}
    values = (volume, high, low, close)
    if any(isinstance(v, bool) for v in values):
        return result
    try:
        v, h, l, c = map(float, values)
    except (TypeError, ValueError, OverflowError):
        return result
    if not all(math.isfinite(x) for x in (v, h, l, c)) or v < 0 or h < l or not l <= c <= h:
        return result
    if v == 0:
        return dict(buy_volume_est=0.0, sell_volume_est=0.0, unclassified_volume=0.0)
    if h == l:
        result['unclassified_volume'] = v
        return result
    # No rounding of the stored estimates: buy + sell exactly retains total V
    # up to floating-point precision, including fractional-volume instruments.
    buy = v * ((c-l)/(h-l))
    return dict(buy_volume_est=buy, sell_volume_est=v-buy, unclassified_volume=0.0)
