"""
한국부동산원(R-ONE) OpenAPI 수집 모듈.

[아파트 매매가격지수 / 전세가격지수 / 전세가율] 주간 데이터

엔드포인트: https://www.reb.or.kr/r-one/openapi/SttsService.do
  파라미터:
    apiKey      : 발급 API 키
    statsCode   : 통계표코드 (아래 STATS_CODES 참조)
    prdSe       : 기간구분 (W=주간)
    startPrdDe  : 시작기간 (YYYYWW, 예: 202401 = 2024년 1주차)
    endPrdDe    : 종료기간
    format      : json

통계표코드 확인:
  R-ONE 포털 (https://www.reb.or.kr/r-one) → 통계서비스 → 오픈API → 통계표코드 조회
  아파트 매매가격지수(주간) 코드를 환경변수 RBONE_SALE_IDX_CODE 에 설정하세요.
  아파트 전세가격지수(주간) 코드를 환경변수 RBONE_JEONSE_IDX_CODE 에 설정하세요.
  전세가율(주간) 코드를 환경변수 RBONE_JEONSE_RATIO_CODE 에 설정하세요.

API 키 발급: https://www.reb.or.kr/r-one → 오픈API → 활용신청
"""

import os
import time
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

RBONE_API_URL = "https://www.reb.or.kr/r-one/openapi/SttsService.do"

# 통계표코드 — R-ONE 포털에서 확인 후 환경변수로 설정
# 기본값은 플레이스홀더이므로 반드시 실제 코드로 교체할 것
DEFAULT_SALE_IDX_CODE    = os.getenv("RBONE_SALE_IDX_CODE",    "R214000000")
DEFAULT_JEONSE_IDX_CODE  = os.getenv("RBONE_JEONSE_IDX_CODE",  "R214000100")
DEFAULT_JEONSE_RATIO_CODE = os.getenv("RBONE_JEONSE_RATIO_CODE", "R214000200")

# R-ONE 권역 코드 (매매가격지수 기준)
# 실제 코드는 R-ONE 포털 통계표에서 확인 필요
REGION_CODES = {
    "전국":   "00",
    "수도권":  "10",
    "서울특별시": "11",
    "인천광역시": "23",
    "경기도":  "41",
}


@dataclass
class PriceIndexResult:
    """주간 아파트 가격지수 1건."""
    period: str        # YYYYWW (예: 202401)
    region: str        # 지역명
    sale_index: float  # 매매가격지수
    jeonse_index: float # 전세가격지수
    source: str = "rbone"


@dataclass
class JeonseRatioResult:
    """주간 전세가율 1건."""
    period: str        # YYYYWW
    region: str        # 지역명
    jeonse_ratio: float  # 전세가율 (%)
    source: str = "rbone"


class RboneScraper:
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
    def _fetch(self, stats_code: str, prd_se: str, start_prd: str, end_prd: str) -> list[dict]:
        """R-ONE SttsService API를 호출하여 통계 행 목록을 반환한다."""
        params = {
            "apiKey":     self._api_key,
            "statsCode":  stats_code,
            "prdSe":      prd_se,
            "startPrdDe": start_prd,
            "endPrdDe":   end_prd,
            "format":     "json",
        }
        resp = self._client.get(RBONE_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

        # 응답 구조: {"SttsService": {"list": [...], "totalCnt": N}}
        # 또는 오류: {"result": {"resultCode": "...", "resultMsg": "..."}}
        if "SttsService" not in data:
            error = data.get("result", {})
            raise RuntimeError(f"R-ONE API 오류: {error.get('resultMsg', data)}")

        return data["SttsService"].get("list", [])

    def _parse_float(self, val: str | None) -> float:
        try:
            return float(str(val).strip().replace(",", ""))
        except (TypeError, ValueError):
            return -1.0

    def get_price_indices(
        self,
        start_period: str,
        end_period: str,
        regions: list[str] | None = None,
    ) -> list[PriceIndexResult]:
        """기간 내 주간 아파트 매매·전세가격지수를 수집한다.

        Args:
            start_period: 시작 주차 (YYYYWW)
            end_period:   종료 주차 (YYYYWW)
            regions:      수집할 지역 목록 (None이면 REGION_CODES 전체)
        """
        if regions is None:
            regions = list(REGION_CODES.keys())

        sale_rows = self._fetch(DEFAULT_SALE_IDX_CODE, "W", start_period, end_period)
        time.sleep(0.5)
        jeonse_rows = self._fetch(DEFAULT_JEONSE_IDX_CODE, "W", start_period, end_period)

        # (period, region) → value 인덱스
        # R-ONE 응답 필드: prdDe(기간), prdNm(기간명), wghtVal(지수), regNm(지역명) 등 — 실제 필드명은 API 응답 확인 후 조정
        sale_idx = {(r.get("prdDe", ""), r.get("regNm", "")): self._parse_float(r.get("wghtVal")) for r in sale_rows}
        jeonse_idx = {(r.get("prdDe", ""), r.get("regNm", "")): self._parse_float(r.get("wghtVal")) for r in jeonse_rows}

        all_keys = sorted(set(sale_idx) | set(jeonse_idx))
        results = []
        for period, region in all_keys:
            if region not in regions:
                continue
            results.append(PriceIndexResult(
                period=period,
                region=region,
                sale_index=sale_idx.get((period, region), -1.0),
                jeonse_index=jeonse_idx.get((period, region), -1.0),
            ))

        logger.info("[rbone] 가격지수 {} ~ {} → {}건", start_period, end_period, len(results))
        return results

    def get_jeonse_ratios(
        self,
        start_period: str,
        end_period: str,
        regions: list[str] | None = None,
    ) -> list[JeonseRatioResult]:
        """기간 내 주간 전세가율을 수집한다."""
        if regions is None:
            regions = list(REGION_CODES.keys())

        rows = self._fetch(DEFAULT_JEONSE_RATIO_CODE, "W", start_period, end_period)
        results = []
        for r in rows:
            region = r.get("regNm", "")
            if region not in regions:
                continue
            results.append(JeonseRatioResult(
                period=r.get("prdDe", ""),
                region=region,
                jeonse_ratio=self._parse_float(r.get("wghtVal")),
            ))

        logger.info("[rbone] 전세가율 {} ~ {} → {}건", start_period, end_period, len(results))
        return results

    def get_latest(self, current_week: str) -> tuple[list[PriceIndexResult], list[JeonseRatioResult]]:
        """최신 주차 1건의 가격지수 + 전세가율을 반환한다."""
        indices = self.get_price_indices(current_week, current_week)
        time.sleep(0.5)
        ratios = self.get_jeonse_ratios(current_week, current_week)
        return indices, ratios
