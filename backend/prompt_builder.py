from __future__ import annotations

import json
from typing import Any, Dict, List

from prompt_rules import (
    BASE_PROMPT,
    CHECK_OUTPUT_RULES,
    CONTENT_HEADER,
    CONTENT_PRIORITY,
    CONTENT_PROBLEM_VALIDITY,
    CONTENT_IMAGE_VALIDATION,
    CONTENT_ANSWER_VALIDATION,
    CONTENT_EXPLANATION_LOGIC,
    CONTENT_SOURCE_CONSISTENCY,
    CONTENT_CHOICE_EXPLANATION_MATCH,
    CONTENT_EXPRESSION_ERROR,
    CONTENT_KEYWORD_VALIDATION,
    FORMAT_HEADER,
    FORMAT_START_SENTENCE,
    FORMAT_CHOICE_EXPLANATION_EXISTS,
    FORMAT_CHOICE_EXPLANATION_FORMAT,
    FORMAT_HONORIFIC_STYLE,
    FORMAT_NEGATIVE_QUESTION,
    FORMAT_CONCLUSION_SENTENCE,
    FORMAT_QUOTE_RULES,
    FORMAT_DUPLICATE_ANSWER,
    FORMAT_LONG_EXPLANATION,
)


DEFAULT_REVIEW_CHECKS: Dict[str, Dict[str, bool]] = {
    "content": {
        "problem_validity": True,
        "answer_validation": True,
        "explanation_logic": True,
        "choice_explanation_match": True,
        "image_validation": True,
        "expression_error": True,
        "keyword_validation": True,
    },
    "format": {
        "start_sentence": True,
        "choice_explanation_exists": True,
        "choice_explanation_format": True,
        "honorific_style": True,
        "negative_question": True,
        "conclusion_sentence": True,
        "quote_rules": True,
        "duplicate_answer_sentence": True,
        "markdown_error": True,
        "long_explanation_manual_check": True,
    },
}


CHECK_PRESETS: Dict[str, Dict[str, Dict[str, bool]]] = {
    "all": DEFAULT_REVIEW_CHECKS,
    "content_only": {
        "content": {key: True for key in DEFAULT_REVIEW_CHECKS["content"]},
        "format": {key: False for key in DEFAULT_REVIEW_CHECKS["format"]},
    },
    "format_only": {
        "content": {key: False for key in DEFAULT_REVIEW_CHECKS["content"]},
        "format": {
            **{key: True for key in DEFAULT_REVIEW_CHECKS["format"]},
            "markdown_error": False,
        },
    },
    "answer_only": {
        "content": {
            "problem_validity": False,
            "answer_validation": True,
            "explanation_logic": False,
            "choice_explanation_match": False,
            "image_validation": False,
            "expression_error": False,
            "keyword_validation": False,
        },
        "format": {key: False for key in DEFAULT_REVIEW_CHECKS["format"]},
    },
    "explanation_only": {
        "content": {
            "problem_validity": False,
            "answer_validation": False,
            "explanation_logic": True,
            "choice_explanation_match": True,
            "image_validation": False,
            "expression_error": True,
            "keyword_validation": False,
        },
        "format": {
            "start_sentence": True,
            "choice_explanation_exists": True,
            "choice_explanation_format": True,
            "honorific_style": True,
            "negative_question": True,
            "conclusion_sentence": True,
            "quote_rules": True,
            "duplicate_answer_sentence": True,
            "markdown_error": True,
            "long_explanation_manual_check": True,
        },
    },
    "cancel": {
        "content": {key: False for key in DEFAULT_REVIEW_CHECKS["content"]},
        "format": {key: False for key in DEFAULT_REVIEW_CHECKS["format"]},
    },
    "none": {
        "content": {key: False for key in DEFAULT_REVIEW_CHECKS["content"]},
        "format": {key: False for key in DEFAULT_REVIEW_CHECKS["format"]},
    },
}


