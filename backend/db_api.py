import os
import json
from pathlib import Path
from io import BytesIO
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

app = FastAPI(title="Question Review Site API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "review_app.db"

raw_database_url = os.getenv("DATABASE_URL", "").strip()

if raw_database_url:
    DATABASE_URL = raw_database_url
else:
    DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

if DATABASE_URL.startswith("sqlite:///"):
    sqlite_path_text = DATABASE_URL.replace("sqlite:///", "", 1)

    if sqlite_path_text and sqlite_path_text != ":memory:":
        sqlite_path = Path(sqlite_path_text)

        if not sqlite_path.is_absolute():
            sqlite_path = (BASE_DIR / sqlite_path).resolve()

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = f"sqlite:///{sqlite_path.as_posix()}"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


CREATE_QUESTIONS_SQL = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    course_name TEXT,
    exam_unique_no TEXT,
    cd_value TEXT,
    question_no TEXT,
    question TEXT,
    view_text TEXT,
    image_url TEXT,
    answer TEXT,
    score TEXT,
    choice1 TEXT,
    choice2 TEXT,
    choice3 TEXT,
    choice4 TEXT,
    choice1_image_url TEXT,
    choice2_image_url TEXT,
    choice3_image_url TEXT,
    choice4_image_url TEXT,
    explanation TEXT,
    keywords TEXT,
    review_status TEXT DEFAULT '미검수',
    error_type TEXT,
    reason TEXT,
    suggestion TEXT,
    reviewer TEXT DEFAULT 'admin',
    reviewed_at TEXT,
    reflect_status TEXT DEFAULT '미반영',
    raw_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""

CREATE_TARGET_MAPS_SQL = """
CREATE TABLE IF NOT EXISTS review_target_maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT,
    course_name TEXT,
    set_name TEXT,
    subject_name TEXT,
    subtype_name TEXT,
    subject_mode TEXT DEFAULT 'specific',
    subject_start_index INTEGER DEFAULT 1,
    subject_end_index INTEGER DEFAULT 1,
    exam_unique_no TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT
);
"""

def ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    existing_columns = {row["name"] for row in rows}

    if column_name not in existing_columns:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
        

def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text(CREATE_QUESTIONS_SQL))
        conn.execute(text(CREATE_TARGET_MAPS_SQL))

        ensure_column(conn, "questions", "course_name", "course_name TEXT")
        ensure_column(conn, "questions", "suggestion", "suggestion TEXT")

init_db()


def clean_value(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    text_value = str(value).strip()
    return text_value if text_value else default


def get_cell(row, aliases, default=""):
    for col in aliases:
        if col in row:
            value = clean_value(row[col], "")
            if value != "":
                return value
    return default


def to_int_or_none(value):
    value = clean_value(value, "")
    if value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]
    return df


def has_column(df: pd.DataFrame, aliases: list[str]) -> bool:
    cols = set(str(col).strip() for col in df.columns)
    return any(alias in cols for alias in aliases)


def is_target_map_sheet(sheet_name: str, df: pd.DataFrame) -> bool:
    name = str(sheet_name).strip().lower()
    if name in {"검수대상매핑", "검수 대상 매핑", "target_map", "target maps", "mapping", "map"}:
        return True

    return (
        has_column(df, ["세트명", "set_name", "set", "세트"])
        and has_column(df, ["시험 고유 번호", "시험고유번호", "exam_unique_no", "exam_no"])
    )


def is_question_sheet(df: pd.DataFrame) -> bool:
    return has_column(df, ["idx", "IDX", "id", "ID"]) and has_column(
        df, ["문제 번호", "문제번호", "question_no", "no", "번호"]
    )

