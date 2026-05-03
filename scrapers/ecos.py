"""
한국은행 ECOS OpenAPI 수집 모듈.

[기준금리]  통계코드 722Y001, 항목코드 0101000 (한국은행 기준금리)
[주담대금리] 통계코드 121Y006, 항목코드 BECBLDG01 (예금은행 주택담보대출 가중평균금리, 잔액기준)

API 키 발급: https://ecos.bok.or.kr → 오픈API → 인증키 신청
API 문서:    https://ecos.bok.or.kr/api/#/DevGuide/StatSearch
"""

import time
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

ECOS_BASE = "https://ecos.bok.or.kr/api"

# 통계코드 / 항목코드
BASE_RATE_STAT    = "722Y001"
BASE_RATE_ITEM    = "0101000"   # 한국은행 기준금리
MORTGAGE_RATE_STAT = "121Y006"
MORTGAGE_RATE_ITEM = "BECBLDG01"  # 주택담보대출 가중평균금리(잔액기준)


@dataclass
class InterestRateResult:
    """월간 금리 데이터."""
    period: str          # YYYYMM
    base_rate: float     # 한국은행 기준금리 (%)
    mortgage_rate: float # 주택담보대출 가중평균금리 (%)
    source: str = "ecos"


class EcosScraper:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        reraise=True,
    )
    def _fetch_stat(
        self,
        stat_code: str,
        item_code: str,
        start_ym: str,
        end_ym: str,
    ) -> list[dict]:
        """ECOS StatisticSearch API를 호출하여 통계값 목록을 반환한다."""
        # URL 구조: /StatisticSearch/{apiKey}/json/kr/{startCount}/{endCount}/{statCode}/M/{startDate}/{endDate}/{itemCode1}
        url = (
            f"{ECOS_BASE}/StatisticSearch"
            f"/{self._api_key}/json/kr/1/100"
            f"/{stat_code}/M/{start_ym}/{end_ym}"
            f"/{item_code}"
        )
        resp = self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        if "StatisticSearch" not in data:
            error = data.get("RESULT", {})
            raise RuntimeError(f"ECOS API 오류: {error.get('MESSAGE', data)}")

        return data["StatisticSearch"].get("row", [])

    def get_interest_rates(self, start_ym: str, end_ym: str) -> list[InterestRateResult]:
        """기간 내 월별 기준금리 + 주담대금리를 반환한다.

        Args:
            start_ym: 시작 년월 (YYYYMM)
            end_ym:   종료 년월 (YYYYMM)
        """
        base_rows = self._fetch_stat(BASE_RATE_STAT, BASE_RATE_ITEM, start_ym, end_ym)
        time.sleep(0.5)
        mortgage_rows = self._fetch_stat(MORTGAGE_RATE_STAT, MORTGAGE_RATE_ITEM, start_ym, end_ym)

        # period → value 인덱스 구성
        base_by_period = {r["TIME"]: float(r["DATA_VALUE"]) for r in base_rows if r.get("DATA_VALUE")}
        mort_by_period = {r["TIME"]: float(r["DATA_VALUE"]) for r in mortgage_rows if r.get("DATA_VALUE")}

        # 두 지표가 모두 있는 기간만 결합
        all_periods = sorted(set(base_by_period) | set(mort_by_period))
        results = []
        for period in all_periods:
            results.append(InterestRateResult(
                period=period,
                base_rate=base_by_period.get(period, -1.0),
                mortgage_rate=mort_by_period.get(period, -1.0),
            ))

        logger.info("[ecos] {} ~ {} → {}개월 금리 수집", start_ym, end_ym, len(results))
        return results

    def get_latest_interest_rate(self, year_month: str) -> InterestRateResult | None:
        """특정 월의 금리를 단건 반환한다. 데이터 없으면 None."""
        results = self.get_interest_rates(year_month, year_month)
        return results[0] if results else None
