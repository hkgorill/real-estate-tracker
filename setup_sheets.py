"""
Google Sheets 초기 스키마 생성 스크립트.

최초 1회 실행으로 6개 시트와 헤더를 만든다.
이미 존재하는 시트는 건드리지 않는다.

사용:
  python setup_sheets.py
  python setup_sheets.py --sheets-id SPREADSHEET_ID
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from loguru import logger

from auth import get_sheets_service
from transform import (
    PriceIndexRow, InterestRateRow,
    AptTradeRow, UnsoldRow,
)
from writer import RunLogRow

load_dotenv()

SHEET_CONFIGS = [
    {
        "name": "price_index",
        "headers": PriceIndexRow.headers(),
        "freeze_rows": 1,
        "col_widths": {0: 160, 1: 80, 2: 120, 3: 110, 4: 120, 5: 130, 6: 80},
    },
    {
        "name": "interest_rate",
        "headers": InterestRateRow.headers(),
        "freeze_rows": 1,
        "col_widths": {0: 160, 1: 80, 2: 100, 3: 130, 4: 80},
    },
    {
        "name": "apt_trade",
        "headers": AptTradeRow.headers(),
        "freeze_rows": 1,
        "col_widths": {0: 160, 1: 80, 2: 100, 3: 120, 4: 120, 5: 100,
                       6: 160, 7: 90, 8: 60, 9: 110, 10: 90, 11: 80},
    },
    {
        "name": "unsold",
        "headers": UnsoldRow.headers(),
        "freeze_rows": 1,
        "col_widths": {0: 160, 1: 80, 2: 120, 3: 110, 4: 110, 5: 120, 6: 80},
    },
    {
        "name": "run_log",
        "headers": RunLogRow.headers(),
        "freeze_rows": 1,
        "col_widths": {0: 160, 1: 80, 2: 90, 3: 100, 4: 160, 5: 110},
    },
]

HEADER_BG = {"red": 0.85, "green": 0.91, "blue": 0.96}


def get_existing_sheets(service, spreadsheet_id: str) -> dict[str, int]:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}


def add_sheet(service, spreadsheet_id: str, sheet_name: str) -> int:
    body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    resp = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return resp["replies"][0]["addSheet"]["properties"]["sheetId"]


def write_headers(service, spreadsheet_id: str, sheet_name: str, headers: list[str]):
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()


def format_sheet(service, spreadsheet_id: str, sheet_id: int, config: dict):
    requests = [
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": HEADER_BG,
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": config["freeze_rows"]},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]
    for col_idx, width_px in config.get("col_widths", {}).items():
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": width_px},
                "fields": "pixelSize",
            }
        })
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def setup(spreadsheet_id: str):
    logger.info("Google Sheets 스키마 초기화: {}", spreadsheet_id)
    service = get_sheets_service()
    existing = get_existing_sheets(service, spreadsheet_id)
    logger.info("기존 시트: {}", list(existing.keys()))

    for config in SHEET_CONFIGS:
        name = config["name"]
        if name in existing:
            logger.info("이미 존재하는 시트, 건너뜀: {}", name)
            continue

        logger.info("시트 생성: {}", name)
        sheet_id = add_sheet(service, spreadsheet_id, name)
        write_headers(service, spreadsheet_id, name, config["headers"])
        format_sheet(service, spreadsheet_id, sheet_id, config)
        logger.info("  → {} 컬럼 완료", len(config["headers"]))

    logger.info("초기화 완료 — 5개 시트: {}", [c["name"] for c in SHEET_CONFIGS])


def parse_args():
    parser = argparse.ArgumentParser(description="Google Sheets 스키마 초기화")
    parser.add_argument(
        "--sheets-id",
        default=os.getenv("GOOGLE_SHEETS_ID"),
        help="스프레드시트 ID (기본: 환경변수 GOOGLE_SHEETS_ID)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.sheets_id:
        logger.error("GOOGLE_SHEETS_ID가 설정되지 않았습니다.")
        sys.exit(1)
    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=True)
    setup(args.sheets_id)