# 화면에 보이는 검수 항목 기준으로 결과 JSON을 강제합니다.
# 내부 프롬프트 키는 더 세분화되어 있어도 출력은 아래 8개 항목 단위로 묶습니다.
VISIBLE_CHECK_GROUPS: Dict[str, Dict[str, Any]] = {
    "problem_data_validation": {
        "group": "content",
        "label": "문제 성립/자료 검수",
        "source_keys": [("content", "problem_validity"), ("content", "image_validation")],
        "allowed_issue_types": ["문제 성립 오류", "기타 내용 오류"],
    },
    "answer_validation": {
        "group": "content",
        "label": "정답 검증",
        "source_keys": [("content", "answer_validation")],
        "allowed_issue_types": ["정답 불일치"],
    },
    "explanation_validation": {
        "group": "content",
        "label": "해설 내용 검수",
        "source_keys": [("content", "explanation_logic"), ("content", "choice_explanation_match")],
        "allowed_issue_types": ["해설 내용 오류", "선지-해설 불일치", "기타 내용 오류"],
    },
    "expression_rendering": {
        "group": "content",
        "label": "표현/렌더링 오류",
        "source_keys": [("content", "expression_error"), ("format", "markdown_error")],
        "allowed_issue_types": ["표현/렌더링 오류"],
    },
    "keyword_validation": {
        "group": "content",
        "label": "키워드 검수",
        "source_keys": [("content", "keyword_validation")],
        "allowed_issue_types": ["키워드 오류"],
    },        
    "answer_sentence_format": {
        "group": "format",
        "label": "정답 문장 형식",
        "source_keys": [
            ("format", "start_sentence"),
            ("format", "negative_question"),
            ("format", "conclusion_sentence"),
            ("format", "quote_rules"),
            ("format", "duplicate_answer_sentence"),
        ],
        "allowed_issue_types": [
            "해설 시작 형식 오류",
            "정답 문장 중복",
            "결론 누락",
            "최종 문장 형식 오류",
            "기타 형식 오류",
        ],
    },
    "choice_explanation_structure": {
        "group": "format",
        "label": "선지/보기 해설 구조",
        "source_keys": [("format", "choice_explanation_exists"), ("format", "choice_explanation_format")],
        "allowed_issue_types": ["선지별 해설 누락", "선지 해설 형식 오류"],
    },
    "honorific_style": {
        "group": "format",
        "label": "존댓말 확인",
        "source_keys": [("format", "honorific_style")],
        "allowed_issue_types": ["기타 형식 오류"],
    },
    "long_explanation_manual_check": {
        "group": "format",
        "label": "긴 해설 수동 검토",
        "source_keys": [("format", "long_explanation_manual_check")],
        "allowed_issue_types": ["긴 해설 수동 검토 필요"],
    },
}


def _copy_checks(checks: Dict[str, Dict[str, bool]]) -> Dict[str, Dict[str, bool]]:
    return {
        "content": dict(checks.get("content", {})),
        "format": dict(checks.get("format", {})),
    }


def merge_review_checks(user_checks: Dict[str, Any] | None = None) -> Dict[str, Dict[str, bool]]:
    """
    프론트에서 전달한 checks를 기본값과 병합합니다.

    지원 입력:
    1) {"content": {...}, "format": {...}}
    2) {"preset": "format_only"}
    3) None -> 전체 검수
    """
    if not user_checks:
        return _copy_checks(DEFAULT_REVIEW_CHECKS)

    preset = str(user_checks.get("preset") or user_checks.get("review_preset") or "").strip()
    if preset and preset in CHECK_PRESETS:
        base = _copy_checks(CHECK_PRESETS[preset])
    else:
        base = _copy_checks(DEFAULT_REVIEW_CHECKS)

    for group in ("content", "format"):
        group_value = user_checks.get(group)
        if not isinstance(group_value, dict):
            continue

        for key, value in group_value.items():
            if key in base[group]:
                base[group][key] = bool(value)

    return base


# 기존 생성 파일과 호환용 alias
merge_checks = merge_review_checks


def should_run_content_review(checks: Dict[str, Any] | None = None) -> bool:
    merged = merge_review_checks(checks)
    return any(merged.get("content", {}).values())


def should_run_format_review(checks: Dict[str, Any] | None = None) -> bool:
    merged = merge_review_checks(checks)
    return any(merged.get("format", {}).values())


def is_check_enabled(checks: Dict[str, Any] | None, group: str, key: str) -> bool:
    merged = merge_review_checks(checks)
    return bool(merged.get(group, {}).get(key))


def _is_visible_check_enabled(merged: Dict[str, Dict[str, bool]], check_id: str) -> bool:
    meta = VISIBLE_CHECK_GROUPS[check_id]
    return any(bool(merged.get(group, {}).get(key)) for group, key in meta["source_keys"])