def normalize_question_row(row, default_course_name: str = "") -> dict[str, Any]:
    excel_idx = get_cell(row, ["idx", "IDX", "id", "ID"], "")
    return {
        "id": to_int_or_none(excel_idx),
        "course_name": get_cell(row, ["강좌명", "course_name", "course"], default_course_name),
        "exam_unique_no": get_cell(row, ["시험 고유 번호", "시험고유번호", "exam_unique_no", "exam_no"], ""),
        "cd_value": get_cell(row, ["CD값", "cd_value", "cd", "code"], ""),        "question_no": get_cell(row, ["문제 번호", "문제번호", "question_no", "번호", "no", "q_no"], ""),
        "question": get_cell(row, ["문제", "question", "question_text", "content", "stem", "title"], ""),
        "view_text": get_cell(row, ["보기_텍스트", "보기텍스트", "보기", "view_text", "view"], ""),
        "image_url": get_cell(row, ["보기_이미지", "보기이미지", "image_url", "img_url", "image"], ""),
        "answer": get_cell(row, ["정답", "answer"], ""),
        "score": get_cell(row, ["점수", "score"], ""),
        "choice1": get_cell(row, ["선택지1", "choice1", "선지1", "보기1", "option1"], ""),
        "choice1_image_url": get_cell(row, ["선택지1_이미지", "choice1_image_url", "선지1 이미지", "선택지1 이미지 URL"], ""),
        "choice2": get_cell(row, ["선택지2", "choice2", "선지2", "보기2", "option2"], ""),
        "choice2_image_url": get_cell(row, ["선택지2_이미지", "choice2_image_url", "선지2 이미지", "선택지2 이미지 URL"], ""),
        "choice3": get_cell(row, ["선택지3", "choice3", "선지3", "보기3", "option3"], ""),
        "choice3_image_url": get_cell(row, ["선택지3_이미지", "choice3_image_url", "선지3 이미지", "선택지3 이미지 URL"], ""),
        "choice4": get_cell(row, ["선택지4", "choice4", "선지4", "보기4", "option4"], ""),
        "choice4_image_url": get_cell(row, ["선택지4_이미지", "choice4_image_url", "선지4 이미지", "선택지4 이미지 URL"], ""),
        "explanation": get_cell(row, ["해설", "explanation"], ""),
        "keywords": get_cell(row, ["키워드", "keywords", "keyword"], ""),
        "review_status": get_cell(row, ["검수상태", "review_status", "status"], "미검수"),
        "error_type": get_cell(row, ["오류유형", "error_type", "issue_type"], ""),
        "reason": get_cell(row, ["기타사유", "검수사유", "reason", "memo", "review_memo"], ""),
        "suggestion": get_cell(row, ["수정제안", "수정 제안", "suggestion", "review_suggestion"], ""),
        "reviewer": get_cell(row, ["검수자", "reviewer", "inspector"], "admin"),
        "reviewed_at": get_cell(row, ["검수일", "reviewed_at", "review_date"], ""),
        "reflect_status": get_cell(row, ["반영상태", "reflect_status", "apply_status"], "미반영"),
        "raw_json": json.dumps(row.to_dict(), ensure_ascii=False, default=str),
        "created_at": now_text(),
        "updated_at": now_text(),
    }


def normalize_target_map_row(row) -> dict[str, Any]:
    display_name = get_cell(row, ["표시명", "display_name", "name", "검수대상명"], "")
    course_name = get_cell(row, ["강좌명", "course_name", "course"], "")
    set_name = get_cell(row, ["세트명", "set_name", "set"], "")
    subject_name = get_cell(row, ["과목명", "과목", "subject_name", "subject"], "")
    subtype_name = get_cell(row, ["하위유형", "subtype_name", "sub_title", "하위유형명"], "")
    exam_unique_no = get_cell(row, ["시험 고유 번호", "시험고유번호", "exam_unique_no", "exam_no"], "")

    if not display_name:
        display_parts = [
            course_name,
            set_name,
            subject_name,
            subtype_name,
        ]
        display_name = " / ".join([part for part in display_parts if part]) or exam_unique_no

    return {
        "display_name": display_name,
        "course_name": course_name,
        "set_name": set_name,
        "subject_name": subject_name,
        "subtype_name": subtype_name,
        "subject_mode": get_cell(row, ["과목모드", "subject_mode"], "specific"),
        "subject_start_index": to_int_or_none(get_cell(row, ["과목시작index", "subject_start_index", "start_index"], "1")) or 1,
        "subject_end_index": to_int_or_none(get_cell(row, ["과목종료index", "subject_end_index", "end_index"], "1")) or 1,
        "exam_unique_no": exam_unique_no,
        "created_at": now_text(),
        "updated_at": now_text(),
    }

