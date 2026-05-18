import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from collect_api import collect_from_target
from chatgpt_api import review_job_dir
from db_api import app as question_api_app

APP_ROOT = Path(os.getenv("APP_ROOT", Path(__file__).resolve().parent)).resolve()
JOBS_DIR = Path(os.getenv("JOBS_DIR", APP_ROOT / "jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)

            
app = FastAPI(
    title="Question Review API",
    version="1.0.0",
    description="사이트에서 전달한 target JSON 기준으로 문제 수집과 ChatGPT 검수를 실행합니다.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.219.167:5173",
    ],
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

    
def run_pipeline(job_id: str, target: dict[str, Any]) -> dict[str, Any]:
    job_path = job_dir(job_id)
    job_path.mkdir(parents=True, exist_ok=True)

    write_json(job_path / "target.json", target)
    update_status(
        job_path,
        "queued",
        job_id=job_id,
        target=target,
        created_at=now_iso(),
        started_at=now_iso(),
    )

    options = target.get("options") or {}
    review_checks = (
        target.get("review_checks")
        or target.get("checks")
        or options.get("review_checks")
        or options.get("checks")
    )
    headless = options.get("headless")
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

        raise_if_cancelled(job_id)

        update_status(job_path, "reviewing")

        reviewed_questions = review_job_dir(
            job_path,
            write_excel=bool(options.get("write_excel", False)),
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

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Question Review API is running",
        "docs": "/docs"
    }