def get_selected_visible_checks(checks: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    merged = merge_review_checks(checks)
    selected = []
    for check_id, meta in VISIBLE_CHECK_GROUPS.items():
        if _is_visible_check_enabled(merged, check_id):
            selected.append({"id": check_id, **meta})
    return selected


def get_selected_visible_check_labels(checks: Dict[str, Any] | None = None) -> list[str]:
    return [item["label"] for item in get_selected_visible_checks(checks)]


def get_review_scope_summary(checks: Dict[str, Any] | None = None) -> str:
    selected = get_selected_visible_checks(checks)
    if not selected:
        return "검수 항목 없음"

    selected_ids = {item["id"] for item in selected}
    all_ids = set(VISIBLE_CHECK_GROUPS.keys())
    content_ids = {check_id for check_id, meta in VISIBLE_CHECK_GROUPS.items() if meta["group"] == "content"}
    format_ids = {check_id for check_id, meta in VISIBLE_CHECK_GROUPS.items() if meta["group"] == "format"}

    if selected_ids == all_ids:
        return "전체 검수"
    if selected_ids == content_ids:
        return "내용 검수"
    if selected_ids == format_ids:
        return "형식 검수"
    return "부분 검수"


def _build_required_check_block(selected: List[Dict[str, Any]]) -> str:
    if not selected:
        return """
[선택된 검수 항목]
선택된 검수 항목이 없다.
content_issues와 format_issues를 빈 배열로 반환한다.
""".strip()

    required_ids = [item["id"] for item in selected]
    labels = [f"{item['id']}={item['label']}" for item in selected]

    return "\n".join([
        "[선택된 검수 항목]",
        f"required_check_ids = {json.dumps(required_ids, ensure_ascii=False)}",
        "선택된 항목:",
        "\n".join(f"- {label}" for label in labels),
        "required_check_ids에 있는 항목만 검수한다.",
    ])


def _build_output_schema_block(selected: List[Dict[str, Any]], checks: Dict[str, Any] | None = None) -> str:
    return """
[반환 JSON 형식]
반드시 JSON만 반환한다.

필수 key:
- question_id
- content_issues
- format_issues
- summary

issue 객체:
{
  "type": "",
  "reason": "",
  "suggestion": ""
}

content_issues:
- 내용 오류가 있을 때만 issue 객체를 넣는다.
- 내용 오류가 없으면 []로 반환한다.

format_issues:
- 형식 오류가 있을 때만 issue 객체를 넣는다.
- 형식 오류가 없으면 []로 반환한다.

summary:
{
  "has_issue": false,
  "issue_count": 0
}

중요:
- summary.issue_count는 content_issues와 format_issues의 총 개수와 일치해야 한다.
- 오류가 없으면 content_issues와 format_issues는 모두 []로 반환한다.
- 정상 판단은 content_issues 또는 format_issues에 기록하지 않는다.
""".strip()

def build_review_prompt(checks: Dict[str, Any] | None = None) -> str:
    """
    문제 JSON은 chatgpt_api.build_user_content()에서 붙입니다.
    이 함수는 규칙 프롬프트만 조립합니다.
    """
    merged = merge_review_checks(checks)
    content_checks = merged["content"]
    format_checks = merged["format"]
    selected_visible_checks = get_selected_visible_checks(checks)

    parts: list[str] = [BASE_PROMPT]
    parts.append(_build_required_check_block(selected_visible_checks))

    if any(content_checks.values()):
        parts.append(CONTENT_HEADER)
        parts.append(CONTENT_PRIORITY)

        if content_checks.get("problem_validity"):
            parts.append(CONTENT_PROBLEM_VALIDITY)
        if content_checks.get("image_validation"):
            parts.append(CONTENT_IMAGE_VALIDATION)
        if content_checks.get("answer_validation"):
            parts.append(CONTENT_ANSWER_VALIDATION)
        if content_checks.get("explanation_logic"):
            parts.append(CONTENT_EXPLANATION_LOGIC)
            parts.append(CONTENT_SOURCE_CONSISTENCY)
        if content_checks.get("choice_explanation_match"):
            parts.append(CONTENT_CHOICE_EXPLANATION_MATCH)
        if content_checks.get("expression_error") or format_checks.get("markdown_error"):
            parts.append(CONTENT_EXPRESSION_ERROR)
        if content_checks.get("keyword_validation"):
            parts.append(CONTENT_KEYWORD_VALIDATION)

    if any(format_checks.values()):
        parts.append(FORMAT_HEADER)

        if format_checks.get("start_sentence"):
            parts.append(FORMAT_START_SENTENCE)
        if format_checks.get("choice_explanation_exists"):
            parts.append(FORMAT_CHOICE_EXPLANATION_EXISTS)
        if format_checks.get("choice_explanation_format"):
            parts.append(FORMAT_CHOICE_EXPLANATION_FORMAT)
        if format_checks.get("honorific_style"):
            parts.append(FORMAT_HONORIFIC_STYLE)
        if format_checks.get("negative_question"):
            parts.append(FORMAT_NEGATIVE_QUESTION)
        if format_checks.get("conclusion_sentence"):
            parts.append(FORMAT_CONCLUSION_SENTENCE)
        if format_checks.get("quote_rules"):
            parts.append(FORMAT_QUOTE_RULES)
        if format_checks.get("duplicate_answer_sentence"):
            parts.append(FORMAT_DUPLICATE_ANSWER)
        # markdown_error는 화면상 "표현/렌더링 오류"에 포함되므로
        # 별도 형식 오류 프롬프트를 붙이지 않는다.
        if format_checks.get("long_explanation_manual_check"):
            parts.append(FORMAT_LONG_EXPLANATION)

    if not any(content_checks.values()) and not any(format_checks.values()):
        parts.append(
            """
[검수 항목 없음]
선택된 검수 항목이 없으므로 오류를 기록하지 말고 빈 결과 JSON을 반환한다.
""".strip()
        )

    parts.append(CHECK_OUTPUT_RULES)
    parts.append(_build_output_schema_block(selected_visible_checks, checks))

    return "\n\n".join(part.strip() for part in parts if str(part).strip())
