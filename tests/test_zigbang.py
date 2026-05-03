"""scrapers/zigbang.py 단위 테스트 (HTTP mocking)."""

import pytest
import respx
import httpx

from scrapers.zigbang import ZigbangScraper, ZigbangResult, ITEMS_URL


SAMPLE_REGION = {
    "region_level1": "서울특별시",
    "region_level2": "강남구",
    "cortar_no": "1123000000",
    "center_lat": 37.5172,
    "center_lng": 127.0473,
}


@pytest.fixture
def scraper():
    s = ZigbangScraper(request_delay_min=0, request_delay_max=0)
    yield s
    s.close()


class TestZigbangScraper:
    @respx.mock
    def test_get_listing_count_success(self, scraper):
        items = [{"id": i} for i in range(42)]
        respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json={"items": items}))

        result = scraper.get_listing_count(
            region_level1="서울특별시",
            region_level2="강남구",
            trade_type="매매",
            center_lat=37.5172,
            center_lng=127.0473,
        )

        assert isinstance(result, ZigbangResult)
        assert result.listing_count == 42
        assert result.trade_type == "매매"
        assert result.source == "zigbang"

    @respx.mock
    def test_get_listing_count_empty(self, scraper):
        respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json={"items": []}))

        result = scraper.get_listing_count(
            region_level1="서울특별시",
            region_level2="강남구",
            trade_type="전세",
            center_lat=37.5172,
            center_lng=127.0473,
        )

        assert result.listing_count == 0

    @respx.mock
    def test_scrape_region_all_trade_types(self, scraper):
        respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json={"items": [{"id": 1}]}))

        results = scraper.scrape_region(SAMPLE_REGION)

        assert len(results) == 3
        trade_types = {r.trade_type for r in results}
        assert trade_types == {"매매", "전세", "월세"}

    @respx.mock
    def test_scrape_region_http_error_returns_error_result(self, scraper):
        respx.get(ITEMS_URL).mock(return_value=httpx.Response(429, text="Too Many Requests"))

        results = scraper.scrape_region(SAMPLE_REGION)

        assert len(results) == 3
        for r in results:
            assert "error" in r.source
            assert r.listing_count == -1

    @respx.mock
    def test_scrape_region_partial_trade_types(self, scraper):
        respx.get(ITEMS_URL).mock(return_value=httpx.Response(200, json={"items": [{"id": 1}]}))

        results = scraper.scrape_region(SAMPLE_REGION, trade_types=["매매"])

        assert len(results) == 1
        assert results[0].trade_type == "매매"

    def test_invalid_trade_type_raises(self, scraper):
        with pytest.raises(ValueError, match="지원하지 않는"):
            scraper.get_listing_count(
                "서울특별시", "강남구", "분양", 37.5, 127.0
            )

    @respx.mock
    def test_geohash_included_in_request(self, scraper):
        route = respx.get(ITEMS_URL).mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        scraper.get_listing_count("서울특별시", "강남구", "매매", 37.5172, 127.0473)

        assert route.called
        request = route.calls.last.request
        assert "geohash" in str(request.url)
