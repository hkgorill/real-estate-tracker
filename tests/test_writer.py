"""writer.py 단위 테스트 (Google Sheets API mock)."""

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from unittest.mock import MagicMock, call, patch

import pytest

from transform import normalize, RawRow, SummaryRow, TransformResult
from writer import SheetsWriter, RunLogRow

KST = timezone(timedelta(hours=9))
FIXED_DT = datetime(2026, 5, 3, 4, 0, 0, tzinfo=KST)
SPREADSHEET_ID = "fake_spreadsheet_id"


@dataclass
class FakeResult:
    region_level1: str
    region_level2: str
    trade_type: str
    listing_count: int
    source: str = "naver"


def make_transform_result(date="2026-05-03") -> TransformResult:
    inputs = [
        FakeResult("서울특별시", "강남구", "매매", 100),
        FakeResult("서울특별시", "강남구", "전세", 50),
        FakeResult("서울특별시", "강남구", "월세", 30),
        FakeResult("경기도", "수원시", "매매", 200),
        FakeResult("경기도", "수원시", "전세", 80),
        FakeResult("경기도", "수원시", "월세", 40),
    ]
    return normalize(inputs, collected_at=FIXED_DT)


def make_mock_service(existing_raw_rows=None, existing_summary_rows=None):
    """Sheets API 서비스 mock을 생성한다."""
    service = MagicMock()
    spreadsheets = service.spreadsheets.return_value

    # get() — 시트 목록 (sheet_id 조회용)
    spreadsheets.get.return_value.execute.return_value = {
        "sheets": [
            {"properties": {"title": "raw_data", "sheetId": 1}},
            {"properties": {"title": "summary", "sheetId": 2}},
            {"properties": {"title": "run_log", "sheetId": 3}},
        ]
    }

    # values().get() — 기존 데이터 조회
    raw_header = [RawRow.headers()]
    summary_header = [SummaryRow.headers()]

    def values_get_side_effect(spreadsheetId, range):
        if "raw_data" in range:
            rows = raw_header + (existing_raw_rows or [])
        elif "summary" in range:
            rows = summary_header + (existing_summary_rows or [])
        else:
            rows = []
        mock = MagicMock()
        mock.execute.return_value = {"values": rows}
        return mock

    spreadsheets.values.return_value.get.side_effect = values_get_side_effect

    # values().append(), batchUpdate() — 쓰기 작업
    spreadsheets.values.return_value.append.return_value.execute.return_value = {}
    spreadsheets.batchUpdate.return_value.execute.return_value = {"replies": []}

    return service


class TestSheetsWriterUpsertRawData:
    def test_appends_rows_when_no_existing(self):
        service = make_mock_service()
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()

        writer.upsert_raw_data(result)

        append_mock = service.spreadsheets.return_value.values.return_value.append
        assert append_mock.called
        appended_values = append_mock.call_args[1]["body"]["values"]
        assert len(appended_values) == 6

    def test_deletes_existing_rows_before_append(self):
        # 기존에 동일 날짜 데이터 3행 존재
        existing = [
            ["2026-05-03 04:00:00", "2026-05-03", "서울특별시", "강남구", "매매", "99", "naver", "ok", ""],
            ["2026-05-03 04:00:00", "2026-05-03", "서울특별시", "강남구", "전세", "49", "naver", "ok", ""],
            ["2026-05-03 04:00:00", "2026-05-03", "서울특별시", "강남구", "월세", "29", "naver", "ok", ""],
        ]
        service = make_mock_service(existing_raw_rows=existing)
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()

        writer.upsert_raw_data(result)

        # batchUpdate(deleteDimension)이 호출됐는지 확인
        assert service.spreadsheets.return_value.batchUpdate.called

    def test_no_delete_when_different_date(self):
        # 다른 날짜의 기존 데이터
        existing = [
            ["2026-05-02 04:00:00", "2026-05-02", "서울특별시", "강남구", "매매", "99", "naver", "ok", ""],
        ]
        service = make_mock_service(existing_raw_rows=existing)
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()

        writer.upsert_raw_data(result)

        # batchUpdate(delete)가 호출되지 않아야 함
        assert not service.spreadsheets.return_value.batchUpdate.called


class TestSheetsWriterUpsertSummary:
    def test_appends_summary_rows(self):
        service = make_mock_service()
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()

        writer.upsert_summary(result)

        append_mock = service.spreadsheets.return_value.values.return_value.append
        assert append_mock.called
        appended_values = append_mock.call_args[1]["body"]["values"]
        assert len(appended_values) == 2  # 강남구, 수원시

    def test_deletes_existing_summary_rows(self):
        existing = [
            ["2026-05-03", "서울특별시", "강남구", "99", "49", "29", "177"],
        ]
        service = make_mock_service(existing_summary_rows=existing)
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()

        writer.upsert_summary(result)

        assert service.spreadsheets.return_value.batchUpdate.called


class TestSheetsWriterRunLog:
    def test_appends_run_log(self):
        service = make_mock_service()
        writer = SheetsWriter(service, SPREADSHEET_ID)
        log = RunLogRow(
            run_at="2026-05-03 04:01:23",
            status="success",
            total_rows=183,
            error_count=0,
            source_used="zigbang",
            duration_sec=47.3,
        )

        writer.append_run_log(log)

        append_mock = service.spreadsheets.return_value.values.return_value.append
        assert append_mock.called
        row = append_mock.call_args[1]["body"]["values"][0]
        assert row[0] == "2026-05-03 04:01:23"
        assert row[1] == "success"
        assert row[2] == 183
        assert row[5] == 47.3


class TestRunLogRow:
    def test_to_row_format(self):
        log = RunLogRow(
            run_at="2026-05-03 04:01:23",
            status="partial",
            total_rows=180,
            error_count=3,
            source_used="naver",
            duration_sec=55.678,
        )
        row = log.to_row()
        assert len(row) == 6
        assert row[1] == "partial"
        assert row[5] == 55.7  # rounded

    def test_duration_rounded(self):
        log = RunLogRow("t", "success", 10, 0, "zigbang", 12.3456789)
        assert log.to_row()[5] == 12.3


class TestSheetsWriterWriteAll:
    def test_write_calls_all_three(self):
        service = make_mock_service()
        writer = SheetsWriter(service, SPREADSHEET_ID)
        result = make_transform_result()
        log = RunLogRow("2026-05-03 04:01:23", "success", 6, 0, "naver", 10.0)

        with patch.object(writer, "upsert_raw_data") as mock_raw, \
             patch.object(writer, "upsert_summary") as mock_summary, \
             patch.object(writer, "append_run_log") as mock_log:
            writer.write(result, log)

        mock_raw.assert_called_once_with(result)
        mock_summary.assert_called_once_with(result)
        mock_log.assert_called_once_with(log)
