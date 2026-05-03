"""
직방(Zigbang) 비공식 API 수집 모듈.

엔드포인트: https://apis.zigbang.com/v3/items
geohash 기반으로 지역별 아파트 매물 건수를 수집한다.
"""

import random
import time
from dataclasses import dataclass

import geohash2
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

BASE_URL = "https://apis.zigbang.com"
ITEMS_URL = f"{BASE_URL}/v3/items"

TRADE_TYPE_MAP = {
    "매매": "SALE",
    "전세": "JEONSE",
    "월세": "MONTHLY_RENT",
}

# geohash precision=5 → 약 4.9km × 4.9km 격자 (구 단위 커버에 적합)
GEOHASH_PRECISION = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.zigbang.com",
    "Referer": "https://www.zigbang.com/",
}


@dataclass
class ZigbangResult:
    region_level1: str
    region_level2: str
    trade_type: str
    listing_count: int
    source: str = "zigbang"


class ZigbangScraper:
    def __init__(
        self,
        request_delay_min: float = 1.0,
        request_delay_max: float = 3.0,
        timeout: float = 30.0,
    ):
        self._delay_min = request_delay_min
        self._delay_max = request_delay_max
        self._client = httpx.Client(
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _sleep(self):
        time.sleep(random.uniform(self._delay_min, self._delay_max))

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def _fetch_items(self, geohash: str, trade_type_en: str) -> list[dict]:
        """geohash + 거래유형으로 items 목록을 조회한다."""
        params = {
            "domain": "zigbang",
            "checkAnyItemWithoutFilter": "true",
            "geohash": geohash,
            "needSummary": "true",
            "isMapView": "false",
            "tradetype": trade_type_en,
            "serviceType": "아파트",
        }
        resp = self._client.get(ITEMS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])

    def get_listing_count(
        self,
        region_level1: str,
        region_level2: str,
        trade_type: str,
        center_lat: float,
        center_lng: float,
    ) -> ZigbangResult:
        """지역과 거래유형으로 아파트 잔여 매물 건수를 반환한다."""
        if trade_type not in TRADE_TYPE_MAP:
            raise ValueError(f"지원하지 않는 거래유형: {trade_type}")

        trade_type_en = TRADE_TYPE_MAP[trade_type]
        geohash = geohash2.encode(center_lat, center_lng, precision=GEOHASH_PRECISION)

        logger.debug(
            "{} {} {} geohash={}", region_level1, region_level2, trade_type, geohash
        )

        self._sleep()
        items = self._fetch_items(geohash, trade_type_en)
        count = len(items)

        logger.info(
            "[zigbang] {} {} {} → {}건", region_level1, region_level2, trade_type, count
        )
        return ZigbangResult(
            region_level1=region_level1,
            region_level2=region_level2,
            trade_type=trade_type,
            listing_count=count,
        )

    def scrape_region(
        self,
        region: dict,
        trade_types: list[str] | None = None,
    ) -> list[ZigbangResult]:
        """단일 지역의 모든 거래유형 매물 수를 수집한다."""
        if trade_types is None:
            trade_types = list(TRADE_TYPE_MAP.keys())

        results = []
        for trade_type in trade_types:
            try:
                result = self.get_listing_count(
                    region_level1=region["region_level1"],
                    region_level2=region["region_level2"],
                    trade_type=trade_type,
                    center_lat=region["center_lat"],
                    center_lng=region["center_lng"],
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "[zigbang] {} {} {} 수집 실패: {}",
                    region["region_level1"],
                    region["region_level2"],
                    trade_type,
                    exc,
                )
                results.append(
                    ZigbangResult(
                        region_level1=region["region_level1"],
                        region_level2=region["region_level2"],
                        trade_type=trade_type,
                        listing_count=-1,
                        source="zigbang_error",
                    )
                )
        return results
