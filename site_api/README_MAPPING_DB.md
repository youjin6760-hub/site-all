# 검수 대상 매핑 DB 적용 안내

## 1. DB 구조

`site_api/main.py`는 두 테이블을 만듭니다.

### questions
엑셀 문제 데이터가 들어갑니다.

- id: 엑셀 idx
- exam_unique_no: 시험 고유 번호
- cd_value: CD값
- question_no: 문제 번호
- question, view_text, image_url
- choice1 ~ choice4
- choice1_image_url ~ choice4_image_url
- answer, score, explanation, keywords
- review_status, error_type, reason, reviewer, reviewed_at, reflect_status

선택지5는 저장하지 않습니다.

### review_target_maps
세트명/과목명/하위유형과 숫자 시험 고유 번호를 연결하는 매핑 DB입니다.

- display_name
- course_name
- set_name
- subject_name
- subtype_name
- subject_mode
- subject_start_index
- subject_end_index
- exam_unique_no
- cd_value
- memo

## 2. 매핑 엑셀 시트 컬럼

기존 엑셀 파일에 `검수대상매핑` 시트를 추가하고 아래 컬럼을 넣으면 됩니다.

| 표시명 | 강좌명 | 세트명 | 과목명 | 하위유형 | 과목모드 | 과목시작index | 과목종료index | 시험 고유 번호 | CD값 | 메모 |
|---|---|---|---|---|---|---:|---:|---|---|---|
| 족집게 200제 / SQLD 26년 재등장 1회 | SQLD 61회 끝장 패키지 PT 2026 | 61회 족집게 문제 200제 | SQLD 26년 재등장 1회 |  | specific | 1 | 1 | 101 | A001 |  |

## 3. 실행

```powershell
cd C:\Users\dataedu\Desktop\claude\site_api
python -m pip install -r requirements_site_api.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8001
```

## 4. 현재 DB는 가짜인가요?

기존 `review_temp.db`는 가짜 메모리 DB가 아니라 실제 SQLite 파일 DB입니다. 다만 로컬 개발용 파일 DB라서 운영 사이트 DB라고 보기는 어렵습니다.

운영 사이트 DB에 직접 넣으려면 `.env` 또는 실행 환경변수에 `DATABASE_URL`을 지정하세요.

예시:

```env
DATABASE_URL=sqlite:///./review_app.db
```

MySQL 예시:

```env
DATABASE_URL=mysql+pymysql://user:password@host:3306/dbname?charset=utf8mb4
```

실제 사이트 DB 계정/주소를 받으면 같은 API 코드가 그 DB에 저장하도록 바꿀 수 있습니다.
