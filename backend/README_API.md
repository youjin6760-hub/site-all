# Question Review System API 안내서

현재 코드 기준으로 정리한 README입니다.  
이 프로젝트는 사이트에서 문제 데이터를 수집하고, ChatGPT로 내용/형식 검수를 실행한 뒤, 검수 결과를 DB와 화면에 반영하는 내부 검수 시스템입니다.

---

## 1. 전체 목적

이 시스템의 목적은 다음과 같습니다.

1. 엑셀로 문제 DB와 검수 대상 매핑 DB를 업로드합니다.
2. 프론트 화면에서 강좌명, 세트명, 과목명, 하위유형, 문제 범위를 선택합니다.
3. 선택된 검수 대상을 백엔드 `/review-jobs` API로 한 번 전송합니다.
4. 백엔드는 DataEdu 사이트에 로그인하여 실제 문제, 보기, 정답, 해설, 이미지 정보를 수집합니다.
5. 수집한 raw JSON을 ChatGPT로 검수합니다.
6. 검수 결과를 `reviewed_json`, `chatgpt.xlsx`, `formula.xlsx`, `result.json`으로 저장합니다.
7. 프론트가 `result.json`을 받아 문제 DB에 `검수상태`, `오류유형`, `reason`, `suggestion`을 저장합니다.

---

## 2. 현재 폴더 구조

권장 폴더명은 `question-review-system`입니다.

```text
question-review-system/
├─ backend/
│  ├─ app.py
│  ├─ db_api.py
│  ├─ collect_api.py
│  ├─ chatgpt_api.py
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ README_API.md
│  ├─ 내용검수프롬프트.txt
│  ├─ 형식검수프롬프트.txt
│  ├─ .env                  # GitHub 업로드 금지
│  ├─ review_app.db          # GitHub 업로드 금지
│  └─ jobs/                  # GitHub 업로드 금지
│     └─ 26_5_12_1/
│        ├─ target.json
│        ├─ status.json
│        ├─ result.json
│        ├─ raw/
│        ├─ images/
│        ├─ debug/
│        ├─ reviewed_json/
│        ├─ debug_api_response/
│        ├─ chatgpt.xlsx
│        └─ formula.xlsx
│
├─ frontend/
│  ├─ index.html
│  ├─ package.json
│  ├─ package-lock.json
│  ├─ vite.config.js
│  ├─ .env                  # GitHub 업로드 금지
│  └─ src/
│     ├─ App.jsx
│     └─ App.css
│
├─ docker-compose.yml
└─ .gitignore
```

---

## 3. 주요 파일 역할

### `backend/app.py`

백엔드 통합 진입점입니다.

역할:

- FastAPI 서버 생성
- CORS 설정
- `/review-jobs` 관련 API 제공
- `db_api.py`의 `/api/` 라우트를 같은 FastAPI 앱에 연결
- 작업 ID 생성
- `target.json`, `status.json`, `result.json` 관리
- 문제 수집 `collect_from_target()` 실행
- ChatGPT 검수 `review_job_dir()` 실행

현재 job_id는 아래 형식으로 자동 생성됩니다.

```text
26_5_12_1
26_5_12_2
26_5_13_1
```

형식은 다음과 같습니다.

```text
년도2자리_월_일_당일실행번호
```

---

### `backend/db_api.py`

사이트 화면용 DB API입니다.

역할:

- SQLite DB 기본 생성 및 관리
- 문제 DB 테이블 `questions` 관리
- 검수 대상 매핑 테이블 `review_target_maps` 관리
- 엑셀 업로드
- 문제 목록 조회
- 문제 검수 결과 업데이트
- 검수 대상 매핑 CRUD

기본 DB 파일은 다음 위치입니다.

```text
backend/review_app.db
```

`.env`에 `DATABASE_URL`을 넣으면 다른 DB로 바꿀 수 있습니다.

예:

```env
DATABASE_URL=sqlite:///./review_app.db
```

---

### `backend/collect_api.py`

DataEdu 사이트에서 문제를 수집하는 Playwright 코드입니다.

역할:

