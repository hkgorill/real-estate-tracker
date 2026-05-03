# 수도권 부동산 시장 지표 자동 수집 시스템

수도권(서울·인천·경기) 아파트 시장의 주요 지표를 공식 API에서 자동 수집하여
Google Sheets에 적재하는 시스템입니다.

---

## 수집 데이터

| 소스 | 데이터 | 주기 | API |
|------|--------|------|-----|
| 한국부동산원 R-ONE | 아파트 매매·전세 가격지수, 전세가율(파생) | 주간 | R-ONE OpenAPI |
| 한국은행 ECOS | 기준금리, 주택담보대출금리 | 월간 | ECOS OpenAPI |
| 국토교통부 MOLIT | 아파트 실거래가 (수도권 66개 시군구) | 월간 | 공공데이터포털 |
| 국토교통부 MOLIT | 미분양주택 현황 (수도권 시도별) | 월간 | 공공데이터포털 |

> **전세가율** — R-ONE에 주간 전세가율 통계가 없어 `전세지수 / 매매지수 × 100` 으로 내부 계산합니다.
> 실제 전세가율(절대값)과 다를 수 있으나, 방향성·변화폭 분석에 유효합니다.

---

## 프로젝트 구조

```
real-estate-tracker/
├── .github/
│   └── workflows/
│       └── collect.yml             # GitHub Actions cron (KST 04:00 매일)
├── data/
│   └── regions.json                # 수도권 66개 시군구 법정동코드
├── docs/
│   ├── setup_workload_identity.md  # Google Cloud WIF 설정 가이드
│   └── api_key_setup.md            # API 키 발급 가이드 (3종)
├── scrapers/
│   ├── __init__.py
│   ├── rbone.py                    # 한국부동산원 R-ONE (가격지수)
│   ├── ecos.py                     # 한국은행 ECOS (금리)
│   └── molit.py                    # 국토교통부 (실거래가, 미분양)
├── tests/
│   ├── test_rbone.py
│   ├── test_ecos.py
│   ├── test_molit.py
│   ├── test_transform.py
│   └── test_writer.py
├── auth.py                         # Google 인증 (ADC / WIF / SA Key)
├── check_apis.py                   # API 키 및 통계코드 검증 스크립트
├── collect.py                      # 메인 수집 CLI
├── setup_sheets.py                 # Google Sheets 시트 초기화 (최초 1회)
├── transform.py                    # 수집 결과 정규화·집계
├── writer.py                       # Google Sheets 적재 (upsert)
├── .env.example
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

---

## Google Sheets 스키마 (5개 시트)

### `price_index` — 주간 아파트 가격지수
| 컬럼 | 설명 |
|------|------|
| collected_at | 수집 시각 (KST) |
| period | 주차 (YYYYWW) |
| region | 지역명 (전국/수도권/서울특별시/경기도/인천광역시) |
| sale_index | 아파트 매매가격지수 |
| jeonse_index | 아파트 전세가격지수 |
| jeonse_idx_ratio | 전세/매매 지수 비율 (%) |
| source | rbone |

### `interest_rate` — 월간 금리
| 컬럼 | 설명 |
|------|------|
| collected_at | 수집 시각 (KST) |
| period | 월 (YYYYMM) |
| base_rate | 기준금리 (%) |
| mortgage_rate | 주택담보대출금리 (%) |
| source | ecos |

### `apt_trade` — 월간 아파트 실거래가
| 컬럼 | 설명 |
|------|------|
| collected_at | 수집 시각 (KST) |
| deal_ym | 거래년월 (YYYYMM) |
| deal_date | 거래일 (YYYY-MM-DD) |
| region_level1 | 광역시도 |
| region_level2 | 시/군/구 |
| dong | 법정동 |
| apt_name | 아파트명 |
| area_sqm | 전용면적 (㎡) |
| floor | 층 |
| price_manwon | 거래금액 (만원) |
| build_year | 건축년도 |
| source | molit |

### `unsold` — 월간 미분양주택 현황
| 컬럼 | 설명 |
|------|------|
| collected_at | 수집 시각 (KST) |
| deal_ym | 기준년월 (YYYYMM) |
| region_level1 | 광역시도 |
| unsold_total | 미분양 합계 (호) |
| unsold_before | 준공 전 미분양 |
| unsold_after | 준공 후 미분양 |
| source | molit_unsold |

### `run_log` — 실행 이력
| 컬럼 | 설명 |
|------|------|
| run_at | 실행 시각 |
| status | success / partial / failed |
| total_rows | 수집 행 수 |
| error_count | 오류 건수 |
| sources_used | 사용된 소스 목록 |
| duration_sec | 소요 시간(초) |

---

## 설정 방법

### 1. API 키 발급 (3종)

| 키 | 발급처 | GitHub Secret 이름 |
|----|--------|-------------------|
| 공공데이터포털 | [data.go.kr](https://www.data.go.kr) | `DATA_GO_KR_API_KEY` |
| 한국은행 ECOS | [ecos.bok.or.kr](https://ecos.bok.or.kr) | `ECOS_API_KEY` |
| 한국부동산원 R-ONE | [reb.or.kr/r-one](https://www.reb.or.kr/r-one) | `RBONE_API_KEY` |

자세한 발급 절차는 [docs/api_key_setup.md](docs/api_key_setup.md)를 참고하세요.

### 2. Google Cloud 설정

서비스 계정 및 Workload Identity Federation 설정은
[docs/setup_workload_identity.md](docs/setup_workload_identity.md)를 참고하세요.

**프로젝트 정보**
- GCP Project: `real-estate-tracker-495203`
- Service Account: `sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com`

스프레드시트 → 공유 → 편집자로 추가:
```
sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com
```

### 3. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions

| Secret | 설명 |
|--------|------|
| `WIF_PROVIDER` | Workload Identity Provider 리소스 이름 |
| `WIF_SERVICE_ACCOUNT` | GCP 서비스 계정 이메일 |
| `GOOGLE_SHEETS_ID` | 스프레드시트 ID |
| `DATA_GO_KR_API_KEY` | 공공데이터포털 API 키 |
| `ECOS_API_KEY` | 한국은행 ECOS API 키 |
| `RBONE_API_KEY` | 한국부동산원 R-ONE API 키 |

### 4. Sheets 초기화 (최초 1회)

GitHub Actions에서 자동으로 실행됩니다. 로컬에서 직접 실행하려면:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/spreadsheets

GOOGLE_SHEETS_ID=your_spreadsheet_id python setup_sheets.py
```

