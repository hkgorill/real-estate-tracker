"""
Google Sheets API 인증 모듈.

우선순위:
1. Application Default Credentials (ADC) — Workload Identity Federation / gcloud 로그인
2. GOOGLE_SERVICE_ACCOUNT_KEY  — JSON 문자열 (키 생성이 허용된 환경 전용)
3. GOOGLE_SERVICE_ACCOUNT_JSON — JSON 파일 경로 (키 생성이 허용된 환경 전용)

권장 설정:
- GitHub Actions  → Workload Identity Federation (키 불필요, ADC 자동 설정)
- 로컬 개발       → gcloud auth application-default login
"""

import json
import os
from pathlib import Path

import google.auth
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def get_credentials():
    # 1순위: ADC (Workload Identity Federation, gcloud login, Cloud Run 등)
    adc_error = None
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        return creds
    except google.auth.exceptions.DefaultCredentialsError as e:
        adc_error = e

    # 2순위: Service Account 키 JSON 문자열 (레거시 / 허용된 환경)
    key_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY")
    if key_json:
        info = json.loads(key_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    # 3순위: Service Account 키 파일 경로 (레거시 / 허용된 환경)
    key_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if key_path:
        path = Path(key_path)
        if not path.exists():
            raise FileNotFoundError(f"Service account JSON 파일 없음: {path}")
        return Credentials.from_service_account_file(str(path), scopes=SCOPES)

    raise EnvironmentError(
        "Google 인증 정보를 찾을 수 없습니다.\n"
        "  권장: gcloud auth application-default login  (로컬)\n"
        "  권장: Workload Identity Federation           (GitHub Actions)\n"
        f"  ADC 오류: {adc_error}"
    )


def get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)
