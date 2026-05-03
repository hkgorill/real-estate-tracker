# 수도권 아파트 잔여 매물 자동 수집 시스템

수도권(서울·인천·경기) 아파트 매매/전세/월세 잔여 매물 건수를 매일 KST 04:00에 자동 수집하여
Google Sheets에 적재하는 시스템입니다.

---

## 프로젝트 구조

```
estate_count_search/
├── .github/
│   └── workflows/
│       └── collect.yml         # GitHub Actions cron 워크플로우 (KST 04:00)
├── data/
│   └── regions.json            # 수도권 66개 지역 코드 + 좌표
├── docs/
│   └── setup_workload_identity.md  # Google Cloud WIF 설정 가이드
├── scrapers/
│   ├── __init__.py
│   ├── zigbang.py              # 직방 비공식 API (Primary)
│   └── naver.py                # 네이버부동산 API (Fallback)
├── tests/
│   ├── test_naver.py
│   ├── test_transform.py
│   ├── test_writer.py
│   └── test_zigbang.py
├── auth.py                     # Google 인증 (ADC / WIF / SA Key)
├── collect.py                  # 메인 수집 CLI
├── setup_sheets.py             # Google Sheets 시트 초기화 (최초 1회)
├── transform.py                # 수집 결과 정규화·집계
├── writer.py                   # Google Sheets 적재 (upsert)
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── ARD.md                      # 작업계획서
```

---

## 수집 대상

| 광역 | 지역 수 | 거래유형 |
|------|---------|---------|
| 서울특별시 | 25개 자치구 | 매매 / 전세 / 월세 |
| 인천광역시 | 10개 군·구 | 매매 / 전세 / 월세 |
| 경기도 | 31개 시·군 | 매매 / 전세 / 월세 |

총 66개 지역 × 3개 거래유형 = **198개 항목** / 1회 수집

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| 데이터 수집 | Python 3.12 + httpx + tenacity |
| 데이터 소스 | 직방 비공식 API (Primary) → 네이버부동산 (Fallback) |
| 저장소 | Google Sheets (google-api-python-client) |
| 인증 | Workload Identity Federation (키 없음) |
| 스케줄러 | GitHub Actions (`cron: '0 19 * * *'`) |

---

## Google Sheets 스키마

### `raw_data` 시트 (수집 원본)
| 컬럼 | 설명 |
|------|------|
| collected_at | 수집 시각 (KST) |
| date | 수집 날짜 |
| region_level1 | 광역시도 |
| region_level2 | 시/군/구 |
| trade_type | 매매 \| 전세 \| 월세 |
| listing_count | 잔여 매물 건수 |
| source | zigbang \| naver |
| status | ok \| error |
| error_msg | 오류 메시지 |

### `summary` 시트 (일별 지역 요약)
| 컬럼 | 설명 |
|------|------|
| date | 날짜 |
| region_level1 | 광역시도 |
| region_level2 | 시/군/구 |
| sale_count | 매매 매물 수 |
| jeonse_count | 전세 매물 수 |
| monthly_count | 월세 매물 수 |
| total_count | 합계 |

### `run_log` 시트 (실행 이력)
| 컬럼 | 설명 |
|------|------|
| run_at | 실행 시각 |
| status | success \| partial \| failed |
| total_rows | 수집 행 수 |
| error_count | 오류 건수 |
| source_used | 주 데이터 소스 |
| duration_sec | 소요 시간(초) |

---

## 설정 방법

### 1. Google Cloud 설정

서비스 계정 및 Workload Identity Federation 설정은
[docs/setup_workload_identity.md](docs/setup_workload_identity.md)를 참고하세요.

**프로젝트 정보**
- GCP Project: `real-estate-tracker-495203`
- Service Account: `sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com`

### 2. Google Sheets 공유

스프레드시트 → 공유 → 편집자로 추가:
```
sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com
```

### 3. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions

| Secret | 값 |
|--------|----|
| `WIF_PROVIDER` | `projects/762734791875/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `WIF_SERVICE_ACCOUNT` | `sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com` |
| `GOOGLE_SHEETS_ID` | 스프레드시트 ID |

### 4. Sheets 초기화 (최초 1회)

```bash
# 로컬 인증
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/cloud-platform

# 시트 + 헤더 생성
GOOGLE_SHEETS_ID=your_spreadsheet_id python setup_sheets.py
```

---

## 로컬 실행

### 환경 설정

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env
# .env에서 GOOGLE_SHEETS_ID 설정
```

### 수집 실행

```bash
# 전체 수집 (Sheets 적재 포함)
python collect.py

# 특정 지역만 테스트
python collect.py --region 강남구 --source naver

# API 호출 없이 대상 지역 목록 확인
python collect.py --dry-run

# Sheets 적재 없이 CSV로만 저장
python collect.py --csv --no-sheets

# 데이터 소스 지정 (auto / zigbang / naver)
python collect.py --source naver
```

### 테스트

```bash
pytest tests/ -v
```

---

## GitHub Actions

### 자동 실행
- 매일 KST 04:00 (UTC 19:00) 자동 실행

### 수동 실행
[Actions → 수도권 아파트 매물 수집 → Run workflow](https://github.com/hkgorill/real-estate-tracker/actions)

| 입력 | 설명 | 기본값 |
|------|------|--------|
| region | 지역 필터 (예: `강남구`) | 전체 |
| source | 데이터 소스 | `auto` |

---

## 진행 현황

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 1 | 스크래퍼 개발 (직방 + 네이버, 테스트 38개) | ✅ 완료 |
| Phase 2 | Google Sheets 연동 (upsert, run_log) | ✅ 완료 |
| Phase 3 | GitHub Actions 자동화 (WIF 인증) | ✅ 완료 |
| Phase 4 | Claude 아티팩트 대시보드 시각화 | 🔜 예정 |
