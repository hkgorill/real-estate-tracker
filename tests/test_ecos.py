"""
ECOS 스크래퍼 단위 테스트.
"""

from unittest.mock import patch

import pytest

from scrapers.ecos import EcosScraper, InterestRateResult


SAMPLE_BASE_RATE_RESPONSE = {
    "StatisticSearch": {
        "row": [
            {"TIME": "202501", "ITEM_NAME1": "기준금리", "DATA_VALUE": "3.00"},
            {"TIME": "202502", "ITEM_NAME1": "기준금리", "DATA_VALUE": "2.75"},
            {"TIME": "202503", "ITEM_NAME1": "기준금리", "DATA_VALUE": "2.75"},
        ]
    }
}

SAMPLE_MORTGAGE_RESPONSE = {
    "StatisticSearch": {
        "row": [
            {"TIME": "202501", "ITEM_NAME1": "주택담보대출", "DATA_VALUE": "4.21"},
            {"TIME": "202502", "ITEM_NAME1": "주택담보대출", "DATA_VALUE": "4.15"},
            {"TIME": "202503", "ITEM_NAME1": "주택담보대출", "DATA_VALUE": "4.10"},
        ]
    }
}

SAMPLE_ERROR_RESPONSE = {
    "RESULT": {"CODE": "200", "MESSAGE": "인증키가 유효하지 않습니다."}
}


def make_scraper() -> EcosScraper:
    return EcosScraper(api_key="test_key")


class TestGetInterestRates:
    def test_returns_combined_results(self):
        sc = make_scraper()

        def mock_fetch(stat_code, item_code, start_ym, end_ym):
            if stat_code.startswith("722"):
                return SAMPLE_BASE_RATE_RESPONSE["StatisticSearch"]["row"]
            return SAMPLE_MORTGAGE_RESPONSE["StatisticSearch"]["row"]

        with patch.object(sc, "_fetch_stat", side_effect=mock_fetch):
            results = sc.get_interest_rates("202501", "202503")

        assert len(results) == 3
        assert all(isinstance(r, InterestRateResult) for r in results)

    def test_rate_values(self):
        sc = make_scraper()

        def mock_fetch(stat_code, item_code, start_ym, end_ym):
            if stat_code.startswith("722"):
                return SAMPLE_BASE_RATE_RESPONSE["StatisticSearch"]["row"]
            return SAMPLE_MORTGAGE_RESPONSE["StatisticSearch"]["row"]

        with patch.object(sc, "_fetch_stat", side_effect=mock_fetch):
            results = sc.get_interest_rates("202501", "202503")

        jan = next(r for r in results if r.period == "202501")
        assert jan.base_rate == pytest.approx(3.00)
        assert jan.mortgage_rate == pytest.approx(4.21)
        assert jan.source == "ecos"

    def test_partial_data_includes_missing_as_negative(self):
        # base_rate 데이터는 있고, mortgage_rate 누락된 경우
        sc = make_scraper()

        def mock_fetch(stat_code, item_code, start_ym, end_ym):
            if stat_code.startswith("722"):
                return [{"TIME": "202504", "DATA_VALUE": "2.50"}]
            return []  # mortgage 없음

        with patch.object(sc, "_fetch_stat", side_effect=mock_fetch):
            results = sc.get_interest_rates("202504", "202504")

        assert len(results) == 1
        assert results[0].base_rate == pytest.approx(2.50)
        assert results[0].mortgage_rate == -1.0

    def test_api_error_raises(self):
        sc = make_scraper()
        with patch.object(sc, "_fetch_stat", side_effect=RuntimeError("인증키 오류")):
            with pytest.raises(RuntimeError):
                sc.get_interest_rates("202501", "202501")

    def test_get_latest_returns_single(self):
        sc = make_scraper()

        def mock_fetch(stat_code, item_code, start_ym, end_ym):
            if stat_code.startswith("722"):
                return [{"TIME": "202503", "DATA_VALUE": "2.75"}]
            return [{"TIME": "202503", "DATA_VALUE": "4.10"}]

        with patch.object(sc, "_fetch_stat", side_effect=mock_fetch):
            result = sc.get_latest_interest_rate("202503")

        assert result is not None
        assert result.period == "202503"

    def test_get_latest_returns_none_when_empty(self):
        sc = make_scraper()
        with patch.object(sc, "_fetch_stat", return_value=[]):
            result = sc.get_latest_interest_rate("202503")
        assert result is None
