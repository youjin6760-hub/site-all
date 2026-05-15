import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./App.css";

const API_BASE = import.meta.env.VITE_QUESTION_API_BASE || "http://192.168.219.167:8000";
const DEFAULT_REVIEW_API_BASE = import.meta.env.VITE_REVIEW_API_BASE || "http://192.168.219.167:8000";

const CONTENT_ERROR_TYPES = [
  "문제 매핑 오류",
  "문제 성립 오류",
  "정답 불일치",
  "해설 내용 오류",
  "선지-해설 불일치",
  "표현/렌더링 오류",
  "키워드 오류",
  "기타 내용 오류",
];

const FORMAT_ERROR_TYPES = [
  "형식 오류",
  "긴 해설 수동 검토 필요",
];

const LEGACY_FORMAT_ERROR_TYPES = [
  "해설 시작 형식 오류",
  "선지별 해설 누락",
  "선지 해설 형식 오류",
  "정답 문장 중복",
  "결론 누락",
  "최종 문장 형식 오류",
  "기타 형식 오류",
];

const DEFAULT_FILTERS = {
  courseName: "전체",
  setName: "전체",
  examUniqueNo: "전체",
  subjectName: "전체",
  subtypeName: "전체",
  cdValue: "전체",
  reviewStatus: "전체",
  errorType: "전체",
  reflectStatus: "전체",
  search: "",
  pageSize: "20",
};

const DEFAULT_REVIEW_TARGET = {
  reviewApiBase: DEFAULT_REVIEW_API_BASE,
  targetMapId: "",
  targetMapIds: [],
  courseName: "",
  setName: "",
  subjectName: "",
  subtypeName: "",
  examUniqueNo: "",
  cdValue: "",
  subjectMode: "all",
  subjectStartIndex: "1",
  subjectEndIndex: "1",
  questionRange: "",
  targetScope: "filtered",
};


const DEFAULT_REVIEW_CHECKS = {
  content: {
    problem_validity: true,
    answer_validation: true,
    explanation_logic: true,
    choice_explanation_match: true,
    image_validation: true,
    expression_error: true,
    keyword_validation: true,
  },
  format: {
    start_sentence: true,
    choice_explanation_exists: true,
    choice_explanation_format: true,
    honorific_style: true,
    negative_question: true,
    conclusion_sentence: true,
    quote_rules: true,
    duplicate_answer_sentence: true,
    markdown_error: true,
    long_explanation_manual_check: true,
  },
};

const EMPTY_REVIEW_CHECKS = {
  content: {
    problem_validity: false,
    answer_validation: false,
    explanation_logic: false,
    choice_explanation_match: false,
    image_validation: false,
    expression_error: false,
    keyword_validation: false,
  },
  format: {
    start_sentence: false,
    choice_explanation_exists: false,
    choice_explanation_format: false,
    honorific_style: false,
    negative_question: false,
    conclusion_sentence: false,
    quote_rules: false,
    duplicate_answer_sentence: false,
    markdown_error: false,
    long_explanation_manual_check: false,
  },
};

const REVIEW_CHECK_PRESETS = {
  all: {
    label: "전체 검수",
    checks: DEFAULT_REVIEW_CHECKS,
  },
  contentOnly: {
    label: "내용만",
    checks: {
      content: {
        problem_validity: true,
        answer_validation: true,
        explanation_logic: true,
        choice_explanation_match: true,
        image_validation: true,
        expression_error: true,
        keyword_validation: true,
      },
      format: {
        start_sentence: false,
        choice_explanation_exists: false,
        choice_explanation_format: false,
        honorific_style: false,
        negative_question: false,
        conclusion_sentence: false,
        quote_rules: false,
        duplicate_answer_sentence: false,
        // 표현/렌더링 오류 버튼에 포함된 Markdown 잔여 문법 검수입니다.
        // 화면에서는 내용 검수 쪽 버튼으로 보이지만, API payload는 기존 format.markdown_error 키를 유지합니다.
        markdown_error: true,
        long_explanation_manual_check: false,
      },
    },
  },
  formatOnly: {
    label: "형식만",
    checks: {
      content: {
        problem_validity: false,
        answer_validation: false,
        explanation_logic: false,
        choice_explanation_match: false,
        image_validation: false,
        expression_error: false,
        keyword_validation: false,
      },
      format: {
        start_sentence: true,
        choice_explanation_exists: true,
        choice_explanation_format: true,
        honorific_style: true,
        negative_question: true,
        conclusion_sentence: true,
        quote_rules: true,
        duplicate_answer_sentence: true,
        markdown_error: true,
        long_explanation_manual_check: true,
      },
    },
  },
  answerOnly: {
    label: "정답만",
    checks: {
      content: {
        problem_validity: false,
        answer_validation: true,
        explanation_logic: false,
        choice_explanation_match: false,
        image_validation: false,
        expression_error: false,
        keyword_validation: false,
      },
      format: {
        start_sentence: false,
        choice_explanation_exists: false,
        choice_explanation_format: false,
        honorific_style: false,
        negative_question: false,
        conclusion_sentence: false,
        quote_rules: false,
        duplicate_answer_sentence: false,
        markdown_error: false,
        long_explanation_manual_check: false,
      },
    },
  },
  explanationOnly: {
    label: "해설만",
    checks: {
      content: {
        problem_validity: false,
        answer_validation: false,
        explanation_logic: true,
        choice_explanation_match: true,
        image_validation: false,
        expression_error: true,
        keyword_validation: false,
      },
      format: {
        start_sentence: true,
        choice_explanation_exists: true,
        choice_explanation_format: true,
        honorific_style: true,
        negative_question: true,
        conclusion_sentence: true,
        quote_rules: true,
        duplicate_answer_sentence: true,
        markdown_error: true,
        long_explanation_manual_check: true,
      },
    },
  },
  cancel: {
    label: "취소",
    checks: EMPTY_REVIEW_CHECKS,
  },
};

const REVIEW_CHECK_GROUPS = {
  content: {
    problem_material: {
      label: "문제 성립/자료 검수",
      keys: ["problem_validity", "image_validation"],
      description: "문제 풀이에 필요한 본문, 보기, 이미지, 표, SQL, 수식 등이 충분한지 확인합니다.",
    },
    answer_validation: {
      label: "정답 검증",
      keys: ["answer_validation"],
      description: "문제 조건을 기준으로 실제 정답과 answer 값이 일치하는지 확인합니다.",
    },
    explanation_content: {
      label: "해설 내용 검수",
      keys: ["explanation_logic", "choice_explanation_match"],
      description: "해설 논리와 선지/보기 해설이 문제 조건과 맞는지 확인합니다.",
    },
    expression_rendering: {
      label: "표현/렌더링 오류",
      keys: ["expression_error"],
      description: "수식, 특수문자, 글리프, Markdown 잔여 문법 등 표시 문제를 확인합니다.",
    },
    keyword_validation: {
      label: "키워드 검수",
      keys: ["keyword_validation"],
      description: "키워드가 문제의 핵심 개념과 맞는지, 누락되었거나 과도하게 넓지 않은지 확인합니다.",
    },
  },

  format: {
    answer_sentence_format: {
      label: "정답 문장 형식",
      keys: [
        "start_sentence",
        "conclusion_sentence",
        "duplicate_answer_sentence",
        "quote_rules",
        "negative_question",
      ],
      description: "해설 시작 문장, 결론 문장, 정답 문장 중복, 따옴표 예외, 부정형 예외를 확인합니다.",
    },
    choice_view_explanation_structure: {
      label: "선지/보기 해설 구조",
      keys: [
        "choice_explanation_exists",
        "choice_explanation_format",
      ],
      description: "일반 문제는 선지별 해설 구조를 확인하고, ㄱ/ㄴ/ㄷ/ㄹ 보기제시형은 보기별 해설이 있으면 정상으로 인정합니다.",
    },
    honorific_style: {
      label: "존댓말 확인",
      keys: ["honorific_style"],
      description: "해설이 학습자에게 노출하기에 자연스러운 존댓말인지 확인합니다.",
    },
    long_explanation_manual_check: {
      label: "긴 해설 수동 검토",
      keys: ["long_explanation_manual_check"],
      description: "해설이 너무 길어 스크린샷 검증이 제한된 경우 형식 검수 항목으로 표시합니다.",
    },
  },
};

const REVIEW_CONTENT_CHECK_DESCRIPTIONS = {
  problem_validity: "필수 정보, 이미지, 표, SQL, 수식 누락 등으로 문제가 풀 수 있는 상태인지 확인합니다.",
  answer_validation: "문제 조건을 기준으로 실제 정답과 answer 값이 일치하는지 확인합니다.",
  explanation_logic: "해설이 문제 조건과 핵심 개념을 올바르게 설명하는지 확인합니다.",
  choice_explanation_match: "일반 문제는 선지별 해설을 비교하고, ㄱ/ㄴ/ㄷ/ㄹ 보기제시형은 보기별 해설이 있으면 정상으로 인정합니다.",
  image_validation: "문제/선지/해설 이미지가 깨지거나 누락되어 풀이에 지장이 있는지 확인합니다.",
  expression_error: "수식, 특수문자, 글리프, Markdown 잔여 문법 등 표시 깨짐을 확인합니다.",
  keyword_validation: "키워드가 문제의 핵심 개념과 일치하는지, 핵심 키워드가 누락되었거나 지나치게 넓은지 확인합니다.",
};

const REVIEW_FORMAT_CHECK_DESCRIPTIONS = {
  start_sentence: "해설 첫 문장이 '정답은 X번입니다.' 형식인지 확인합니다.",
  choice_explanation_exists: "일반 문제는 각 선지 해설 존재 여부를 확인하고, 보기제시형은 ㄱ/ㄴ/ㄷ/ㄹ 보기별 해설이 있으면 정상으로 인정합니다.",
  choice_explanation_format: "일반 문제는 'X. 선지 내용' 다음 줄 ': 설명' 구조를 확인하고, 보기제시형은 보기별 해설 형식을 허용합니다.",
  honorific_style: "해설이 학습자에게 노출하기에 자연스러운 존댓말인지 확인합니다. 단순한 '~다' 포함만으로 오류 처리하지 않습니다.",
  negative_question: "틀린 것/옳지 않은 것 문제에서 정답 선지를 부적절한 설명으로 해설하는 정상 케이스를 예외 처리합니다.",
  conclusion_sentence: "마지막 결론 문장이 정답 선지와 함께 적절한 형식으로 있는지 확인합니다.",
  quote_rules: "SQL 문자열이나 선지 원문 때문에 따옴표가 중첩된 정상 케이스를 오류로 보지 않게 합니다.",
  duplicate_answer_sentence: "해설 시작 외 위치에 '정답은 X번입니다.' 문장이 반복되는지 확인합니다.",
  markdown_error: "사용자 노출 해설에 백틱(`) 또는 Markdown 굵게 표시(**)가 남았는지 확인합니다.",
  long_explanation_manual_check: "해설이 너무 길어 스크린샷 검증이 제한된 경우 수동 검토 항목으로 표시합니다.",
};

const DEFAULT_TARGET_MAP_FORM = {
  id: "",
  courseName: "",
  setName: "",
  subjectName: "",
  subtypeName: "",
  examUniqueNo: "",
};

const TARGET_MAP_PAGE_SIZE = 10;

function getValue(obj, keys, fallback = "") {
  for (const key of keys) {
    const value = obj?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return value;
    }
  }
  return fallback;
}

function pick(item, keys, fallback = "") {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return value;
    }
  }
  return fallback;
}

function toText(value, fallback = "-") {
  if (value === undefined || value === null || String(value).trim() === "") {
    return fallback;
  }
  return String(value);
}

function lower(value) {
  return String(value ?? "").toLowerCase();
}

