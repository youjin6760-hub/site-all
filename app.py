import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from collect_api import collect_from_target
from claude_api import ERROR_CODES, review_job_dir

APP_ROOT = Path(os.getenv("APP_ROOT", Path(__file__).resolve().parent)).resolve()
JOBS_DIR = Path(os.getenv("JOBS_DIR", APP_ROOT / "jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Question Review API",
    version="1.0.0",
    description="사이트에서 전달한 target JSON 기준으로 문제 수집과 Claude 검수를 실행합니다.",
)

# 같은 도메인에서만 호출한다면 CORS 설정은 더 좁게 제한해도 됩니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_id() -> str:
    return "review_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def job_dir(job_id: str) -> Path:
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise HTTPException(status_code=400, detail="job_id 형식이 올바르지 않습니다.")
    return JOBS_DIR / job_id


def write_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"파일을 찾을 수 없습니다: {path.name}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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

    if status in {"completed", "failed"}:
        current.setdefault("completed_at", now_iso())

    write_json(status_path, current)


def get_question_site_meta_map(target: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    사이트 DB 문제와 collect 결과를 연결하기 위한 매핑입니다.
    기본 매칭키는 question_no입니다.

    주의:
    한 job 안에는 같은 exam_unique_no에 속한 문제만 넣는 것을 권장합니다.
    서로 다른 exam_unique_no의 같은 question_no가 섞이면 question_no만으로 구분이 어렵습니다.
    """
    mapping: dict[str, dict[str, Any]] = {}
    questions = target.get("questions") or []

    if not isinstance(questions, list):
        return mapping

    default_exam_unique_no = target.get("exam_unique_no")

    for q in questions:
        if not isinstance(q, dict):
            continue

        qno = q.get("question_no") or q.get("no")
        if qno is None:
            continue

        site_id = q.get("site_question_id") or q.get("site_problem_id") or q.get("idx") or q.get("id")
        exam_unique_no = q.get("exam_unique_no") or default_exam_unique_no

        mapping[str(int(qno))] = {
            "site_question_id": site_id,
            "exam_unique_no": exam_unique_no,
            "source_question": q,
        }

    return mapping


def normalize_issues(reviewed: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for issue in reviewed.get("content_issues", []) or []:
        issue_type = issue.get("type", "")
        issues.append({
            "issue_area": "content",
            "issue_type": issue_type,
            "error_code": ERROR_CODES.get(issue_type, 0),
            "reason": issue.get("reason", ""),
            "suggestion": issue.get("suggestion", ""),
            "confidence": issue.get("confidence", 0),
        })

    for issue in reviewed.get("format_issues", []) or []:
        issue_type = issue.get("type", "")
        issues.append({
            "issue_area": "format",
            "issue_type": issue_type,
            "error_code": ERROR_CODES.get(issue_type, 0),
            "reason": issue.get("reason", ""),
            "suggestion": issue.get("suggestion", ""),
            "confidence": issue.get("confidence", 0),
        })

    return issues


def build_site_result(job_id: str, target: dict[str, Any], reviewed_questions: list[dict[str, Any]]) -> dict[str, Any]:
    site_meta_map = get_question_site_meta_map(target)
    include_raw_data = bool((target.get("options") or {}).get("include_raw_data", True))

    items: list[dict[str, Any]] = []

    total_questions = len(reviewed_questions)
    issue_question_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0

    for reviewed in reviewed_questions:
        summary = reviewed.get("summary", {}) or {}
        has_issue = bool(summary.get("has_issue"))
        severity = summary.get("severity", "low") or "low"

        if has_issue:
            issue_question_count += 1

        if severity == "high":
            high_count += 1
        elif severity == "medium":
            medium_count += 1
        else:
            low_count += 1

        qno = reviewed.get("question_no")
        site_meta = site_meta_map.get(str(qno), {})
        issues = normalize_issues(reviewed)

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
            "severity": severity,
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
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
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
    headless = options.get("headless")
    if headless is not None:
        headless = bool(headless)

    try:
        update_status(job_path, "collecting")
        collect_from_target(target, job_id=job_id, job_dir=job_path, headless=headless)

        update_status(job_path, "reviewing")
        reviewed_questions = review_job_dir(
            job_path,
            write_excel=bool(options.get("write_excel", True)),
        )

        if not reviewed_questions:
            raise RuntimeError(
                "검수할 문제가 수집되지 않았습니다. course_name, set_name, subject_name, subtype_name, question_range를 확인하세요."
            )

        result = build_site_result(job_id, target, reviewed_questions)
        write_json(job_path / "result.json", result)

        update_status(
            job_path,
            "completed",
            total_questions=result["summary"]["total_questions"],
            issue_question_count=result["summary"]["issue_question_count"],
        )
        return result

    except Exception as e:
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


@app.post("/review-jobs/run")
def run_review_job_now(target: dict[str, Any]):
    """
    테스트용 동기 실행입니다.
    요청이 끝날 때까지 수집/검수를 모두 기다린 뒤 결과 JSON을 반환합니다.
    운영에서는 /review-jobs 비동기 방식을 권장합니다.
    """
    job_id = target.get("job_id") or new_job_id()
    job_path = job_dir(job_id)

    if job_path.exists() and (job_path / "status.json").exists():
        raise HTTPException(status_code=409, detail="이미 존재하는 job_id입니다.")

    try:
        return run_pipeline(job_id, target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
