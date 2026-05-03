"""
transform 모듈 단위 테스트.
"""

from datetime import datetime, timezone, timedelta

import pytest

from scrapers.rbone import PriceIndexResult
from scrapers.ecos import InterestRateResult
from scrapers.molit import AptTradeItem, UnsoldItem
from transform import (
    normalize_price_index,
    normalize_interest_rate, normalize_apt_trade, normalize_unsold,
    CollectResult, to_csv_rows,
    PriceIndexRow, InterestRateRow, AptTradeRow, UnsoldRow,
)

KST = timezone(timedelta(hours=9))
FIXED_TS = datetime(2025, 5, 3, 4, 0, 0, tzinfo=KST)


class TestNormalizePriceIndex:
    def test_basic_conversion(self):
        results = [
            PriceIndexResult(period="202518", region="서울특별시", sale_index=105.2, jeonse_index=103.0),
            PriceIndexResult(period="202518", region="경기도", sale_index=98.7, jeonse_index=96.5),
        ]
        rows = normalize_price_index(results, collected_at=FIXED_TS)
        assert len(rows) == 2
        assert all(isinstance(r, PriceIndexRow) for r in rows)
        assert rows[0].period == "202518"
        assert rows[0].sale_index == pytest.approx(105.2)
        assert rows[0].collected_at == "2025-05-03 04:00:00"

    def test_jeonse_idx_ratio_calculated(self):
        results = [PriceIndexResult(period="202518", region="전국", sale_index=120.0, jeonse_index=108.0)]
        rows = normalize_price_index(results, collected_at=FIXED_TS)
        assert rows[0].jeonse_idx_ratio == pytest.approx(90.0)

    def test_jeonse_idx_ratio_negative_on_invalid(self):
        results = [PriceIndexResult(period="202518", region="전국", sale_index=-1.0, jeonse_index=108.0)]
        rows = normalize_price_index(results, collected_at=FIXED_TS)
        assert rows[0].jeonse_idx_ratio == -1.0

    def test_to_row_length(self):
        results = [PriceIndexResult(period="202518", region="전국", sale_index=100.0, jeonse_index=99.0)]
        rows = normalize_price_index(results, collected_at=FIXED_TS)
        assert len(rows[0].to_row()) == len(PriceIndexRow.headers())


class TestNormalizeInterestRate:
    def test_basic_conversion(self):
        results = [InterestRateResult(period="202503", base_rate=2.75, mortgage_rate=4.10)]
        rows = normalize_interest_rate(results, collected_at=FIXED_TS)
        assert rows[0].period == "202503"
        assert rows[0].base_rate == pytest.approx(2.75)
        assert rows[0].mortgage_rate == pytest.approx(4.10)
        assert len(rows[0].to_row()) == len(InterestRateRow.headers())


class TestNormalizeAptTrade:
    def test_date_construction(self):
        items = [
            AptTradeItem(
                deal_ym="202503", deal_day="15",
                region_level1="서울특별시", region_level2="강남구",
                dong="역삼동", apt_name="래미안역삼",
                area_sqm=84.98, floor=12, price_manwon=85000, build_year=2010,
            )
        ]
        rows = normalize_apt_trade(items, collected_at=FIXED_TS)
        assert rows[0].deal_date == "2025-03-15"
        assert rows[0].price_manwon == 85000
        assert len(rows[0].to_row()) == len(AptTradeRow.headers())

    def test_missing_day_defaults_to_01(self):
        items = [
            AptTradeItem(
                deal_ym="202503", deal_day="",
                region_level1="서울특별시", region_level2="강남구",
                dong="", apt_name="테스트",
                area_sqm=0.0, floor=0, price_manwon=0, build_year=2000,
            )
        ]
        rows = normalize_apt_trade(items, collected_at=FIXED_TS)
        assert rows[0].deal_date == "2025-03-01"


class TestNormalizeUnsold:
    def test_basic_conversion(self):
        items = [
            UnsoldItem(
                deal_ym="202503", region_level1="서울특별시",
                unsold_total=1234, unsold_before=800, unsold_after=434,
            )
        ]
        rows = normalize_unsold(items, collected_at=FIXED_TS)
        assert rows[0].unsold_total == 1234
        assert rows[0].unsold_before == 800
        assert rows[0].unsold_after == 434
        assert len(rows[0].to_row()) == len(UnsoldRow.headers())


class TestCollectResult:
    def test_recount(self):
        result = CollectResult(collected_at="2025-05-03 04:00:00")
        result.price_index_rows = [PriceIndexRow("ts", "202518", "전국", 100.0, 99.0, 99.0, "rbone")] * 3
        result.interest_rate_rows = [InterestRateRow("ts", "202503", 2.75, 4.10, "ecos")] * 2
        result.recount()
        assert result.total_rows == 5

    def test_to_csv_rows_has_all_sheets(self):
        result = CollectResult(collected_at="2025-05-03 04:00:00")
        tables = to_csv_rows(result)
        expected_sheets = {"price_index", "interest_rate", "apt_trade", "unsold"}
        assert set(tables.keys()) == expected_sheets

    def test_to_csv_rows_headers_only_when_empty(self):
        result = CollectResult(collected_at="2025-05-03 04:00:00")
        tables = to_csv_rows(result)
        assert tables["price_index"] == [PriceIndexRow.headers()]
        assert tables["interest_rate"] == [InterestRateRow.headers()]