---

## 로컬 실행

```bash
# 환경 설정
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

pip install -r requirements-dev.txt
cp .env.example .env
# .env 파일에 API 키 및 GOOGLE_SHEETS_ID 입력

# API 키 검증
python check_apis.py

# 수집 계획 확인 (API 호출 없음)
python collect.py --dry-run

# 수집 실행 (Sheets 적재 없이 CSV만)
python collect.py --no-sheets --csv

# 소스별 단독 실행
python collect.py --source rbone
python collect.py --source ecos
python collect.py --source molit

# 특정 기간 지정
python collect.py --source molit --deal-ym 202503
python collect.py --source rbone --week 202518

# 전체 수집 + Sheets 적재
python collect.py
```

### 테스트

```bash
pytest tests/ -v
```

---

## GitHub Actions

### 자동 실행
매일 KST 04:00 (UTC 19:00) 자동 실행됩니다.

### 수동 실행
[Actions → 부동산 시장 지표 수집 → Run workflow](https://github.com/hkgorill/real-estate-tracker/actions)

| 입력 | 설명 | 기본값 |
|------|------|--------|
| `source` | 수집 소스 (`all` / `rbone` / `ecos` / `molit`) | `all` |
| `deal_ym` | MOLIT 거래년월 (YYYYMM) | 전월 자동 |
| `week` | R-ONE 주차 (YYYYWW) | 현재 주차 자동 |
| `region` | MOLIT 지역 필터 (예: `강남구`) | 전체 |

---

## 진행 현황

| Phase | 내용 | 상태 |
|-------|------|------|
| Phase 1 | 스크래퍼 개발 (R-ONE, ECOS, MOLIT, 테스트 37개) | ✅ 완료 |
| Phase 2 | Google Sheets 연동 (upsert, run_log) | ✅ 완료 |
| Phase 3 | GitHub Actions 자동화 (WIF 인증) | ✅ 완료 |
| Phase 4 | 대시보드 시각화 | 🔜 예정 |
