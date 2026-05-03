"""
네이버 부동산(Naver Land) 비공식 API 수집 모듈 (Fallback).

엔드포인트: https://new.land.naver.com/api/articles
cortarNo 기반으로 지역별 아파트 매물 총 건수를 수집한다.

주의: 네이버는 데이터센터 IP(GitHub Actions 등)에서 타임아웃이 발생할 수 있음.
      timeout=10s, retry=2로 짧게 실패하여 zigbang fallback으로 빠르게 전환.
"""

import random
import time
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

BASE_URL = "https://new.land.naver.com"
ARTICLE_LIST_URL = f"{BASE_URL}/api/articles"

# 네이버 부동산 거래유형 코드
TRADE_TYPE_MAP = {
    "매매": "A1",
    "전세": "B1",
    "월세": "B2",
}

# 데이터센터 IP 차단 대비: connect/read timeout을 짧게 설정
DEFAULT_TIMEOUT = httpx.Timeout(connect=8.0, read=10.0, write=5.0, pool=5.0)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://new.land.naver.com/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-platform": '"Windows"',
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
        timeout: float = 10.0,  # 데이터센터 IP 차단 대비 짧게 유지
    ):
        self._delay_min = request_delay_min
        self._delay_max = request_delay_max
        self._client = httpx.Client(
            headers=HEADERS,
            timeout=DEFAULT_TIMEOUT,
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
        stop=stop_after_attempt(2),   # 빠른 실패 → zigbang fallback 유도
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch_article_list(
        self,
        cortar_no: str,
        trade_type_code: str,
    ) -> dict:
        """네이버 부동산 매물 목록 API를 호출한다."""
        params = {
            "cortarNo": cortar_no,
            "realEstateType": "APT",
            "tradeType": trade_type_code,
            "page": 1,
            "perPage": 1,   # 건수만 필요하므로 1건만 요청
            "showHidden": "false",
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
        center_lat: float = 0.0,   # 하위 호환용, 미사용
        center_lng: float = 0.0,   # 하위 호환용, 미사용
    ) -> NaverResult:
        """지역과 거래유형으로 아파트 잔여 매물 총 건수를 반환한다."""
        if trade_type not in TRADE_TYPE_MAP:
            raise ValueError(f"지원하지 않는 거래유형: {trade_type}")

        trade_code = TRADE_TYPE_MAP[trade_type]
        logger.debug(
            "{} {} {} cortarNo={}", region_level1, region_level2, trade_type, cortar_no
        )

        self._sleep()
        data = self._fetch_article_list(cortar_no, trade_code)

        # 응답 구조: {"totalCount": N, "articleList": [...]} 또는 {"body": {"totalCount": N}}
        count = (
            data.get("totalCount")
            or (data.get("body") or {}).get("totalCount")
            or 0
        )

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
