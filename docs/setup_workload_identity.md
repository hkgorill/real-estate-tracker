# Google Cloud Workload Identity Federation 설정 가이드

Service Account 키 없이 GitHub Actions에서 Google Sheets API를 사용합니다.

**프로젝트 정보**
| 항목 | 값 |
|------|-----|
| Project ID | `real-estate-tracker-495203` |
| Service Account | `sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com` |
| GitHub 저장소 | `hkgorill/real-estate-tracker` |

---

## 1. 터미널 설정 (gcloud CLI)

```bash
export PROJECT_ID=real-estate-tracker-495203
export SA_EMAIL=sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com
export GITHUB_REPO=hkgorill/real-estate-tracker
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# PROJECT_NUMBER 확인
echo $PROJECT_NUMBER
```

---

## 2. Sheets API 활성화

```bash
gcloud services enable sheets.googleapis.com --project=$PROJECT_ID
```

---

## 3. Workload Identity Pool 생성

```bash
gcloud iam workload-identity-pools create "github-pool" \
  --project=$PROJECT_ID \
  --location="global" \
  --display-name="GitHub Actions Pool"
```

---

## 4. GitHub OIDC Provider 생성

```bash
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub Actions Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
```

---

## 5. 서비스 계정에 GitHub 위임 권한 부여

```bash
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GITHUB_REPO}"
```

---

## 6. WIF_PROVIDER 값 확인 → GitHub Secret에 저장

```bash
gcloud iam workload-identity-pools providers describe "github-provider" \
  --project=$PROJECT_ID \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --format='value(name)'
```

출력 예시:
```
projects/123456789012/locations/global/workloadIdentityPools/github-pool/providers/github-provider
```

이 값을 GitHub Secret `WIF_PROVIDER`에 저장합니다.

---

## 7. Google Spreadsheet 공유

스프레드시트 열기 → 공유 버튼 → 아래 이메일 주소를 **편집자**로 추가:

```
sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com
```

---

## 8. GitHub Secrets 등록

저장소 → Settings → Secrets and variables → Actions → **New repository secret**

| Secret 이름 | 값 |
|-------------|-----|
| `WIF_PROVIDER` | 6단계 출력값 전체 |
| `WIF_SERVICE_ACCOUNT` | `sheet-bot@real-estate-tracker-495203.iam.gserviceaccount.com` |
| `GOOGLE_SHEETS_ID` | 스프레드시트 URL의 `/d/` 뒤 긴 문자열 |

---

## 9. 로컬 개발 인증 (선택)

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/cloud-platform

# 시트 초기화
python setup_sheets.py

# 특정 지역 테스트 수집
python collect.py --region 강남구 --source naver --csv
```

---

## 완료 확인

```bash
python -c "
from auth import get_sheets_service
svc = get_sheets_service()
print('인증 성공:', type(svc).__name__)
"
```