- DataEdu 사이트 로그인
- 강좌명/세트명/과목명/하위유형 기준으로 문제 접근
- 문제 본문, 보기, 정답, 해설 추출
- 문제 이미지, 선지 이미지, 해설 이미지 캡처
- 수집 결과를 `jobs/{job_id}/raw`에 JSON으로 저장
- 이미지 파일을 `jobs/{job_id}/images`에 저장
- 오류성 디버그 파일을 `jobs/{job_id}/debug`에 저장

현재 `collect_from_target()`은 아래 형태를 지원합니다.

1. 단일 target 객체
2. target 객체 리스트
3. `{ "targets": [...] }`
4. `{ "configs": [...] }`
5. `{ "questions": [...] }`가 포함된 target

프론트에서 여러 매핑을 선택해도 `/review-jobs` 요청은 한 번만 보내고, `targets` 배열로 묶어 보내는 방식입니다.

---

### `backend/chatgpt_api.py`

ChatGPT 검수 실행 파일입니다.

역할:

- `jobs/{job_id}/raw` 안의 JSON을 읽음
- 내용 검수 프롬프트 실행
- 형식 검수 프롬프트 실행
- content issues와 format issues 병합
- 정상 판단이 issue로 잘못 들어온 경우 후처리 제거
- 중복 이슈 제거
- 검수 결과 JSON을 `jobs/{job_id}/reviewed_json`에 저장
- 오류 엑셀을 `jobs/{job_id}/chatgpt.xlsx`로 저장
- 수식/긴 해설 수동 확인 엑셀을 `jobs/{job_id}/formula.xlsx`로 저장
- ChatGPT 응답 파싱 실패 시 `jobs/{job_id}/debug_api_response`에 원문 저장

현재 코드 기준 API 키 환경변수는 아래 이름을 사용합니다.

```env
CHATGPT_API_KEY=...
```

모델 기본값은 코드상 아래와 같습니다.

```env
CHATGPT_MODEL=gpt-5.4
CHATGPT_REASONING_EFFORT=medium
CHATGPT_MAX_OUTPUT_TOKENS=6000
```

---

### `frontend/src/App.jsx`

프론트 화면 전체 로직입니다.

역할:

- 문제 목록 조회
- 검수 대상 매핑 조회
- 필터링
- 검수 대상 문제 목록 표시
- 검수 실행 버튼 처리
- `/review-jobs` 작업 생성
- 작업 상태 polling
- 결과 수신 후 DB 반영
- 선택 정상처리/선택 보류 처리
- 검수 모달에서 문제 수정 및 검수 결과 저장

현재 여러 매핑을 한 번에 검수할 때는 `targets` 배열을 구성해 `/review-jobs`를 한 번만 호출하는 구조입니다.

---

## 4. 환경변수 설정

### `backend/.env`

```env
# DataEdu 로그인
DATAEDU_ID=사이트아이디
DATAEDU_PW=사이트비밀번호

# ChatGPT API
CHATGPT_API_KEY=sk-...
CHATGPT_MODEL=gpt-5.4
CHATGPT_REASONING_EFFORT=medium
CHATGPT_MAX_OUTPUT_TOKENS=6000

# Playwright
PLAYWRIGHT_HEADLESS=true

# 선택 사항
APP_ROOT=/app
JOBS_DIR=/app/jobs
DATABASE_URL=sqlite:///./review_app.db
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://192.168.219.167:5173
```

주의:

```text
현재 코드 기준으로 chatgpt_api_key 소문자 변수는 사용하지 않습니다.
현재 코드는 CHATGPT_API_KEY를 읽습니다.
```

---

### `frontend/.env`

같은 PC에서만 접속할 경우:

```env
VITE_QUESTION_API_BASE=http://localhost:8000
VITE_REVIEW_API_BASE=http://localhost:8000
```

같은 공유기 안의 다른 PC나 휴대폰에서 접속할 경우:

```env
VITE_QUESTION_API_BASE=http://192.168.219.167:8000
VITE_REVIEW_API_BASE=http://192.168.219.167:8000
```

---

## 5. 실행 방법

### 5-1. 백엔드 Docker 실행

프로젝트 루트에서 실행합니다.

```powershell
docker compose down
docker compose up -d --build
```

상태 확인:

```powershell
docker compose ps
```

로그 확인:

```powershell
docker compose logs -f
```

백엔드 접속 확인:

```text
http://localhost:8000/health
```

---

### 5-2. 프론트 실행

