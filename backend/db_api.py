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

# Supabase/Heroku 계열에서 postgres:// 로 주는 경우 SQLAlchemy용으로 변환
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

QUESTION_NO_ORDER_SQL = (
    "CASE WHEN question_no ~ '^[0-9]+$' THEN question_no::INTEGER ELSE 999999999 END ASC"
    if IS_POSTGRES
    else "CAST(question_no AS INTEGER) ASC"
)

if IS_SQLITE and DATABASE_URL.startswith("sqlite:///"):
    sqlite_path_text = DATABASE_URL.replace("sqlite:///", "", 1)

    if sqlite_path_text and sqlite_path_text != ":memory:":
        sqlite_path = Path(sqlite_path_text)

        if not sqlite_path.is_absolute():
            sqlite_path = (BASE_DIR / sqlite_path).resolve()

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        DATABASE_URL = f"sqlite:///{sqlite_path.as_posix()}"

if IS_SQLITE:
    connect_args = {"check_same_thread": False}
elif IS_POSTGRES:
    connect_args = {"sslmode": "require"}
else:
    connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


QUESTION_ID_SQL = "id INTEGER PRIMARY KEY" if IS_SQLITE else "id SERIAL PRIMARY KEY"
TARGET_MAP_ID_SQL = "id INTEGER PRIMARY KEY AUTOINCREMENT" if IS_SQLITE else "id SERIAL PRIMARY KEY"

CREATE_QUESTIONS_SQL = f"""
CREATE TABLE IF NOT EXISTS questions (
    {QUESTION_ID_SQL},
    course_name TEXT,
    upload_file TEXT,
    exam_unique_no TEXT,
    cd_value TEXT,
    subject_name TEXT,
    chapter TEXT,
    section TEXT,
    learning_goal TEXT,
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
    review_check_labels TEXT,
    review_scope_summary TEXT,
    review_check_history TEXT,
    raw_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""

CREATE_TARGET_MAPS_SQL = f"""
CREATE TABLE IF NOT EXISTS review_target_maps (
    {TARGET_MAP_ID_SQL},
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

CREATE_QUESTION_CD_META_MAPS_SQL = f"""
CREATE TABLE IF NOT EXISTS question_cd_meta_maps (
    {TARGET_MAP_ID_SQL},
    cd_value TEXT NOT NULL UNIQUE,
    subject_name TEXT,
    chapter TEXT,
    section TEXT,
    learning_goal TEXT,
    raw_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
"""

def ensure_column(conn, table_name: str, column_name: str, column_sql: str) -> None:
    # SQLite는 ADD COLUMN IF NOT EXISTS를 지원하지 않는 버전이 있어 PRAGMA로 확인합니다.
    if IS_SQLITE:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
        existing_columns = {row["name"] for row in rows}

        if column_name not in existing_columns:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))
        return

    # PostgreSQL/Supabase용입니다.
    if IS_POSTGRES:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_sql}"))
        return
        

def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text(CREATE_QUESTIONS_SQL))
        conn.execute(text(CREATE_TARGET_MAPS_SQL))
        conn.execute(text(CREATE_QUESTION_CD_META_MAPS_SQL))

        ensure_column(conn, "questions", "course_name", "course_name TEXT")
        ensure_column(conn, "questions", "upload_file", "upload_file TEXT")
        ensure_column(conn, "questions", "subject_name", "subject_name TEXT")
        ensure_column(conn, "questions", "chapter", "chapter TEXT")
        ensure_column(conn, "questions", "section", "section TEXT")
        ensure_column(conn, "questions", "learning_goal", "learning_goal TEXT")
        ensure_column(conn, "questions", "suggestion", "suggestion TEXT")
        ensure_column(conn, "questions", "review_check_labels", "review_check_labels TEXT")
        ensure_column(conn, "questions", "review_scope_summary", "review_scope_summary TEXT")
        ensure_column(conn, "questions", "review_check_history", "review_check_history TEXT")

        ensure_column(conn, "question_cd_meta_maps", "raw_json", "raw_json TEXT")

