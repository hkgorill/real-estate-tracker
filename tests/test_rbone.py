"""
R-ONE 스크래퍼 단위 테스트.
"""

from unittest.mock import patch

import pytest

import scrapers.rbone as rbone_mod
from scrapers.rbone import RboneScraper, PriceIndexResult


SAMPLE_SALE_IDX_ROWS = [
    {"CLS_NM": "전국",  "DTA_VAL": "100.5"},
    {"CLS_NM": "서울",  "DTA_VAL": "105.2"},
    {"CLS_NM": "경기",  "DTA_VAL": "98.7"},
    {"CLS_NM": "수도권", "DTA_VAL": "102.1"},
    {"CLS_NM": "인천",  "DTA_VAL": "97.3"},
]

SAMPLE_JEONSE_IDX_ROWS = [
    {"CLS_NM": "전국",  "DTA_VAL": "99.1"},
    {"CLS_NM": "서울",  "DTA_VAL": "103.0"},
    {"CLS_NM": "경기",  "DTA_VAL": "96.5"},
    {"CLS_NM": "수도권", "DTA_VAL": "100.0"},
    {"CLS_NM": "인천",  "DTA_VAL": "95.2"},
]


SALE_CODE   = "T244183132827305"
JEONSE_CODE = "T247713133046872"


def make_scraper() -> RboneScraper:
    return RboneScraper(api_key="test_key")


def patch_codes():
    """테스트용 통계코드 패치 컨텍스트."""
    return patch.multiple(
        rbone_mod,
        DEFAULT_SALE_IDX_CODE=SALE_CODE,
        DEFAULT_JEONSE_IDX_CODE=JEONSE_CODE,
    )


class TestGetPriceIndices:
    def test_returns_five_regions(self):
        sc = make_scraper()

        def mock_fetch(statbl_id, period):
            if statbl_id == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518")

        assert len(results) == 5

    def test_price_values(self):
        sc = make_scraper()

        def mock_fetch(statbl_id, period):
            if statbl_id == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518")

        seoul = next(r for r in results if r.region == "서울")
        assert seoul.sale_index == pytest.approx(105.2)
        assert seoul.jeonse_index == pytest.approx(103.0)
        assert seoul.period == "202518"
        assert seoul.source == "rbone"

    def test_region_filter(self):
        sc = make_scraper()

        def mock_fetch(statbl_id, period):
            return SAMPLE_SALE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518", regions=["서울"])
        assert len(results) == 1
        assert results[0].region == "서울"

    def test_invalid_value_returns_negative(self):
        sc = make_scraper()
        rows = [{"CLS_NM": "전국", "DTA_VAL": None}]
        with patch_codes(), patch.object(sc, "_fetch", return_value=rows):
            results = sc.get_price_indices("202518", regions=["전국"])
        assert results[0].sale_index == -1.0


class TestGetLatest:
    def test_returns_price_index_list(self):
        sc = make_scraper()

        def mock_fetch(statbl_id, period):
            if statbl_id == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_latest("202518")

        assert isinstance(results, list)
        assert len(results) == 5
        assert all(isinstance(r, PriceIndexResult) for r in results)
