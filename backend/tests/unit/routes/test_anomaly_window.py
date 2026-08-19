"""Unit tests for spending-anomaly display window filtering (#130)."""

from datetime import date
from decimal import Decimal

import pytest

from app.routes.analytics import (
    build_anomalies_from_monthly_df,
    filter_anomalies_to_window,
)
from app.schemas.analytics import AnomalyAlert


def _alert(month: str, amount: str = "500.00") -> AnomalyAlert:
    return AnomalyAlert(
        month=month,
        amount=Decimal(amount),
        baseline=Decimal("100.00"),
        deviation_percent=Decimal("400.00"),
        severity="critical",
        message=f"test {month}",
    )


@pytest.fixture
def fixed_today(monkeypatch: pytest.MonkeyPatch):
    """Pin date.today() used by filter_anomalies_to_window."""
    monkeypatch.setattr(
        "app.routes.analytics.date_type",
        type(
            "FixedDate",
            (date,),
            {"today": classmethod(lambda cls: date(2026, 8, 15))},
        ),
    )


@pytest.mark.unit
@pytest.mark.analytics
class TestFilterAnomaliesToWindow:
    def test_all_keeps_everything(self, fixed_today):
        anomalies = [_alert("2024-01"), _alert("2026-08")]
        assert filter_anomalies_to_window(anomalies, "all", None, None) == anomalies

    def test_3m_keeps_recent_months_only(self, fixed_today):
        # today=2026-08-15 → 3m start ≈ 2026-05-17; May 1 is before that.
        anomalies = [
            _alert("2026-04"),
            _alert("2026-05"),
            _alert("2026-06"),
            _alert("2026-07"),
            _alert("2026-08"),
        ]
        months = [a.month for a in filter_anomalies_to_window(anomalies, "3m", None, None)]
        assert months == ["2026-06", "2026-07", "2026-08"]

    def test_ytd_from_january(self, fixed_today):
        anomalies = [_alert("2025-12"), _alert("2026-01"), _alert("2026-06")]
        months = [a.month for a in filter_anomalies_to_window(anomalies, "ytd", None, None)]
        assert months == ["2026-01", "2026-06"]

    def test_custom_range_inclusive_end_month(self, fixed_today):
        anomalies = [
            _alert("2026-01"),
            _alert("2026-02"),
            _alert("2026-03"),
            _alert("2026-04"),
        ]
        months = [
            a.month
            for a in filter_anomalies_to_window(
                anomalies,
                "custom",
                date(2026, 2, 1),
                date(2026, 3, 15),
            )
        ]
        assert months == ["2026-02", "2026-03"]


@pytest.mark.unit
@pytest.mark.analytics
class TestBuildAnomaliesBaseline:
    def test_short_series_cannot_fire_when_filtered_before_detect(self):
        """Document why detect-then-filter matters: n=3 max z ≈ 1.15 < 2.0."""
        import pandas as pd

        short = pd.DataFrame(
            [
                {"year": 2026, "month": 6, "month_name": "June", "total_cost": 100.0},
                {"year": 2026, "month": 7, "month_name": "July", "total_cost": 100.0},
                {"year": 2026, "month": 8, "month_name": "August", "total_cost": 500.0},
            ]
        )
        assert build_anomalies_from_monthly_df(short) == []

    def test_full_history_detects_then_window_can_show_spike(self, fixed_today):
        import pandas as pd

        rows = []
        for year, month in [
            (2025, 8),
            (2025, 9),
            (2025, 10),
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
            (2026, 3),
            (2026, 4),
            (2026, 5),
            (2026, 6),
            (2026, 7),
            (2026, 8),
        ]:
            cost = 800.0 if (year, month) == (2026, 7) else 100.0
            rows.append(
                {
                    "year": year,
                    "month": month,
                    "month_name": "Month",
                    "total_cost": cost,
                }
            )
        full = pd.DataFrame(rows)
        all_anomalies = build_anomalies_from_monthly_df(full)
        assert any(a.month == "2026-07" for a in all_anomalies)

        windowed = filter_anomalies_to_window(all_anomalies, "3m", None, None)
        assert [a.month for a in windowed] == ["2026-07"]
        # Baseline stays the full-history mean, not the 3m mean
        july = next(a for a in all_anomalies if a.month == "2026-07")
        assert windowed[0].baseline == july.baseline