function parseMaybeJson(value) {
  if (!value || typeof value !== "string") return {};
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function toNumber(value) {
  const n = Number(String(value ?? "").trim());
  return Number.isFinite(n) ? n : null;
}

function uniqueJoin(values) {
  return Array.from(new Set(values.filter(Boolean))).join(", ");
}


function cloneReviewChecks(checks) {
  return JSON.parse(JSON.stringify(checks));
}

function getReviewGroupCheckItems(group, groupKey) {
  const item = REVIEW_CHECK_GROUPS[group]?.[groupKey];
  if (!item) return [];

  if (Array.isArray(item.checkItems)) {
    return item.checkItems;
  }

  return (item.keys || []).map((key) => ({ group, key }));
}

function countSelectedReviewChecks(checks) {
  return Object.entries(REVIEW_CHECK_GROUPS).reduce((total, [group, groupItems]) => {
    return total + Object.keys(groupItems).filter((groupKey) => {
      const checkItems = getReviewGroupCheckItems(group, groupKey);
      return checkItems.every(({ group: itemGroup, key }) => !!checks[itemGroup]?.[key]);
    }).length;
  }, 0);
}

function isReviewGroupChecked(reviewChecks, group, groupKey) {
  const checkItems = getReviewGroupCheckItems(group, groupKey);
  return checkItems.every(({ group: itemGroup, key }) => !!reviewChecks[itemGroup]?.[key]);
}

function getSelectedReviewCheckLabels(checks) {
  return Object.entries(REVIEW_CHECK_GROUPS).flatMap(([group, groupItems]) =>
    Object.entries(groupItems)
      .filter(([groupKey]) => isReviewGroupChecked(checks, group, groupKey))
      .map(([, item]) => item.label)
  );
}

function formatSelectedReviewCheckLabels(labels) {
  return labels.length > 0 ? labels.join(", ") : "-";
}

function parseJsonArray(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function parseLabelList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean);
  return String(value)
    .split(/[,|\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueLabels(labels) {
  return Array.from(new Set((labels || []).map(String).map((item) => item.trim()).filter(Boolean)));
}

function getAllReviewLabelGroups() {
  const content = Object.values(REVIEW_CHECK_GROUPS.content).map((item) => item.label);
  const format = Object.values(REVIEW_CHECK_GROUPS.format).map((item) => item.label);
  return { content, format, all: [...content, ...format] };
}

function makeReviewScopeSummary(labels) {
  const normalized = uniqueLabels(labels);
  if (normalized.length === 0) return "-";

  const { content, format, all } = getAllReviewLabelGroups();
  const hasAllContent = content.every((label) => normalized.includes(label));
  const hasAllFormat = format.every((label) => normalized.includes(label));
  const hasAll = all.every((label) => normalized.includes(label));

  if (hasAll) return "전체 검수";

  const remainingContent = content.filter((label) => normalized.includes(label));
  const remainingFormat = format.filter((label) => normalized.includes(label));

  if (hasAllContent && remainingFormat.length === 0) return "내용 검수";
  if (hasAllFormat && remainingContent.length === 0) return "형식 검수";

  if (hasAllContent) {
    return ["내용 검수", ...remainingFormat].join(", ");
  }

  if (hasAllFormat) {
    return [...remainingContent, "형식 검수"].join(", ");
  }

  return normalized.join(", ");
}

function makeReviewRunTitle(labels) {
  return makeReviewScopeSummary(labels);
}

function mergeTextBlock(existingText, title, body) {
  const current = String(existingText || "").trim();
  const nextBody = String(body || "").trim();
  if (!nextBody) return current;

  const block = `[${title}]\n${nextBody}`;
  return current ? `${current}\n\n${block}` : block;
}

function formatIssuesForHistory(issues) {
  return (issues || []).map((issue) => ({
    issue_type: issue.issue_type || "",
    reason: issue.reason || "",
    suggestion: issue.suggestion || "",
  }));
}

function normalizeReviewHistory(history) {
  return parseJsonArray(history).map((item, index) => {
    const labels = uniqueLabels(item.labels || []);
    const issues = formatIssuesForHistory(item.issues || []);
    const summary = item.summary || makeReviewScopeSummary(labels);

    return {
      ...item,
      at: item.at || `history-${index}`,
      labels,
      summary,
      issues,
      issue_count: issues.length,
      result: issues.length > 0 ? "오류있음" : "정상",
    };
  });
}

function rebuildReviewFieldsFromHistory(history) {
  const normalizedHistory = normalizeReviewHistory(history);
  const allIssues = normalizedHistory.flatMap((item) => item.issues || []);

  const errorTypes = normalizeErrorTypes(
    allIssues
      .map((issue) => issue.issue_type)
      .filter(Boolean)
  );

  const reviewCheckLabels = uniqueLabels(
    normalizedHistory.flatMap((item) => item.labels || [])
  );

  const reason = normalizedHistory
    .map((item) => {
      const body = (item.issues || [])
        .map((issue) => issue.reason || "")
        .filter(Boolean)
        .join("\n\n");

      return body ? `[${item.summary || "-"}]\n${body}` : "";
    })
    .filter(Boolean)
    .join("\n\n");

  const suggestion = normalizedHistory
    .map((item) => {
      const body = (item.issues || [])
        .map((issue) => issue.suggestion || "")
        .filter(Boolean)
        .join("\n\n");

      return body ? `[${item.summary || "-"}]\n${body}` : "";
    })
    .filter(Boolean)
    .join("\n\n");

  const nextStatus = errorTypes.length > 0 ? "오류있음" : "정상";

  return {
    review_check_history: normalizedHistory,
    review_check_labels: reviewCheckLabels,
    review_scope_summary: makeReviewScopeSummary(reviewCheckLabels),
    error_types: errorTypes,
    error_type: errorTypes.join(", "),
    reason,
    suggestion,
    status: nextStatus,
    review_status: nextStatus,
  };
}

function toggleReviewGroup(setReviewChecks, group, groupKey) {
  const checkItems = getReviewGroupCheckItems(group, groupKey);

  setReviewChecks((prev) => {
    const currentlyChecked = checkItems.every(
      ({ group: itemGroup, key }) => !!prev[itemGroup]?.[key]
    );

    const next = {
      ...prev,
      content: { ...prev.content },
      format: { ...prev.format },
    };

    checkItems.forEach(({ group: itemGroup, key }) => {
      if (!next[itemGroup]) next[itemGroup] = {};
      next[itemGroup][key] = !currentlyChecked;
    });

    return next;
  });
}

function normalizeReviewChecksForPayload(checks) {
  const next = cloneReviewChecks(checks);

  // 화면에는 "표현/렌더링 오류" 1개 항목만 보이게 하고,
  // 실제 AI 검수 payload에서는 기존 호환용 markdown_error를 같은 값으로 맞춥니다.
  if (!next.format) next.format = {};
  next.format.markdown_error = !!next.content?.expression_error;

  return next;
}

function parseReviewRange(rangeText) {
  const text = String(rangeText ?? "").trim();
  if (!text || text === "all") return null;

  const match = text.match(/^(\d+)\s*-\s*(\d+)$/);
  if (!match) return null;

  const start = Number(match[1]);
  const end = Number(match[2]);
  return { start: Math.min(start, end), end: Math.max(start, end) };
}

function makeOptions(rows, key, shouldSort = false) {
  const values = rows
    .map((row) => row[key])
    .filter((value) => value !== undefined && value !== null && String(value).trim() !== "" && String(value).trim() !== "-")
    .map(String);

  const uniqueValues = Array.from(new Set(values));

  const sortedValues = shouldSort
    ? [...uniqueValues].sort((a, b) =>
        a.localeCompare(b, "ko-KR", {
          numeric: true,
          sensitivity: "base",
        })
      )
    : uniqueValues;

  return ["전체", ...sortedValues];
}

function makeErrorTypeOptions(rows) {
  const values = rows.flatMap((row) =>
    normalizeErrorTypes(splitErrorTypes(row.errorType))
  );

  const uniqueValues = Array.from(
    new Set(
      values
        .map((item) => String(item || "").trim())
        .filter((item) => item && item !== "-")
    )
  );

  const sortedValues = uniqueValues.sort((a, b) =>
    a.localeCompare(b, "ko-KR", {
      numeric: true,
      sensitivity: "base",
    })
  );

  return ["전체", ...sortedValues];
}

function makeSubjectOptions(rows) {
  const values = rows
    .map((row) => String(row.subjectName || "").trim() || "미지정")
    .filter(Boolean);

  const sortedValues = Array.from(new Set(values)).sort((a, b) =>
    a.localeCompare(b, "ko-KR", {
      numeric: true,
      sensitivity: "base",
    })
  );

  return ["전체", ...sortedValues];
}

function makeCourseOptions(rows) {
  const values = rows
    .map((row) => String(row.courseName || "").trim() || "미지정")
    .filter(Boolean);

  const sortedValues = Array.from(new Set(values)).sort((a, b) =>
    a.localeCompare(b, "ko-KR", {
      numeric: true,
      sensitivity: "base",
    })
  );

  return ["전체", ...sortedValues];
}

function makeTextOptions(rows, key) {
  const values = rows
    .map((row) => String(row[key] || "").trim() || "미지정")
    .filter(Boolean);

  const sortedValues = Array.from(new Set(values)).sort((a, b) =>
    a.localeCompare(b, "ko-KR", {
      numeric: true,
      sensitivity: "base",
    })
  );

  return ["전체", ...sortedValues];
}

function makeTargetMapOptions(items, key) {
  const values = items
    .map((item) => String(item?.[key] || "").trim())
    .filter(Boolean);

  return Array.from(new Set(values)).sort((a, b) =>
    a.localeCompare(b, "ko-KR", {
      numeric: true,
      sensitivity: "base",
    })
  );
}

function getStatusClass(status) {
  const text = String(status ?? "");
  if (text.includes("오류")) return "status-error";
  if (text.includes("정상")) return "status-normal";
  if (text.includes("완료")) return "status-complete";
  if (text.includes("검수중")) return "status-working";
  if (text.includes("보류")) return "status-hold";
  if (text.includes("미검수")) return "status-unchecked";
  return "status-default";
}

function getReflectClass(status) {
  const text = String(status ?? "");
  if (text.includes("반영완료")) return "reflect-done";
  if (text.includes("미반영")) return "reflect-pending";
  return "reflect-default";
}

function splitErrorTypes(value) {
  const text = String(value ?? "").trim();
  if (!text || text === "-" || text === "없음") return [];

  return text
    .split(/[,|·\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeErrorTypes(types) {
  const rawTypes = (types || [])
    .map((item) => String(item || "").trim())
    .filter(Boolean);

  const hasBrokenExpressionRendering =
    rawTypes.includes("표현") && rawTypes.includes("렌더링 오류");

  const result = [];

  for (const type of rawTypes) {
    if (hasBrokenExpressionRendering && (type === "표현" || type === "렌더링 오류")) {
      if (!result.includes("표현/렌더링 오류")) {
        result.push("표현/렌더링 오류");
      }
      continue;
    }

    if (type === "표현" || type === "렌더링 오류") {
      if (!result.includes("표현/렌더링 오류")) {
        result.push("표현/렌더링 오류");
      }
      continue;
    }

    if (type === "긴 해설 수동 검토 필요") {
      result.push(type);
      continue;
    }

    if (type === "형식 오류" || LEGACY_FORMAT_ERROR_TYPES.includes(type)) {
      result.push("형식 오류");
      continue;
    }

    result.push(type);
  }

  return Array.from(new Set(result));
}

function toDisplayList(value, fallback = "-") {
  if (value === undefined || value === null) return fallback;

  if (Array.isArray(value)) {
    const text = value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    return text || fallback;
  }

  const text = String(value).trim();
  if (!text) return fallback;

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) {
      const parsedText = parsed.map((item) => String(item).trim()).filter(Boolean).join(", ");
      return parsedText || fallback;
    }
  } catch {
    // JSON 문자열이 아니면 그대로 사용합니다.
  }

  return text;
}

function mapQuestion(item, index) {
  const parsedRaw = parseMaybeJson(item?.raw_json);
  const merged = { ...parsedRaw, ...item };

  const id = pick(merged, ["id", "idx", "IDX", "question_id", "qid"], index + 1);
  const examUniqueNo = pick(
    merged,
    [
      "exam_unique_no",
      "examUniqueNo",
      "시험 고유 번호",
      "시험고유번호",
      "exam_code",
      "test_code",
      "chapter",
      "장",
    ],
    ""
  );
  const cdValue = pick(
    merged,
    [
      "cd_value",
      "cdValue",
      "CD값",
      "cd",
      "code",
      "section",
      "절",
      "learning_goal",
      "학습목표",
    ],
    ""
  );
  // 과목은 raw_json의 "subject/과목" 값으로 보완하지 않습니다.
  // 문제 엑셀의 subject/과목에는 강좌명이나 1과목/2과목 같은 값이 들어갈 수 있어서,
  // 백엔드가 CD 매핑으로 만든 subject_name만 화면에 표시합니다.
  const subjectName = pick(item, ["subject_name", "subjectName"], "");

  const courseName = pick(
    merged,
    [
      "course_name",
      "courseName",
      "강좌명",
      "course",
    ],
    ""
  );

  const setName = pick(
    merged,
    [
      "set_name",
      "setName",
      "세트명",
      "set",
    ],
    ""
  );

  const subtypeName = pick(
    merged,
    [
      "subtype_name",
      "subtypeName",
      "하위유형",
      "sub_title",
      "subTitle",
      "subtype",
    ],
    ""
  );

  return {
    rowKey: `${id}-${index}`,
    id: toText(id),
    courseName: toText(courseName, ""),
    setName: toText(setName, ""),
    examUniqueNo: toText(examUniqueNo, ""),
    subjectName: toText(subjectName, ""),
    subtypeName: toText(subtypeName, ""),
    cdValue: toText(cdValue, ""),
    uploadFile: toText(pick(item, ["upload_file", "uploaded_file", "uploadFile", "file_name", "filename", "source_file", "업로드파일", "업로드 파일"], ""), ""),
    chapter: toText(pick(item, ["chapter", "chapter_name", "chapterName"], ""), ""),
    section: toText(pick(item, ["section", "section_name", "sectionName"], ""), ""),
    learningGoal: toText(pick(item, ["learning_goal", "learningGoal"], ""), ""),
    number: toText(pick(merged, ["number", "question_no", "q_no", "no", "번호", "문제번호", "문제 번호"]), "-"),
    question: toText(pick(merged, ["question", "question_text", "content", "stem", "title", "문제"]), "-"),
    viewText: toText(pick(merged, ["view_text", "view", "보기", "보기텍스트"], ""), ""),
    answer: toText(pick(merged, ["answer", "정답"], ""), ""),
    reviewStatus: toText(pick(merged, ["review_status", "status", "검수상태"]), "미검수"),
    statusMemo: toText(pick(merged, ["status_memo", "review_memo", "status_detail", "result_detail"], ""), ""),
    errorType: toText(pick(merged, ["error_type", "issue_type", "errorType", "오류유형"]), "-"),
    reason: toText(pick(merged, ["reason", "etc_reason", "other_reason", "기타사유", "오류사유"], "-"), "-"),
    suggestion: toText(pick(merged, ["suggestion", "review_suggestion", "수정제안", "수정 제안"], ""), ""),
    reviewer: toText(pick(merged, ["reviewer", "inspector", "검수자"]), "admin"),
    reviewedAt: toText(pick(merged, ["reviewed_at", "review_date", "checked_at", "검수일"]), "-"),
    reflectStatus: toText(pick(merged, ["reflect_status", "reflection_status", "apply_status", "반영상태"]), "미반영"),
    reviewCheckLabels: parseLabelList(pick(merged, ["review_check_labels", "reviewCheckLabels", "검수항목"], "")),
    reviewScopeSummary: toText(pick(merged, ["review_scope_summary", "reviewScopeSummary", "검수범위"], ""), ""),
    reviewCheckHistory: parseJsonArray(pick(merged, ["review_check_history", "reviewCheckHistory"], "")),
    raw: merged,
  };
}

function App() {
  const [pageMode, setPageMode] = useState("review");
  const [questions, setQuestions] = useState([]);
  const [targetMaps, setTargetMaps] = useState([]);
  const [reviewQuestion, setReviewQuestion] = useState(null);
  const [editForm, setEditForm] = useState(null);
  const questionFileInputRef = useRef(null);
  const cdMetaFileInputRef = useRef(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [currentPage, setCurrentPage] = useState(1);
  const [reviewCurrentPage, setReviewCurrentPage] = useState(1);
  const [reviewTarget, setReviewTarget] = useState(DEFAULT_REVIEW_TARGET);
  const [targetMapForm, setTargetMapForm] = useState(DEFAULT_TARGET_MAP_FORM);
  const [targetMapSearch, setTargetMapSearch] = useState("");
  const [targetMapSaving, setTargetMapSaving] = useState(false);
  const [targetMapPage, setTargetMapPage] = useState(1);
  const [reviewRunning, setReviewRunning] = useState(false);
  const [cancelingReview, setCancelingReview] = useState(false);
  const [reviewJobInfo, setReviewJobInfo] = useState(null);
  const [reviewChecks, setReviewChecks] = useState(() => cloneReviewChecks(DEFAULT_REVIEW_CHECKS));
  const [activeReviewPreset, setActiveReviewPreset] = useState("all");
  const [selectedRows, setSelectedRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");

  const fetchQuestions = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const res = await fetch(`${API_BASE}/api/questions`);
      if (!res.ok) throw new Error(`API 요청 실패: ${res.status}`);
      const json = await res.json();
      const items = Array.isArray(json) ? json : json.items || json.data || json.results || [];
      setQuestions(items);
      setSelectedRows([]);
      setReviewTarget((prev) => ({
        ...prev,
        targetScope: "filtered",
      }));
    } catch (error) {
      console.error(error);
      setLoadError("문제 데이터를 불러오지 못했습니다. backend 서버 실행 여부를 확인하세요.");
      setQuestions([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchTargetMaps = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/target-maps`);
      if (!res.ok) throw new Error(`매핑 DB 요청 실패: ${res.status}`);
      const json = await res.json();
      const items = Array.isArray(json) ? json : json.items || [];
      setTargetMaps(items);
    } catch (error) {
      console.error(error);
      setTargetMaps([]);
    }
  };

  useEffect(() => {
    fetchQuestions();
    fetchTargetMaps();
  }, []);

  const toggleReviewCheck = (group, key) => {
    setActiveReviewPreset("");

    setReviewChecks((prev) => ({
      ...prev,
      [group]: {
        ...prev[group],
        [key]: !prev[group][key],
      },
    }));
  };

  const applyReviewCheckPreset = (presetKey) => {
    const preset = REVIEW_CHECK_PRESETS[presetKey];
    if (!preset) return;

    setReviewChecks(cloneReviewChecks(preset.checks));
    setActiveReviewPreset(presetKey);
  };

  const selectedReviewCheckCount = countSelectedReviewChecks(reviewChecks);
  const selectedReviewCheckLabels = getSelectedReviewCheckLabels(reviewChecks);
  const selectedReviewCheckText = formatSelectedReviewCheckLabels(selectedReviewCheckLabels);

  const handleQuestionExcelUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const courseName = window.prompt("이 엑셀 파일의 강좌명을 입력해 주세요.");

    if (!courseName || !courseName.trim()) {
      alert("강좌명을 입력해야 엑셀을 업로드할 수 있습니다.");
      event.target.value = "";
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("course_name", courseName.trim());

    try {
      const res = await fetch(`${API_BASE}/api/questions/upload-excel`, {
        method: "POST",
        body: formData,
      });

      const text = await res.text();
      let result = {};

      try {
        result = text ? JSON.parse(text) : {};
      } catch {
        result = { raw: text };
      }

      if (!res.ok) {
        throw new Error(result.detail || result.message || text || "엑셀 업로드 실패");
      }

      await fetchQuestions();
      await fetchTargetMaps();

      const questionCount = result.questions_upserted ?? 0;
      const mapCount = result.target_maps_upserted ?? 0;
      const skippedSheets = result.skipped_sheets || [];

      if (questionCount === 0 && mapCount === 0) {
        alert(
          [
            "엑셀 파일은 읽었지만 DB에 저장된 데이터가 없습니다.",
            "",
            `문제 저장: ${questionCount}건`,
            `매핑 저장: ${mapCount}건`,
            `건너뛴 시트: ${skippedSheets.length ? skippedSheets.join(", ") : "없음"}`,
            "",
            "엑셀 시트의 컬럼명이 코드에서 인식하는 이름과 맞는지 확인해 주세요.",
          ].join("\n")
        );
        return;
      }

      alert(
        [
          "엑셀 데이터를 DB에 업로드했습니다.",
          "",
          `문제 저장/갱신: ${questionCount}건`,
          `검수대상매핑 저장/갱신: ${mapCount}건`,
          skippedSheets.length ? `건너뛴 시트: ${skippedSheets.join(", ")}` : "",
        ].filter(Boolean).join("\n")
      );
    } catch (error) {
      console.error(error);
      alert(`엑셀 업로드 중 오류가 발생했습니다.\n${error.message}`);
    } finally {
      event.target.value = "";
    }
  };

  const handleCdMetaExcelUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/cd-meta/upload-excel`, {
        method: "POST",
        body: formData,
      });

      const text = await res.text();
      let result = {};

      try {
        result = text ? JSON.parse(text) : {};
      } catch {
        result = { raw: text };
      }

      if (!res.ok) {
        throw new Error(result.detail || result.message || text || "CD 매핑 엑셀 업로드 실패");
      }

      await fetchQuestions();

      const cdMetaCount = result.cd_meta_upserted ?? 0;
      const updatedQuestionCount = result.questions_updated ?? 0;
      const skippedSheets = result.skipped_sheets || [];

      if (cdMetaCount === 0) {
        alert(
          [
            "CD 매핑 엑셀 파일은 읽었지만 저장된 데이터가 없습니다.",
            "",
            `CD 매핑 저장/갱신: ${cdMetaCount}건`,
            `기존 문제 반영: ${updatedQuestionCount}건`,
            `건너뛴 시트: ${skippedSheets.length ? skippedSheets.join(", ") : "없음"}`,
            "",
            "엑셀에 CD값, 과목, 장, 절, 학습목표 컬럼이 있는지 확인해 주세요.",
          ].join("\n")
        );
        return;
      }

      alert(
        [
          "CD 매핑 엑셀 데이터를 DB에 업로드했습니다.",
          "",
          `CD 매핑 저장/갱신: ${cdMetaCount}건`,
          `기존 문제 반영: ${updatedQuestionCount}건`,
          skippedSheets.length ? `건너뛴 시트: ${skippedSheets.join(", ")}` : "",
        ].filter(Boolean).join("\n")
      );
    } catch (error) {
      console.error(error);
      alert(`CD 매핑 엑셀 업로드 중 오류가 발생했습니다.\n${error.message}`);
    } finally {
      event.target.value = "";
    }
  };

  const rows = useMemo(() => {
    const subjectByExamUniqueNo = new Map();
    const courseByExamUniqueNo = new Map();
    const setByExamUniqueNo = new Map();
    const subtypeByExamUniqueNo = new Map();

    targetMaps.forEach((item) => {
      const examUniqueNo = String(item.exam_unique_no || "").trim();
      const subjectName = String(item.subject_name || "").trim();
      const courseName = String(item.course_name || "").trim();
      const setName = String(item.set_name || "").trim();
      const subtypeName = String(item.subtype_name || "").trim();

      if (examUniqueNo && subjectName && !subjectByExamUniqueNo.has(examUniqueNo)) {
        subjectByExamUniqueNo.set(examUniqueNo, subjectName);
      }

      if (examUniqueNo && courseName && !courseByExamUniqueNo.has(examUniqueNo)) {
        courseByExamUniqueNo.set(examUniqueNo, courseName);
      }

      if (examUniqueNo && setName && !setByExamUniqueNo.has(examUniqueNo)) {
        setByExamUniqueNo.set(examUniqueNo, setName);
      }

      if (examUniqueNo && subtypeName && !subtypeByExamUniqueNo.has(examUniqueNo)) {
        subtypeByExamUniqueNo.set(examUniqueNo, subtypeName);
      }
    });

    return questions
      .map((item, index) => {
        const row = mapQuestion(item, index);
        const examUniqueNo = String(row.examUniqueNo || "").trim();

        return {
          ...row,
          courseName:
            row.courseName ||
            courseByExamUniqueNo.get(examUniqueNo) ||
            "",
          setName:
            row.setName ||
            setByExamUniqueNo.get(examUniqueNo) ||
            "",
          subjectName:
            row.subjectName ||
            subjectByExamUniqueNo.get(examUniqueNo) ||
            "",
          subtypeName:
            row.subtypeName ||
            subtypeByExamUniqueNo.get(examUniqueNo) ||
            "",
        };
      })
      .sort(compareQuestionRows);
  }, [questions, targetMaps]);
  
  function compareNatural(a, b) {
    return String(a ?? "").localeCompare(String(b ?? ""), "ko-KR", {
      numeric: true,
      sensitivity: "base",
    });
  }

  function compareQuestionRows(a, b) {
    const examCompare = compareNatural(a.examUniqueNo, b.examUniqueNo);
    if (examCompare !== 0) return examCompare;

    const aNo = toNumber(a.number);
    const bNo = toNumber(b.number);

    if (aNo !== null && bNo !== null && aNo !== bNo) {
      return aNo - bNo;
    }

    const numberCompare = compareNatural(a.number, b.number);
    if (numberCompare !== 0) return numberCompare;

    const aId = toNumber(a.id);
    const bId = toNumber(b.id);

    if (aId !== null && bId !== null && aId !== bId) {
      return aId - bId;
    }

    return compareNatural(a.id, b.id);
  }

  const options = useMemo(() => ({
    courseName: makeCourseOptions(rows),
    setName: makeTextOptions(rows, "setName"),
    examUniqueNo: makeOptions(rows, "examUniqueNo"),
    subjectName: makeSubjectOptions(rows),
    subtypeName: makeTextOptions(rows, "subtypeName"),
    cdValue: makeOptions(rows, "cdValue", true),
    reviewStatus: makeOptions(rows, "reviewStatus"),
    errorType: makeErrorTypeOptions(rows),
    reflectStatus: makeOptions(rows, "reflectStatus"),
  }), [rows]);

  const filteredRows = useMemo(() => {
    const keyword = lower(filters.search);

    return rows.filter((row) => {
      const targetText = lower([
        row.id,
        row.courseName,
        row.setName,
        row.examUniqueNo,
        String(row.subjectName || "").trim() || "미지정",
        row.subtypeName,
        row.cdValue,
        row.uploadFile,
        row.chapter,
        row.section,
        row.learningGoal,
        row.number,
        row.question,
        row.viewText,
        row.answer,
        row.reviewStatus,
        row.reviewScopeSummary,
        formatSelectedReviewCheckLabels(row.reviewCheckLabels || []),
        row.errorType,
        row.reason,
        row.reviewer,
        row.reviewedAt,
        row.reflectStatus,
      ].join(" "));

      const matchExamUniqueNo = filters.examUniqueNo === "전체" || row.examUniqueNo === filters.examUniqueNo;
      const rowSubjectName = String(row.subjectName || "").trim() || "미지정";
      const matchSubjectName = filters.subjectName === "전체" || rowSubjectName === filters.subjectName;
      const rowCourseName = String(row.courseName || "").trim() || "미지정";
      const matchCourseName = filters.courseName === "전체" || rowCourseName === filters.courseName;
      const rowSetName = String(row.setName || "").trim() || "미지정";
      const matchSetName = filters.setName === "전체" || rowSetName === filters.setName;
      const rowSubtypeName = String(row.subtypeName || "").trim() || "미지정";
      const matchSubtypeName = filters.subtypeName === "전체" || rowSubtypeName === filters.subtypeName;
      const matchCdValue = filters.cdValue === "전체" || row.cdValue === filters.cdValue;
      const matchReviewStatus = filters.reviewStatus === "전체" || row.reviewStatus === filters.reviewStatus;

      const rowErrorTypes = normalizeErrorTypes(splitErrorTypes(row.errorType));

      const matchErrorType =
        filters.errorType === "전체" ||
        rowErrorTypes.includes(filters.errorType);

      const matchReflectStatus = filters.reflectStatus === "전체" || row.reflectStatus === filters.reflectStatus;
      const matchKeyword = !keyword || targetText.includes(keyword);

      return matchCourseName &&
        matchSetName &&
        matchExamUniqueNo &&
        matchSubjectName &&
        matchSubtypeName &&
        matchCdValue &&
        matchReviewStatus &&
        matchErrorType &&
        matchReflectStatus &&
        matchKeyword;
    });
  }, [rows, filters]);

  const pageSizeNumber = Number(filters.pageSize) || 20;

  const totalPages = useMemo(() => {
    return Math.max(1, Math.ceil(filteredRows.length / pageSizeNumber));
  }, [filteredRows.length, pageSizeNumber]);

  const pageRows = useMemo(() => {
    const startIndex = (currentPage - 1) * pageSizeNumber;
    const endIndex = startIndex + pageSizeNumber;
    return filteredRows.slice(startIndex, endIndex);
  }, [filteredRows, currentPage, pageSizeNumber]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const stats = useMemo(() => ({
    total: rows.length,
    unchecked: rows.filter((row) => row.reviewStatus.includes("미검수")).length,
    working: rows.filter((row) => row.reviewStatus.includes("검수중")).length,
    normal: rows.filter((row) => row.reviewStatus.includes("정상")).length,
    error: rows.filter((row) => row.reviewStatus.includes("오류")).length,
    hold: rows.filter((row) => row.reviewStatus.includes("보류")).length,
    complete: rows.filter((row) => row.reviewStatus.includes("완료")).length,
    reflected: rows.filter((row) => row.reflectStatus.includes("반영완료")).length,
  }), [rows]);

  const handleFilterChange = (event) => {
    const { name, value } = event.target;
    setFilters((prev) => ({ ...prev, [name]: value }));
    setCurrentPage(1);
  };

  const resetFilters = () => {
    setFilters(DEFAULT_FILTERS);
    setSelectedRows([]);
    setCurrentPage(1);
  };

  const toggleAll = (checked, visibleRows) => {
    setReviewCurrentPage(1);

    if (checked) {
      const next = visibleRows.map((row) => row.rowKey);
      setSelectedRows(next);
      setReviewTarget((prev) => ({
        ...prev,
        targetScope: next.length > 0 ? "selected" : "filtered",
      }));
      return;
    }

    setSelectedRows([]);
    setReviewTarget((prev) => ({
      ...prev,
      targetScope: "filtered",
    }));
  };

  const toggleRow = (rowKey) => {
    setReviewCurrentPage(1);

    setSelectedRows((prev) => {
      const next = prev.includes(rowKey)
        ? prev.filter((key) => key !== rowKey)
        : [...prev, rowKey];

      setReviewTarget((targetPrev) => ({
        ...targetPrev,
        targetScope: next.length > 0 ? "selected" : "filtered",
      }));

      return next;
    });
  };

  const handleBulkAction = async (action) => {
    const selectedItems = rows.filter((row) => selectedRows.includes(row.rowKey));

    if (selectedItems.length === 0) {
      alert("선택된 문제가 없습니다.");
      return;
    }

    const confirmMessage =
      action === "정상"
        ? `${selectedItems.length}개 문제를 정상 처리하시겠습니까?\n오류유형, Reason, Suggestion은 비워집니다.`
        : `${selectedItems.length}개 문제를 보류 처리하시겠습니까?`;

    if (!window.confirm(confirmMessage)) {
      return;
    }

    try {
      if (action === "정상") {
        await Promise.all(
          selectedItems.map((row) =>
            fetch(`${API_BASE}/api/questions/${row.id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                review_status: "정상",
                error_type: "",
                reason: "",
                suggestion: "",
                reviewer: "admin",
                reflect_status: "미반영",
              }),
            }).then((res) => {
              if (!res.ok) {
                throw new Error(`정상 처리 실패: ID ${row.id}`);
              }
              return res.json();
            })
          )
        );
      }

      if (action === "보류") {
        await Promise.all(
          selectedItems.map((row) =>
            fetch(`${API_BASE}/api/questions/${row.id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                review_status: "보류",
                reviewer: "admin",
                reflect_status: "미반영",
              }),
            }).then((res) => {
              if (!res.ok) {
                throw new Error(`보류 처리 실패: ID ${row.id}`);
              }
              return res.json();
            })
          )
        );
      }

      await fetchQuestions();
      setSelectedRows([]);

      alert(`${selectedItems.length}개 문제가 ${action} 처리되었습니다.`);
    } catch (error) {
      console.error(error);
      alert(error.message || "선택 처리 중 오류가 발생했습니다.");
    }
  };

  const handleReviewTargetChange = (event) => {
    const { name, value, type, checked } = event.target;
    setReviewCurrentPage(1);

    if (name === "courseName") {
      setReviewTarget((prev) => ({
        ...prev,
        courseName: value,
        setName: "",
        subjectName: "",
        subtypeName: "",
        targetMapId: "",
        targetMapIds: [],
        examUniqueNo: "",
        cdValue: "",
      }));
      return;
    }

    if (name === "setName") {
      setReviewTarget((prev) => ({
        ...prev,
        setName: value,
        subjectName: "",
        subtypeName: "",
        targetMapId: "",
        targetMapIds: [],
        examUniqueNo: "",
        cdValue: "",
      }));
      return;
    }

    if (name === "subjectName") {
      setReviewTarget((prev) => ({
        ...prev,
        subjectName: value,
        subtypeName: "",
        targetMapId: "",
        targetMapIds: [],
        examUniqueNo: "",
        cdValue: "",
      }));
      return;
    }

    if (name === "subtypeName") {
      setReviewTarget((prev) => ({
        ...prev,
        subtypeName: value,
        targetMapId: "",
        targetMapIds: [],
        examUniqueNo: "",
        cdValue: "",
      }));
      return;
    }

    setReviewTarget((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }));
  };


const handleTargetMapFormChange = (event) => {
  const { name, value } = event.target;
  setTargetMapForm((prev) => ({ ...prev, [name]: value }));
};

const resetTargetMapForm = () => {
  setTargetMapForm(DEFAULT_TARGET_MAP_FORM);
};

const editTargetMap = (item) => {
  setTargetMapForm({
    id: String(item.id || ""),
    courseName: item.course_name || "",
    setName: item.set_name || "",
    subjectName: item.subject_name || "",
    subtypeName: item.subtype_name || "",
    examUniqueNo: item.exam_unique_no || "",
  });

  setPageMode("map");
};

const saveTargetMap = async () => {
  const courseName = targetMapForm.courseName.trim();
  const setName = targetMapForm.setName.trim();
  const subjectName = targetMapForm.subjectName.trim();
  const subtypeName = targetMapForm.subtypeName.trim();
  const examUniqueNo = targetMapForm.examUniqueNo.trim();

  if (!courseName) {
    alert("강좌명을 입력해 주세요.");
    return;
  }

  if (!setName) {
    alert("세트명을 입력해 주세요.");
    return;
  }

  if (!subjectName) {
    alert("과목명을 입력해 주세요.");
    return;
  }

  if (!examUniqueNo) {
    alert("시험 고유 번호를 입력해 주세요.");
    return;
  }

  const payload = {
    display_name: [courseName, setName, subjectName, subtypeName].filter(Boolean).join(" / "),
    course_name: courseName,
    set_name: setName,
    subject_name: subjectName,
    subtype_name: subtypeName,
    exam_unique_no: examUniqueNo,

    subject_mode: "specific",
    subject_start_index: 1,
    subject_end_index: 1,
  };

  const isEdit = Boolean(targetMapForm.id);
  const url = isEdit
    ? `${API_BASE}/api/target-maps/${targetMapForm.id}`
    : `${API_BASE}/api/target-maps`;

  try {
    setTargetMapSaving(true);

    const res = await fetch(url, {
      method: isEdit ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const text = await res.text();
    let result = {};

    try {
      result = text ? JSON.parse(text) : {};
    } catch {
      result = { raw: text };
    }

    if (!res.ok) {
      throw new Error(result.detail || result.message || text || "매핑 저장 실패");
    }

    await fetchTargetMaps();

    if (isEdit && String(reviewTarget.targetMapId) === String(targetMapForm.id)) {
      setReviewTarget((prev) => ({
        ...prev,
        courseName: payload.course_name,
        setName: payload.set_name,
        subjectName: payload.subject_name,
        subtypeName: payload.subtype_name,
        subjectMode: "specific",
        subjectStartIndex: "1",
        subjectEndIndex: "1",
        examUniqueNo: payload.exam_unique_no,
        cdValue: "",
      }));
    }

    resetTargetMapForm();
    alert(isEdit ? "검수 대상 매핑을 수정했습니다." : "검수 대상 매핑을 등록했습니다.");
  } catch (error) {
    console.error(error);
    alert(`매핑 저장 중 오류가 발생했습니다.\n${error.message}`);
  } finally {
    setTargetMapSaving(false);
  }
};

const deleteTargetMap = async (item) => {
  const ok = window.confirm(`'${item.display_name || item.set_name || item.exam_unique_no}' 매핑을 삭제할까요?`);
  if (!ok) return;

  try {
    const res = await fetch(`${API_BASE}/api/target-maps/${item.id}`, {
      method: "DELETE",
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "매핑 삭제 실패");
    }

    await fetchTargetMaps();
    resetTargetMapForm();
    alert("검수 대상 매핑을 삭제했습니다.");
  } catch (error) {
    console.error(error);
    alert(`매핑 삭제 중 오류가 발생했습니다.\n${error.message}`);
  }
};

const targetCourseOptions = useMemo(() => {
  return makeTargetMapOptions(targetMaps, "course_name");
}, [targetMaps]);

const targetSetOptions = useMemo(() => {
  return makeTargetMapOptions(
    targetMaps.filter((item) => {
      if (!reviewTarget.courseName) return false;

      return String(item.course_name || "").trim() === String(reviewTarget.courseName || "").trim();
    }),
    "set_name"
  );
}, [targetMaps, reviewTarget.courseName]);

const targetSubjectOptions = useMemo(() => {
  return makeTargetMapOptions(
    targetMaps.filter((item) => {
      if (!reviewTarget.courseName) return false;

      if (String(item.course_name || "").trim() !== String(reviewTarget.courseName || "").trim()) {
        return false;
      }

      if (
        reviewTarget.setName &&
        String(item.set_name || "").trim() !== String(reviewTarget.setName || "").trim()
      ) {
        return false;
      }

      return true;
    }),
    "subject_name"
  );
}, [targetMaps, reviewTarget.courseName, reviewTarget.setName]);

const targetSubtypeOptions = useMemo(() => {
  return makeTargetMapOptions(
    targetMaps.filter((item) => {
      if (!reviewTarget.courseName) return false;

      if (String(item.course_name || "").trim() !== String(reviewTarget.courseName || "").trim()) {
        return false;
      }

      if (
        reviewTarget.setName &&
        String(item.set_name || "").trim() !== String(reviewTarget.setName || "").trim()
      ) {
        return false;
      }

      if (
        reviewTarget.subjectName &&
        String(item.subject_name || "").trim() !== String(reviewTarget.subjectName || "").trim()
      ) {
        return false;
      }

      return true;
    }),
    "subtype_name"
  );
}, [targetMaps, reviewTarget.courseName, reviewTarget.setName, reviewTarget.subjectName]);

  const selectedTargetMaps = useMemo(() => {
    const courseName = String(reviewTarget.courseName || "").trim();
    const setName = String(reviewTarget.setName || "").trim();
    const subjectName = String(reviewTarget.subjectName || "").trim();
    const subtypeName = String(reviewTarget.subtypeName || "").trim();

    if (!courseName) {
      return [];
    }

    return targetMaps.filter((item) => {
      if (String(item.course_name || "").trim() !== courseName) return false;
      if (setName && String(item.set_name || "").trim() !== setName) return false;
      if (subjectName && String(item.subject_name || "").trim() !== subjectName) return false;
      if (subtypeName && String(item.subtype_name || "").trim() !== subtypeName) return false;
      return true;
    });
  }, [
    targetMaps,
    reviewTarget.courseName,
    reviewTarget.setName,
    reviewTarget.subjectName,
    reviewTarget.subtypeName,
  ]);

  const getBaseReviewRows = (mode = reviewTarget.targetScope) => {
    return mode === "selected"
      ? rows.filter((row) => selectedRows.includes(row.rowKey))
      : rows;
  };

  const isInReviewQuestionRange = (row) => {
    const range = parseReviewRange(reviewTarget.questionRange);
    if (!range) return true;

    const qno = toNumber(row.number);
    if (qno === null) return false;

    return qno >= range.start && qno <= range.end;
  };

  const getReviewRowsForMap = (targetMap, mode = reviewTarget.targetScope) => {
    const baseRows = getBaseReviewRows(mode);
    const examUniqueNo = String(targetMap?.exam_unique_no || "").trim();

    if (!examUniqueNo) {
      return [];
    }

    return baseRows.filter((row) => {
      if (!isInReviewQuestionRange(row)) return false;
      return String(row.examUniqueNo || "").trim() === examUniqueNo;
    });
  };

  const getReviewRows = (mode = reviewTarget.targetScope) => {
    const baseRows = getBaseReviewRows(mode);

    // 강좌명을 아직 선택하지 않았으면 초기 화면에서는 전체 문제 표시
    if (!reviewTarget.courseName) {
      return baseRows.filter((row) => isInReviewQuestionRange(row));
    }

    // 강좌명은 선택했는데 매칭 매핑이 없으면 빈 목록
    if (selectedTargetMaps.length === 0) {
      return [];
    }

    const selectedExamNos = new Set(
      selectedTargetMaps
        .map((item) => String(item.exam_unique_no || "").trim())
        .filter(Boolean)
    );

    return baseRows.filter((row) => {
      if (!isInReviewQuestionRange(row)) return false;
      return selectedExamNos.has(String(row.examUniqueNo || "").trim());
    });
  };

  const reviewTargetRows = getReviewRows("filtered");
  const REVIEW_TARGET_PAGE_SIZE = 20;

  const reviewTargetTotalPages = useMemo(() => {
    return Math.max(1, Math.ceil(reviewTargetRows.length / REVIEW_TARGET_PAGE_SIZE));
  }, [reviewTargetRows.length]);

  const reviewTargetPageRows = useMemo(() => {
    const startIndex = (reviewCurrentPage - 1) * REVIEW_TARGET_PAGE_SIZE;
    const endIndex = startIndex + REVIEW_TARGET_PAGE_SIZE;
    return reviewTargetRows.slice(startIndex, endIndex);
  }, [reviewTargetRows, reviewCurrentPage]);

  useEffect(() => {
    if (reviewCurrentPage > reviewTargetTotalPages) {
      setReviewCurrentPage(reviewTargetTotalPages);
    }
  }, [reviewCurrentPage, reviewTargetTotalPages]);

  const buildReviewPayloadForMap = (targetMap, targetRows) => {
    const numbers = targetRows
      .map((row) => toNumber(row.number))
      .filter((value) => value !== null)
      .sort((a, b) => a - b);

    if (numbers.length === 0) {
      throw new Error("검수할 문제 번호가 없습니다.");
    }

    const manualQuestionRange = reviewTarget.questionRange.trim();
    const questionRange = manualQuestionRange || "all";
    const defaultExamUniqueNo = String(targetMap.exam_unique_no || "").trim();

    if (!defaultExamUniqueNo) {
      throw new Error("시험 고유 번호가 없는 매핑입니다.");
    }

    return {
      course_name: String(targetMap.course_name || "").trim(),
      set_name: String(targetMap.set_name || "").trim(),
      subject_name: String(targetMap.subject_name || "").trim() || undefined,
      subtype_name: String(targetMap.subtype_name || "").trim() || undefined,
      exam_unique_no: defaultExamUniqueNo,
      subject_mode: targetMap.subject_mode || "specific",
      subject_start_index: Number(targetMap.subject_start_index) || 1,
      subject_end_index: Number(targetMap.subject_end_index) || 1,
      question_range: questionRange,
      question_numbers: numbers,
      questions: targetRows.map((row) => ({
        site_question_id: toNumber(row.id),
        exam_unique_no: defaultExamUniqueNo,
        question_no: toNumber(row.number),
      })),
      options: {
        headless: true,
        write_excel: true,
        include_raw_data: true,
      },
    };
  };

  const buildCombinedReviewPayload = (jobTargets) => {
    const targets = jobTargets.map(({ targetMap, rowsForMap }) =>
      buildReviewPayloadForMap(targetMap, rowsForMap)
    );

    const configs = targets.map(({ options, ...config }) => config);

    return {
      course_name: String(reviewTarget.courseName || "").trim(),
      review_mode: "batch",
      targets: configs,
      review_checks: normalizeReviewChecksForPayload(reviewChecks),
      checks: normalizeReviewChecksForPayload(reviewChecks),
      options: {
        headless: true,
        write_excel: true,
        include_raw_data: true,
        review_checks: normalizeReviewChecksForPayload(reviewChecks),
      },
    };
  };

  const filterRowsByReviewStatus = (targetRows, statusFilter) => {
    if (statusFilter === "uncheckedOrError") {
      return targetRows.filter((row) =>
        (row.reviewStatus || "").includes("미검수") ||
        (row.reviewStatus || "").includes("오류")
      );
    }

    if (statusFilter === "errorOnly") {
      return targetRows.filter((row) => (row.reviewStatus || "").includes("오류"));
    }

    if (statusFilter === "holdOnly") {
      return targetRows.filter((row) => (row.reviewStatus || "").includes("보류"));
    }

    if (statusFilter === "normalOnly") {
      return targetRows.filter((row) => (row.reviewStatus || "").includes("정상"));
    }

    return targetRows;
  };

  const applyAiReviewResult = async (result, reviewMeta = {}) => {
    const items = result?.items || [];
    const currentRowsById = new Map(rows.map((row) => [String(row.id), row]));
    const runLabels = uniqueLabels(reviewMeta.labels || selectedReviewCheckLabels);
    const runSummary = reviewMeta.summary || makeReviewRunTitle(runLabels);
    const runAt = new Date().toISOString();

    for (const item of items) {
      const siteQuestionId = item.site_question_id;
      if (!siteQuestionId) continue;

      const currentRow = currentRowsById.get(String(siteQuestionId));
      const currentRaw = currentRow?.raw || {};
      const previousErrorTypes = splitErrorTypes(
        currentRow?.errorType && currentRow.errorType !== "-"
          ? currentRow.errorType
          : getValue(currentRaw, ["error_type", "issue_type", "errorType", "오류유형"], "")
      );

      const previousReason = currentRow?.reason && currentRow.reason !== "-"
        ? currentRow.reason
        : getValue(currentRaw, ["reason", "기타사유", "오류사유"], "");

      const previousSuggestion = currentRow?.suggestion || getValue(currentRaw, ["suggestion", "수정제안", "수정 제안"], "");
      const previousLabels = uniqueLabels(currentRow?.reviewCheckLabels || parseLabelList(currentRaw.review_check_labels));
      const previousHistory = parseJsonArray(currentRaw.review_check_history);

      const issues = item.issues || [];
      const hasIssue = item.review_status === "issue_found" || issues.length > 0;
      const newErrorTypes = hasIssue
        ? normalizeErrorTypes(issues.map((issue) => issue.issue_type)).filter(Boolean)
        : [];

      const errorTypeList = normalizeErrorTypes([...previousErrorTypes, ...newErrorTypes]);
      const reviewCheckLabels = uniqueLabels([...previousLabels, ...runLabels]);
      const reviewScopeSummary = makeReviewScopeSummary(reviewCheckLabels);

      const issueReason = hasIssue
        ? issues
            .map((issue) => issue.reason || "")
            .filter(Boolean)
            .join("\n\n")
        : "";

      const issueSuggestion = hasIssue
        ? issues
            .map((issue) => issue.suggestion || "")
            .filter(Boolean)
            .join("\n\n")
        : "";

      const nextReason = hasIssue
        ? mergeTextBlock(previousReason, runSummary, issueReason)
        : previousReason;

      const nextSuggestion = hasIssue
        ? mergeTextBlock(previousSuggestion, runSummary, issueSuggestion)
        : previousSuggestion;

      const historyEntry = {
        at: runAt,
        summary: runSummary,
        labels: runLabels,
        result: hasIssue ? "오류있음" : "정상",
        issue_count: issues.length,
        issues: formatIssuesForHistory(issues, runAt, runSummary),
      };

      const reviewCheckHistory = [...previousHistory, historyEntry].slice(-50);
      const hasAnyIssue = errorTypeList.length > 0 || String(nextReason || "").trim() !== "";

      const res = await fetch(`${API_BASE}/api/questions/${siteQuestionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_status: hasAnyIssue ? "오류있음" : "정상",
          error_type: errorTypeList.join(", "),
          reason: nextReason,
          suggestion: nextSuggestion,
          review_check_labels: reviewCheckLabels.join(", "),
          review_scope_summary: reviewScopeSummary,
          review_check_history: JSON.stringify(reviewCheckHistory),
          reviewer: "AI검수",
          reflect_status: "미반영",
        }),
      });
      if (!res.ok) throw new Error(`IDX ${siteQuestionId} 결과 저장 실패`);
    }
  };

  const waitForReviewResult = async (baseUrl, jobId) => {
    while (true) {
      const statusRes = await fetch(`${baseUrl}/review-jobs/${jobId}`);

      if (!statusRes.ok) {
        throw new Error(`검수 상태 조회 실패: ${statusRes.status}`);
      }

      const statusJson = await statusRes.json();

      setReviewJobInfo((prev) => ({
        ...(prev || {}),
        ...statusJson,
        selected_review_check_count:
          prev?.selected_review_check_count ?? selectedReviewCheckCount,
        selected_review_check_labels:
          prev?.selected_review_check_labels?.length
            ? prev.selected_review_check_labels
            : selectedReviewCheckLabels,
      }));

      if (["completed", "partial_failed", "partial_canceled"].includes(statusJson.status)) {
        const resultRes = await fetch(`${baseUrl}/review-jobs/${jobId}/result`);

        if (!resultRes.ok) {
          if (statusJson.status === "completed") {
            throw new Error(`검수 결과 조회 실패: ${resultRes.status}`);
          }

          throw new Error(statusJson.error_message || "부분 검수 결과를 찾지 못했습니다.");
        }

        return await resultRes.json();
      }

      if (statusJson.status === "canceled") {
        throw new Error("검수 작업이 취소되었습니다. 저장된 부분 결과가 없습니다.");
      }

      if (statusJson.status === "failed") {
        throw new Error(statusJson.error_message || "검수 작업이 실패했습니다.");
      }

      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
  };

  const cancelCurrentReview = async () => {
    const jobId = reviewJobInfo?.job_id;

    if (!jobId) {
      alert("취소할 검수 작업이 없습니다.");
      return;
    }

    const ok = window.confirm("현재 진행 중인 검수 작업을 취소할까요?");
    if (!ok) return;

    const baseUrl = reviewTarget.reviewApiBase.replace(/\/$/, "");

    try {
      setCancelingReview(true);

      const res = await fetch(`${baseUrl}/review-jobs/${jobId}/cancel`, {
        method: "POST",
      });

      const text = await res.text();
      let result = {};

      try {
        result = text ? JSON.parse(text) : {};
      } catch {
        result = { raw: text };
      }

      if (!res.ok) {
        throw new Error(result.detail || result.message || text || "검수 취소 실패");
      }

      setReviewJobInfo((prev) => ({
        ...(prev || {}),
        status: "cancel_requested",
      }));

      alert("검수 취소를 요청했습니다. 현재 처리 중인 단계가 끝나면 중단됩니다.");
    } catch (error) {
      console.error(error);
      alert(`검수 취소 중 오류가 발생했습니다.\n${error.message}`);
    } finally {
      setCancelingReview(false);
    }
  };

  const runAiReview = async (mode = reviewTarget.targetScope, statusFilter = null) => {
    if (reviewRunning) return;

    const baseUrl = reviewTarget.reviewApiBase.replace(/\/$/, "");

    if (!String(reviewTarget.courseName || "").trim()) {
      alert("검수 실행 전에는 강좌명을 선택해 주세요.");
      return;
    }

    const mapsToReview = selectedTargetMaps;

    if (mapsToReview.length === 0) {
      alert("선택한 조건에 맞는 검수 대상 매핑이 없습니다. 매핑 관리 화면을 확인해 주세요.");
      return;
    }

    const jobTargets = mapsToReview
      .map((targetMap) => {
        const rowsForMap = filterRowsByReviewStatus(
          getReviewRowsForMap(targetMap, mode),
          statusFilter
        );

        return {
          targetMap,
          rowsForMap,
        };
      })
      .filter((item) => item.rowsForMap.length > 0);

    if (jobTargets.length === 0) {
      alert("검수할 문제가 없습니다. 선택한 매핑, 문제 범위, 체크 선택 상태를 확인해 주세요.");
      return;
    }

    const invalidMap = jobTargets.find(({ targetMap }) => {
      return !String(targetMap.course_name || "").trim() || !String(targetMap.exam_unique_no || "").trim();
    });

    if (invalidMap) {
      alert("선택된 매핑 중 강좌명 또는 시험 고유 번호가 없는 항목이 있습니다. 매핑 DB를 확인해 주세요.");
      return;
    }

    const totalQuestionCount = jobTargets.reduce((sum, item) => sum + item.rowsForMap.length, 0);

    if (selectedReviewCheckCount === 0) {
      alert("선택된 검수 항목이 없습니다. 최소 1개 이상의 검수 항목을 선택해 주세요.");
      return;
    }

    const proceed = window.confirm(
      `${jobTargets.length}개 매핑의 총 ${totalQuestionCount}개 문제를 AI 검수 API로 보낼까요?
선택된 검수 항목: ${selectedReviewCheckCount}개
${selectedReviewCheckLabels.map((label) => `- ${label}`).join("\n")}`
    );

    if (!proceed) return;

    setReviewRunning(true);
    setReviewJobInfo(null);

    let totalReviewed = 0;
    let totalIssues = 0;
    let totalMappingErrors = 0;

      try {
        const payload = buildCombinedReviewPayload(jobTargets);

        const createRes = await fetch(`${baseUrl}/review-jobs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!createRes.ok) {
          const text = await createRes.text();
          throw new Error(`검수 작업 생성 실패: ${createRes.status} ${text}`);
        }

        const created = await createRes.json();
        setReviewJobInfo({
          ...created,
          selected_review_check_count: selectedReviewCheckCount,
          selected_review_check_labels: selectedReviewCheckLabels,
        });

        const result = await waitForReviewResult(baseUrl, created.job_id);
        await applyAiReviewResult(result, {
          labels: selectedReviewCheckLabels,
          summary: makeReviewRunTitle(selectedReviewCheckLabels),
        });

        totalReviewed = result.summary?.total_questions ?? 0;
        totalIssues = result.summary?.issue_question_count ?? 0;
        totalMappingErrors = result.summary?.mapping_error_count ?? 0;

        const skippedQuestionCount = result.summary?.skipped_question_count ?? 0;
        const requestedQuestionCount =
          result.summary?.requested_question_count ?? totalReviewed + skippedQuestionCount;

        await fetchQuestions();

        const isPartial =
          !!result.partial ||
          ["partial_failed", "partial_canceled"].includes(result.status);

        alert(
          [
            isPartial
              ? "AI 검수가 중간에 중단되었지만, 완료된 문제 결과는 반영했습니다."
              : skippedQuestionCount
                ? "AI 검수가 완료되었습니다. 단, 일부 문제는 API 오류로 건너뛰었습니다."
                : "AI 검수가 완료되었습니다.",
            "검수 작업: 1개",
            `검수 매핑: ${jobTargets.length}개`,
            `요청 문제: ${requestedQuestionCount}개`,
            `ChatGPT 검수 완료 문제: ${totalReviewed}개`,
            skippedQuestionCount ? `API 오류로 건너뛴 문제: ${skippedQuestionCount}개` : "",
            `적용 검수 항목: ${selectedReviewCheckText}`,
            `오류 문제: ${totalIssues}개`,
            totalMappingErrors ? `매핑 오류: ${totalMappingErrors}개` : "",
            isPartial && result.error_message ? `중단 사유: ${result.error_message}` : "",
          ].filter(Boolean).join("\n")
        );
    } catch (error) {
      console.error(error);
      alert(`AI 검수 중 오류가 발생했습니다.\n${error.message}`);
    } finally {
      setReviewRunning(false);
    }
  };

  const openReviewModal = (row) => {
    const raw = row.raw || row;
    const errorTypes = row.errorType && row.errorType !== "-"
      ? splitErrorTypes(row.errorType)
      : splitErrorTypes(getValue(raw, ["error_type", "issue_type", "errorType", "오류유형"], ""));

    const answerValue =
      row.answer ||
      getValue(raw, ["answer", "정답"], "") ||
      getValue(raw?.data, ["answer"], "");

    const keywordsValue =
      getValue(raw, ["keywords", "keyword", "키워드"], "") ||
      getValue(raw?.data, ["keywords", "keyword"], "");

    setReviewQuestion(row);
    setEditForm({
      ...raw,
      id: row.id || raw.id || raw.idx,
      exam_unique_no: row.examUniqueNo || getValue(raw, ["exam_unique_no", "시험 고유 번호", "chapter"], ""),
      cd_value: row.cdValue || getValue(raw, ["cd_value", "CD값", "section", "learning_goal"], ""),
      question_no: row.number || getValue(raw, ["question_no", "number", "no"], ""),
      question: row.question || getValue(raw, ["question", "question_text", "content", "stem"], ""),
      view_text: getValue(raw, ["view", "보기", "view_text"], ""),
      image_url: getValue(raw, ["image_url", "image", "img_url"], ""),
      choice1: getValue(raw, ["choice1", "선택지1", "선지1"], ""),
      choice2: getValue(raw, ["choice2", "선택지2", "선지2"], ""),
      choice3: getValue(raw, ["choice3", "선택지3", "선지3"], ""),
      choice4: getValue(raw, ["choice4", "선택지4", "선지4"], ""),
      choice1_image_url: getValue(raw, ["choice1_image_url", "선지1 이미지 URL", "선택지1 이미지 URL"], ""),
      choice2_image_url: getValue(raw, ["choice2_image_url", "선지2 이미지 URL", "선택지2 이미지 URL"], ""),
      choice3_image_url: getValue(raw, ["choice3_image_url", "선지3 이미지 URL", "선택지3 이미지 URL"], ""),
      choice4_image_url: getValue(raw, ["choice4_image_url", "선지4 이미지 URL", "선택지4 이미지 URL"], ""),
      status: row.reviewStatus || getValue(raw, ["status", "review_status"], "완료"),
      error_types: normalizeErrorTypes(errorTypes),
      reason: row.reason !== "-" ? row.reason : getValue(raw, ["reason", "기타사유"], ""),
      suggestion: row.suggestion || getValue(raw, ["suggestion", "review_suggestion", "수정제안", "수정 제안"], ""),
      memo: row.reason !== "-" ? row.reason : getValue(raw, ["memo", "review_memo", "reason"], ""),
      reflect_status: row.reflectStatus || getValue(raw, ["reflect_status"], "미반영"),
      answer: row.answer || getValue(raw, ["answer", "정답"], ""),
      keywords: getValue(raw, ["keywords", "keyword", "키워드"], ""),
      review_check_labels: row.reviewCheckLabels || parseLabelList(raw.review_check_labels),
      review_scope_summary: row.reviewScopeSummary || getValue(raw, ["review_scope_summary"], ""),
      review_check_history: normalizeReviewHistory(row.reviewCheckHistory || raw.review_check_history),

    });
  };

  const closeReviewModal = () => {
    setReviewQuestion(null);
    setEditForm(null);
  };

  const handleEditChange = (e) => {
    const { name, value } = e.target;
    setEditForm((prev) => ({ ...prev, [name]: value }));
  };

  const toggleErrorType = (type) => {
    setEditForm((prev) => {
      const current = prev.error_types || [];
      return { ...prev, error_types: current.includes(type) ? current.filter((item) => item !== type) : [...current, type] };
    });
  };

  const deleteReviewHistoryEntry = (targetIndex) => {
    setEditForm((prev) => {
      const currentHistory = normalizeReviewHistory(prev.review_check_history);
      const nextHistory = currentHistory.filter((_, index) => index !== targetIndex);
      const rebuilt = rebuildReviewFieldsFromHistory(nextHistory);

      return {
        ...prev,
        ...rebuilt,
      };
    });
  };


  const saveReview = async (nextStatus) => {
    if (!editForm?.id) {
      alert("저장할 문제 ID가 없습니다.");
      return;
    }

    const updated = {
      ...editForm,
      review_status: nextStatus || editForm.status,
      status: nextStatus || editForm.status,
      error_type: normalizeErrorTypes(editForm.error_types || []).join(", "),
      reason: editForm.reason || "",
      suggestion: editForm.suggestion || "",
      keywords: editForm.keywords || "",
      review_check_history: normalizeReviewHistory(editForm.review_check_history),
      review_check_labels: uniqueLabels(editForm.review_check_labels || []),
      review_scope_summary: editForm.review_scope_summary || makeReviewScopeSummary(editForm.review_check_labels || []),
    };

    try {
      const res = await fetch(`${API_BASE}/api/questions/${editForm.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_status: updated.review_status,
          error_type: updated.error_type,
          reason: updated.reason,
          suggestion: updated.suggestion,
          keywords: updated.keywords,
          review_check_labels: updated.review_check_labels.join(", "),
          review_scope_summary: updated.review_scope_summary,
          review_check_history: JSON.stringify(updated.review_check_history || []),
          reviewer: "admin",
          reflect_status: updated.reflect_status || "미반영",
        }),
      });

      if (!res.ok) {
        throw new Error("DB 저장 실패");
      }

      await fetchQuestions();
      closeReviewModal();
    } catch (error) {
      console.error(error);
      alert("저장 중 오류가 발생했습니다.");
    }
  };

  
  const renderTargetForm = () => (
    <section className="filter-card review-target-card">
      <div className="filter-section-title">검수 대상 지정</div>
      <div className="filter-grid review-target-grid compact-review-grid">
        <label className="field">
          <span>강좌명 *</span>
          <select
            name="courseName"
            value={reviewTarget.courseName}
            onChange={handleReviewTargetChange}
          >
            <option value="">강좌명을 선택하세요</option>
            {targetCourseOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>세트명 <em className="field-hint">선택 안 하면 전체</em></span>
          <select
            name="setName"
            value={reviewTarget.setName}
            onChange={handleReviewTargetChange}
            disabled={!reviewTarget.courseName}
          >
            <option value="">전체 세트</option>
            {targetSetOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>과목명 <em className="field-hint">선택 안 하면 전체</em></span>
          <select
            name="subjectName"
            value={reviewTarget.subjectName}
            onChange={handleReviewTargetChange}
            disabled={!reviewTarget.courseName}
          >
            <option value="">전체 과목</option>
            {targetSubjectOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>하위유형 <em className="field-hint">선택 안 하면 전체</em></span>
          <select
            name="subtypeName"
            value={reviewTarget.subtypeName}
            onChange={handleReviewTargetChange}
            disabled={!reviewTarget.courseName}
          >
            <option value="">전체 하위유형</option>
            {targetSubtypeOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>문제 범위 (선택, 예: 1-10)</span>
          <input name="questionRange" value={reviewTarget.questionRange} onChange={handleReviewTargetChange} placeholder="비우면 선택 매핑 전체" />
        </label>
        <label className="field">
          <span>검수 대상</span>
          <select name="targetScope" value={reviewTarget.targetScope} onChange={handleReviewTargetChange}>
            <option value="filtered">선택 매핑 기준 전체</option>
            <option value="selected">체크 선택 문제 중 선택 매핑 기준</option>
          </select>
        </label>
      </div>

      {reviewTarget.courseName ? (
        selectedTargetMaps.length > 0 ? (
          <div className="review-status-line map-summary-line">
            <strong>매칭된 검수 대상 {selectedTargetMaps.length}개</strong>

            <span>강좌명: {reviewTarget.courseName}</span>
            <span>세트명: {reviewTarget.setName || "전체"}</span>
            <span>과목명: {reviewTarget.subjectName || "전체"}</span>
            <span>하위유형: {reviewTarget.subtypeName || "전체"}</span>

            <span>
              시험 고유 번호:{" "}
              {Array.from(
                new Set(
                  selectedTargetMaps
                    .map((item) => String(item.exam_unique_no || "").trim())
                    .filter(Boolean)
                )
              ).join(", ") || "-"}
            </span>
          </div>
        ) : (
          <div className="review-status-line map-summary-line muted-line">
            <strong>매칭 없음</strong>
            <span>선택한 조건에 맞는 검수 대상 매핑이 없습니다. 매핑 관리 화면을 확인해 주세요.</span>
          </div>
        )
      ) : (
        <div className="review-status-line map-summary-line muted-line">
          <strong>강좌명 미선택</strong>
          <span>초기 화면에는 전체 문제가 표시됩니다. 검수 실행 전에는 강좌명을 선택해 주세요.</span>
        </div>
      )}

      <div className="review-check-panel">
        <div className="review-check-head">
          <strong>검수 항목 선택</strong>
          <span>선택 {selectedReviewCheckCount}개</span>
        </div>

        <div className="review-selected-checks">
          <strong>현재 선택된 검수</strong>
          <span>{selectedReviewCheckText}</span>
        </div>

        <div className="review-check-presets">
          {Object.entries(REVIEW_CHECK_PRESETS).map(([key, preset]) => (
            <button
              key={key}
              type="button"
              className={[
                "review-check-preset-btn",
                key === "cancel" ? "danger" : "",
                activeReviewPreset === key ? "active" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => applyReviewCheckPreset(key)}
              disabled={reviewRunning}
            >
              {preset.label}
            </button>
          ))}
        </div>

        <div className="review-check-grid">
          <div className="review-check-group">
            <div className="review-check-group-title">내용 검수</div>
            <div className="review-check-list">
              {Object.entries(REVIEW_CHECK_GROUPS.content).map(([groupKey, item]) => (
                <label
                  key={groupKey}
                  className="review-check-item"
                  title={item.description}
                >
                  <input
                    type="checkbox"
                    checked={isReviewGroupChecked(reviewChecks, "content", groupKey)}
                    onChange={() => {
                      setActiveReviewPreset("");
                      toggleReviewGroup(setReviewChecks, "content", groupKey);
                    }}
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="review-check-group">
            <div className="review-check-group-title">형식 검수</div>
            <div className="review-check-list">
              {Object.entries(REVIEW_CHECK_GROUPS.format).map(([groupKey, item]) => (
                <label
                  key={groupKey}
                  className="review-check-item"
                  title={item.description}
                >
                  <input
                    type="checkbox"
                    checked={isReviewGroupChecked(reviewChecks, "format", groupKey)}
                    onChange={() => {
                      setActiveReviewPreset("");
                      toggleReviewGroup(setReviewChecks, "format", groupKey);
                    }}
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      </div>

      {reviewJobInfo && (
        <div className="review-status-line">
          <strong>최근 작업</strong>
          <span>job_id: {reviewJobInfo.job_id || "-"}</span>
          <span>status: {reviewJobInfo.status || "-"}</span>
          <span>검수 항목: {formatSelectedReviewCheckLabels(reviewJobInfo.selected_review_check_labels || [])}</span>
        </div>
      )}

      <div className="filter-actions">
        <button className="btn btn-primary" type="button" onClick={() => { fetchQuestions(); fetchTargetMaps(); }} disabled={reviewRunning}>DB 새로고침</button>
        <button className="btn btn-light" type="button" onClick={() => { setReviewTarget(DEFAULT_REVIEW_TARGET); setReviewCurrentPage(1);}} disabled={reviewRunning}> 입력 초기화 </button>
        <button className="btn btn-success" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "uncheckedOrError")} disabled={reviewRunning}>{reviewRunning ? "검수 진행중" : "미검수/오류 문제 검수하기"}</button>
        <button className="btn btn-warning" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "errorOnly")} disabled={reviewRunning}>오류있음만 검수하기</button>
        <button className="btn btn-gray" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "holdOnly")} disabled={reviewRunning}>보류만 검수하기</button>
        <button className="btn btn-blue" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "normalOnly")} disabled={reviewRunning}>정상 문제 재검수하기</button>
        <button className="btn btn-light" type="button" onClick={() => runAiReview(reviewTarget.targetScope, null)} disabled={reviewRunning}>선택 매핑 전체 검수</button>
        <button className="btn btn-danger" type="button" onClick={cancelCurrentReview} disabled={!reviewRunning || !reviewJobInfo?.job_id || cancelingReview}> {cancelingReview ? "취소 요청 중" : "검수 취소"} </button>      
      </div>
    </section>
  );

  const filteredTargetMaps = useMemo(() => {
    const keyword = lower(targetMapSearch);

    if (!keyword) {
      return targetMaps;
    }

    return targetMaps.filter((item) => {
      const targetText = lower([
        item.id,
        item.display_name,
        item.course_name,
        item.set_name,
        item.subject_name,
        item.subtype_name,
        item.exam_unique_no,
      ].join(" "));

      return targetText.includes(keyword);
    });
  }, [targetMaps, targetMapSearch]);

  const targetMapTotalPages = useMemo(() => {
    return Math.max(1, Math.ceil(filteredTargetMaps.length / TARGET_MAP_PAGE_SIZE));
  }, [filteredTargetMaps.length]);

  const targetMapPageRows = useMemo(() => {
    const startIndex = (targetMapPage - 1) * TARGET_MAP_PAGE_SIZE;
    const endIndex = startIndex + TARGET_MAP_PAGE_SIZE;
    return filteredTargetMaps.slice(startIndex, endIndex);
  }, [filteredTargetMaps, targetMapPage]);

  useEffect(() => {
    if (targetMapPage > targetMapTotalPages) {
      setTargetMapPage(targetMapTotalPages);
    }
  }, [targetMapPage, targetMapTotalPages]);

  const handleTargetMapSearchChange = (event) => {
    setTargetMapSearch(event.target.value);
    setTargetMapPage(1);
  };

  const resetTargetMapSearch = () => {
    setTargetMapSearch("");
    setTargetMapPage(1);
  };

  const renderTargetMapManager = () => (
    <section className="filter-card target-map-manager">
      <div className="filter-section-title">검수 대상 매핑 직접 등록</div>

      <div className="filter-grid target-map-form-grid">
        <label className="field">
          <span>강좌명 *</span>
          <input
            name="courseName"
            value={targetMapForm.courseName}
            onChange={handleTargetMapFormChange}
            placeholder="예: SQLD 61회 끝장 패키지 PT 2026"
          />
        </label>

        <label className="field">
          <span>세트명 *</span>
          <input
            name="setName"
            value={targetMapForm.setName}
            onChange={handleTargetMapFormChange}
            placeholder="예: 최신기출 문제"
          />
        </label>

        <label className="field">
          <span>과목명 *</span>
          <input
            name="subjectName"
            value={targetMapForm.subjectName}
            onChange={handleTargetMapFormChange}
            placeholder="예: SQLD 25년 60회 기출복원문제"
          />
        </label>

        <label className="field">
          <span>하위유형</span>
          <input
            name="subtypeName"
            value={targetMapForm.subtypeName}
            onChange={handleTargetMapFormChange}
            placeholder="sub_title이 있을 때만 입력"
          />
        </label>

        <label className="field">
          <span>시험 고유 번호 *</span>
          <input
            name="examUniqueNo"
            value={targetMapForm.examUniqueNo}
            onChange={handleTargetMapFormChange}
            placeholder="예: 123"
          />
        </label>
      </div>

      <div className="filter-actions">
        <button
          className="btn btn-success"
          type="button"
          onClick={saveTargetMap}
          disabled={targetMapSaving}
        >
          {targetMapForm.id ? "매핑 수정 저장" : "매핑 등록"}
        </button>

        <button
          className="btn btn-light"
          type="button"
          onClick={resetTargetMapForm}
          disabled={targetMapSaving}
        >
          입력 초기화
        </button>

        <button
          className="btn btn-primary"
          type="button"
          onClick={fetchTargetMaps}
          disabled={targetMapSaving}
        >
          매핑 새로고침
        </button>
      </div>

      <div className="target-map-search-row">
        <label className="field target-map-search-field">
          <span>매핑 검색</span>
          <input
            value={targetMapSearch}
            onChange={handleTargetMapSearchChange}
            placeholder="강좌명, 세트명, 과목명, 하위유형, 시험 고유 번호 검색"
          />
        </label>

        <button
          className="btn btn-light"
          type="button"
          onClick={resetTargetMapSearch}
        >
          검색 초기화
        </button>
      </div>

      <div className="target-map-list-wrap">
        <table className="target-map-list-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>표시명</th>
              <th>강좌명</th>
              <th>세트명</th>
              <th>과목명</th>
              <th>하위유형</th>
              <th>시험 고유 번호</th>
              <th>관리</th>
            </tr>
          </thead>
          <tbody>
            {targetMaps.length === 0 ? (
              <tr>
                <td colSpan="8" className="empty-cell">
                  등록된 검수 대상 매핑이 없습니다.
                </td>
              </tr>
            ) : filteredTargetMaps.length === 0 ? (
              <tr>
                <td colSpan="8" className="empty-cell">
                  검색 결과가 없습니다.
                </td>
              </tr>
            ) : (
              targetMapPageRows.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.display_name || "-"}</td>
                  <td>{item.course_name || "-"}</td>
                  <td>{item.set_name || "-"}</td>
                  <td>{item.subject_name || "-"}</td>
                  <td>{item.subtype_name || "-"}</td>
                  <td>{item.exam_unique_no || "-"}</td>
                  <td>
                    <div className="target-map-row-actions">
                      <button
                        className="btn btn-row"
                        type="button"
                        onClick={() => editTargetMap(item)}
                      >
                        수정
                      </button>
                      <button
                        className="btn btn-danger btn-small"
                        type="button"
                        onClick={() => deleteTargetMap(item)}
                      >
                        삭제
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {renderTargetMapPagination()}
    </section>
  );

  const renderSearchFilters = () => (
    <section className="filter-card">
      <div className="filter-section-title">문제 목록 검색 조건</div>
      <div className="filter-grid">
        <label className="field">
          <span>강좌명</span>
          <select name="courseName" value={filters.courseName} onChange={handleFilterChange}>
            {options.courseName.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>세트명</span>
          <select name="setName" value={filters.setName} onChange={handleFilterChange}>
            {options.setName.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>과목명</span>
          <select name="subjectName" value={filters.subjectName} onChange={handleFilterChange}>
            {options.subjectName.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>하위유형</span>
          <select name="subtypeName" value={filters.subtypeName} onChange={handleFilterChange}>
            {options.subtypeName.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>시험 고유 번호</span>
          <select name="examUniqueNo" value={filters.examUniqueNo} onChange={handleFilterChange}>
            {options.examUniqueNo.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>CD값</span>
          <select name="cdValue" value={filters.cdValue} onChange={handleFilterChange}>
            {options.cdValue.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>검수 상태</span>
          <select name="reviewStatus" value={filters.reviewStatus} onChange={handleFilterChange}>
            {options.reviewStatus.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>오류 유형</span>
          <select name="errorType" value={filters.errorType} onChange={handleFilterChange}>
            {options.errorType.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>반영 상태</span>
          <select name="reflectStatus" value={filters.reflectStatus} onChange={handleFilterChange}>
            {options.reflectStatus.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label className="field">
          <span>페이지당 개수</span>
          <select name="pageSize" value={filters.pageSize} onChange={handleFilterChange}>
            <option value="20">20개</option>
            <option value="50">50개</option>
            <option value="100">100개</option>
          </select>
        </label>
        <label className="field field-wide">
          <span>검색</span>
          <input name="search" value={filters.search} onChange={handleFilterChange} placeholder="IDX, 강좌명, 세트명, 과목명, 하위유형, 업로드파일, 장, 절, 학습목표, 번호, 문제 검색" />
        </label>
      </div>
      <div className="filter-actions">
        <button className="btn btn-primary" type="button" onClick={fetchQuestions}>검색</button>
        <button className="btn btn-light" type="button" onClick={resetFilters}>초기화</button>
      </div>
    </section>
  );

  const renderStats = () => (
    <section className="stats-panel">
      <div className="stat-card"><span>전체</span><strong>{stats.total.toLocaleString()}</strong></div>
      <div className="stat-card"><span>미검수</span><strong>{stats.unchecked.toLocaleString()}</strong></div>
      <div className="stat-card"><span>검수중</span><strong>{stats.working.toLocaleString()}</strong></div>
      <div className="stat-card"><span>정상</span><strong>{stats.normal.toLocaleString()}</strong></div>
      <div className="stat-card"><span>오류있음</span><strong>{stats.error.toLocaleString()}</strong></div>
      <div className="stat-card"><span>보류</span><strong>{stats.hold.toLocaleString()}</strong></div>
      <div className="stat-card"><span>완료</span><strong>{stats.complete.toLocaleString()}</strong></div>
      <div className="stat-card"><span>반영완료</span><strong>{stats.reflected.toLocaleString()}</strong></div>
    </section>
  );

  const renderTargetMapPagination = () => {
    const totalCount = filteredTargetMaps.length;

    const startNumber = totalCount === 0
      ? 0
      : (targetMapPage - 1) * TARGET_MAP_PAGE_SIZE + 1;

    const endNumber = Math.min(targetMapPage * TARGET_MAP_PAGE_SIZE, totalCount);

    return (
      <div className="pagination-bar target-map-pagination">
        <div className="pagination-info">
          전체 {totalCount.toLocaleString()}건 중{" "}
          {startNumber.toLocaleString()}-{endNumber.toLocaleString()} 표시
        </div>

        <div className="pagination-actions">
          <button
            className="btn btn-light"
            type="button"
            onClick={() => setTargetMapPage(1)}
            disabled={targetMapPage === 1}
          >
            처음
          </button>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setTargetMapPage((prev) => Math.max(1, prev - 1))}
            disabled={targetMapPage === 1}
          >
            이전
          </button>

          <span className="pagination-current">
            {targetMapPage.toLocaleString()} / {targetMapTotalPages.toLocaleString()}
          </span>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setTargetMapPage((prev) => Math.min(targetMapTotalPages, prev + 1))}
            disabled={targetMapPage === targetMapTotalPages}
          >
            다음
          </button>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setTargetMapPage(targetMapTotalPages)}
            disabled={targetMapPage === targetMapTotalPages}
          >
            마지막
          </button>
        </div>
      </div>
    );
  };

  const renderPagination = () => {
    const startNumber = filteredRows.length === 0 ? 0 : (currentPage - 1) * pageSizeNumber + 1;
    const endNumber = Math.min(currentPage * pageSizeNumber, filteredRows.length);

    return (
      <div className="pagination-bar">
        <div className="pagination-info">
          전체 {filteredRows.length.toLocaleString()}건 중{" "}
          {startNumber.toLocaleString()}-{endNumber.toLocaleString()} 표시
        </div>

        <div className="pagination-actions">
          <button
            className="btn btn-light"
            type="button"
            onClick={() => setCurrentPage(1)}
            disabled={currentPage === 1}
          >
            처음
          </button>
          <button
            className="btn btn-light"
            type="button"
            onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
          >
            이전
          </button>

          <span className="pagination-current">
            {currentPage.toLocaleString()} / {totalPages.toLocaleString()}
          </span>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
          >
            다음
          </button>
          <button
            className="btn btn-light"
            type="button"
            onClick={() => setCurrentPage(totalPages)}
            disabled={currentPage === totalPages}
          >
            마지막
          </button>
        </div>
      </div>
    );
  };

  const renderReviewPagination = () => {
    const startNumber =
      reviewTargetRows.length === 0
        ? 0
        : (reviewCurrentPage - 1) * REVIEW_TARGET_PAGE_SIZE + 1;

    const endNumber = Math.min(
      reviewCurrentPage * REVIEW_TARGET_PAGE_SIZE,
      reviewTargetRows.length
    );

    return (
      <div className="pagination-bar">
        <div className="pagination-info">
          전체 {reviewTargetRows.length.toLocaleString()}건 중{" "}
          {startNumber.toLocaleString()}-{endNumber.toLocaleString()} 표시
        </div>

        <div className="pagination-actions">
          <button
            className="btn btn-light"
            type="button"
            onClick={() => setReviewCurrentPage(1)}
            disabled={reviewCurrentPage === 1}
          >
            처음
          </button>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setReviewCurrentPage((prev) => Math.max(1, prev - 1))}
            disabled={reviewCurrentPage === 1}
          >
            이전
          </button>

          <span className="pagination-current">
            {reviewCurrentPage.toLocaleString()} / {reviewTargetTotalPages.toLocaleString()}
          </span>

          <button
            className="btn btn-light"
            type="button"
            onClick={() =>
              setReviewCurrentPage((prev) => Math.min(reviewTargetTotalPages, prev + 1))
            }
            disabled={reviewCurrentPage === reviewTargetTotalPages}
          >
            다음
          </button>

          <button
            className="btn btn-light"
            type="button"
            onClick={() => setReviewCurrentPage(reviewTargetTotalPages)}
            disabled={reviewCurrentPage === reviewTargetTotalPages}
          >
            마지막
          </button>
        </div>
      </div>
    );
  };

  const renderQuestionTable = ({rowsToShow, title, showCount = false, totalCount = null, emptyText = "조회된 문제가 없습니다.", tableVariant = "list",}) => {
    const allVisibleChecked = rowsToShow.length > 0 && rowsToShow.every((row) => selectedRows.includes(row.rowKey));
    const isTargetTable = tableVariant === "target";
    const emptyColSpan = isTargetTable ? 16 : 15;

    return (
      <section className="table-card">
        <div className="table-top">
          <div className="table-title">
            {title}
            {showCount ? (
              <> <strong>{(totalCount ?? rowsToShow.length).toLocaleString()}</strong>건</>
            ) : null}
          </div>
          <div className="table-actions">
            <button
              className="btn btn-light"
              type="button"
              onClick={() => handleBulkAction("정상")}
            >
              선택 정상처리
            </button>

            <button
              className="btn btn-warning"
              type="button"
              onClick={() => handleBulkAction("보류")}
            >
              선택 보류
            </button>
          </div>
        </div>

        {loadError && <div className="alert">{loadError}</div>}

        <div className="table-wrap">
          <table className={`review-table compact-review-table ${isTargetTable ? "target-review-table" : ""}`}>
            <thead>
              <tr>
                <th className="check-col"><input type="checkbox" checked={allVisibleChecked} onChange={(event) => toggleAll(event.target.checked, rowsToShow)} /></th>
                {isTargetTable ? (
                  <>
                    <th className="idx-col">IDX</th>
                    <th className="upload-file-col">업로드파일</th>
                    <th className="subject-col">과목</th>
                    <th className="chapter-col">장</th>
                    <th className="section-col">절</th>
                    <th className="goal-col">학습목표</th>
                    <th className="number-col">번호</th>
                    <th className="question-main-col">문제</th>
                    <th className="review-status-col">검수상태</th>
                    <th className="error-type-col">오류유형</th>
                    <th className="reason-col">기타사유</th>
                    <th className="reviewer-col">검수자</th>
                    <th className="reviewed-at-col">검수일</th>
                    <th className="reflect-status-col">반영상태</th>
                    <th className="manage-col">관리</th>
                  </>
                ) : (
                  <>
                    <th>IDX</th>
                    <th>강좌명</th>
                    <th className="exam-no-col">시험 고유 번호</th>
                    <th>과목명</th>
                    <th className="cd-col">CD값</th>
                    <th className="number-col">번호</th>
                    <th>문제</th>
                    <th className="review-status-col">검수상태</th>
                    <th>오류유형</th>
                    <th>오류사유</th>
                    <th className="reviewer-col">검수자</th>
                    <th>검수일</th>
                    <th>반영상태</th>
                    <th className="manage-col">관리</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={emptyColSpan} className="empty-cell">데이터를 불러오는 중입니다.</td></tr>
              ) : rowsToShow.length === 0 ? (
                <tr><td colSpan={emptyColSpan} className="empty-cell">{emptyText}</td></tr>
              ) : rowsToShow.map((row) => {
                const errorTypes = normalizeErrorTypes(splitErrorTypes(row.errorType));
                return (
                  <tr
                    key={row.rowKey}
                    className={selectedRows.includes(row.rowKey) ? "row-selected" : ""}
                  >
                    <td className="check-col">
                      <input
                        type="checkbox"
                        checked={selectedRows.includes(row.rowKey)}
                        onChange={() => toggleRow(row.rowKey)}
                      />
                    </td>

                    {isTargetTable ? (
                      <>
                        <td className="idx-col">{row.id}</td>
                        <td className="upload-file-col file-cell" title={row.uploadFile || "-"}>{row.uploadFile || "-"}</td>
                        <td className="subject-col">{row.subjectName || "-"}</td>
                        <td className="chapter-col">{row.chapter || "-"}</td>
                        <td className="section-col">{row.section || "-"}</td>
                        <td className="goal-col">{row.learningGoal || "-"}</td>
                        <td className="number-col">{row.number}</td>
                        <td className="question-cell question-main-col">{row.question}</td>
                      </>
                    ) : (
                      <>
                        <td>{row.id}</td>
                        <td>{row.courseName || "-"}</td>
                        <td className="exam-no-col">{row.examUniqueNo || "-"}</td>
                        <td>{row.subjectName || "-"}</td>
                        <td className="cd-col">{row.cdValue || "-"}</td>
                        <td className="number-col">{row.number}</td>
                        <td className="question-cell">{row.question}</td>
                      </>
                    )}

                    <td className="review-status-col">
                      <div className="status-box">
                        <span className={`badge ${getStatusClass(row.reviewStatus)}`}>
                          {row.reviewStatus}
                        </span>
                        {row.statusMemo && <small>{row.statusMemo}</small>}
                        {row.reviewScopeSummary && <small className="review-scope-small">검수: {row.reviewScopeSummary}</small>}
                      </div>
                    </td>

                    <td className={isTargetTable ? "error-type-col" : ""}>
                      <div className="pill-list">
                        {errorTypes.length === 0 ? (
                          <span className="pill pill-muted">-</span>
                        ) : (
                          errorTypes.map((type) => (
                            <span key={type} className="pill pill-error">
                              {type}
                            </span>
                          ))
                        )}
                      </div>
                    </td>

                    <td className={isTargetTable ? "reason-cell reason-col" : "reason-cell"}>
                      <div className="reason-preview">{row.reason}</div>
                    </td>
                    <td className="reviewer-col">{row.reviewer}</td>
                    <td className={isTargetTable ? "reviewed-at-col" : ""}>{row.reviewedAt}</td>

                    <td className={isTargetTable ? "reflect-status-col" : ""}>
                      <span className={`reflect ${getReflectClass(row.reflectStatus)}`}>
                        {row.reflectStatus}
                      </span>
                    </td>

                    <td className="manage-col">
                      <button
                        className="btn btn-row"
                        type="button"
                        onClick={() => openReviewModal(row)}
                      >
                        검수하기
                      </button>
                    </td>
                  </tr>                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    );
  };

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1>
            {pageMode === "review"
              ? "AI 검수 실행"
              : pageMode === "list"
                ? "문제 목록 검색"
                : "검수 대상 매핑 관리"}
          </h1>
        </div>
        <div className="header-actions">
          <button
            className={`btn ${pageMode === "review" ? "btn-primary" : "btn-light"}`}
            type="button"
            onClick={() => setPageMode("review")}
          >
            검수 화면
          </button>

          <button
            className={`btn ${pageMode === "list" ? "btn-primary" : "btn-light"}`}
            type="button"
            onClick={() => setPageMode("list")}
          >
            문제 목록 검색
          </button>

          <button
            className={`btn ${pageMode === "map" ? "btn-primary" : "btn-light"}`}
            type="button"
            onClick={() => setPageMode("map")}
          >
            매핑 관리
          </button>
          <input ref={questionFileInputRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleQuestionExcelUpload} />
          <input ref={cdMetaFileInputRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleCdMetaExcelUpload} />
          <button className="btn btn-primary" type="button" onClick={() => questionFileInputRef.current?.click()}>문제 엑셀 업로드</button>
          <button className="btn btn-success" type="button" onClick={() => cdMetaFileInputRef.current?.click()}>CD 매핑 엑셀 업로드</button>
        </div>
      </header>

      {pageMode === "review" ? (
        <>
          {renderTargetForm()}
          {renderQuestionTable({
            rowsToShow: reviewTargetPageRows,
            title: "검수 대상 문제 내역 ",
            tableVariant: "target",
            showCount: true,
            totalCount: reviewTargetRows.length,
            emptyText: "표시할 문제가 없습니다. 매핑 DB와 문제 DB의 시험 고유 번호를 확인해 주세요.",
          })}
          {renderReviewPagination()}
        </>
      ) : pageMode === "list" ? (
        <>
          {renderStats()}
          {renderSearchFilters()}
          {renderQuestionTable({
            rowsToShow: pageRows,
            title: "문제 목록 ",
            tableVariant: "target",
            showCount: true,
            totalCount: filteredRows.length,
            emptyText: "조회된 문제가 없습니다.",
          })}
          {renderPagination()}
        </>
      ) : (
        <>
          {renderTargetMapManager()}
        </>
      )}

      {reviewQuestion && editForm && (
        <div className="review-modal-backdrop" onClick={closeReviewModal}>
          <div className="review-modal" onClick={(e) => e.stopPropagation()}>
            <div className="review-modal-header">
              <div>
                <div className="review-modal-title">문제 검수 <span className="review-modal-status">{editForm.status}</span></div>
                <div className="review-modal-path">시험 고유 번호: {editForm.exam_unique_no || "-"} | CD값: {editForm.cd_value || "-"} | IDX: {editForm.id || "-"}</div>
              </div>
              <div className="review-modal-actions">
                <button type="button" className="modal-btn red" onClick={closeReviewModal}>닫기</button>
              </div>
            </div>

            <div className="review-modal-body">
              <section className="review-panel original-panel">
                <div className="panel-title">검수 문제</div>

                <div className="original-summary-grid">
                  <div>
                    <span>번호</span>
                    <strong>{editForm.question_no || "-"}</strong>
                  </div>

                  <label>
                    <span>정답</span>
                    <input
                      name="answer"
                      value={editForm.answer || ""}
                      onChange={handleEditChange}
                    />
                  </label>

                  <label>
                    <span>키워드</span>
                    <input
                      name="keywords"
                      value={editForm.keywords || ""}
                      onChange={handleEditChange}
                    />
                  </label>

                  <div>
                    <span>검수 상태</span>
                    <strong>{editForm.status || "-"}</strong>
                  </div>
                </div>

                <label className="full-field">
                  문제
                  <textarea
                    name="question"
                    value={editForm.question || ""}
                    onChange={handleEditChange}
                    placeholder="문제를 입력하세요."
                  />
                </label>

                <label className="full-field">
                  보기
                  <textarea
                    name="view_text"
                    value={editForm.view_text || ""}
                    onChange={handleEditChange}
                    placeholder="보기를 입력하세요."
                  />
                </label>

                <label className="full-field">
                  보기 이미지 URL
                  <input
                    name="image_url"
                    value={editForm.image_url || ""}
                    onChange={handleEditChange}
                    placeholder="보기 이미지 URL을 입력하세요."
                  />
                </label>

                <div className="choice-edit-list">
                  {[1, 2, 3, 4].map((num) => (
                    <div className="choice-edit-block" key={`choice-edit-${num}`}>
                      <label className="full-field">
                        선지{num}
                        <textarea
                          name={`choice${num}`}
                          value={editForm[`choice${num}`] || ""}
                          onChange={handleEditChange}
                          placeholder={`선지${num} 내용을 입력하세요.`}
                        />
                      </label>

                      <label className="full-field choice-image-field">
                        선지{num} 이미지
                        <input
                          name={`choice${num}_image_url`}
                          value={editForm[`choice${num}_image_url`] || ""}
                          onChange={handleEditChange}
                          placeholder={`선지${num} 이미지 URL을 입력하세요.`}
                        />
                      </label>
                    </div>
                  ))}
                </div>
              </section>

              <aside className="review-panel side-panel review-content-panel">
                <div className="panel-title">검수 내용</div>

                <div className="review-history-box">
                  <div className="review-history-head">
                    <strong>누적 검수 내역</strong>
                    <span>{editForm.review_scope_summary || makeReviewScopeSummary(editForm.review_check_labels || [])}</span>
                  </div>

                  {Array.isArray(editForm.review_check_history) && editForm.review_check_history.length > 0 ? (
                    <div className="review-history-list">
                      {normalizeReviewHistory(editForm.review_check_history)
                        .map((item, originalIndex) => ({ item, originalIndex }))
                        .reverse()
                        .slice(0, 6)
                        .map(({ item, originalIndex }) => (
                          <div className="review-history-item" key={`${item.at || originalIndex}-${originalIndex}`}>
                            <div className="review-history-text">
                              <strong>{item.summary || makeReviewScopeSummary(item.labels || [])}</strong>
                              <span>{item.result || "-"} · {item.issue_count ?? 0}건</span>
                            </div>

                            <button
                              type="button"
                              className="review-history-delete-btn"
                              onClick={() => deleteReviewHistoryEntry(originalIndex)}
                            >
                              삭제
                            </button>
                          </div>
                        ))}
                    </div>
                  ) : (
                    <div className="review-history-empty">아직 저장된 검수 항목 내역이 없습니다.</div>
                  )}
                </div>

                <div className="review-content-top">
                  <label className="full-field review-status-field">
                    검수 상태
                    <select name="status" value={editForm.status} onChange={handleEditChange}>
                      <option value="완료">완료</option>
                      <option value="정상">정상</option>
                      <option value="오류있음">오류있음</option>
                      <option value="보류">보류</option>
                      <option value="검수중">검수중</option>
                    </select>
                  </label>

                  <div className="side-actions top-actions">
                    <button type="button" className="save-green" onClick={() => saveReview("정상")}>
                      정상 처리 후 닫기
                    </button>

                    <button type="button" className="save-dark" onClick={() => saveReview(editForm.status)}>
                      저장 후 닫기
                    </button>

                    <button type="button" className="save-yellow" onClick={() => saveReview("보류")}>
                      보류 처리
                    </button>
                  </div>
                </div>

                <div className="review-content-grid">
                  <div className="review-error-column">
                    <div className="review-content-block error-block content-error-block">
                      <h3>내용 오류</h3>
                      <div className="error-type-box">
                        <div className="error-check-list">
                          {CONTENT_ERROR_TYPES.map((type) => (
                            <label key={type} className="error-check-item">
                              <input
                                type="checkbox"
                                checked={editForm.error_types.includes(type)}
                                onChange={() => toggleErrorType(type)}
                              />
                              <span>{type}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="review-content-block error-block format-error-block">
                      <h3>형식 오류</h3>
                      <div className="error-type-box">
                        <div className="error-check-list">
                          {FORMAT_ERROR_TYPES.map((type) => (
                            <label key={type} className="error-check-item">
                              <input
                                type="checkbox"
                                checked={editForm.error_types.includes(type)}
                                onChange={() => toggleErrorType(type)}
                              />
                              <span>{type}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="review-text-column">
                    <label className="full-field review-content-block reason-block">
                      Reason / 오류 사유
                      <textarea
                        name="reason"
                        value={editForm.reason || ""}
                        onChange={handleEditChange}
                        placeholder="오류 사유를 입력하세요."
                      />
                    </label>

                    <label className="full-field review-content-block suggestion-block">
                      Suggestion / 수정 제안
                      <textarea
                        name="suggestion"
                        value={editForm.suggestion || ""}
                        onChange={handleEditChange}
                        placeholder="수정 제안을 입력하세요."
                      />
                    </label>
                  </div>
                </div>


              </aside>
            </div>


          </div>
        </div>
      )}
    </div>
  );
}

export default App;
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);