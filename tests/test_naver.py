"""scrapers/naver.py 단위 테스트 (HTTP mocking)."""

import pytest
import respx
import httpx

from scrapers.naver import NaverScraper, NaverResult, ARTICLE_LIST_URL


SAMPLE_REGION = {
    "region_level1": "서울특별시",
    "region_level2": "강남구",
    "cortar_no": "1123000000",
    "center_lat": 37.5172,
    "center_lng": 127.0473,
}

NAVER_SUCCESS_BODY = {
    "isSuccess": True,
    "body": {
        "totalCount": 1234,
        "list": [],
    },
}

NAVER_EMPTY_BODY = {
    "isSuccess": True,
    "body": {
        "totalCount": 0,
        "list": [],
    },
}


@pytest.fixture
def scraper():
    s = NaverScraper(request_delay_min=0, request_delay_max=0)
    yield s
    s.close()


class TestNaverScraper:
    @respx.mock
    def test_get_listing_count_success(self, scraper):
        respx.get(ARTICLE_LIST_URL).mock(
            return_value=httpx.Response(200, json=NAVER_SUCCESS_BODY)
        )

        result = scraper.get_listing_count(
            region_level1="서울특별시",
            region_level2="강남구",
            trade_type="매매",
            cortar_no="1123000000",
            center_lat=37.5172,
            center_lng=127.0473,
        )

        assert isinstance(result, NaverResult)
        assert result.listing_count == 1234
        assert result.trade_type == "매매"
        assert result.source == "naver"

    @respx.mock
    def test_get_listing_count_zero(self, scraper):
        respx.get(ARTICLE_LIST_URL).mock(
            return_value=httpx.Response(200, json=NAVER_EMPTY_BODY)
        )

        result = scraper.get_listing_count(
            "서울특별시", "강남구", "월세", "1123000000", 37.5172, 127.0473
        )

        assert result.listing_count == 0

    @respx.mock
    def test_scrape_region_all_trade_types(self, scraper):
        respx.get(ARTICLE_LIST_URL).mock(
            return_value=httpx.Response(200, json=NAVER_SUCCESS_BODY)
        )

        results = scraper.scrape_region(SAMPLE_REGION)

        assert len(results) == 3
        trade_types = {r.trade_type for r in results}
        assert trade_types == {"매매", "전세", "월세"}

    @respx.mock
    def test_scrape_region_http_error_returns_error_result(self, scraper):
        respx.get(ARTICLE_LIST_URL).mock(return_value=httpx.Response(403, text="Forbidden"))

        results = scraper.scrape_region(SAMPLE_REGION)

        assert len(results) == 3
        for r in results:
            assert "error" in r.source
            assert r.listing_count == -1

    @respx.mock
    def test_missing_body_key_returns_zero(self, scraper):
        """응답에 body 키가 없어도 0으로 안전하게 처리."""
        respx.get(ARTICLE_LIST_URL).mock(
            return_value=httpx.Response(200, json={"isSuccess": True})
        )

        result = scraper.get_listing_count(
            "서울특별시", "강남구", "전세", "1123000000", 37.5172, 127.0473
        )

        assert result.listing_count == 0

    @respx.mock
    def test_trade_type_code_in_request(self, scraper):
        route = respx.get(ARTICLE_LIST_URL).mock(
            return_value=httpx.Response(200, json=NAVER_SUCCESS_BODY)
        )

        scraper.get_listing_count(
            "서울특별시", "강남구", "매매", "1123000000", 37.5172, 127.0473
        )

        request = route.calls.last.request
        url_str = str(request.url)
        assert "tradeType=A1" in url_str
        assert "cortarNo=1123000000" in url_str
        assert "realEstateType=APT" in url_str

    def test_invalid_trade_type_raises(self, scraper):
        with pytest.raises(ValueError, match="지원하지 않는"):
            scraper.get_listing_count(
                "서울특별시", "강남구", "분양", "1123000000", 37.5, 127.0
            )
