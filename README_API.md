# Question Review API 적용 안내

## 핵심 변경점

기존 방식은 `run_config.json` 수정 → `collect.py` 실행 → `클로드.PY` 내부 `TARGET_PREFIXES` 수정 → 검수 실행이었습니다.

수정된 방식은 사이트에서 target JSON을 한 번만 넘기면 다음 순서로 자동 진행됩니다.

```text
사이트 target JSON 1회 전송
→ job_id 생성
→ job_id/raw 에 문제 수집 JSON 저장
→ job_id/reviewed_json 에 Claude 검수 결과 저장
→ 사이트 저장용 result.json 반환
```

## 실행

```bash
cp .env.example .env
# .env 값 입력

docker build -t question-review-api .
docker run --rm -p 8000:8000 --env-file .env -v ./jobs:/app/jobs question-review-api
```

로컬 실행:

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 8000
```

## 비동기 작업 생성

```http
POST /review-jobs
Content-Type: application/json
```

```json
{
  "job_id": "review_20260508_001",
  "course_id": 10,
  "set_id": 3,
  "subject_id": 21,
  "course_name": "SQLD 61회 끝장 패키지 PT 2026",
  "set_name": "핵심개념 문제",
  "subject_mode": "all",
  "subject_start_index": 2,
  "subject_end_index": 2,
  "subtype_name": "SQLD 핵심개념체크 2과목 2장",
  "question_range": "41-42",
  "questions": [
    {"site_question_id": 501, "question_no": 41},
    {"site_question_id": 502, "question_no": 42}
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
  "job_id": "review_20260508_001",
  "status": "queued",
  "status_url": "/review-jobs/review_20260508_001",
  "result_url": "/review-jobs/review_20260508_001/result"
}
```

## 작업 상태 조회

```http
GET /review-jobs/{job_id}
```

상태값:

```text
queued
collecting
reviewing
completed
failed
```

## 결과 조회

```http
GET /review-jobs/{job_id}/result
```

결과 예시:

```json
{
  "job_id": "review_20260508_001",
  "status": "completed",
  "summary": {
    "total_questions": 2,
    "issue_question_count": 1,
    "passed_question_count": 1,
    "high_count": 0,
    "medium_count": 1,
    "low_count": 1
  },
  "items": [
    {
      "site_question_id": 501,
      "question_id": "SQLD_..._41",
      "question_no": 41,
      "review_status": "issue_found",
      "severity": "medium",
      "issue_count": 1,
      "issues": [
        {
          "issue_area": "format",
          "issue_type": "해설 시작 형식 오류",
          "error_code": 7,
          "reason": "...",
          "suggestion": "...",
          "confidence": 0.9
        }
      ]
    }
  ]
}
```

## 사이트 DB 저장 권장 구조

### review_jobs

- job_id
- status
- target_json
- total_questions
- issue_question_count
- started_at
- completed_at
- error_message

### question_reviews

- job_id
- site_question_id
- question_id
- question_no
- review_status
- severity
- issue_count
- raw_review_json
- created_at

### question_review_issues

- review_id
- issue_area
- issue_type
- error_code
- reason
- suggestion
- confidence

## 사이트 화면 연결 방식

문제 상세 화면에서 `site_question_id` 기준으로 `question_reviews`를 조회하고, 연결된 `question_review_issues`를 표시하면 됩니다.

```text
문제 상세
→ 최근 검수 결과 조회
→ 오류 유형 / 사유 / 수정 제안 표시
```

## 참고

- `collect_api.py`는 기존 `collect.py`의 수집 로직을 유지하되, target을 함수 인자로 받을 수 있게 수정했습니다.
- `claude_api.py`는 기존 `클로드.PY`의 검수 로직을 유지하되, `TARGET_PREFIXES` 하드코딩 없이 job 폴더의 raw JSON만 검수하도록 수정했습니다.
- Docker 서버에서는 기본적으로 `PLAYWRIGHT_HEADLESS=true`로 실행됩니다.
