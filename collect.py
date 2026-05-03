"""
부동산 시장 지표 자동 수집 메인 진입점.

수집 대상 (4종):
  R-ONE  → 아파트 매매·전세 가격지수, 전세가율 (주간)
  ECOS   → 기준금리, 주담대금리 (월간)
  MOLIT  → 아파트 실거래가 (월간, 시군구별)
  MOLIT  → 미분양주택 현황 (월간, 시도별)

사용법:
  python collect.py                          # 전체 수집 (이번 주 R-ONE + 전월 MOLIT)
  python collect.py --source rbone           # R-ONE만
  python collect.py --source ecos            # ECOS만
  python collect.py --source molit           # MOLIT 실거래가+미분양만
  python collect.py --deal-ym 202503         # 특정 거래년월 지정 (MOLIT용)
  python collect.py --week 202520            # 특정 주차 지정 (R-ONE용, YYYYWW)
  python collect.py --csv                    # 로컬 CSV 저장 (디버그)
  python collect.py --no-sheets              # Sheets 적재 생략
  python collect.py --dry-run                # API 호출 없이 수집 계획 출력
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from transform import (
    CollectResult,
    normalize_price_index,
    normalize_interest_rate, normalize_apt_trade, normalize_unsold,
    to_csv_rows,
)

load_dotenv()

KST = timezone(timedelta(hours=9))
REGIONS_PATH = Path(__file__).parent / "data" / "regions.json"


# ── 날짜 헬퍼 ──────────────────────────────────────────────────────────────────

def _now_kst() -> datetime:
    return datetime.now(KST)


def _prev_month_ym(dt: datetime) -> str:
    """전월 YYYYMM 반환."""
    first = dt.replace(day=1)
    prev = first - timedelta(days=1)
    return prev.strftime("%Y%m")


def _current_week(dt: datetime) -> str:
    """현재 주차 YYYYWW 반환 (ISO 주차)."""
    return f"{dt.isocalendar()[0]}{dt.isocalendar()[1]:02d}"


# ── 지역 로드 ──────────────────────────────────────────────────────────────────

def load_regions(region_filter: str | None = None) -> list[dict]:
    with open(REGIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    regions = data["regions"]
    if region_filter:
        regions = [
            r for r in regions
            if region_filter in (r["region_level1"] + r["region_level2"])
        ]
    return regions


# ── 수집 함수 ──────────────────────────────────────────────────────────────────

def collect_rbone(result: CollectResult, week: str):
    """R-ONE에서 주간 가격지수 + 전세가율을 수집한다."""
    api_key = os.getenv("RBONE_API_KEY")
    if not api_key:
        logger.warning("[rbone] RBONE_API_KEY 미설정 — 건너뜀")
        return

    from scrapers.rbone import RboneScraper
    logger.info("[rbone] 주차 {} 수집 시작", week)
    try:
        with RboneScraper(api_key) as sc:
            indices = sc.get_latest(week)
        result.price_index_rows.extend(normalize_price_index(indices))
        result.sources_used.append("rbone")
        logger.info("[rbone] 완료 — 가격지수 {}건 (jeonse_idx_ratio 파생 포함)", len(indices))
    except Exception as exc:
        logger.error("[rbone] 수집 실패: {}", exc)
        result.error_count += 1


def collect_ecos(result: CollectResult, year_month: str):
    """ECOS에서 월간 금리를 수집한다."""
    api_key = os.getenv("ECOS_API_KEY")
    if not api_key:
        logger.warning("[ecos] ECOS_API_KEY 미설정 — 건너뜀")
        return

    from scrapers.ecos import EcosScraper
    logger.info("[ecos] {} 금리 수집 시작", year_month)
    try:
        with EcosScraper(api_key) as sc:
            rates = sc.get_interest_rates(year_month, year_month)
        result.interest_rate_rows.extend(normalize_interest_rate(rates))
        result.sources_used.append("ecos")
        logger.info("[ecos] 완료 — {}건", len(rates))
    except Exception as exc:
        logger.error("[ecos] 수집 실패: {}", exc)
        result.error_count += 1


def collect_molit(result: CollectResult, deal_ym: str, regions: list[dict]):
    """MOLIT에서 실거래가 + 미분양을 수집한다."""
    api_key = os.getenv("DATA_GO_KR_API_KEY")
    if not api_key:
        logger.warning("[molit] DATA_GO_KR_API_KEY 미설정 — 건너뜀")
        return

    from scrapers.molit import MolitScraper
    logger.info("[molit] {} 수집 시작 ({} 개 시군구)", deal_ym, len(regions))
    try:
        with MolitScraper(api_key) as sc:
            trades = sc.scrape_all_trades(regions, deal_ym)
            unsold = sc.get_unsold(deal_ym)
        result.apt_trade_rows.extend(normalize_apt_trade(trades))
        result.unsold_rows.extend(normalize_unsold(unsold))
        result.sources_used.append("molit")
        logger.info("[molit] 완료 — 실거래가 {}건, 미분양 {}건", len(trades), len(unsold))
    except Exception as exc:
        logger.error("[molit] 수집 실패: {}", exc)
        result.error_count += 1


# ── CSV 저장 ───────────────────────────────────────────────────────────────────

def save_csv(result: CollectResult, output_dir: str = "./output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    tables = to_csv_rows(result)
    timestamp = _now_kst().strftime("%Y%m%d_%H%M%S")
    for sheet_name, rows in tables.items():
        if len(rows) <= 1:
            continue
        path = Path(output_dir) / f"{timestamp}_{sheet_name}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        logger.info("CSV 저장: {}", path)


# ── Sheets 적재 ────────────────────────────────────────────────────────────────

def write_to_sheets(result: CollectResult, elapsed: float):
    from auth import get_sheets_service
    from writer import SheetsWriter, RunLogRow

    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    error_rate = result.error_count / max(result.total_rows, 1)
    status = "success" if result.error_count == 0 else (
        "failed" if error_rate >= 0.5 else "partial"
    )
    log_row = RunLogRow(
        run_at=result.collected_at,
        status=status,
        total_rows=result.total_rows,
        error_count=result.error_count,
        sources_used=",".join(result.sources_used),
        duration_sec=elapsed,
    )
    service = get_sheets_service()
    writer = SheetsWriter(service, sheets_id)
    writer.write(result, log_row)
    logger.info("Google Sheets 적재 완료")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="부동산 시장 지표 수집")
    parser.add_argument(
        "--source",
        choices=["all", "rbone", "ecos", "molit"],
        default="all",
        help="수집할 소스 (기본: all)",
    )
    parser.add_argument("--deal-ym", default=None, help="MOLIT 거래년월 (YYYYMM, 기본: 전월)")
    parser.add_argument("--week", default=None, help="R-ONE 주차 (YYYYWW, 기본: 현재 주차)")
    parser.add_argument("--region", default=None, help="지역 필터 (예: 강남구, 서울)")
    parser.add_argument("--csv", action="store_true", help="로컬 CSV 저장")
    parser.add_argument("--no-sheets", action="store_true", help="Sheets 적재 생략")
    parser.add_argument("--dry-run", action="store_true", help="수집 계획만 출력")
    return parser.parse_args()


def main():
    args = parse_args()
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"), colorize=True)

    now = _now_kst()
    deal_ym = args.deal_ym or _prev_month_ym(now)
    week = args.week or _current_week(now)
    regions = load_regions(args.region)

    if args.dry_run:
        print(f"수집 계획 (dry-run)")
        print(f"  R-ONE 주차:   {week}")
        print(f"  MOLIT 거래월:  {deal_ym}")
        print(f"  대상 지역:    {len(regions)}개 시군구")
        print(f"  소스:         {args.source}")
        return

    logger.info("=== 수집 시작 source={} deal_ym={} week={} ===", args.source, deal_ym, week)
    start = time.time()
    result = CollectResult(collected_at=now.strftime("%Y-%m-%d %H:%M:%S"))
    run_all = args.source == "all"

    if run_all or args.source == "rbone":
        collect_rbone(result, week)
    if run_all or args.source == "ecos":
        collect_ecos(result, deal_ym)
    if run_all or args.source == "molit":
        collect_molit(result, deal_ym, regions)

    result.recount()
    elapsed = time.time() - start
    logger.info(
        "=== 수집 완료: 총 {}행, 오류 {}건, 소요 {:.1f}초 ===",
        result.total_rows, result.error_count, elapsed,
    )

    if args.csv or os.getenv("OUTPUT_CSV", "").lower() == "true":
        save_csv(result, os.getenv("OUTPUT_CSV_PATH", "./output"))

    skip_sheets = args.no_sheets or not os.getenv("GOOGLE_SHEETS_ID")
    if skip_sheets:
        if not args.no_sheets:
            logger.info("GOOGLE_SHEETS_ID 미설정 → Sheets 적재 생략")
    else:
        try:
            write_to_sheets(result, elapsed)
        except Exception as exc:
            logger.error("Sheets 적재 실패: {}", exc)
            sys.exit(1)

    error_rate = result.error_count / max(result.total_rows, 1)
    if error_rate >= 0.20:
        logger.error("오류율 {:.1%} 임계값 초과", error_rate)
        sys.exit(1)


if __name__ == "__main__":
    main()
