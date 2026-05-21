import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from prompt_builder import merge_review_checks
from fastapi.responses import FileResponse

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from collect_api import collect_from_target
from chatgpt_api import review_job_dir
from db_api import (
    app as question_api_app,
    engine as question_db_engine,
    IS_POSTGRES,
    now_text as db_now_text,
)

APP_ROOT = Path(os.getenv("APP_ROOT", Path(__file__).resolve().parent)).resolve()
load_dotenv(APP_ROOT / ".env")

JOBS_DIR = Path(os.getenv("JOBS_DIR", APP_ROOT / "jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)

            
app = FastAPI(
    title="Question Review API",
    version="1.0.0",
    description="사이트에서 전달한 target JSON 기준으로 문제 수집과 ChatGPT 검수를 실행합니다.",
)

CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://192.168.219.167:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for route in question_api_app.router.routes:
    route_path = getattr(route, "path", "")

    if route_path.startswith("/api/"):
        app.router.routes.append(route)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    now = datetime.now()

    prefix = f"{now.strftime('%y')}_{now.month}_{now.day}_"

    max_count = 0

    if JOBS_DIR.exists():
        for item in JOBS_DIR.iterdir():
            if not item.is_dir():
                continue

            name = item.name

            if not name.startswith(prefix):
                continue

            suffix = name[len(prefix):]

            if suffix.isdigit():
                max_count = max(max_count, int(suffix))

    next_count = max_count + 1

    while True:
        job_id = f"{prefix}{next_count}"

        if not (JOBS_DIR / job_id).exists():
            return job_id

        next_count += 1

def job_dir(job_id: str) -> Path:
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="job_id 형식이 올바르지 않습니다.")
    return JOBS_DIR / job_id

class JobCancelled(RuntimeError):
    pass


def cancel_file(job_id: str) -> Path:
    return job_dir(job_id) / "cancel.requested"


def is_cancel_requested(job_id: str) -> bool:
    return cancel_file(job_id).exists()


def raise_if_cancelled(job_id: str) -> None:
    if is_cancel_requested(job_id):
        raise JobCancelled("사용자가 검수 작업을 취소했습니다.")
    
def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {path.name}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_reviewed_questions_from_job(job_path: Path) -> list[dict[str, Any]]:
    reviewed_dir = job_path / "reviewed_json"

    if not reviewed_dir.exists():
        return []

    results: list[dict[str, Any]] = []

    for path in sorted(reviewed_dir.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                results.append(json.load(f))
        except Exception as e:
            print(f"[부분 결과 로드 실패] {path.name}: {e}")

    return results

def load_review_errors_from_job(job_path: Path) -> list[dict[str, Any]]:
    error_path = job_path / "review_errors.json"

    if not error_path.exists():
        return []

    try:
        with open(error_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception as e:
        print(f"[검수 오류 목록 로드 실패] {e}")
        return []


def attach_review_errors_to_result(job_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    review_errors = load_review_errors_from_job(job_path)
    skipped_count = len(review_errors)

    result["review_errors"] = review_errors

    result.setdefault("summary", {})
    reviewed_count = int(result["summary"].get("total_questions") or 0)

    result["summary"]["reviewed_question_count"] = reviewed_count
    result["summary"]["skipped_question_count"] = skipped_count
    result["summary"]["requested_question_count"] = reviewed_count + skipped_count

    if skipped_count:
        result["message"] = (
            f"일부 문제 {skipped_count}개는 API 오류로 건너뛰고, "
            f"나머지 문제 검수를 완료했습니다."
        )

    return result


def write_partial_result_if_exists(
    job_id: str,
    job_path: Path,
    target: dict[str, Any],
    status: str,
    error_message: str = "",
) -> dict[str, Any] | None:
    reviewed_questions = load_reviewed_questions_from_job(job_path)

    if not reviewed_questions:
        return None

    result = build_site_result(job_id, target, reviewed_questions)
    result = attach_review_errors_to_result(job_path, result)
    result["status"] = status
    result["partial"] = True
    result["error_message"] = error_message

    write_json(job_path / "result.json", result)

    update_status(
        job_path,
        status,
        error_message=error_message,
        total_questions=result["summary"]["total_questions"],
        issue_question_count=result["summary"]["issue_question_count"],
        mapping_error_count=result["summary"].get("mapping_error_count", 0),
        result_url=f"/review-jobs/{job_id}/result",
    )

    return result

def update_status(job_path: Path, status: str, **extra: Any) -> None:
    status_path = job_path / "status.json"
    current: dict[str, Any] = {}
    if status_path.exists():
        try:
            current = read_json(status_path)
        except Exception:
            current = {}

    current.update(extra)
    current["status"] = status
    current["updated_at"] = now_iso()

    if status in {"completed", "failed", "canceled", "partial_failed", "partial_canceled"}:
        current.setdefault("completed_at", now_iso())

    write_json(status_path, current)

def normalize_question_no(value: Any) -> str:
    if value is None:
        return ""

    text_value = str(value).strip()
    if not text_value:
        return ""

    try:
        return str(int(float(text_value)))
    except Exception:
        return text_value
   
def make_site_meta_key(
    set_name: Any,
    subject_name: Any,
    subtype_name: Any,
    question_no: Any,
) -> str:
    return "||".join([
        str(set_name or "").strip(),
        str(subject_name or "").strip(),
        str(subtype_name or "").strip(),
        normalize_question_no(question_no),
    ])

def get_question_site_meta_map(target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}

    def add_source(source: dict[str, Any]) -> None:
        questions = source.get("questions") or []

        if not isinstance(questions, list):
            return

        default_exam_unique_no = source.get("exam_unique_no")
        set_name = source.get("set_name", "")
        subject_name = source.get("subject_name", "")
        subtype_name = source.get("subtype_name") or source.get("sub_title") or ""

        for q in questions:
            if not isinstance(q, dict):
                continue

            qno = q.get("question_no") or q.get("no")
            qno_key = normalize_question_no(qno)

            if not qno_key:
                continue

            site_id = (
                q.get("site_question_id")
                or q.get("site_problem_id")
                or q.get("idx")
                or q.get("id")
            )

            exam_unique_no = q.get("exam_unique_no") or default_exam_unique_no

            meta = {
                "site_question_id": site_id,
                "exam_unique_no": exam_unique_no,
                "source_question": q,
            }

            composite_key = make_site_meta_key(
                set_name,
                subject_name,
                subtype_name,
                qno,
            )

            mapping[composite_key] = meta

            # 기존 단일 target 방식 호환용 fallback
            mapping.setdefault(qno_key, meta)

    add_source(target)

    for child in target.get("targets") or target.get("configs") or []:
        if isinstance(child, dict):
            add_source(child)

    return mapping

def normalize_issues(reviewed: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for issue in reviewed.get("content_issues", []) or []:
        issues.append({
            "issue_area": "content",
            "issue_type": issue.get("type", ""),
            "reason": issue.get("reason", ""),
            "suggestion": issue.get("suggestion", ""),
        })

    for issue in reviewed.get("format_issues", []) or []:
        issues.append({
            "issue_area": "format",
            "issue_type": issue.get("type", ""),
            "reason": issue.get("reason", ""),
            "suggestion": issue.get("suggestion", ""),
        })

    return issues


def first_question_image_url(data: dict[str, Any]) -> str:
    for item in data.get("image_elements", []) or []:
        if item.get("location") == "question":
            return str(item.get("saved_path") or "")
    return ""


def choice_image_url(data: dict[str, Any], choice_no: int) -> str:
    target_caption = f"choice_{choice_no}"

    for item in data.get("image_elements", []) or []:
        if item.get("location") != "choice":
            continue

        caption = str(item.get("caption_or_near_text") or "")
        if caption == target_caption:
            return str(item.get("saved_path") or "")

    return ""


def get_choice_text(choices: list[Any], index: int) -> str:
    if index < 0 or index >= len(choices):
        return ""
    return str(choices[index] or "")


def question_no_from_raw_file(path: Path) -> int:
    try:
        value = path.stem.split("_")[-1]
        return int(float(value))
    except Exception:
        return 999999999


def insert_collected_raw_to_questions_db(
    job_id: str,
    job_path: Path,
    target: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    collect_api.py가 만든 job/raw/*.json을 questions 테이블에 임시 문제로 저장합니다.

    options.save_collected_to_db=true일 때만 실행합니다.
    idx/site_question_id/exam_unique_no를 모르는 상태에서도 DB가 새 id를 만들고,
    그 id를 site_question_id처럼 target["questions"]에 붙여 기존 결과 반영 흐름을 사용합니다.
    """
    raw_dir = job_path / "raw"

    if not raw_dir.exists():
        return []

    raw_files = sorted(raw_dir.glob("*.json"), key=question_no_from_raw_file)

    if not raw_files:
        return []

    temp_exam_unique_no = str(target.get("exam_unique_no") or f"TEMP_{job_id}")
    inserted_questions: list[dict[str, Any]] = []

    columns = [
        "course_name",
        "upload_file",
        "exam_unique_no",
        "cd_value",
        "set_name",
        "subtype_name",
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

    insert_sql = f"""
        INSERT INTO questions ({", ".join(columns)})
        VALUES ({", ".join([f":{col}" for col in columns])})
    """

    if IS_POSTGRES:
        insert_sql += " RETURNING id"

    with question_db_engine.begin() as conn:
        for raw_file in raw_files:
            with open(raw_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            data = raw.get("data", {}) or {}
            choices = data.get("choices", []) or []

            question_no = raw.get("question_no") or data.get("question_no") or ""
            subject_name = raw.get("subject_name") or target.get("subject_name") or ""
            sub_title = (
                raw.get("sub_title")
                or target.get("subtype_name")
                or target.get("sub_title")
                or ""
            )
            set_name = raw.get("set_name") or target.get("set_name") or ""
            now = db_now_text()

            keywords = data.get("keywords") or ""
            if isinstance(keywords, list):
                keywords = ", ".join(str(item) for item in keywords if str(item).strip())
            else:
                keywords = str(keywords or "")

            params = {
                "course_name": raw.get("course_name") or target.get("course_name") or "",
                "upload_file": f"collect:{job_id}",
                "exam_unique_no": temp_exam_unique_no,
                "cd_value": str(data.get("cd_value") or raw.get("cd_value") or target.get("cd_value") or ""),
                "set_name": set_name,
                "subject_name": subject_name,
                "subtype_name": sub_title,
                "chapter": "",
                "section": "",
                "learning_goal": "",
                "question_no": str(question_no),
                "question": str(data.get("body") or ""),
                "view_text": str(data.get("extra_text") or ""),
                "image_url": first_question_image_url(data),
                "answer": str(data.get("answer") or ""),
                "score": str(data.get("score") or ""),
                "choice1": get_choice_text(choices, 0),
                "choice2": get_choice_text(choices, 1),
                "choice3": get_choice_text(choices, 2),
                "choice4": get_choice_text(choices, 3),
                "choice1_image_url": choice_image_url(data, 1),
                "choice2_image_url": choice_image_url(data, 2),
                "choice3_image_url": choice_image_url(data, 3),
                "choice4_image_url": choice_image_url(data, 4),
                "explanation": str(data.get("explanation") or ""),
                "keywords": keywords,
                "review_status": "미검수",
                "error_type": "",
                "reason": "",
                "suggestion": "",
                "reviewer": "admin",
                "reviewed_at": "",
                "reflect_status": "미반영",
                "review_check_labels": "",
                "review_scope_summary": "",
                "review_check_history": "",
                "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
                "created_at": now,
                "updated_at": now,
            }

            result = conn.execute(text(insert_sql), params)

            if IS_POSTGRES:
                inserted_id = result.scalar_one()
            else:
                inserted_id = result.lastrowid

            inserted_questions.append({
                "site_question_id": inserted_id,
                "exam_unique_no": temp_exam_unique_no,
                "question_no": str(question_no),
                "set_name": set_name,
                "subject_name": subject_name,
                "subtype_name": sub_title,
            })

    return inserted_questions


def build_site_result(job_id: str, target: dict[str, Any], reviewed_questions: list[dict[str, Any]]) -> dict[str, Any]:
    site_meta_map = get_question_site_meta_map(target)
    include_raw_data = bool((target.get("options") or {}).get("include_raw_data", False))

    items: list[dict[str, Any]] = []

    total_questions = len(reviewed_questions)
    issue_question_count = 0
    mapping_error_count = 0

    for reviewed in reviewed_questions:
        summary = reviewed.get("summary", {}) or {}

        qno = reviewed.get("question_no")
        qno_key = normalize_question_no(qno)

        site_key = make_site_meta_key(
            reviewed.get("set_name", ""),
            reviewed.get("subject_name", ""),
            reviewed.get("sub_title", ""),
            qno,
        )

        site_meta = site_meta_map.get(site_key) or site_meta_map.get(qno_key, {})
        issues = normalize_issues(reviewed)

        # summary.has_issue가 false여도 실제 issues가 있으면 오류 문제로 봅니다.
        has_issue = bool(summary.get("has_issue")) or bool(issues)

        if has_issue:
            issue_question_count += 1

        # site_question_id가 없으면 프론트 DB에 반영할 수 없으므로 매핑 오류로 집계합니다.
        if not site_meta.get("site_question_id"):
            mapping_error_count += 1

        item = {
            "site_question_id": site_meta.get("site_question_id"),
            "exam_unique_no": site_meta.get("exam_unique_no") or target.get("exam_unique_no"),
            "question_id": reviewed.get("question_id", ""),
            "question_no": qno,
            "course_name": reviewed.get("course_name", ""),
            "set_name": reviewed.get("set_name", ""),
            "subject_name": reviewed.get("subject_name", ""),
            "sub_title": reviewed.get("sub_title", ""),
            "review_status": "issue_found" if has_issue else "passed",
            "issue_count": len(issues),
            "issues": issues,
        }

        if include_raw_data:
            data = reviewed.get("data", {}) or {}

            item["raw_data"] = {
                "body": data.get("body", ""),
                "extra_text": data.get("extra_text", ""),
                "choices": data.get("choices", []),
                "answer": data.get("answer", ""),
                "keywords": data.get("keywords", ""),
                "explanation": data.get("explanation", ""),
                "has_image": data.get("has_image", False),
                "has_question_image": data.get("has_question_image", False),
                "has_choice_image": data.get("has_choice_image", False),
                "image_elements": data.get("image_elements", []),
                "explanation_images": data.get("explanation_images", []),
                "explanation_capture_meta": data.get("explanation_capture_meta", {}),
                "question_image_capture_meta": data.get("question_image_capture_meta", {}),
                "pt_teacher_tip": data.get("pt_teacher_tip", {"has_tip": False}),
            }

        items.append(item)

    return {
        "job_id": job_id,
        "status": "completed",
        "target": target,
        "summary": {
            "total_questions": total_questions,
            "issue_question_count": issue_question_count,
            "passed_question_count": total_questions - issue_question_count,
            "mapping_error_count": mapping_error_count,
        },
        "items": items,
    }


def build_collect_options_from_review_checks(review_checks: dict[str, Any] | None) -> dict[str, bool]:
    """
    프론트의 개별 검수 항목 기준으로 collect_api.py에서 필요한 자료만 수집합니다.
    """
    checks = merge_review_checks(review_checks)

    content = checks.get("content", {}) or {}
    format_checks = checks.get("format", {}) or {}
    pt_tip = checks.get("pt_teacher_tip", {}) or {}

    # =========================
    # 화면상 검수 항목 기준
    # =========================

    # 1. 문제 성립/자료 검수
    problem_material_review = bool(
        content.get("problem_validity")
        or content.get("image_validation")
    )

    # 2. 정답 검증
    answer_review = bool(content.get("answer_validation"))

    # 3. 해설 내용 검수
    explanation_review = bool(
        content.get("explanation_logic")
        or content.get("choice_explanation_match")
    )

    # 4. 표현/렌더링 오류
    expression_review = bool(
        content.get("expression_error")
        or format_checks.get("markdown_error")
    )

    # 5. 키워드 검수
    keyword_review = bool(content.get("keyword_validation"))

    # 6. 정답 문장 형식
    answer_sentence_format_review = bool(
        format_checks.get("start_sentence")
        or format_checks.get("negative_question")
        or format_checks.get("conclusion_sentence")
        or format_checks.get("quote_rules")
        or format_checks.get("duplicate_answer_sentence")
    )

    # 7. 선지/보기 해설 구조
    choice_view_explanation_structure_review = bool(
        format_checks.get("choice_explanation_exists")
        or format_checks.get("choice_explanation_format")
    )

    # 8. 존댓말 확인
    honorific_review = bool(format_checks.get("honorific_style"))

    # 9. 긴 해설 수동 검토
    # 수식/LaTeX 조건이 있을 때 해설 스크린샷 캡처를 시도하고,
    # 0.8 배율까지 실패하면 후처리에서 "긴 해설 수동 검토 필요"로 잡습니다.
    long_explanation_review = bool(format_checks.get("long_explanation_manual_check"))

    # 10. PT쌤 합격팁 검수
    pt_teacher_tip_review = bool(pt_tip.get("pt_teacher_tip_validation"))

    # =========================
    # 실제 수집 옵션
    # =========================

    collect_body = bool(
        problem_material_review
        or answer_review
        or explanation_review
        or expression_review
        or keyword_review
        or choice_view_explanation_structure_review
        or pt_teacher_tip_review
    )

    collect_choices = bool(
        problem_material_review
        or answer_review
        or explanation_review
        or expression_review
        or keyword_review
        or choice_view_explanation_structure_review
        or pt_teacher_tip_review
    )

    collect_answer = bool(
        answer_review
        or explanation_review
        or keyword_review
        or pt_teacher_tip_review
    )

    # 현재 ChatGPT 검수 payload에서 section_tags를 직접 쓰지 않으므로 기본 생략
    collect_section_tags = False

    collect_explanation = bool(
        problem_material_review
        or answer_review
        or explanation_review
        or expression_review
        or keyword_review
        or answer_sentence_format_review
        or choice_view_explanation_structure_review
        or honorific_review
        or long_explanation_review
        or pt_teacher_tip_review
    )

    # 키워드 검수 선택 시에만 키워드 수집
    # PT쌤 합격팁 검수에는 키워드 수집하지 않음
    collect_keywords = bool(keyword_review)

    collect_pt_teacher_tip = bool(pt_teacher_tip_review)

    collect_question_images = bool(
        problem_material_review
        or answer_review
        or explanation_review
        or expression_review
        or keyword_review
        or pt_teacher_tip_review
    )

    # 해설 이미지는 실제 캡처 조건이 should_capture_explanation()에서 한 번 더 걸러집니다.
    # 즉, 여기서 True여도 해설에 LaTeX/수식/렌더링 요소가 없으면 캡처하지 않습니다.
    collect_explanation_images = bool(
        explanation_review
        or expression_review
        or long_explanation_review
    )
    # 문제/보기 영역의 MathJax 표, HTML 표, 수식 렌더링 스크린샷은
    # 표현 오류뿐 아니라 정답/해설/자료 검수에서도 필요합니다.
    # 텍스트 추출만으로는 행·열 경계나 SQL 공백이 붙을 수 있으므로,
    # 내용 검수 계열이 선택된 경우에도 collect_api.py에서 실제 렌더링 요소가 있으면 캡처합니다.
    collect_render_images = bool(
        problem_material_review
        or answer_review
        or explanation_review
        or expression_review
        or keyword_review
        or pt_teacher_tip_review
    )

    return {
        "collect_body": collect_body,
        "collect_choices": collect_choices,
        "collect_answer": collect_answer,
        "collect_section_tags": collect_section_tags,
        "collect_explanation": collect_explanation,
        "collect_keywords": collect_keywords,
        "collect_pt_teacher_tip": collect_pt_teacher_tip,
        "collect_question_images": collect_question_images,
        "collect_explanation_images": collect_explanation_images,
        "collect_render_images": collect_render_images,
    }


def attach_collect_options_to_target(
    target: dict[str, Any],
    collect_options: dict[str, bool],
) -> dict[str, Any]:
    """
    collect_api.normalize_target_configs()가 target["targets"]를 우선 사용하므로,
    parent뿐 아니라 각 child target에도 collect_options를 넣어야 합니다.
    """
    target = deepcopy(target)

    target["collect_options"] = collect_options

    options = target.get("options") or {}
    options["collect_options"] = collect_options
    target["options"] = options

    for key in ("targets", "configs"):
        children = target.get(key)

        if isinstance(children, list):
            for child in children:
                if not isinstance(child, dict):
                    continue

                child["collect_options"] = collect_options

                child_options = child.get("options") or {}
                child_options["collect_options"] = collect_options
                child["options"] = child_options

    return target

    
def run_pipeline(job_id: str, target: dict[str, Any]) -> dict[str, Any]:
    job_path = job_dir(job_id)
    job_path.mkdir(parents=True, exist_ok=True)

    options = target.get("options") or {}
    review_checks = (
        target.get("review_checks")
        or target.get("checks")
        or options.get("review_checks")
        or options.get("checks")
    )

    collect_options = build_collect_options_from_review_checks(review_checks)
    target = attach_collect_options_to_target(target, collect_options)

    # collect_options가 붙은 최종 target 기준으로 options를 다시 읽습니다.
    options = target.get("options") or {}

    headless = options.get("headless")
    if headless is not None:
        headless = bool(headless)

    write_json(job_path / "target.json", target)
    update_status(
        job_path,
        "queued",
        job_id=job_id,
        target=target,
        collect_options=collect_options,
        created_at=now_iso(),
        started_at=now_iso(),
    )
    

    if headless is not None:
        headless = bool(headless)

    try:
        raise_if_cancelled(job_id)

        update_status(job_path, "collecting")

        collect_from_target(
            target,
            job_id=job_id,
            job_dir=job_path,
            headless=headless,
            cancel_checker=lambda: raise_if_cancelled(job_id),
        )

        if bool(options.get("save_collected_to_db", False)):
            raise_if_cancelled(job_id)

            update_status(job_path, "saving_collected_to_db")

            inserted_questions = insert_collected_raw_to_questions_db(
                job_id=job_id,
                job_path=job_path,
                target=target,
            )

            if inserted_questions:
                temp_exam_unique_no = inserted_questions[0].get("exam_unique_no") or f"TEMP_{job_id}"

                target["exam_unique_no"] = temp_exam_unique_no
                target["questions"] = inserted_questions

                # 이후 result 조회/부분 실패 처리에서도 같은 target을 쓰도록 저장합니다.
                write_json(job_path / "target.json", target)

        raise_if_cancelled(job_id)

        update_status(job_path, "reviewing")

        reviewed_questions = review_job_dir(
            job_path,
            write_excel=bool(options.get("write_excel", True)),
            cancel_checker=lambda: raise_if_cancelled(job_id),
            review_checks=review_checks,
        )

        raise_if_cancelled(job_id)

        if not reviewed_questions:
            raise RuntimeError(
                "검수할 문제가 수집되지 않았습니다. course_name, set_name, subject_name, subtype_name, question_range를 확인하세요."
            )

        result = build_site_result(job_id, target, reviewed_questions)
        result = attach_review_errors_to_result(job_path, result)

        write_json(job_path / "result.json", result)

        update_status(
            job_path,
            "completed",
            total_questions=result["summary"]["total_questions"],
            issue_question_count=result["summary"]["issue_question_count"],
            mapping_error_count=result["summary"].get("mapping_error_count", 0),
        )

        return result

    except JobCancelled as e:
        partial_result = write_partial_result_if_exists(
            job_id=job_id,
            job_path=job_path,
            target=target,
            status="partial_canceled",
            error_message=str(e),
        )

        if partial_result:
            return partial_result

        update_status(job_path, "canceled", error_message=str(e))
        return {
            "job_id": job_id,
            "status": "canceled",
            "message": str(e),
        }
        
    except Exception as e:
        partial_result = write_partial_result_if_exists(
            job_id=job_id,
            job_path=job_path,
            target=target,
            status="partial_failed",
            error_message=str(e),
        )

        if partial_result:
            return partial_result

        update_status(job_path, "failed", error_message=str(e))
        raise
        
@app.get("/health")
def health():
    return {"ok": True, "time": now_iso()}


@app.post("/review-jobs")
def create_review_job(target: dict[str, Any], background_tasks: BackgroundTasks):
    """
    비동기 권장 방식입니다.
    사이트는 job_id를 받은 뒤 GET /review-jobs/{job_id}, GET /review-jobs/{job_id}/result로 조회합니다.
    """
    job_id = target.get("job_id") or new_job_id()
    job_path = job_dir(job_id)

    if job_path.exists() and (job_path / "status.json").exists():
        raise HTTPException(status_code=409, detail="이미 존재하는 job_id입니다.")

    job_path.mkdir(parents=True, exist_ok=True)
    write_json(job_path / "target.json", target)
    update_status(job_path, "queued", job_id=job_id, target=target, created_at=now_iso())

    background_tasks.add_task(run_pipeline, job_id, target)

    return {
        "job_id": job_id,
        "status": "queued",
        "status_url": f"/review-jobs/{job_id}",
        "result_url": f"/review-jobs/{job_id}/result",
    }


@app.post("/review-jobs/{job_id}/cancel")
def cancel_review_job(job_id: str):
    job_path = job_dir(job_id)
    status_path = job_path / "status.json"

    if not status_path.exists():
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    current = read_json(status_path)
    current_status = current.get("status")

    if current_status in {"completed", "failed", "canceled", "partial_failed", "partial_canceled"}:
        return {
            "ok": True,
            "job_id": job_id,
            "status": current_status,
            "message": "이미 종료된 작업입니다.",
        }

    cancel_file(job_id).write_text(now_iso(), encoding="utf-8")

    update_status(
        job_path,
        "cancel_requested",
        cancel_requested_at=now_iso(),
    )

    return {
        "ok": True,
        "job_id": job_id,
        "status": "cancel_requested",
    }

@app.get("/review-jobs/{job_id}")
def get_review_job(job_id: str):
    return read_json(job_dir(job_id) / "status.json")


@app.get("/review-jobs/{job_id}/result")
def get_review_job_result(job_id: str):
    return read_json(job_dir(job_id) / "result.json")


@app.get("/review-jobs/{job_id}/raw")
def list_raw_files(job_id: str):
    raw_dir = job_dir(job_id) / "raw"
    if not raw_dir.exists():
        return {"job_id": job_id, "files": []}
    return {"job_id": job_id, "files": sorted(p.name for p in raw_dir.glob("*.json"))}


@app.get("/review-jobs/{job_id}/chatgpt.xlsx")
def download_chatgpt_xlsx(job_id: str):
    path = job_dir(job_id) / "chatgpt.xlsx"

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="chatgpt.xlsx 파일이 아직 생성되지 않았거나 오류 문제가 없습니다.",
        )

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{job_id}_chatgpt.xlsx",
    )

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Question Review API is running",
        "docs": "/docs"
    }