프론트는 보통 Docker가 아니라 로컬 Vite로 실행합니다.

```powershell
cd frontend
npm install
npm run dev
```

접속 주소:

```text
http://localhost:5173
http://127.0.0.1:5173
http://192.168.219.167:5173
```

`vite.config.js`는 아래처럼 `0.0.0.0`으로 열려 있어야 네트워크 IP 접속이 가능합니다.

```js
server: {
  host: "0.0.0.0",
  port: 5173,
  strictPort: true,
}
```

---

### 5-3. 백엔드 로컬 실행

Docker 없이 실행하려면:

```powershell
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## 6. 전체 검수 흐름

### 1단계: 엑셀 업로드

프론트에서 엑셀 파일을 업로드하면 백엔드의 아래 API가 실행됩니다.

```http
POST /api/questions/upload-excel
```

엑셀 안의 문제 시트는 `questions` 테이블로 들어갑니다.

주요 컬럼:

```text
id
course_name
exam_unique_no
cd_value
question_no
question
view_text
image_url
answer
choice1~choice4
choice1_image_url~choice4_image_url
explanation
keywords
review_status
error_type
reason
suggestion
reviewer
reviewed_at
reflect_status
```

검수 대상 매핑 시트는 `review_target_maps` 테이블로 들어갑니다.

주요 컬럼:

```text
display_name
course_name
set_name
subject_name
subtype_name
subject_mode
subject_start_index
subject_end_index
exam_unique_no
```

---

### 2단계: 프론트에서 검수 대상 선택

프론트 화면에서 아래 조건을 선택합니다.

```text
강좌명
세트명
과목명
하위유형
검수 범위
검수 상태 필터
```

강좌명만 선택하고 세트명 이하를 전체로 두면 여러 매핑이 잡힐 수 있습니다.  
현재 구조에서는 이 여러 매핑을 각각 따로 job으로 만들지 않고, 하나의 payload 안에 `targets` 배열로 묶습니다.

---

### 3단계: `/review-jobs` 작업 생성

프론트는 아래 API를 한 번만 호출합니다.

```http
POST /review-jobs
Content-Type: application/json
```

예시:

```json
{
  "course_name": "SQLD 61회 끝장 패키지 PT 2026",
  "review_mode": "batch",
  "targets": [
    {
      "course_name": "SQLD 61회 끝장 패키지 PT 2026",
      "set_name": "핵심개념 문제",
      "subject_name": "1과목",
      "subtype_name": "SQLD 핵심개념체크 1과목 1장",
      "exam_unique_no": "101",
      "subject_mode": "specific",
      "subject_start_index": 1,
      "subject_end_index": 1,
      "question_range": "1-20",
      "question_numbers": [1, 2, 3, 4],
      "questions": [
        {
          "site_question_id": 501,
          "exam_unique_no": "101",
          "question_no": 1
        },
        {
          "site_question_id": 502,
          "exam_unique_no": "101",
          "question_no": 2
        }
      ]
    },
    {
      "course_name": "SQLD 61회 끝장 패키지 PT 2026",
      "set_name": "핵심개념 문제",
      "subject_name": "2과목",
      "subtype_name": "SQLD 핵심개념체크 2과목 1장",
      "exam_unique_no": "102",
      "subject_mode": "specific",
      "subject_start_index": 1,
      "subject_end_index": 1,
      "question_range": "1-20",
      "question_numbers": [1, 2, 3],
      "questions": [
        {
          "site_question_id": 601,
          "exam_unique_no": "102",
          "question_no": 1
        }
      ]
    }
  ],
  "options": {
    "headless": true,
    "write_excel": true,
    "include_raw_data": true
  }
}
```

응답:

```json
{
  "job_id": "26_5_12_1",
  "status": "queued",
  "status_url": "/review-jobs/26_5_12_1",
  "result_url": "/review-jobs/26_5_12_1/result"
}
```

---

### 4단계: 작업 폴더 생성

백엔드는 `backend/jobs` 아래에 작업 폴더를 만듭니다.

```text
backend/jobs/26_5_12_1/
```

먼저 아래 파일이 생깁니다.

```text
target.json
status.json
```

---

### 5단계: 문제 수집

`app.py`의 `run_pipeline()`이 `collect_from_target()`을 호출합니다.

수집 결과는 아래에 저장됩니다.

```text
backend/jobs/26_5_12_1/raw/
backend/jobs/26_5_12_1/images/
backend/jobs/26_5_12_1/debug/
```

`raw`에는 문제별 JSON이 저장됩니다.

예:

```text
SQLD_61회_핵심개념_1과목_1.json
SQLD_61회_핵심개념_1과목_2.json
```

---

### 6단계: ChatGPT 검수

수집이 끝나면 `review_job_dir()`가 실행됩니다.

입력:

```text
backend/jobs/26_5_12_1/raw/*.json
```

출력:

```text
backend/jobs/26_5_12_1/reviewed_json/*.json
backend/jobs/26_5_12_1/chatgpt.xlsx
backend/jobs/26_5_12_1/formula.xlsx
```

ChatGPT 검수는 두 번 실행됩니다.

1. 내용 검수
2. 형식 검수

사용 프롬프트:

```text
내용검수프롬프트.txt
형식검수프롬프트.txt
```

---

### 7단계: 최종 결과 생성

검수가 끝나면 `result.json`이 생성됩니다.

```text
backend/jobs/26_5_12_1/result.json
```

`result.json`에는 프론트가 DB에 반영할 수 있도록 아래 정보가 들어갑니다.

```json
{
  "job_id": "26_5_12_1",
  "status": "completed",
  "summary": {
    "total_questions": 10,
    "issue_question_count": 3,
    "passed_question_count": 7,
    "high_count": 1,
    "medium_count": 2,
    "low_count": 7
  },
  "items": [
    {
      "site_question_id": 501,
      "exam_unique_no": "101",
      "question_id": "...",
      "question_no": 1,
      "course_name": "...",
      "set_name": "...",
      "subject_name": "...",
      "sub_title": "...",
      "review_status": "issue_found",
      "severity": "high",
      "issue_count": 1,
      "issues": [
        {
          "issue_area": "content",
          "issue_type": "정답 불일치",
          "error_code": 2,
          "reason": "오류 사유",
          "suggestion": "수정 제안",
          "confidence": 0.95
        }
      ]
    }
  ]
}
```

---

### 8단계: 프론트에서 DB 반영

프론트는 `result.json`을 받은 뒤 문제별로 아래 API를 호출합니다.

```http
PUT /api/questions/{question_id}
```

저장되는 값:

```json
{
  "review_status": "오류있음",
  "error_type": "정답 불일치",
  "reason": "오류 사유",
  "suggestion": "수정 제안",
  "reviewer": "AI검수",
  "reflect_status": "미반영"
}
```

정상 문제는 보통 아래처럼 저장됩니다.

```json
{
  "review_status": "정상",
  "error_type": "",
  "reason": "",
  "suggestion": "",
  "reviewer": "AI검수",
  "reflect_status": "미반영"
}
```

---

## 7. 주요 API 목록

## 7-1. 상태 확인

```http
GET /health
```

응답:

```json
{
  "ok": true,
  "time": "2026-05-12T00:00:00+00:00"
}
```

---

## 7-2. 검수 작업 생성

```http
POST /review-jobs
```

비동기 방식입니다.  
프론트는 job_id를 받은 뒤 상태를 주기적으로 조회합니다.

---

## 7-3. 검수 작업 즉시 실행

```http
POST /review-jobs/run
```

동기 테스트용입니다.  
요청이 끝날 때까지 수집과 검수를 모두 기다립니다.

운영에서는 `/review-jobs` 사용을 권장합니다.

---

## 7-4. 검수 작업 상태 조회

```http
GET /review-jobs/{job_id}
```

응답 예:

```json
{
  "job_id": "26_5_12_1",
  "status": "reviewing",
  "created_at": "...",
  "started_at": "...",
  "updated_at": "..."
}
```

가능한 상태값:

```text
queued
collecting
reviewing
completed
failed
canceled
cancel_requested
```

---

## 7-5. 검수 결과 조회

```http
GET /review-jobs/{job_id}/result
```

---

## 7-6. raw 파일 목록 조회

```http
GET /review-jobs/{job_id}/raw
```

응답:

```json
{
  "job_id": "26_5_12_1",
  "files": [
    "question_1.json",
    "question_2.json"
  ]
}
```

---

## 7-7. 검수 취소

```http
POST /review-jobs/{job_id}/cancel
```

주의:

취소는 즉시 프로세스를 강제 종료하는 방식이 아닙니다.  
수집/검수 루프 중간중간 `cancel.requested` 파일을 확인하고 중단하는 방식입니다.

---

## 7-8. 문제 목록 조회

```http
GET /api/questions
```

---

## 7-9. 엑셀 업로드

```http
POST /api/questions/upload-excel
```

multipart/form-data:

```text
file: 업로드할 xlsx 또는 csv
course_name: 기본 강좌명
```

---

## 7-10. 문제 수정

```http
PUT /api/questions/{question_id}
```

수정 가능한 주요 값:

```text
course_name
exam_unique_no
cd_value
question_no
question
view_text
image_url
answer
score
choice1~choice4
choice1_image_url~choice4_image_url
explanation
keywords
review_status
error_type
reason
suggestion
reviewer
reflect_status
```

---

## 7-11. 전체 문제 삭제

```http
DELETE /api/questions
```

주의:

이 API는 `questions` 테이블을 비웁니다.  
검수 결과만 초기화하는 API가 아니라 문제 데이터 자체를 삭제합니다.

---

## 7-12. 검수 대상 매핑 목록 조회

```http
GET /api/target-maps
```

---

## 7-13. 검수 대상 매핑 생성

```http
POST /api/target-maps
```

---

## 7-14. 검수 대상 매핑 수정

```http
PUT /api/target-maps/{map_id}
```

---

## 7-15. 검수 대상 매핑 삭제

```http
DELETE /api/target-maps/{map_id}
```

---

## 7-16. 특정 매핑의 문제 조회

```http
GET /api/target-maps/{map_id}/questions?question_range=1-20
```

---

## 7-17. 검수 대상 매핑 자동 매칭

```http
POST /api/target-maps/resolve
```

입력:

```json
{
  "course_name": "강좌명",
  "set_name": "세트명",
  "subject_name": "과목명",
  "subtype_name": "하위유형"
}
```

---

## 7-18. DB 전체 초기화

```http
POST /api/db/reset?confirm=YES
```

주의:

이 API는 `questions`, `review_target_maps`를 모두 삭제합니다.

---

## 8. `target.json`, `status.json`, `result.json` 역할

### `target.json`

이번 검수 작업에 어떤 대상을 검수하라고 요청했는지 저장합니다.

예:

```text
강좌명
세트명
과목명
하위유형
시험 고유 번호
문제 번호 목록
옵션
```

---

### `status.json`

작업 진행 상태를 저장합니다.

예:

```json
{
  "job_id": "26_5_12_1",
  "status": "reviewing",
  "created_at": "...",
  "started_at": "...",
  "updated_at": "..."
}
```

프론트는 이 파일을 API로 읽어 검수 진행 상태를 확인합니다.

---

### `result.json`

검수 완료 후 최종 결과입니다.

프론트는 이 파일을 읽고 DB에 검수 결과를 반영합니다.

---

## 9. 엑셀 출력 파일

### `chatgpt.xlsx`

오류가 있는 문제만 정리한 엑셀입니다.

컬럼:

```text
question_id
file_name
question_no
subject_name
sub_title
severity
issue_area
issue_type
error_code
reason
suggestion
```

---

### `formula.xlsx`

수식/긴 해설/해설 이미지 등 수동 확인이 필요한 문제를 정리한 엑셀입니다.

컬럼:

```text
question_id
file_name
question_no
subject_name
sub_title
has_formula_explanation
explanation_image_count
capture_mode
needs_manual_review
explanation_images
formula_reason
```

---

## 10. GitHub 업로드 금지 항목

아래 파일/폴더는 GitHub에 올리면 안 됩니다.

```text
backend/.env
frontend/.env
backend/review_app.db
backend/jobs/
backend/raw/
backend/images/
backend/debug/
backend/reviewed_json/
backend/debug_api_response/
__pycache__/
backend/__pycache__/
frontend/node_modules/
frontend/dist/
```

`.gitignore` 예:

```gitignore
# env
.env
backend/.env
frontend/.env

# database
*.db
backend/review_app.db

# runtime outputs
backend/jobs/
backend/raw/
backend/images/
backend/debug/
backend/reviewed_json/
backend/debug_api_response/

# python
__pycache__/
*.pyc

# node
node_modules/
frontend/node_modules/

# build
dist/
frontend/dist/
```

---

## 11. 자주 발생하는 문제

### 11-1. `CHATGPT_API_KEY` 오류

오류:

```text
환경변수 CHATGPT_API_KEY가 필요합니다.
```

해결:

`backend/.env`에 아래 값을 넣습니다.

```env
CHATGPT_API_KEY=sk-...
```

---

### 11-2. DataEdu 로그인 오류

오류:

```text
환경변수 DATAEDU_ID, DATAEDU_PW가 필요합니다.
```

해결:

`backend/.env`에 아래 값을 넣습니다.

```env
DATAEDU_ID=...
DATAEDU_PW=...
```

---

### 11-3. 192.168 주소 접속이 안 됨

확인할 것:

1. `vite.config.js`의 `host`가 `0.0.0.0`인지 확인
2. `frontend/.env`의 API 주소가 `localhost`가 아니라 `192.168.219.167`인지 확인
3. Windows 방화벽에서 5173, 8000 포트 허용

방화벽 허용 예:

```powershell
New-NetFirewallRule -DisplayName "Vite 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow
New-NetFirewallRule -DisplayName "FastAPI 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

---

### 11-4. jobs 폴더가 여러 개 생김

정상 구조에서는 `/review-jobs` 요청 1번당 `jobs/{job_id}` 폴더 1개가 생깁니다.

강좌명만 선택해서 여러 세트가 포함되어도, 프론트가 `targets` 배열로 묶어 한 번만 요청하면 jobs 폴더는 하나만 생깁니다.

여러 개가 생기면 확인할 것:

```text
App.jsx에서 /review-jobs를 for문 안에서 반복 호출하고 있지 않은지 확인
buildCombinedReviewPayload()로 targets 배열을 만들고 있는지 확인
```

---

### 11-5. reason과 suggestion이 합쳐져 보임

현재 구조에서는 `reason`과 `suggestion`을 분리 저장합니다.

기존 데이터가 합쳐져 있다면 과거 DB 데이터입니다.  
새로 검수한 데이터부터는 분리 저장됩니다.

---

### 11-6. `database is locked`

SQLite DB를 서버가 잡고 있을 수 있습니다.

해결:

```powershell
docker compose down
```

그 뒤 DB 수정 작업을 다시 실행합니다.

---

## 12. 운영 시 권장 순서

일반 작업 순서:

```text
1. docker compose up -d --build
2. cd frontend
3. npm run dev
4. 프론트 접속
5. 엑셀 업로드
6. 검수 대상 확인
7. 검수 실행
8. 완료 후 오류 문제 확인
9. 필요한 문제 수정
10. 선택 정상처리 또는 선택 보류 처리
```

---

## 13. 현재 구조 요약

```text
frontend/App.jsx
→ 사용자 화면
→ 검수 대상 선택
→ /review-jobs 요청

backend/app.py
→ job_id 생성
→ target.json/status.json 관리
→ collect_api 실행
→ chatgpt_api 실행
→ result.json 생성
→ db_api 라우트 통합

backend/collect_api.py
→ DataEdu 사이트 접속
→ 문제/이미지/해설 수집
→ jobs/{job_id}/raw, images, debug 저장

backend/chatgpt_api.py
→ raw JSON 검수
→ reviewed_json 저장
→ chatgpt.xlsx, formula.xlsx 저장

backend/db_api.py
→ review_app.db 관리
→ questions, review_target_maps 관리
→ 프론트에서 검수 결과 저장
```

---

## 14. 주의 사항

- `backend/review_app.db`는 실제 문제 DB입니다. 삭제하면 문제 목록과 검수 결과가 사라집니다.
- `backend/jobs`는 검수 실행 기록입니다. DB 반영 후 필요 없으면 삭제할 수 있지만, 과거 검수 추적이 필요하면 보관합니다.
- `.env`에는 API 키와 로그인 정보가 들어 있으므로 절대 GitHub에 올리지 않습니다.
- `chatgpt.xlsx`, `formula.xlsx`는 job 폴더 안에 생성되는 결과 파일입니다.
- `debug_api_response`는 ChatGPT 응답이 JSON으로 파싱되지 않았을 때만 생성됩니다.
