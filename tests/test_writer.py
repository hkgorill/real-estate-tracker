"""writer.py 단위 테스트 (Google Sheets API mock)."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from transform import CollectResult, PriceIndexRow, InterestRateRow, UnsoldRow
from writer import SheetsWriter, RunLogRow

KST = timezone(timedelta(hours=9))
SPREADSHEET_ID = "fake_spreadsheet_id"


def make_mock_service(existing_values=None):
    svc = MagicMock()
    # spreadsheets().get() → sheet metadata
    svc.spreadsheets().get().execute.return_value = {
        "sheets": [
            {"properties": {"title": "price_index",   "sheetId": 1}},
            {"properties": {"title": "jeonse_ratio",  "sheetId": 2}},
            {"properties": {"title": "interest_rate", "sheetId": 3}},
            {"properties": {"title": "apt_trade",     "sheetId": 4}},
            {"properties": {"title": "unsold",        "sheetId": 5}},
            {"properties": {"title": "run_log",       "sheetId": 6}},
        ]
    }
    # spreadsheets().values().get() → existing row data
    vals = existing_values or []
    svc.spreadsheets().values().get().execute.return_value = {"values": vals}
    # append / batchUpdate return empty
    svc.spreadsheets().values().append().execute.return_value = {}
    svc.spreadsheets().batchUpdate().execute.return_value = {"replies": []}
    return svc


class TestRunLogRow:
    def test_to_row(self):
        row = RunLogRow(
            run_at="2025-05-03 04:00:00",
            status="success",
            total_rows=100,
            error_count=0,
            sources_used="rbone,ecos,molit",
            duration_sec=42.5,
        )
        data = row.to_row()
        assert data[0] == "2025-05-03 04:00:00"
        assert data[1] == "success"
        assert data[2] == 100
        assert data[3] == 0
        assert data[4] == "rbone,ecos,molit"
        assert data[5] == 42.5

    def test_headers_length(self):
        assert len(RunLogRow.headers()) == 6


class TestSheetsWriterUpsert:
    def test_upsert_appends_when_no_existing(self):
        svc = make_mock_service(existing_values=[["collected_at", "period", "region", "sale_index", "jeonse_index", "source"]])
        writer = SheetsWriter(svc, SPREADSHEET_ID)
        rows = [PriceIndexRow("2025-05-03 04:00:00", "202518", "전국", 100.0, 99.0, "rbone")]
        writer.upsert_price_index(rows, "202518")
        svc.spreadsheets().values().append.assert_called()

    def test_upsert_deletes_existing_then_appends(self):
        existing = [
            ["collected_at", "period", "region", "sale_index", "jeonse_index", "source"],
            ["2025-05-02 04:00:00", "202518", "전국", "99.0", "98.0", "rbone"],
        ]
        svc = make_mock_service(existing_values=existing)
        writer = SheetsWriter(svc, SPREADSHEET_ID)
        rows = [PriceIndexRow("2025-05-03 04:00:00", "202518", "전국", 100.0, 99.0, "rbone")]
        writer.upsert_price_index(rows, "202518")
        # batchUpdate(삭제) 호출 확인
        svc.spreadsheets().batchUpdate.assert_called()

    def test_append_run_log(self):
        svc = make_mock_service()
        writer = SheetsWriter(svc, SPREADSHEET_ID)
        log = RunLogRow("2025-05-03 04:00:00", "success", 50, 0, "rbone,ecos", 30.0)
        writer.append_run_log(log)
        svc.spreadsheets().values().append.assert_called()


class TestSheetsWriterWrite:
    def test_write_calls_all_upserts(self):
        svc = make_mock_service()
        writer = SheetsWriter(svc, SPREADSHEET_ID)

        result = CollectResult(collected_at="2025-05-03 04:00:00")
        result.price_index_rows = [PriceIndexRow("ts", "202518", "전국", 100.0, 99.0, "rbone")]
        result.interest_rate_rows = [InterestRateRow("ts", "202503", 2.75, 4.10, "ecos")]
        result.unsold_rows = [UnsoldRow("ts", "202503", "서울특별시", 100, 60, 40, "molit_unsold")]

        log = RunLogRow("2025-05-03 04:00:00", "success", 3, 0, "rbone,ecos,molit", 15.0)
        writer.write(result, log)

        # append가 최소 3번 이상 호출 (price_index, interest_rate, unsold, run_log)
        assert svc.spreadsheets().values().append.call_count >= 3
