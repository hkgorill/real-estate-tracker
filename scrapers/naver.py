"""
네이버 부동산(Naver Land) 비공식 API 수집 모듈 (Fallback).

엔드포인트: https://m.land.naver.com/cluster/ajax/articleList
cortarNo 기반으로 지역별 아파트 매물 총 건수를 수집한다.
"""

import random
import time
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

BASE_URL = "https://m.land.naver.com"
ARTICLE_LIST_URL = f"{BASE_URL}/cluster/ajax/articleList"

# 네이버 부동산 거래유형 코드
TRADE_TYPE_MAP = {
    "매매": "A1",
    "전세": "B1",
    "월세": "B2",
}

# 지도 뷰포트 오프셋 (±도 단위, 구 레벨 커버에 적합)
LAT_OFFSET = 0.08
LNG_OFFSET = 0.10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.6367.82 Mobile Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://m.land.naver.com/",
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass
class NaverResult:
    region_level1: str
    region_level2: str
    trade_type: str
    listing_count: int
    source: str = "naver"


class NaverScraper:
    def __init__(
        self,
        request_delay_min: float = 1.5,
        request_delay_max: float = 4.0,
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
        wait=wait_exponential(multiplier=2, min=3, max=60),
        reraise=True,
    )
    def _fetch_article_list(
        self,
        cortar_no: str,
        trade_type_code: str,
        lat: float,
        lng: float,
    ) -> dict:
        """네이버 부동산 매물 목록 API를 호출한다."""
        params = {
            "rletTypeCd": "A01",          # 아파트
            "tradTpCd": trade_type_code,
            "cortarNo": cortar_no,
            "z": 12,
            "lat": lat,
            "lng": lng,
            "btm": lat - LAT_OFFSET,
            "lft": lng - LNG_OFFSET,
            "top": lat + LAT_OFFSET,
            "rgt": lng + LNG_OFFSET,
            "sort": "rank",
            "page": 1,
        }
        resp = self._client.get(ARTICLE_LIST_URL, params=params)
        resp.raise_for_status()
        return resp.json()

    def get_listing_count(
        self,
        region_level1: str,
        region_level2: str,
        trade_type: str,
        cortar_no: str,
        center_lat: float,
        center_lng: float,
    ) -> NaverResult:
        """지역과 거래유형으로 아파트 잔여 매물 총 건수를 반환한다."""
        if trade_type not in TRADE_TYPE_MAP:
            raise ValueError(f"지원하지 않는 거래유형: {trade_type}")

        trade_code = TRADE_TYPE_MAP[trade_type]
        logger.debug(
            "{} {} {} cortarNo={}", region_level1, region_level2, trade_type, cortar_no
        )

        self._sleep()
        data = self._fetch_article_list(cortar_no, trade_code, center_lat, center_lng)

        # 응답 구조: {"isSuccess": true, "body": {"totalCount": N, "list": [...]}}
        body = data.get("body") or {}
        count = body.get("totalCount", 0)

        logger.info(
            "[naver] {} {} {} → {}건", region_level1, region_level2, trade_type, count
        )
        return NaverResult(
            region_level1=region_level1,
            region_level2=region_level2,
            trade_type=trade_type,
            listing_count=count,
        )

    def scrape_region(
        self,
        region: dict,
        trade_types: list[str] | None = None,
    ) -> list[NaverResult]:
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
                    cortar_no=region["cortar_no"],
                    center_lat=region["center_lat"],
                    center_lng=region["center_lng"],
                )
                results.append(result)
            except Exception as exc:
                logger.warning(
                    "[naver] {} {} {} 수집 실패: {}",
                    region["region_level1"],
                    region["region_level2"],
                    trade_type,
                    exc,
                )
                results.append(
                    NaverResult(
                        region_level1=region["region_level1"],
                        region_level2=region["region_level2"],
                        trade_type=trade_type,
                        listing_count=-1,
                        source="naver_error",
                    )
                )
        return results
