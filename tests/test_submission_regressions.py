import json
from datetime import datetime, timedelta, timezone

from finn.alerts import digest, save_prices
from finn.db import Database
from finn.models import PriceImport


def test_digest_keeps_earlier_threshold_alerts_when_latest_day_is_quiet(tmp_path):
    db = Database(tmp_path / 'alerts.sqlite')
    db.initialize()
    db.execute('INSERT INTO portfolio VALUES (?,?)', ('UNSEEN', json.dumps({'ticker': 'UNSEEN', 'name': 'Unseen', 'exchange': 'NSE'})))
    end = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
    days = [(end - timedelta(days=35-i)).date() for i in range(35)]
    prices = [{'day': day, 'close': 100 if i < 28 else 110, 'volume': 350 if i == 30 else 100} for i, day in enumerate(days)]
    save_prices(db, PriceImport(ticker='UNSEEN', mode='live', prices=prices))
    result = digest(db, end - timedelta(days=30), end, 'live', True)
    alerts = [item for item in result['items'] if item['type'] == 'market_alert']
    assert len(alerts) == 2
    assert any(item['price_change_percent'] == 10 for item in alerts)
    assert any(item['volume_multiple'] >= 2 and item['volume_baseline_complete'] for item in alerts)
    assert len({item['id'] for item in alerts}) == 2
    assert not digest(db, end - timedelta(days=1), end, 'live', True)['items']


def test_cached_statement_without_revenue_reference_is_a_valid_partial_result():
    from engine.financials import cross_check
    from finn.models import FinancialRecord
    filing = FinancialRecord(ticker='UNSEEN', period_end='2026-09-30', basis='consolidated', metrics={'pat': 10}, source_type='filing')
    reference = FinancialRecord(ticker='UNSEEN', period_end='2026-06-30', basis='consolidated', metrics={'pat': 9}, source_type='screener')
    check = cross_check(filing, reference)
    assert check['status'] == 'incompatible_period_basis_or_units'
    assert check['metrics'] == {}
