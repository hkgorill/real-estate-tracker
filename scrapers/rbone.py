"""
한국부동산원(R-ONE) OpenAPI 수집 모듈.

[아파트 매매가격지수 / 전세가격지수] 주간 데이터

전세가율(주간) R-ONE 통계표 없음 → transform에서 (전세지수/매매지수×100)으로 파생 계산.
이 값은 실제 전세가율이 아닌 지수 비율이며, 방향성·변화폭 분석에 활용한다.

엔드포인트: https://www.reb.or.kr/r-one/openapi/SttsService.do
  파라미터:
    apiKey      : 발급 API 키
    statsCode   : 통계표코드 (환경변수 RBONE_SALE_IDX_CODE / RBONE_JEONSE_IDX_CODE)
    prdSe       : 기간구분 (W=주간)
    startPrdDe  : 시작기간 (YYYYWW)
    endPrdDe    : 종료기간 (YYYYWW)
    항목코드     : 지수=10001 (환경변수 RBONE_ITEM_CODE, 기본 10001)

  응답: XML (format=json 미지원)
  성공 구조: <SttsService><list><item><prdDe>…</prdDe><regNm>…</regNm><wghtVal>…</wghtVal></item></list></SttsService>
  오류 구조: <RESULT><CODE>ERROR-XXX</CODE><MESSAGE>…</MESSAGE></RESULT>

통계표코드 확인:
  R-ONE 포털 → 오픈API → 통계표코드 조회 → "(주) 매매가격지수" / "(주) 전세가격지수"

API 키 발급: https://www.reb.or.kr/r-one → 오픈API → 활용신청
"""

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

RBONE_API_URL = "https://www.reb.or.kr/r-one/openapi/SttsService.do"

DEFAULT_SALE_IDX_CODE   = os.getenv("RBONE_SALE_IDX_CODE",   "")
DEFAULT_JEONSE_IDX_CODE = os.getenv("RBONE_JEONSE_IDX_CODE", "")
DEFAULT_ITEM_CODE       = os.getenv("RBONE_ITEM_CODE", "10001")  # 지수 항목코드

# R-ONE 통계표 지역명 (API 응답 regNm 필드 기준)
# 실제 응답이 "서울" 또는 "서울특별시" 등 두 형태로 올 수 있어 모두 허용
REGION_NAMES = ["전국", "수도권", "서울", "서울특별시", "경기", "경기도", "인천", "인천광역시"]

# 지역상세코드 (참고용 — API 파라미터 없이 전체 수집 후 필터링)
REGION_DETAIL_CODES = {
    "전국":  "1000010",
    "수도권": "1000020",
    "서울":  "11000000",
    "경기":  "41000000",
    "인천":  "26000000",
}


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
    def _fetch(self, stats_code: str, prd_se: str, start_prd: str, end_prd: str) -> list[dict]:
        """R-ONE SttsService API를 호출하여 통계 행 목록을 반환한다 (XML 파싱)."""
        params = {
            "apiKey":     self._api_key,
            "statsCode":  stats_code,
            "prdSe":      prd_se,
            "startPrdDe": start_prd,
            "endPrdDe":   end_prd,
            "항목코드":    DEFAULT_ITEM_CODE,
        }
        resp = self._client.get(RBONE_API_URL, params=params)
        resp.raise_for_status()

        text = resp.text.strip()
        if not text:
            raise RuntimeError(
                f"R-ONE API 빈 응답 (statsCode={stats_code}). "
                "통계표코드·항목코드를 확인하세요."
            )

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise RuntimeError(f"R-ONE XML 파싱 실패: {e}. 응답: {text[:300]}")

        # 오류 응답: <RESULT><CODE>ERROR-XXX</CODE><MESSAGE>…</MESSAGE></RESULT>
        error_code = root.findtext("CODE") or root.findtext("code")
        if error_code:
            msg = root.findtext("MESSAGE") or root.findtext("message") or "알 수 없는 오류"
            raise RuntimeError(f"R-ONE API 오류 {error_code}: {msg}")

        # 성공 응답: <SttsService><list><item>…</item></list></SttsService>
        rows = []
        for item in root.findall(".//item"):
            row = {child.tag: (child.text or "").strip() for child in item}
            rows.append(row)

        return rows

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
        """기간 내 주간 아파트 매매·전세가격지수를 수집한다."""
        sale_code   = DEFAULT_SALE_IDX_CODE
        jeonse_code = DEFAULT_JEONSE_IDX_CODE
        if not sale_code or not jeonse_code:
            raise RuntimeError(
                "RBONE_SALE_IDX_CODE / RBONE_JEONSE_IDX_CODE 환경변수가 설정되지 않았습니다."
            )
        if regions is None:
            regions = REGION_NAMES

        sale_rows = self._fetch(sale_code, prd_se="W",
                                start_prd=start_period, end_prd=end_period)
        time.sleep(0.5)
        jeonse_rows = self._fetch(jeonse_code, prd_se="W",
                                  start_prd=start_period, end_prd=end_period)

        # 첫 행을 로깅해서 실제 XML 필드명 확인
        if sale_rows:
            logger.debug("[rbone] 매매 첫 행 필드: {}", list(sale_rows[0].keys()))

        # prdDe(기간), regNm(지역명), wghtVal(가중지수값) — 실제 필드명에 따라 조정
        def _key(row: dict) -> tuple[str, str]:
            return row.get("prdDe", ""), row.get("regNm", "")

        def _val(row: dict) -> float:
            return self._parse_float(row.get("wghtVal") or row.get("dataValue"))

        sale_idx   = {_key(r): _val(r) for r in sale_rows}
        jeonse_idx = {_key(r): _val(r) for r in jeonse_rows}

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

    def get_latest(self, current_week: str) -> list[PriceIndexResult]:
        """최신 주차의 가격지수를 반환한다."""
        return self.get_price_indices(current_week, current_week)
