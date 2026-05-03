# API 키 발급 가이드

이 시스템은 3개의 공식 API 키가 필요합니다.

---

## 1. 공공데이터포털 (국토교통부 실거래가 + 미분양)

**환경변수:** `DATA_GO_KR_API_KEY`

### 발급 절차
1. https://www.data.go.kr 회원가입 및 로그인
2. 상단 메뉴 → **마이페이지** → **인증키 발급현황**
3. 일반 인증키(Encoding) 복사

### 활용 신청 (API별 승인 필요)
아래 두 API에 활용 신청:
- **아파트매매 실거래 상세 자료**  
  https://www.data.go.kr 검색 → "아파트매매 실거래 상세 자료" → 활용신청
- **미분양주택현황보고**  
  https://www.data.go.kr 검색 → "미분양주택현황보고" → 활용신청

> 일반 인증키는 모든 공공데이터포털 API에 공통으로 사용됩니다.
> 활용 신청 후 즉시 또는 수 분 내 승인됩니다.

---

## 2. 한국은행 ECOS (기준금리 + 주담대금리)

**환경변수:** `ECOS_API_KEY`

### 발급 절차
1. https://ecos.bok.or.kr 접속
2. 상단 메뉴 → **오픈API** → **인증키 신청**
3. 회원가입 후 인증키 발급 (즉시 발급)

### 사용 통계 코드
코드가 변경될 경우 ECOS 포털 → 통계검색 → API에서 확인:

| 지표 | 통계코드 | 항목코드 |
|------|---------|---------|
| 한국은행 기준금리 | `722Y001` | `0101000` |
| 주택담보대출 가중평균금리(잔액) | `121Y006` | `BECBLDG01` |

---

## 3. 한국부동산원 R-ONE (아파트 가격지수 + 전세가율)

**환경변수:** `RBONE_API_KEY`

### 발급 절차
1. https://www.reb.or.kr/r-one 접속
2. 상단 메뉴 → **통계서비스** → **오픈API** → **활용신청**
3. 회원가입 후 API 활용 신청 (승인까지 1~3 영업일 소요)

### 통계표 코드 확인 (필수)
R-ONE 통계표 코드는 포털에서 직접 확인해야 합니다:

1. R-ONE 로그인 후 **통계서비스 → 오픈API → 통계표코드 조회**
2. 아래 통계를 검색하여 코드 확인:
   - `아파트 매매가격지수` (주간) → `RBONE_SALE_IDX_CODE`
   - `아파트 전세가격지수` (주간) → `RBONE_JEONSE_IDX_CODE`
   - `아파트 전세가율` (주간) → `RBONE_JEONSE_RATIO_CODE`

3. 확인한 코드를 `.env` 또는 GitHub Secrets에 추가:
   ```
   RBONE_SALE_IDX_CODE=실제코드
   RBONE_JEONSE_IDX_CODE=실제코드
   RBONE_JEONSE_RATIO_CODE=실제코드
   ```

> **주의:** `scrapers/rbone.py`의 `DEFAULT_*_CODE` 기본값은 플레이스홀더입니다.  
> 실제 코드로 반드시 교체하세요. API 응답이 비어있으면 코드 확인이 필요합니다.

---

## GitHub Secrets 설정

GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 값 |
|-------------|---|
| `DATA_GO_KR_API_KEY` | 공공데이터포털 인증키 |
| `ECOS_API_KEY` | ECOS 인증키 |
| `RBONE_API_KEY` | R-ONE API 키 |
| `GOOGLE_SHEETS_ID` | 스프레드시트 ID |
| `WIF_PROVIDER` | Workload Identity Provider (기존 설정 유지) |
| `WIF_SERVICE_ACCOUNT` | 서비스 계정 (기존 설정 유지) |

---

## 로컬 테스트

키 발급 후 개별 소스 테스트:

```bash
# .env 파일에 키 설정 후

# ECOS 테스트 (즉시 확인 가능)
python collect.py --source ecos --deal-ym 202503 --no-sheets --csv

# MOLIT 실거래가 테스트 (강남구만)
python collect.py --source molit --region 강남구 --deal-ym 202503 --no-sheets --csv

# R-ONE 테스트
python collect.py --source rbone --week 202518 --no-sheets --csv

# 전체 dry-run
python collect.py --dry-run
```