def resolve_target_map_by_names(
    conn,
    course_name: str,
    set_name: str,
    subject_name: str,
    sub_title: str = "",
):
    params = {
        "course_name": str(course_name or "").strip(),
        "set_name": str(set_name or "").strip(),
        "subject_name": str(subject_name or "").strip(),
        "subtype_name": str(sub_title or "").strip(),
    }

    # 1순위: sub_title이 있으면 4개 조건으로 정확히 매칭
    if params["subtype_name"]:
        row = conn.execute(
            text(
                """
                SELECT * FROM review_target_maps
                WHERE TRIM(COALESCE(course_name, '')) = :course_name
                  AND TRIM(COALESCE(set_name, '')) = :set_name
                  AND TRIM(COALESCE(subject_name, '')) = :subject_name
                  AND TRIM(COALESCE(subtype_name, '')) = :subtype_name
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()

        if row:
            return dict(row)

    # 2순위: sub_title이 없거나, 4개 조건 매칭 실패 시 3개 조건으로 매칭
    row = conn.execute(
        text(
            """
            SELECT * FROM review_target_maps
            WHERE TRIM(COALESCE(course_name, '')) = :course_name
              AND TRIM(COALESCE(set_name, '')) = :set_name
              AND TRIM(COALESCE(subject_name, '')) = :subject_name
              AND TRIM(COALESCE(subtype_name, '')) = ''
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        params,
    ).mappings().first()

    return dict(row) if row else None

def upsert_question(conn, data: dict[str, Any]) -> None:
    columns = [
        "id",
        "course_name",
        "exam_unique_no",
        "cd_value",
        "question_no",
        "question",
        "view_text",
        "image_url",
        "answer",
        "score",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice1_image_url",
        "choice2_image_url",
        "choice3_image_url",
        "choice4_image_url",
        "explanation",
        "keywords",
        "review_status",
        "error_type",
        "reason",
        "suggestion",
        "reviewer",
        "reviewed_at",
        "reflect_status",
        "raw_json",
        "created_at",
        "updated_at",
    ]
    if data.get("id") is not None:
        exists = conn.execute(text("SELECT id FROM questions WHERE id = :id"), {"id": data["id"]}).first()
    else:
        exists = None

    if exists:
        update_columns = [c for c in columns if c not in {"id", "created_at"}]
        set_clause = ", ".join([f"{c} = :{c}" for c in update_columns])
        conn.execute(text(f"UPDATE questions SET {set_clause} WHERE id = :id"), data)
    else:
        insert_columns = columns if data.get("id") is not None else [c for c in columns if c != "id"]
        col_clause = ", ".join(insert_columns)
        val_clause = ", ".join([f":{c}" for c in insert_columns])
        conn.execute(text(f"INSERT INTO questions ({col_clause}) VALUES ({val_clause})"), data)


def insert_target_map(conn, data: dict[str, Any]) -> None:
    if not data.get("exam_unique_no"):
        return

    columns = [
        "display_name", "course_name", "set_name", "subject_name", "subtype_name", "subject_mode",
        "subject_start_index", "subject_end_index", "exam_unique_no", "created_at", "updated_at",
    ]

    # 같은 세트/과목/시험번호 조합이 있으면 갱신합니다.
    existing = conn.execute(
        text(
            """
            SELECT id FROM review_target_maps
            WHERE TRIM(COALESCE(course_name, '')) = TRIM(COALESCE(:course_name, ''))
            AND TRIM(COALESCE(set_name, '')) = TRIM(COALESCE(:set_name, ''))
            AND TRIM(COALESCE(subject_name, '')) = TRIM(COALESCE(:subject_name, ''))
            AND TRIM(COALESCE(subtype_name, '')) = TRIM(COALESCE(:subtype_name, ''))
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        data,
    ).first()

    if existing:
        data = {**data, "id": existing[0]}
        update_columns = [c for c in columns if c != "created_at"]
        set_clause = ", ".join([f"{c} = :{c}" for c in update_columns])
        conn.execute(text(f"UPDATE review_target_maps SET {set_clause} WHERE id = :id"), data)
    else:
        col_clause = ", ".join(columns)
        val_clause = ", ".join([f":{c}" for c in columns])
        conn.execute(text(f"INSERT INTO review_target_maps ({col_clause}) VALUES ({val_clause})"), data)


@app.get("/api/health")
def health():
    return {"ok": True, "database_url": DATABASE_URL.split("@")[0] if "@" in DATABASE_URL else DATABASE_URL}


@app.get("/api/questions")
def get_questions():
    init_db()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM questions
                ORDER BY
                exam_unique_no ASC,
                CAST(question_no AS INTEGER) ASC,
                question_no ASC,
                id ASC
                """
            )
        ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/questions/upload-excel")
async def upload_excel(
    file: UploadFile = File(...),
    course_name: str = Form(""),
):
    init_db()
    filename = file.filename or "uploaded.xlsx"
    contents = await file.read()

    try:
        if filename.lower().endswith(".csv"):
            df = normalize_headers(pd.read_csv(BytesIO(contents)))
            sheets = {"csv": df}
        else:
            raw_sheets = pd.read_excel(BytesIO(contents), sheet_name=None)
            sheets = {name: normalize_headers(df) for name, df in raw_sheets.items()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"엑셀 파일을 읽을 수 없습니다: {e}")

    question_count = 0
    map_count = 0
    skipped_sheets = []

    with engine.begin() as conn:
        for sheet_name, df in sheets.items():
            if df.empty:
                continue

            if is_target_map_sheet(sheet_name, df):
                for _, row in df.iterrows():
                    data = normalize_target_map_row(row)
                    if not data.get("exam_unique_no"):
                        continue
                    insert_target_map(conn, data)
                    map_count += 1
                continue

            if is_question_sheet(df):
                for _, row in df.iterrows():
                    data = normalize_question_row(row, default_course_name=course_name.strip())
                    if not data.get("question_no"):
                        continue
                    upsert_question(conn, data)
                    question_count += 1
                continue

            skipped_sheets.append(str(sheet_name))

    return {
        "ok": True,
        "filename": filename,
        "course_name": course_name.strip(),
        "questions_upserted": question_count,
        "target_maps_upserted": map_count,
        "skipped_sheets": skipped_sheets,
    }


@app.put("/api/questions/{question_id}")
def update_question(question_id: int, payload: dict):
    init_db()
    allowed = {
        "course_name",
        "exam_unique_no",
        "cd_value",
        "question_no",
        "question",
        "view_text",
        "image_url",
        "answer",
        "score",
        "choice1",
        "choice2",
        "choice3",
        "choice4",
        "choice1_image_url",
        "choice2_image_url",
        "choice3_image_url",
        "choice4_image_url",
        "explanation",
        "keywords",
        "review_status",
        "error_type",
        "reason",
        "suggestion",
        "reviewer",
        "reflect_status",
    }
    update_data = {key: value for key, value in payload.items() if key in allowed}
    update_data["reviewed_at"] = now_text()
    update_data["updated_at"] = now_text()

    if not update_data:
        raise HTTPException(status_code=400, detail="수정할 데이터가 없습니다.")

    set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
    update_data["id"] = question_id

    with engine.begin() as conn:
        conn.execute(text(f"UPDATE questions SET {set_clause} WHERE id = :id"), update_data)

    return {"ok": True, "id": question_id}


@app.delete("/api/questions")
def clear_questions():
    init_db()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM questions"))
    return {"ok": True}


@app.get("/api/target-maps")
def get_target_maps():
    init_db()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM review_target_maps ORDER BY id DESC")).mappings().all()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/target-maps")
def create_target_map(payload: dict):
    init_db()
    data = {
        "display_name": payload.get("display_name") or payload.get("displayName") or "",
        "course_name": payload.get("course_name") or payload.get("courseName") or "",
        "set_name": payload.get("set_name") or payload.get("setName") or "",
        "subject_name": payload.get("subject_name") or payload.get("subjectName") or "",
        "subtype_name": payload.get("subtype_name") or payload.get("subtypeName") or "",
        "subject_mode": payload.get("subject_mode") or payload.get("subjectMode") or "specific",
        "subject_start_index": int(payload.get("subject_start_index") or payload.get("subjectStartIndex") or 1),
        "subject_end_index": int(payload.get("subject_end_index") or payload.get("subjectEndIndex") or 1),
        "exam_unique_no": str(payload.get("exam_unique_no") or payload.get("examUniqueNo") or "").strip(),
        "created_at": now_text(),
        "updated_at": now_text(),
    }

    if not data["exam_unique_no"]:
        raise HTTPException(status_code=400, detail="시험 고유 번호가 필요합니다.")

    if not data["display_name"]:
        data["display_name"] = f"{data['set_name'] or data['course_name']} / {data['subtype_name'] or data['subject_name'] or data['exam_unique_no']}"

    with engine.begin() as conn:
        insert_target_map(conn, data)

    return {"ok": True}


@app.put("/api/target-maps/{map_id}")
def update_target_map(map_id: int, payload: dict):
    init_db()
    allowed_map = {
        "display_name": ["display_name", "displayName"],
        "course_name": ["course_name", "courseName"],
        "set_name": ["set_name", "setName"],
        "subject_name": ["subject_name", "subjectName"],
        "subtype_name": ["subtype_name", "subtypeName"],
        "subject_mode": ["subject_mode", "subjectMode"],
        "subject_start_index": ["subject_start_index", "subjectStartIndex"],
        "subject_end_index": ["subject_end_index", "subjectEndIndex"],
        "exam_unique_no": ["exam_unique_no", "examUniqueNo"],
    }

    update_data = {}
    for db_key, aliases in allowed_map.items():
        for alias in aliases:
            if alias in payload:
                update_data[db_key] = payload[alias]
                break
    update_data["updated_at"] = now_text()

    if not update_data:
        raise HTTPException(status_code=400, detail="수정할 데이터가 없습니다.")

    set_clause = ", ".join([f"{key} = :{key}" for key in update_data.keys()])
    update_data["id"] = map_id

    with engine.begin() as conn:
        conn.execute(text(f"UPDATE review_target_maps SET {set_clause} WHERE id = :id"), update_data)

    return {"ok": True, "id": map_id}


@app.delete("/api/target-maps/{map_id}")
def delete_target_map(map_id: int):
    init_db()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM review_target_maps WHERE id = :id"), {"id": map_id})
    return {"ok": True, "id": map_id}


@app.get("/api/target-maps/{map_id}/questions")
def get_questions_for_target_map(
    map_id: int,
    question_range: str = Query("", description="예: 1-20, 비우면 전체"),
):
    init_db()
    with engine.begin() as conn:
        target = conn.execute(text("SELECT * FROM review_target_maps WHERE id = :id"), {"id": map_id}).mappings().first()
        if not target:
            raise HTTPException(status_code=404, detail="매핑 정보를 찾을 수 없습니다.")

        rows = conn.execute(
            text("SELECT * FROM questions WHERE exam_unique_no = :exam_unique_no ORDER BY CAST(question_no AS INTEGER), id ASC"),
            {"exam_unique_no": target["exam_unique_no"]},
        ).mappings().all()

    items = [dict(row) for row in rows]
    if question_range and question_range.strip() and question_range.strip() != "all":
        try:
            start, end = [int(x.strip()) for x in question_range.split("-", 1)]
            lo, hi = min(start, end), max(start, end)
            items = [item for item in items if str(item.get("question_no", "")).isdigit() and lo <= int(item["question_no"]) <= hi]
        except Exception:
            raise HTTPException(status_code=400, detail="question_range는 '1-20' 형식이어야 합니다.")

    return {"target": dict(target), "items": items}


@app.post("/api/db/reset")
def reset_database(confirm: str = Query("", description="YES 입력 시 전체 삭제")):
    if confirm != "YES":
        raise HTTPException(status_code=400, detail="전체 삭제하려면 confirm=YES가 필요합니다.")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM questions"))
        conn.execute(text("DELETE FROM review_target_maps"))
    return {"ok": True}


@app.post("/api/target-maps/resolve")
def resolve_target_map(payload: dict):
    course_name = payload.get("course_name") or payload.get("courseName") or ""
    set_name = payload.get("set_name") or payload.get("setName") or ""
    subject_name = payload.get("subject_name") or payload.get("subjectName") or ""
    sub_title = (
        payload.get("sub_title")
        or payload.get("subTitle")
        or payload.get("subtype_name")
        or payload.get("subtypeName")
        or ""
    )

    with engine.begin() as conn:
        matched = resolve_target_map_by_names(
            conn,
            course_name=course_name,
            set_name=set_name,
            subject_name=subject_name,
            sub_title=sub_title,
        )

    if not matched:
        raise HTTPException(
            status_code=404,
            detail="해당 강좌명/세트명/과목명/하위유형에 맞는 시험 고유 번호 매핑을 찾지 못했습니다.",
        )

    return {
        "ok": True,
        "matched": matched,
        "exam_unique_no": matched.get("exam_unique_no"),
        "cd_value": matched.get("cd_value"),
    }