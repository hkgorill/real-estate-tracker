"""
R-ONE 스크래퍼 단위 테스트.
"""

from unittest.mock import patch

import pytest

from scrapers.rbone import RboneScraper, PriceIndexResult, JeonseRatioResult


SAMPLE_SALE_IDX_ROWS = [
    {"prdDe": "202518", "regNm": "전국",    "wghtVal": "100.5"},
    {"prdDe": "202518", "regNm": "서울특별시", "wghtVal": "105.2"},
    {"prdDe": "202518", "regNm": "경기도",   "wghtVal": "98.7"},
    {"prdDe": "202518", "regNm": "수도권",   "wghtVal": "102.1"},
    {"prdDe": "202518", "regNm": "인천광역시", "wghtVal": "97.3"},
]

SAMPLE_JEONSE_IDX_ROWS = [
    {"prdDe": "202518", "regNm": "전국",    "wghtVal": "99.1"},
    {"prdDe": "202518", "regNm": "서울특별시", "wghtVal": "103.0"},
    {"prdDe": "202518", "regNm": "경기도",   "wghtVal": "96.5"},
    {"prdDe": "202518", "regNm": "수도권",   "wghtVal": "100.0"},
    {"prdDe": "202518", "regNm": "인천광역시", "wghtVal": "95.2"},
]

SAMPLE_RATIO_ROWS = [
    {"prdDe": "202518", "regNm": "전국",    "wghtVal": "68.5"},
    {"prdDe": "202518", "regNm": "서울특별시", "wghtVal": "55.2"},
    {"prdDe": "202518", "regNm": "경기도",   "wghtVal": "72.3"},
    {"prdDe": "202518", "regNm": "수도권",   "wghtVal": "62.1"},
    {"prdDe": "202518", "regNm": "인천광역시", "wghtVal": "71.0"},
]


def make_scraper() -> RboneScraper:
    return RboneScraper(api_key="test_key")


class TestGetPriceIndices:
    def test_returns_five_regions(self):
        sc = make_scraper()

        def mock_fetch(stats_code, prd_se, start, end):
            if "SALE" in stats_code or stats_code.endswith("000"):
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518", "202518")

        assert len(results) == 5

    def test_price_values(self):
        sc = make_scraper()

        def mock_fetch(stats_code, prd_se, start, end):
            from scrapers.rbone import DEFAULT_SALE_IDX_CODE
            if stats_code == DEFAULT_SALE_IDX_CODE:
                return SAMPLE_SALE_IDX_ROWS
            return SAMPLE_JEONSE_IDX_ROWS

        with patch.object(sc, "_fetch", side_effect=mock_fetch):
            results = sc.get_price_indices("202518", "202518")

        seoul = next(r for r in results if r.region == "서울특별시")
        assert seoul.sale_index == pytest.approx(105.2)
        assert seoul.period == "202518"
        assert seoul.source == "rbone"

    def test_region_filter(self):
        sc = make_scraper()
        with patch.object(sc, "_fetch", return_value=SAMPLE_SALE_IDX_ROWS):
            results = sc.get_price_indices("202518", "202518", regions=["서울특별시"])
        assert len(results) == 1
        assert results[0].region == "서울특별시"

    def test_invalid_value_returns_negative(self):
        sc = make_scraper()
        rows = [{"prdDe": "202518", "regNm": "전국", "wghtVal": None}]
        with patch.object(sc, "_fetch", return_value=rows):
            results = sc.get_price_indices("202518", "202518", regions=["전국"])
        assert results[0].sale_index == -1.0


class TestGetJeonseRatios:
    def test_returns_five_regions(self):
        sc = make_scraper()
        with patch.object(sc, "_fetch", return_value=SAMPLE_RATIO_ROWS):
            results = sc.get_jeonse_ratios("202518", "202518")
        assert len(results) == 5

    def test_ratio_values(self):
        sc = make_scraper()
        with patch.object(sc, "_fetch", return_value=SAMPLE_RATIO_ROWS):
            results = sc.get_jeonse_ratios("202518", "202518")
        gyeonggi = next(r for r in results if r.region == "경기도")
        assert gyeonggi.jeonse_ratio == pytest.approx(72.3)
        assert gyeonggi.source == "rbone"
