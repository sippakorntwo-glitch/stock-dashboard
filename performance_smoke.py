"""Verify the displayed return from actual chart closes, and absence of value tips."""
from __future__ import annotations
import math
from playwright.sync_api import expect
from enhanced_smoke import wait_range


def assert_plain_value_cells(app):
    # Every explanatory table declares the single column allowed to retain help.
    tables = app.locator('.workspace-help-table')
    assert tables.count() >= 4
    counts = []
    for table in tables.all():
        label = int(table.get_attribute('data-tooltip-column'))
        assert table.locator('thead abbr, thead [title]').count() == 0
        findings = table.evaluate('''(table) => {
            const allowed = Number(table.dataset.tooltipColumn);
            let valid = 0, forbidden = 0;
            for (const row of table.tBodies[0].rows) {
                Array.from(row.cells).forEach((cell, i) => {
                    const tips = cell.querySelectorAll('abbr, [title]').length;
                    if (i === allowed) valid += tips;
                    else forbidden += tips + (cell.textContent.includes('ⓘ') ? 1 : 0);
                });
            }
            return {valid, forbidden};
        }''')
        assert findings['forbidden'] == 0, findings
        if label >= 0:
            assert findings['valid'] > 0, findings
        counts.append(findings)
    return counts


def verify_growth_and_plain_cells(page, app):
    report = {'plain_value_cells': assert_plain_value_cells(app), 'period_returns': []}
    for period in ('7 วัน', '10 ปี', '1 ปี'):
        app.get_by_role('radiogroup', name='ช่วงเวลาแสดงกราฟ').get_by_text(period, exact=True).click()
        frame, payload = wait_range(page, app, period)
        perf = payload['periodReturn']
        rows = payload['records'][payload['visibleStart']:]
        expected = (rows[-1]['close'] / rows[0]['close'] - 1) * 100
        assert len(rows) >= 2 and not payload.get('demo')
        assert perf['basis'] == 'first-visible-close-to-last-close'
        assert perf['start_price'] == rows[0]['close'] and perf['end_price'] == rows[-1]['close']
        assert math.isclose(perf['percent'], expected, rel_tol=1e-10, abs_tol=1e-10)
        value = frame.locator('#range-return-value')
        expect(value).to_be_visible()
        actual = float(value.get_attribute('data-value'))
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
        display = '0.00%' if abs(expected) < .005 else f'{expected:+,.2f}%'
        expect(value).to_have_text(display)
        expect(frame.locator('#range-return-label')).to_contain_text(period)
        expect(frame.locator('#range-return-basis')).to_contain_text('ไม่ใช่ CAGR')
        # The last-bar change remains separate; resizing must not alter the return.
        expect(frame.locator('#change')).to_contain_text('จากแท่งก่อน')
        page.set_viewport_size({'width': 1100, 'height': 900})
        page.wait_for_timeout(400)
        expect(value).to_have_text(display)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        report['period_returns'].append({'ticker': payload['ticker'], 'period': period,
            'percent': actual, 'display': display, 'first': rows[0]['time'], 'last': rows[-1]['time'],
            'start_price': rows[0]['close'], 'end_price': rows[-1]['close'], 'bars': len(rows)})
    assert_plain_value_cells(app)
    return report
