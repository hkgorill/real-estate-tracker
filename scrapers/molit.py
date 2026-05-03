"""
국토교통부 실거래가 공개시스템 API 수집 모듈.

[아파트 매매 실거래 상세자료]
  URL: http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev
  파라미터: serviceKey, LAWD_CD (5자리), DEAL_YMD (YYYYMM), pageNo, numOfRows

[미분양주택현황보고]
  URL: http://apis.data.go.kr/1613000/UsrRtmsDataSvcUnsldRtclc/getRTMSDataSvcUnsldRtclcList
  파라미터: serviceKey, DEAL_YMD (YYYYMM), pageNo, numOfRows

API 키 발급: https://www.data.go.kr → 마이페이지 → 인증키
"""

import random
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

BASE_URL = "http://apis.data.go.kr/1613000"
TRADE_URL = f"{BASE_URL}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
UNSOLD_URL = f"{BASE_URL}/UsrRtmsDataSvcUnsldRtclc/getRTMSDataSvcUnsldRtclcList"

ROWS_PER_PAGE = 100


@dataclass
class AptTradeItem:
    """아파트 매매 실거래 1건."""
    deal_ym: str          # YYYYMM
    deal_day: str         # DD
    region_level1: str
    region_level2: str
    dong: str             # 법정동
    apt_name: str         # 아파트명
    area_sqm: float       # 전용면적 (m²)
    floor: int            # 층
    price_manwon: int     # 거래금액 (만원)
    build_year: int       # 건축년도
    source: str = "molit_trade"


@dataclass
class UnsoldItem:
    """미분양주택 현황 1건 (시도 단위)."""
    deal_ym: str          # YYYYMM
    region_level1: str    # 시도명
    unsold_total: int     # 미분양 합계 (준공 전 + 준공 후)
    unsold_before: int    # 준공 전 미분양
    unsold_after: int     # 준공 후 미분양 (악성 미분양)
    source: str = "molit_unsold"


class MolitScraper:
    def __init__(
        self,
        api_key: str,
        request_delay_min: float = 0.5,
        request_delay_max: float = 1.5,
        timeout: float = 30.0,
    ):
        self._api_key = api_key
        self._delay_min = request_delay_min
        self._delay_max = request_delay_max
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

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
        wait=wait_exponential(multiplier=2, min=2, max=20),
        reraise=True,
    )
    def _get_xml(self, url: str, params: dict) -> ET.Element:
        # serviceKey는 URL 인코딩 없이 직접 전달 (공공데이터포털 특성)
        params_with_key = {"serviceKey": self._api_key, **params}
        resp = self._client.get(url, params=params_with_key)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        result_code = root.findtext("header/resultCode") or root.findtext("resultCode") or "00"
        if result_code not in ("00", "000", "0000"):
            result_msg = root.findtext("header/resultMsg") or root.findtext("resultMsg") or "Unknown"
            raise RuntimeError(f"API 오류 {result_code}: {result_msg}")
        return root

    def _parse_int(self, text: str | None, default: int = 0) -> int:
        if not text:
            return default
        return int(text.strip().replace(",", ""))

    def _parse_float(self, text: str | None, default: float = 0.0) -> float:
        if not text:
            return default
        return float(text.strip().replace(",", ""))

    # ── 실거래가 ──────────────────────────────────────────────────────────────

    def get_apt_trades(
        self,
        region_level1: str,
        region_level2: str,
        lawd_cd: str,
        deal_ym: str,
    ) -> list[AptTradeItem]:
        """시군구 + 거래년월 기준으로 아파트 매매 실거래 전 건을 수집한다."""
        results = []
        page = 1

        while True:
            self._sleep()
            try:
                root = self._get_xml(TRADE_URL, {
                    "LAWD_CD": lawd_cd,
                    "DEAL_YMD": deal_ym,
                    "pageNo": page,
                    "numOfRows": ROWS_PER_PAGE,
                })
            except Exception as exc:
                logger.warning("[molit] {} {} {} 페이지{} 오류: {}", region_level1, region_level2, deal_ym, page, exc)
                break

            items = root.findall(".//item")
            for item in items:
                results.append(AptTradeItem(
                    deal_ym=deal_ym,
                    deal_day=item.findtext("일") or "",
                    region_level1=region_level1,
                    region_level2=region_level2,
                    dong=(item.findtext("법정동") or "").strip(),
                    apt_name=(item.findtext("아파트") or "").strip(),
                    area_sqm=self._parse_float(item.findtext("전용면적")),
                    floor=self._parse_int(item.findtext("층")),
                    price_manwon=self._parse_int(item.findtext("거래금액")),
                    build_year=self._parse_int(item.findtext("건축년도")),
                ))

            total_count = self._parse_int(root.findtext(".//totalCount"))
            if page * ROWS_PER_PAGE >= total_count:
                break
            page += 1

        logger.info("[molit_trade] {} {} {} → {}건", region_level1, region_level2, deal_ym, len(results))
        return results

    def scrape_all_trades(
        self,
        regions: list[dict],
        deal_ym: str,
    ) -> list[AptTradeItem]:
        """수도권 전 지역의 실거래가를 수집한다."""
        all_results = []
        for region in regions:
            try:
                items = self.get_apt_trades(
                    region["region_level1"],
                    region["region_level2"],
                    region["lawd_cd"],
                    deal_ym,
                )
                all_results.extend(items)
            except Exception as exc:
                logger.warning(
                    "[molit_trade] {} {} 수집 실패: {}",
                    region["region_level1"], region["region_level2"], exc,
                )
        return all_results

    # ── 미분양 ────────────────────────────────────────────────────────────────

    def get_unsold(self, deal_ym: str) -> list[UnsoldItem]:
        """전국 시도별 미분양주택 현황을 수집한다."""
        results = []
        page = 1

        while True:
            self._sleep()
            try:
                root = self._get_xml(UNSOLD_URL, {
                    "DEAL_YMD": deal_ym,
                    "pageNo": page,
                    "numOfRows": ROWS_PER_PAGE,
                })
            except Exception as exc:
                logger.warning("[molit_unsold] {} 페이지{} 오류: {}", deal_ym, page, exc)
                break

            items = root.findall(".//item")
            for item in items:
                sido = (item.findtext("시도명") or "").strip()
                # 수도권만 필터링
                if sido not in ("서울특별시", "인천광역시", "경기도"):
                    continue
                results.append(UnsoldItem(
                    deal_ym=deal_ym,
                    region_level1=sido,
                    unsold_total=self._parse_int(item.findtext("미분양합계")),
                    unsold_before=self._parse_int(item.findtext("준공전")),
                    unsold_after=self._parse_int(item.findtext("준공후")),
                ))

            total_count = self._parse_int(root.findtext(".//totalCount"))
            if page * ROWS_PER_PAGE >= total_count:
                break
            page += 1

        logger.info("[molit_unsold] {} → {}건 (수도권)", deal_ym, len(results))
        return results