init_db()


def clean_value(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    text_value = str(value).strip()
    return text_value if text_value else default


def normalize_cd_value(value: Any) -> str:
    """
    엑셀에서 goal_cd/CD값이 2111.0처럼 읽혀도 DB에는 2111로 저장합니다.
    문제 엑셀의 CD값과 커리큘럼 엑셀의 goal_cd를 같은 문자열로 맞추기 위한 함수입니다.
    """
    text_value = clean_value(value, "")
    if not text_value:
        return ""

    try:
        number_value = float(text_value)
        if number_value.is_integer():
            return str(int(number_value))
    except ValueError:
        pass

    return text_value


def get_cd_cell(row, aliases, default=""):
    return normalize_cd_value(get_cell(row, aliases, default))


def cd_value_candidates(value: Any) -> list[str]:
    base = normalize_cd_value(value)
    if not base:
        return []

    candidates = [base]

    # 기존 DB에 2111.0 형태로 저장된 값도 같이 찾아서 업데이트합니다.
    if base.isdigit():
        candidates.append(f"{base}.0")

    return list(dict.fromkeys(candidates))


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


def is_cd_meta_sheet(sheet_name: str, df: pd.DataFrame) -> bool:
    name = str(sheet_name).strip().lower().replace(" ", "")
    if name in {"cd매핑", "cd값매핑", "cd_meta", "cdmetamap", "cdmap", "cd_mapping", "1과목", "2과목"}:
        return True

    # SQLD 커리큘럼 파일은 goal_cd가 문제 엑셀의 CD값과 매칭되는 키입니다.
    # 기존 CD 매핑 파일 형식도 같이 받을 수 있게 alias를 넓게 둡니다.
    return (
        has_column(df, ["goal_cd", "CD값", "cd_value", "cd", "code"])
        and (
            has_column(df, ["s_name", "과목", "과목명", "subject_name", "subject"])
            or has_column(df, ["c_name", "장", "대단원", "chapter"])
            or has_column(df, ["section_name", "section", "절", "소단원"])
            or has_column(df, ["goal", "학습목표", "학습 목표", "learning_goal", "learning goal", "objective"])
        )
    )


def is_question_sheet(df: pd.DataFrame) -> bool:
    return has_column(df, ["idx", "IDX", "id", "ID"]) and has_column(
        df, ["문제 번호", "문제번호", "question_no", "no", "번호"]
    )

def normalize_question_row(row, default_course_name: str = "", default_upload_file: str = "") -> dict[str, Any]:
    excel_idx = get_cell(row, ["idx", "IDX", "id", "ID"], "")
    return {
        "id": to_int_or_none(excel_idx),
        "course_name": get_cell(row, ["강좌명", "course_name", "course"], default_course_name),
        "upload_file": get_cell(row, ["업로드파일", "업로드 파일", "파일명", "upload_file", "file_name", "filename"], default_upload_file),
        "exam_unique_no": get_cell(row, ["시험 고유 번호", "시험고유번호", "exam_unique_no", "exam_no"], ""),
        "cd_value": get_cd_cell(row, ["CD값", "goal_cd", "cd_value", "cd", "code"], ""),
        # 과목/장/절/학습목표는 문제 엑셀의 임의 컬럼값을 쓰지 않고,
        # CD 매핑 엑셀의 goal_cd 기준으로만 채웁니다.
        "subject_name": "",
        "chapter": "",
        "section": "",
        "learning_goal": "",
        "question_no": get_cell(row, ["문제 번호", "문제번호", "question_no", "번호", "no", "q_no"], ""),
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
        "review_check_labels": get_cell(row, ["검수항목", "review_check_labels", "review_checks"], ""),
        "review_scope_summary": get_cell(row, ["검수범위", "review_scope_summary", "review_summary"], ""),
        "review_check_history": get_cell(row, ["검수이력", "review_check_history", "review_history"], ""),
        "raw_json": json.dumps(row.to_dict(), ensure_ascii=False, default=str),
        "created_at": now_text(),
        "updated_at": now_text(),
    }


def normalize_cd_meta_row(row) -> dict[str, Any]:
    return {
        # SQLD 커리큘럼 기준: goal_cd가 기존 문제 엑셀의 CD값입니다.
        "cd_value": get_cd_cell(row, ["goal_cd", "CD값", "cd_value", "cd", "code"], ""),

        # SQLD 커리큘럼 기준 표시값입니다.
        # subject 컬럼은 "1과목/2과목" 값이라 화면용 과목에는 사용하지 않고, s_name을 우선 사용합니다.
        "subject_name": get_cell(row, ["s_name", "과목", "과목명", "subject_name", "subject"], ""),

        # chapter는 "1장" 값이고, c_name이 실제 장 이름입니다.
        "chapter": get_cell(row, ["c_name", "장", "대단원", "chapter_name", "chapter"], ""),

        # s_num은 "1절" 값이고, section_name/section이 실제 절 이름입니다.
        "section": get_cell(row, ["section_name", "section", "절", "소단원", "section_title", "s_num"], ""),

        # goal이 실제 학습목표입니다.
        "learning_goal": get_cell(row, ["goal", "학습목표", "학습 목표", "learning_goal", "learning goal", "objective"], ""),
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
        "upload_file",
        "exam_unique_no",
        "cd_value",
        "subject_name",
        "chapter",
        "section",
        "learning_goal",
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
        "review_check_labels",
        "review_scope_summary",
        "review_check_history",
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


def upsert_cd_meta_map(conn, data: dict[str, Any]) -> None:
    if not data.get("cd_value"):
        return

    columns = [
        "cd_value", "subject_name", "chapter", "section", "learning_goal",
        "raw_json", "created_at", "updated_at",
    ]

    existing = conn.execute(
        text(
            """
            SELECT id FROM question_cd_meta_maps
            WHERE TRIM(COALESCE(cd_value, '')) = TRIM(COALESCE(:cd_value, ''))
            LIMIT 1
            """
        ),
        data,
    ).first()

    if existing:
        data = {**data, "id": existing[0]}
        update_columns = [c for c in columns if c not in {"cd_value", "created_at"}]
        set_clause = ", ".join([f"{c} = :{c}" for c in update_columns])
        conn.execute(text(f"UPDATE question_cd_meta_maps SET {set_clause} WHERE id = :id"), data)
    else:
        col_clause = ", ".join(columns)
        val_clause = ", ".join([f":{c}" for c in columns])
        conn.execute(text(f"INSERT INTO question_cd_meta_maps ({col_clause}) VALUES ({val_clause})"), data)


def get_cd_meta_by_cd_value(conn, cd_value: Any):
    candidates = cd_value_candidates(cd_value)
    if not candidates:
        return None

    params = {f"cd{i}": value for i, value in enumerate(candidates)}
    where_clause = " OR ".join([f"TRIM(COALESCE(cd_value, '')) = :cd{i}" for i in range(len(candidates))])

    return conn.execute(
        text(
            f"""
            SELECT subject_name, chapter, section, learning_goal
            FROM question_cd_meta_maps
            WHERE {where_clause}
            LIMIT 1
            """
        ),
        params,
    ).mappings().first()


def apply_cd_meta_to_question(conn, data: dict[str, Any]) -> dict[str, Any]:
    cd_value = normalize_cd_value(data.get("cd_value"))
    if not cd_value:
        return data

    meta = get_cd_meta_by_cd_value(conn, cd_value)
    if not meta:
        return {**data, "cd_value": cd_value}

    merged = dict(data)
    merged["cd_value"] = cd_value
    for key in ["subject_name", "chapter", "section", "learning_goal"]:
        value = str(meta.get(key) or "").strip()
        if value:
            merged[key] = value
    return merged


def update_questions_from_cd_meta(conn, cd_value: str) -> int:
    candidates = cd_value_candidates(cd_value)
    if not candidates:
        return 0

    meta = get_cd_meta_by_cd_value(conn, candidates[0])
    if not meta:
        return 0

    params = {
        "normalized_cd_value": candidates[0],
        "subject_name": str(meta.get("subject_name") or "").strip(),
        "chapter": str(meta.get("chapter") or "").strip(),
        "section": str(meta.get("section") or "").strip(),
        "learning_goal": str(meta.get("learning_goal") or "").strip(),
        "updated_at": now_text(),
    }
    params.update({f"cd{i}": value for i, value in enumerate(candidates)})
    where_clause = " OR ".join([f"TRIM(COALESCE(cd_value, '')) = :cd{i}" for i in range(len(candidates))])

    result = conn.execute(
        text(
            f"""
            UPDATE questions
            SET cd_value = :normalized_cd_value,
                subject_name = CASE WHEN :subject_name != '' THEN :subject_name ELSE subject_name END,
                chapter = CASE WHEN :chapter != '' THEN :chapter ELSE chapter END,
                section = CASE WHEN :section != '' THEN :section ELSE section END,
                learning_goal = CASE WHEN :learning_goal != '' THEN :learning_goal ELSE learning_goal END,
                updated_at = :updated_at
            WHERE {where_clause}
            """
        ),
        params,
    )
    return result.rowcount or 0


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
                f"""
                SELECT * FROM questions
                ORDER BY
                exam_unique_no ASC,
                {QUESTION_NO_ORDER_SQL},
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
                    data = normalize_question_row(row, default_course_name=course_name.strip(), default_upload_file=filename)
                    if not data.get("question_no"):
                        continue
                    data = apply_cd_meta_to_question(conn, data)
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


@app.get("/api/cd-meta")
def get_cd_meta_maps():
    init_db()
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM question_cd_meta_maps ORDER BY id DESC")).mappings().all()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/cd-meta/upload-excel")
async def upload_cd_meta_excel(file: UploadFile = File(...)):
    init_db()
    filename = file.filename or "cd_meta.xlsx"
    contents = await file.read()

    try:
        if filename.lower().endswith(".csv"):
            df = normalize_headers(pd.read_csv(BytesIO(contents)))
            sheets = {"csv": df}
        else:
            raw_sheets = pd.read_excel(BytesIO(contents), sheet_name=None)
            sheets = {name: normalize_headers(df) for name, df in raw_sheets.items()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CD 매핑 엑셀 파일을 읽을 수 없습니다: {e}")

    cd_meta_count = 0
    updated_question_count = 0
    skipped_sheets = []

    with engine.begin() as conn:
        for sheet_name, df in sheets.items():
            if df.empty:
                continue

            if not is_cd_meta_sheet(sheet_name, df):
                skipped_sheets.append(str(sheet_name))
                continue

            for _, row in df.iterrows():
                data = normalize_cd_meta_row(row)
                if not data.get("cd_value"):
                    continue
                upsert_cd_meta_map(conn, data)
                cd_meta_count += 1
                updated_question_count += update_questions_from_cd_meta(conn, data["cd_value"])

    return {
        "ok": True,
        "filename": filename,
        "cd_meta_upserted": cd_meta_count,
        "questions_updated": updated_question_count,
        "skipped_sheets": skipped_sheets,
    }


@app.put("/api/questions/{question_id}")
def update_question(question_id: int, payload: dict):
    init_db()
    allowed = {
        "course_name",
        "upload_file",
        "exam_unique_no",
        "cd_value",
        "subject_name",
        "chapter",
        "section",
        "learning_goal",
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
        "review_check_labels",
        "review_scope_summary",
        "review_check_history",
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
            text(
                f"""
                SELECT * FROM questions
                WHERE exam_unique_no = :exam_unique_no
                ORDER BY {QUESTION_NO_ORDER_SQL}, id ASC
                """
            ),
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
        conn.execute(text("DELETE FROM question_cd_meta_maps"))
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