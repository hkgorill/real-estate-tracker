"""
R-ONE 스크래퍼 단위 테스트.
"""

from unittest.mock import patch

import pytest

import scrapers.rbone as rbone_mod
from scrapers.rbone import RboneScraper, PriceIndexResult


SAMPLE_SALE_IDX_ROWS = [
    {"prdDe": "202518", "regNm": "전국",  "wghtVal": "100.5"},
    {"prdDe": "202518", "regNm": "서울",  "wghtVal": "105.2"},
    {"prdDe": "202518", "regNm": "경기",  "wghtVal": "98.7"},
    {"prdDe": "202518", "regNm": "수도권", "wghtVal": "102.1"},
    {"prdDe": "202518", "regNm": "인천",  "wghtVal": "97.3"},
]

SAMPLE_JEONSE_IDX_ROWS = [
    {"prdDe": "202518", "regNm": "전국",  "wghtVal": "99.1"},
    {"prdDe": "202518", "regNm": "서울",  "wghtVal": "103.0"},
    {"prdDe": "202518", "regNm": "경기",  "wghtVal": "96.5"},
    {"prdDe": "202518", "regNm": "수도권", "wghtVal": "100.0"},
    {"prdDe": "202518", "regNm": "인천",  "wghtVal": "95.2"},
]

SAMPLE_RATIO_ROWS = [
    {"prdDe": "202518", "regNm": "전국",    "wghtVal": "68.5"},
    {"prdDe": "202518", "regNm": "서울특별시", "wghtVal": "55.2"},
    {"prdDe": "202518", "regNm": "경기도",   "wghtVal": "72.3"},
    {"prdDe": "202518", "regNm": "수도권",   "wghtVal": "62.1"},
    {"prdDe": "202518", "regNm": "인천광역시", "wghtVal": "71.0"},
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

        def mock_fetch(stats_code, prd_se, start_prd, end_prd):
            if stats_code == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518", "202518")

        assert len(results) == 5

    def test_price_values(self):
        sc = make_scraper()

        def mock_fetch(stats_code, prd_se, start_prd, end_prd):
            if stats_code == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518", "202518")

        seoul = next(r for r in results if r.region == "서울")
        assert seoul.sale_index == pytest.approx(105.2)
        assert seoul.period == "202518"
        assert seoul.source == "rbone"

    def test_region_filter(self):
        sc = make_scraper()
        with patch_codes(), patch.object(sc, "_fetch", return_value=SAMPLE_SALE_IDX_ROWS):
            results = sc.get_price_indices("202518", "202518", regions=["서울"])
        assert len(results) == 1
        assert results[0].region == "서울"

    def test_invalid_value_returns_negative(self):
        sc = make_scraper()
        rows = [{"prdDe": "202518", "regNm": "전국", "wghtVal": None}]
        with patch_codes(), patch.object(sc, "_fetch", return_value=rows):
            results = sc.get_price_indices("202518", "202518", regions=["전국"])
        assert results[0].sale_index == -1.0


class TestGetLatest:
    def test_returns_price_index_list(self):
        sc = make_scraper()

        def mock_fetch(stats_code, prd_se, start_prd, end_prd):
            if stats_code == SALE_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch_codes(), patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_latest("202518")

        assert isinstance(results, list)
        assert len(results) == 5
        assert all(isinstance(r, PriceIndexResult) for r in results)
