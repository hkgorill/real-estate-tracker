"""
수도권 아파트 잔여 매물 수집 메인 진입점.

사용법:
  python collect.py                  # 전체 수집
  python collect.py --region 강남구  # 특정 구만 수집
  python collect.py --dry-run        # API 호출 없이 구조 검증
  python collect.py --csv            # CSV로 로컬 저장 (디버그)
  python collect.py --source naver   # 소스 강제 지정 (zigbang|naver)
  python collect.py --no-sheets      # Google Sheets 적재 생략
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

from scrapers.zigbang import ZigbangScraper
from scrapers.naver import NaverScraper
from transform import normalize, to_csv_rows

load_dotenv()

KST = timezone(timedelta(hours=9))
REGIONS_PATH = Path(__file__).parent / "data" / "regions.json"


def load_regions(region_filter: str | None = None) -> list[dict]:
    with open(REGIONS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    regions = data["regions"]
    if region_filter:
        regions = [r for r in regions if region_filter in (r["region_level1"] + r["region_level2"])]
    return regions


def scrape_with_fallback(
    regions: list[dict],
    source: str = "auto",
    delay_min: float = 1.0,
    delay_max: float = 3.0,
    timeout: float = 30.0,
) -> list:
    """
    직방 우선, 실패 시 네이버로 fallback하여 수집한다.
    source="auto"  → 직방 먼저, 지역별로 실패하면 네이버 fallback
    source="zigbang" → 직방만
    source="naver"   → 네이버만
    """
    all_results = []
    total = len(regions)

    zigbang = ZigbangScraper(delay_min, delay_max, timeout) if source in ("auto", "zigbang") else None
    naver = NaverScraper(delay_min, delay_max, timeout) if source in ("auto", "naver") else None

    try:
        for i, region in enumerate(regions, 1):
            name = f"{region['region_level1']} {region['region_level2']}"
            logger.info("[{}/{}] 수집 중: {}", i, total, name)

            if source == "naver":
                results = naver.scrape_region(region)
            elif source == "zigbang":
                results = zigbang.scrape_region(region)
            else:
                # auto: 직방 시도 후, 오류가 있으면 네이버로 보완
                results = zigbang.scrape_region(region)
                failed = [r for r in results if "error" in r.source]
                if failed:
                    logger.info("[fallback] {} 네이버로 재수집 ({} 오류)", name, len(failed))
                    failed_types = [r.trade_type for r in failed]
                    naver_results = naver.scrape_region(region, trade_types=failed_types)
                    # 실패한 거래유형을 네이버 결과로 교체
                    naver_by_type = {r.trade_type: r for r in naver_results}
                    results = [
                        naver_by_type.get(r.trade_type, r) if "error" in r.source else r
                        for r in results
                    ]

            all_results.extend(results)

    finally:
        if zigbang:
            zigbang.close()
        if naver:
            naver.close()

    return all_results


def save_csv(result, output_dir: str = "./output"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    tables = to_csv_rows(result)
    for sheet_name, rows in tables.items():
        path = Path(output_dir) / f"{result.date}_{sheet_name}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        logger.info("CSV 저장: {}", path)


def _write_to_sheets(result, elapsed: float, source: str):
    from auth import get_sheets_service
    from writer import SheetsWriter, RunLogRow

    sheets_id = os.getenv("GOOGLE_SHEETS_ID")
    error_rate = result.error_count / max(result.total_rows, 1)
    status = "success" if result.error_count == 0 else ("failed" if error_rate >= 0.5 else "partial")

    log_row = RunLogRow(
        run_at=result.collected_at,
        status=status,
        total_rows=result.total_rows,
        error_count=result.error_count,
        source_used=source,
        duration_sec=elapsed,
    )

    try:
        service = get_sheets_service()
        writer = SheetsWriter(service, sheets_id)
        writer.write(result, log_row)
        logger.info("Google Sheets 적재 완료")
    except Exception as exc:
        logger.error("Google Sheets 적재 실패: {}", exc)
        raise


def parse_args():
    parser = argparse.ArgumentParser(description="수도권 아파트 잔여 매물 수집")
    parser.add_argument("--region", help="수집할 지역 필터 (예: 강남구, 서울)")
    parser.add_argument("--source", choices=["auto", "zigbang", "naver"], default="auto")
    parser.add_argument("--csv", action="store_true", help="로컬 CSV로 저장")
    parser.add_argument("--dry-run", action="store_true", help="실제 API 호출 없이 지역 목록만 출력")
    parser.add_argument("--no-sheets", action="store_true", help="Google Sheets 적재 생략")
    parser.add_argument("--delay-min", type=float, default=float(os.getenv("REQUEST_DELAY_MIN", "1.0")))
    parser.add_argument("--delay-max", type=float, default=float(os.getenv("REQUEST_DELAY_MAX", "3.0")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("REQUEST_TIMEOUT", "30")))
    return parser.parse_args()


def main():
    args = parse_args()

    log_level = os.getenv("LOG_LEVEL", "INFO")
    logger.remove()
    logger.add(sys.stderr, level=log_level, colorize=True)

    regions = load_regions(args.region)
    logger.info("대상 지역: {}개", len(regions))

    if args.dry_run:
        for r in regions:
            print(f"  {r['region_level1']} {r['region_level2']} (cortarNo={r['cortar_no']})")
        print(f"\n총 {len(regions)}개 지역 × 3 거래유형 = {len(regions) * 3}건 수집 예정")
        return

    start = time.time()
    scraper_results = scrape_with_fallback(
        regions,
        source=args.source,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        timeout=args.timeout,
    )

    result = normalize(scraper_results)
    elapsed = time.time() - start

    logger.info(
        "수집 완료: 총 {}행, 오류 {}건, 소요 {:.1f}초",
        result.total_rows,
        result.error_count,
        elapsed,
    )

    if args.csv or os.getenv("OUTPUT_CSV", "").lower() == "true":
        save_csv(result, os.getenv("OUTPUT_CSV_PATH", "./output"))

    # Google Sheets 적재
    skip_sheets = args.no_sheets or not os.getenv("GOOGLE_SHEETS_ID")
    if skip_sheets:
        if not args.no_sheets:
            logger.info("GOOGLE_SHEETS_ID 미설정 → Sheets 적재 생략")
    else:
        _write_to_sheets(result, elapsed, args.source)

    if result.error_count > 0:
        logger.warning(
            "{}개 항목 수집 실패 (전체 {}개 중)",
            result.error_count,
            result.total_rows,
        )

    # GitHub Actions에서 오류율이 20% 이상이면 exit code 1
    error_rate = result.error_count / max(result.total_rows, 1)
    if error_rate >= 0.20:
        logger.error("오류율 {:.1%}로 임계값 초과, 실패 종료", error_rate)
        sys.exit(1)


if __name__ == "__main__":
    main()
