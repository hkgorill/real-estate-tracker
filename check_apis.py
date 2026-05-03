"""
API 키 및 접속 검증 스크립트.

발급받은 API 키가 실제로 작동하는지, R-ONE 통계코드가 맞는지 확인한다.

사용:
  python check_apis.py
"""

import os
import sys

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

logger.remove()
logger.add(sys.stderr, level="DEBUG", colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")

PASS = "✓"
FAIL = "✗"
SKIP = "─"


def check_ecos():
    api_key = os.getenv("ECOS_API_KEY")
    if not api_key:
        logger.warning(f"{SKIP} ECOS: ECOS_API_KEY 미설정")
        return False

    from scrapers.ecos import EcosScraper
    try:
        with EcosScraper(api_key) as sc:
            rates = sc.get_interest_rates("202503", "202503")
        if rates:
            r = rates[0]
            logger.success(f"{PASS} ECOS: 기준금리={r.base_rate}%, 주담대={r.mortgage_rate}% (202503)")
            return True
        else:
            logger.error(f"{FAIL} ECOS: 응답 데이터 없음")
            return False
    except Exception as e:
        logger.error(f"{FAIL} ECOS: {e}")
        return False


def check_molit():
    api_key = os.getenv("DATA_GO_KR_API_KEY")
    if not api_key:
        logger.warning(f"{SKIP} MOLIT: DATA_GO_KR_API_KEY 미설정")
        return False

    from scrapers.molit import MolitScraper
    try:
        with MolitScraper(api_key) as sc:
            # 강남구만 빠르게 테스트
            regions = [{"region_level1": "서울특별시", "region_level2": "강남구", "lawd_cd": "11680"}]
            trades = sc.scrape_all_trades(regions, "202503")
        if trades:
            t = trades[0]
            logger.success(f"{PASS} MOLIT 실거래가: {t.apt_name} {t.area_sqm}㎡ {t.price_manwon:,}만원 (강남구 202503, 총 {len(trades)}건)")
            return True
        else:
            logger.warning(f"{SKIP} MOLIT 실거래가: 데이터 없음 (API는 정상, 해당 기간 거래 없을 수 있음)")
            return True
    except Exception as e:
        logger.error(f"{FAIL} MOLIT 실거래가: {e}")
        return False


def check_molit_unsold():
    api_key = os.getenv("DATA_GO_KR_API_KEY")
    if not api_key:
        return False

    from scrapers.molit import MolitScraper
    try:
        with MolitScraper(api_key) as sc:
            unsold = sc.get_unsold("202503")
        if unsold:
            u = unsold[0]
            logger.success(f"{PASS} MOLIT 미분양: {u.region_level1} 총{u.unsold_total}호 (202503, 총 {len(unsold)}건)")
            return True
        else:
            logger.warning(f"{SKIP} MOLIT 미분양: 데이터 없음")
            return True
    except Exception as e:
        logger.error(f"{FAIL} MOLIT 미분양: {e}")
        return False


def check_rbone():
    api_key = os.getenv("RBONE_API_KEY")
    if not api_key:
        logger.warning(f"{SKIP} R-ONE: RBONE_API_KEY 미설정")
        return False

    sale_code = os.getenv("RBONE_SALE_IDX_CODE", "R214000000")
    jeonse_code = os.getenv("RBONE_JEONSE_IDX_CODE", "R214000100")
    logger.info(f"R-ONE 매매 코드: {sale_code} / 전세 코드: {jeonse_code}")

    from scrapers.rbone import RboneScraper
    try:
        with RboneScraper(api_key) as sc:
            results = sc.get_latest("202518")
        if results:
            r = next((x for x in results if x.region == "전국"), results[0])
            logger.success(
                f"{PASS} R-ONE: 전국 매매지수={r.sale_index} 전세지수={r.jeonse_index} "
                f"(202518, 총 {len(results)}개 지역)"
            )
            return True
        else:
            logger.error(f"{FAIL} R-ONE: 응답 데이터 없음 — 통계코드를 확인하세요")
            logger.error(f"  현재 코드: RBONE_SALE_IDX_CODE={sale_code}, RBONE_JEONSE_IDX_CODE={jeonse_code}")
            logger.error(f"  R-ONE 포털에서 실제 코드 확인: https://www.reb.or.kr/r-one → 오픈API → 통계표코드 조회")
            return False
    except Exception as e:
        logger.error(f"{FAIL} R-ONE: {e}")
        if "statsCode" in str(e) or "resultCode" in str(e) or "통계표" in str(e):
            logger.error(f"  통계코드가 올바르지 않을 수 있습니다.")
            logger.error(f"  R-ONE 포털에서 실제 코드 확인: https://www.reb.or.kr/r-one → 오픈API → 통계표코드 조회")
        return False


def check_rbone_raw():
    """R-ONE 요청 URL을 출력하고 원본 응답(첫 500자)을 보여준다."""
    api_key = os.getenv("RBONE_API_KEY")
    if not api_key:
        return

    import urllib.parse
    import httpx
    from scrapers.rbone import RBONE_DATA_URL, DEFAULT_SALE_IDX_CODE

    params = {
        "apiKey":           api_key,
        "STATBL_ID":        DEFAULT_SALE_IDX_CODE,
        "DTACYCLE_CD":      "WK",
        "WRTTIME_IDTFR_ID": "202518",
    }
    full_url = RBONE_DATA_URL + "?" + urllib.parse.urlencode(params, encoding="utf-8")
    logger.info("R-ONE 테스트 URL (브라우저에서 직접 확인 가능):")
    logger.info("  {}", full_url)

    try:
        resp = httpx.get(RBONE_DATA_URL, params=params, timeout=15, follow_redirects=True)
        logger.info("  HTTP 상태: {}", resp.status_code)
        logger.info("  응답 내용: {}", resp.text[:500] if resp.text else "(빈 응답)")
    except Exception as e:
        logger.error(f"  원본 응답 확인 실패: {e}")


def main():
    print("=" * 55)
    print("  API 연결 검증")
    print("=" * 55)

    results = {
        "ECOS":         check_ecos(),
        "MOLIT 실거래가":  check_molit(),
        "MOLIT 미분양":   check_molit_unsold(),
        "R-ONE":        check_rbone(),
    }

    # R-ONE 실패 시 원본 응답 구조 확인
    if not results["R-ONE"]:
        print()
        check_rbone_raw()

    print()
    print("=" * 55)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"  결과: {passed}/{total} 통과")
    for name, ok in results.items():
        icon = PASS if ok else (SKIP if ok is None else FAIL)
        print(f"  {icon} {name}")
    print("=" * 55)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
