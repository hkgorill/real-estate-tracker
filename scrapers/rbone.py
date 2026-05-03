"""
한국부동산원(R-ONE) OpenAPI 수집 모듈.

[아파트 매매가격지수 / 전세가격지수] 주간(WK) 데이터

엔드포인트:
  목록 조회 : GET https://www.reb.or.kr/r-one/openapi/SttsApiTbl.do
  항목 조회 : GET https://www.reb.or.kr/r-one/openapi/SttsApiTblItm.do
  데이터 조회: GET https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do

데이터 조회 파라미터:
  apiKey          : 발급 API 키
  STATBL_ID       : 통계표ID (환경변수 RBONE_SALE_IDX_CODE / RBONE_JEONSE_IDX_CODE)
  DTACYCLE_CD     : WK (주간 고정)
  WRTTIME_IDTFR_ID: 조회 주차 (YYYYWW, 예: 202518)

통계표ID 확인:
  R-ONE 포털 → 오픈API → 통계표코드 조회
  (주) 매매가격지수 → RBONE_SALE_IDX_CODE
  (주) 전세가격지수 → RBONE_JEONSE_IDX_CODE

전세가율: R-ONE 주간 전세가율 통계 없음 → transform에서 (전세지수/매매지수×100) 파생
"""

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

RBONE_BASE_URL   = "https://www.reb.or.kr/r-one/openapi"
RBONE_DATA_URL   = f"{RBONE_BASE_URL}/SttsApiTblData.do"

DEFAULT_SALE_IDX_CODE   = os.getenv("RBONE_SALE_IDX_CODE",   "")
DEFAULT_JEONSE_IDX_CODE = os.getenv("RBONE_JEONSE_IDX_CODE", "")

# 수집 대상 지역명 (API 응답 CLS_NM 기준, 전국·수도권·서울·경기·인천)
REGION_NAMES = ["전국", "수도권", "서울", "서울특별시", "경기", "경기도", "인천", "인천광역시"]


@dataclass
class PriceIndexResult:
    """주간 아파트 가격지수 1건."""
    period: str         # YYYYWW (예: 202518)
    region: str         # 지역명
    sale_index: float   # 매매가격지수
    jeonse_index: float # 전세가격지수
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
    def _fetch(self, statbl_id: str, period: str) -> list[dict]:
        """SttsApiTblData.do를 호출하여 주간 통계 행 목록을 반환한다."""
        params = {
            "apiKey":           self._api_key,
            "STATBL_ID":        statbl_id,
            "DTACYCLE_CD":      "WK",
            "WRTTIME_IDTFR_ID": period,
        }
        resp = self._client.get(RBONE_DATA_URL, params=params)
        resp.raise_for_status()

        text = resp.text.strip()
        if not text:
            raise RuntimeError(f"R-ONE 빈 응답 (STATBL_ID={statbl_id}, period={period})")

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise RuntimeError(f"R-ONE XML 파싱 실패: {e}. 응답: {text[:300]}")

        # 오류 응답: <RESULT><CODE>...</CODE><MESSAGE>...</MESSAGE></RESULT>
        result_code = root.findtext("CODE") or (root.find("head/RESULT/CODE") and root.findtext("head/RESULT/CODE"))
        if result_code and result_code.startswith("ERROR"):
            msg = root.findtext("MESSAGE") or root.findtext("head/RESULT/MESSAGE") or ""
            raise RuntimeError(f"R-ONE API 오류 {result_code}: {msg}")

        # INFO-200: 데이터 없음 (정상 - 해당 주차 데이터 미발표)
        info_code = root.findtext("head/RESULT/CODE") or root.findtext("CODE") or ""
        if info_code == "INFO-200":
            logger.warning("[rbone] {} {} 데이터 없음 (아직 미발표)", statbl_id, period)
            return []

        # 성공: <row> 목록 파싱
        rows = []
        for row in root.findall(".//row"):
            item = {child.tag: (child.text or "").strip() for child in row}
            rows.append(item)

        if rows:
            logger.debug("[rbone] 첫 행 필드: {}", list(rows[0].keys()))

        return rows

    def _parse_float(self, val: str | None) -> float:
        try:
            return float(str(val).strip().replace(",", ""))
        except (TypeError, ValueError):
            return -1.0

    def get_price_indices(
        self,
        period: str,
        regions: list[str] | None = None,
    ) -> list[PriceIndexResult]:
        """주간 아파트 매매·전세가격지수를 수집한다.

        Args:
            period:  조회 주차 (YYYYWW, 예: 202518)
            regions: 수집할 지역명 목록 (None이면 REGION_NAMES 전체)
        """
        sale_code   = DEFAULT_SALE_IDX_CODE
        jeonse_code = DEFAULT_JEONSE_IDX_CODE
        if not sale_code or not jeonse_code:
            raise RuntimeError(
                "RBONE_SALE_IDX_CODE / RBONE_JEONSE_IDX_CODE 환경변수가 설정되지 않았습니다."
            )
        if regions is None:
            regions = REGION_NAMES

        sale_rows   = self._fetch(sale_code, period)
        time.sleep(0.5)
        jeonse_rows = self._fetch(jeonse_code, period)

        # ITM_NM(지역명) → DTA_VAL(지수값) 인덱스 구성
        # 응답 필드명은 첫 성공 호출 후 DEBUG 로그로 확인 가능
        def _region(row: dict) -> str:
            return row.get("CLS_NM", "")

        def _val(row: dict) -> float:
            # 실제 값 필드명은 첫 응답 확인 후 확정 (DTA_VAL 추정)
            for key in ("DTA_VAL", "WGHT_VAL", "DATA_VALUE", "wghtVal", "dataValue"):
                if key in row and row[key]:
                    return self._parse_float(row[key])
            return -1.0

        sale_idx   = {_region(r): _val(r) for r in sale_rows}
        jeonse_idx = {_region(r): _val(r) for r in jeonse_rows}

        all_regions = sorted(set(sale_idx) | set(jeonse_idx))
        results = []
        for region in all_regions:
            if region not in regions:
                continue
            results.append(PriceIndexResult(
                period=period,
                region=region,
                sale_index=sale_idx.get(region, -1.0),
                jeonse_index=jeonse_idx.get(region, -1.0),
            ))

        logger.info("[rbone] {} 가격지수 → {}건", period, len(results))
        return results

    def get_latest(self, current_week: str) -> list[PriceIndexResult]:
        """최신 주차의 가격지수를 반환한다."""
        return self.get_price_indices(current_week)
