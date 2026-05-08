import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_QUESTION_API_BASE || "http://127.0.0.1:8001";
const DEFAULT_REVIEW_API_BASE = import.meta.env.VITE_REVIEW_API_BASE || "http://192.168.219.167:8000";

const CONTENT_ERROR_TYPES = [
  "문제 성립 오류",
  "정답 불일치",
  "해설 내용 오류",
  "선지-해설 불일치",
  "표현 오류",
  "기타 내용 오류",
];

const FORMAT_ERROR_TYPES = [
  "해설 시작 형식 오류",
  "선지별 해설 누락",
  "선지 해설 형식 오류",
  "정답 문장 중복",
  "결론 누락",
  "최종 문장 형식 오류",
  "기타 형식 오류",
  "긴 해설 수동 검토 필요",
];

const DEFAULT_FILTERS = {
  examUniqueNo: "전체",
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
  includeRawData: false,
};

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

function makeJobId(prefix = "site_review") {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
  const rand = Math.random().toString(16).slice(2, 8);
  return `${prefix}_${stamp}_${rand}`;
}

function uniqueJoin(values) {
  return Array.from(new Set(values.filter(Boolean))).join(", ");
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

function makeOptions(rows, key) {
  const values = rows
    .map((row) => row[key])
    .filter((value) => value !== undefined && value !== null && String(value).trim() !== "" && String(value).trim() !== "-")
    .map(String);
  return ["전체", ...Array.from(new Set(values))];
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
  return text.split(/[,/|·\n]/).map((item) => item.trim()).filter(Boolean);
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

  return {
    rowKey: `${id}-${index}`,
    id: toText(id),
    examUniqueNo: toText(examUniqueNo, ""),
    cdValue: toText(cdValue, ""),
    number: toText(pick(merged, ["number", "question_no", "q_no", "no", "번호", "문제번호", "문제 번호"]), "-"),
    question: toText(pick(merged, ["question", "question_text", "content", "stem", "title", "문제"]), "-"),
    viewText: toText(pick(merged, ["view_text", "view", "보기", "보기텍스트"], ""), ""),
    answer: toText(pick(merged, ["answer", "정답"], ""), ""),
    reviewStatus: toText(pick(merged, ["review_status", "status", "검수상태"]), "미검수"),
    statusMemo: toText(pick(merged, ["status_memo", "review_memo", "status_detail", "result_detail"], ""), ""),
    errorType: toText(pick(merged, ["error_type", "issue_type", "errorType", "오류유형"]), "-"),
    reason: toText(pick(merged, ["reason", "etc_reason", "other_reason", "기타사유"], "-"), "-"),
    reviewer: toText(pick(merged, ["reviewer", "inspector", "검수자"]), "admin"),
    reviewedAt: toText(pick(merged, ["reviewed_at", "review_date", "checked_at", "검수일"]), "-"),
    reflectStatus: toText(pick(merged, ["reflect_status", "reflection_status", "apply_status", "반영상태"]), "미반영"),
    raw: merged,
  };
}

function App() {
  const [pageMode, setPageMode] = useState("review");
  const [questions, setQuestions] = useState([]);
  const [targetMaps, setTargetMaps] = useState([]);
  const [reviewQuestion, setReviewQuestion] = useState(null);
  const [editForm, setEditForm] = useState(null);
  const fileInputRef = useRef(null);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [reviewTarget, setReviewTarget] = useState(DEFAULT_REVIEW_TARGET);
  const [reviewRunning, setReviewRunning] = useState(false);
  const [reviewJobInfo, setReviewJobInfo] = useState(null);
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
    } catch (error) {
      console.error(error);
      setLoadError("문제 데이터를 불러오지 못했습니다. site_api 서버 실행 여부를 확인하세요.");
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

  const handleExcelUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_BASE}/api/questions/upload-excel`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("엑셀 업로드 실패");
      await fetchQuestions();
      await fetchTargetMaps();
      alert("엑셀 데이터를 DB에 업로드했습니다. 검수대상매핑 시트가 있으면 매핑 DB에도 반영됩니다.");
    } catch (error) {
      console.error(error);
      alert("엑셀 업로드 중 오류가 발생했습니다.");
    } finally {
      event.target.value = "";
    }
  };

  const rows = useMemo(() => questions.map((item, index) => mapQuestion(item, index)), [questions]);

  const options = useMemo(() => ({
    examUniqueNo: makeOptions(rows, "examUniqueNo"),
    cdValue: makeOptions(rows, "cdValue"),
    reviewStatus: makeOptions(rows, "reviewStatus"),
    errorType: makeOptions(rows, "errorType"),
    reflectStatus: makeOptions(rows, "reflectStatus"),
  }), [rows]);

  const filteredRows = useMemo(() => {
    const keyword = lower(filters.search);
    return rows.filter((row) => {
      const targetText = lower([
        row.id,
        row.examUniqueNo,
        row.cdValue,
        row.number,
        row.question,
        row.viewText,
        row.answer,
        row.reviewStatus,
        row.errorType,
        row.reason,
        row.reviewer,
        row.reviewedAt,
        row.reflectStatus,
      ].join(" "));

      const matchExamUniqueNo = filters.examUniqueNo === "전체" || row.examUniqueNo === filters.examUniqueNo;
      const matchCdValue = filters.cdValue === "전체" || row.cdValue === filters.cdValue;
      const matchReviewStatus = filters.reviewStatus === "전체" || row.reviewStatus === filters.reviewStatus;
      const matchErrorType = filters.errorType === "전체" || row.errorType === filters.errorType;
      const matchReflectStatus = filters.reflectStatus === "전체" || row.reflectStatus === filters.reflectStatus;
      const matchKeyword = !keyword || targetText.includes(keyword);

      return matchExamUniqueNo && matchCdValue && matchReviewStatus && matchErrorType && matchReflectStatus && matchKeyword;
    });
  }, [rows, filters]);

  const pageRows = useMemo(() => filteredRows.slice(0, Number(filters.pageSize)), [filteredRows, filters.pageSize]);

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
  };

  const resetFilters = () => {
    setFilters(DEFAULT_FILTERS);
    setSelectedRows([]);
  };

  const toggleAll = (checked, visibleRows) => {
    if (checked) {
      setSelectedRows(visibleRows.map((row) => row.rowKey));
      return;
    }
    setSelectedRows([]);
  };

  const toggleRow = (rowKey) => {
    setSelectedRows((prev) => prev.includes(rowKey) ? prev.filter((key) => key !== rowKey) : [...prev, rowKey]);
  };

  const handleBulkAction = (label) => {
    if (selectedRows.length === 0) {
      alert("선택된 문제가 없습니다.");
      return;
    }
    alert(`${selectedRows.length}개 문제를 '${label}' 처리합니다.`);
  };

  const handleReviewTargetChange = (event) => {
    const { name, value, type, checked } = event.target;

    if (name === "targetMapId") {
      const selected = targetMaps.find((item) => String(item.id) === String(value));

      if (!selected) {
        setReviewTarget((prev) => ({
          ...prev,
          targetMapId: "",
          courseName: "",
          setName: "",
          subjectName: "",
          subtypeName: "",
          subjectMode: "specific",
          subjectStartIndex: "1",
          subjectEndIndex: "1",
          examUniqueNo: "",
          cdValue: "",
        }));
        return;
      }

      setReviewTarget((prev) => ({
        ...prev,
        targetMapId: value,
        courseName: selected.course_name || "",
        setName: selected.set_name || "",
        subjectName: selected.subject_name || "",
        subtypeName: selected.subtype_name || "",
        subjectMode: selected.subject_mode || "specific",
        subjectStartIndex: String(selected.subject_start_index || 1),
        subjectEndIndex: String(selected.subject_end_index || 1),
        examUniqueNo: selected.exam_unique_no || "",
        cdValue: selected.cd_value || "",
      }));
      return;
    }

    setReviewTarget((prev) => ({ ...prev, [name]: type === "checkbox" ? checked : value }));
  };

  const getReviewRows = (mode = reviewTarget.targetScope) => {
    const range = parseReviewRange(reviewTarget.questionRange);
    const examUniqueNo = reviewTarget.examUniqueNo.trim();
    const cdValue = reviewTarget.cdValue.trim();
    const baseRows = mode === "selected" ? rows.filter((row) => selectedRows.includes(row.rowKey)) : rows;

    if (!reviewTarget.targetMapId || !examUniqueNo) {
      return [];
    }

    return baseRows.filter((row) => {
      const qno = toNumber(row.number);
      const idx = toNumber(row.id);
      if (qno === null || idx === null) return false;
      if (range && (qno < range.start || qno > range.end)) return false;
      if (String(row.examUniqueNo) !== examUniqueNo) return false;
      if (cdValue && String(row.cdValue) !== cdValue) return false;
      return true;
    });
  };

  const reviewTargetRows = getReviewRows(reviewTarget.targetScope);

  const buildReviewPayload = (targetRows) => {
    const numbers = targetRows.map((row) => toNumber(row.number)).filter((value) => value !== null).sort((a, b) => a - b);
    if (numbers.length === 0) throw new Error("검수할 문제 번호가 없습니다.");

    const manualQuestionRange = reviewTarget.questionRange.trim();
    const questionRange = manualQuestionRange || "all";
    const defaultExamUniqueNo = reviewTarget.examUniqueNo.trim();
    const defaultCdValue = reviewTarget.cdValue.trim();

    if (!reviewTarget.targetMapId || !defaultExamUniqueNo) {
      throw new Error("검수 대상 매핑을 먼저 선택해 주세요.");
    }

    return {
      job_id: makeJobId(),
      course_name: reviewTarget.courseName.trim(),
      set_name: reviewTarget.setName.trim(),
      subject_name: reviewTarget.subjectName.trim() || undefined,
      exam_unique_no: defaultExamUniqueNo,
      cd_value: defaultCdValue || undefined,
      subject_mode: reviewTarget.subjectMode,
      subject_start_index: Number(reviewTarget.subjectStartIndex) || 1,
      subject_end_index: Number(reviewTarget.subjectEndIndex) || 1,
      subtype_name: reviewTarget.subtypeName.trim() || undefined,
      question_range: questionRange,
      questions: targetRows.map((row) => ({
        site_question_id: toNumber(row.id),
        exam_unique_no: defaultExamUniqueNo,
        cd_value: defaultCdValue || row.cdValue || undefined,
        question_no: toNumber(row.number),
      })),
      options: {
        headless: true,
        write_excel: true,
        include_raw_data: Boolean(reviewTarget.includeRawData),
      },
    };
  };

  const applyAiReviewResult = async (result) => {
    const items = result?.items || [];

    for (const item of items) {
      const siteQuestionId = item.site_question_id;
      if (!siteQuestionId) continue;

      const issues = item.issues || [];
      const hasIssue = item.review_status === "issue_found" || issues.length > 0;
      const errorType = hasIssue ? uniqueJoin(issues.map((issue) => issue.issue_type)) : "";
      const reason = hasIssue
        ? issues.map((issue, index) => {
            const title = `[${index + 1}] ${issue.issue_area || ""} / ${issue.issue_type || ""}`.trim();
            const suggestion = issue.suggestion ? `\n수정 제안: ${issue.suggestion}` : "";
            return `${title}\n${issue.reason || ""}${suggestion}`;
          }).join("\n\n")
        : "";

      const res = await fetch(`${API_BASE}/api/questions/${siteQuestionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_status: hasIssue ? "오류있음" : "정상",
          error_type: errorType,
          reason,
          reviewer: "AI검수",
          reflect_status: "미반영",
        }),
      });
      if (!res.ok) throw new Error(`IDX ${siteQuestionId} 결과 저장 실패`);
    }
  };

  const waitForReviewResult = async (baseUrl, jobId) => {
    for (let i = 0; i < 360; i += 1) {
      const statusRes = await fetch(`${baseUrl}/review-jobs/${jobId}`);
      if (!statusRes.ok) throw new Error(`검수 상태 조회 실패: ${statusRes.status}`);
      const statusJson = await statusRes.json();
      setReviewJobInfo(statusJson);

      if (statusJson.status === "completed") {
        const resultRes = await fetch(`${baseUrl}/review-jobs/${jobId}/result`);
        if (!resultRes.ok) throw new Error(`검수 결과 조회 실패: ${resultRes.status}`);
        return await resultRes.json();
      }
      if (statusJson.status === "failed") throw new Error(statusJson.error_message || "검수 작업이 실패했습니다.");
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    throw new Error("검수 결과 대기 시간이 초과되었습니다.");
  };

  const runAiReview = async (mode = reviewTarget.targetScope, statusFilter = null) => {
    if (reviewRunning) return;
    const baseUrl = reviewTarget.reviewApiBase.replace(/\/$/, "");
    let targetRows = getReviewRows(mode);

    if (statusFilter === "uncheckedOrError") {
      targetRows = targetRows.filter((row) => (row.reviewStatus || "").includes("미검수") || (row.reviewStatus || "").includes("오류"));
    } else if (statusFilter === "errorOnly") {
      targetRows = targetRows.filter((row) => (row.reviewStatus || "").includes("오류"));
    } else if (statusFilter === "holdOnly") {
      targetRows = targetRows.filter((row) => (row.reviewStatus || "").includes("보류"));
    } else if (statusFilter === "normalOnly") {
      targetRows = targetRows.filter((row) => (row.reviewStatus || "").includes("정상"));
    }

    if (!reviewTarget.targetMapId) {
      alert("검수 대상 매핑을 먼저 선택해 주세요.");
      return;
    }
    if (!reviewTarget.courseName.trim() || !reviewTarget.setName.trim()) {
      alert("선택된 매핑에 강좌명 또는 세트명이 없습니다. 매핑 DB를 확인해 주세요.");
      return;
    }
    if (targetRows.length === 0) {
      alert("검수할 문제가 없습니다. 선택한 매핑, 문제 범위, 체크 선택 상태를 확인해 주세요.");
      return;
    }

    const proceed = window.confirm(`${targetRows.length}개 문제를 AI 검수 API로 보낼까요?`);
    if (!proceed) return;

    setReviewRunning(true);
    setReviewJobInfo(null);

    try {
      const payload = buildReviewPayload(targetRows);
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
      setReviewJobInfo(created);
      const result = await waitForReviewResult(baseUrl, created.job_id);
      await applyAiReviewResult(result);
      await fetchQuestions();
      alert(`AI 검수가 완료되었습니다. 전체 ${result.summary?.total_questions ?? 0}개 / 오류 ${result.summary?.issue_question_count ?? 0}개`);
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
      error_types: errorTypes,
      memo: row.reason !== "-" ? row.reason : getValue(raw, ["memo", "review_memo", "reason"], ""),
      reflect_status: row.reflectStatus || getValue(raw, ["reflect_status"], "미반영"),
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

  const saveReview = async (nextStatus) => {
    const updated = {
      ...editForm,
      review_status: nextStatus || editForm.status,
      status: nextStatus || editForm.status,
      error_type: (editForm.error_types || []).join(", "),
      reason: editForm.memo,
    };

    try {
      const res = await fetch(`${API_BASE}/api/questions/${editForm.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          exam_unique_no: updated.exam_unique_no,
          cd_value: updated.cd_value,
          question_no: updated.question_no,
          question: updated.question,
          view_text: updated.view_text,
          image_url: updated.image_url,
          choice1: updated.choice1 || "",
          choice2: updated.choice2 || "",
          choice3: updated.choice3 || "",
          choice4: updated.choice4 || "",
          choice1_image_url: updated.choice1_image_url || "",
          choice2_image_url: updated.choice2_image_url || "",
          choice3_image_url: updated.choice3_image_url || "",
          choice4_image_url: updated.choice4_image_url || "",
          review_status: updated.review_status,
          error_type: updated.error_type,
          reason: updated.reason,
          reviewer: "admin",
          reflect_status: updated.reflect_status || "미반영",
        }),
      });
      if (!res.ok) throw new Error("DB 저장 실패");
      await fetchQuestions();
      closeReviewModal();
    } catch (error) {
      console.error(error);
      alert("저장 중 오류가 발생했습니다.");
    }
  };

  const selectedTargetMap = targetMaps.find((item) => String(item.id) === String(reviewTarget.targetMapId));

  const renderTargetForm = () => (
    <section className="filter-card review-target-card">
      <div className="filter-section-title">검수 대상 지정</div>
      <div className="filter-grid review-target-grid compact-review-grid">
        <label className="field">
          <span>검수 API 주소</span>
          <input name="reviewApiBase" value={reviewTarget.reviewApiBase} onChange={handleReviewTargetChange} placeholder="예: http://192.168.219.167:8000" />
        </label>
        <label className="field field-wide">
          <span>검수 대상 매핑 <em className="field-hint">세트명+과목명 → 시험 고유 번호</em></span>
          <select name="targetMapId" value={reviewTarget.targetMapId} onChange={handleReviewTargetChange}>
            <option value="">검수 대상 매핑을 선택하세요</option>
            {targetMaps.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name || `${item.set_name || "세트"} / ${item.subtype_name || item.subject_name || item.exam_unique_no}`}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>문제 범위 (선택)</span>
          <input name="questionRange" value={reviewTarget.questionRange} onChange={handleReviewTargetChange} placeholder="비우면 선택 매핑 전체" />
        </label>
        <label className="field">
          <span>검수 대상</span>
          <select name="targetScope" value={reviewTarget.targetScope} onChange={handleReviewTargetChange}>
            <option value="filtered">선택 매핑 기준 전체</option>
            <option value="selected">체크 선택 문제 중 선택 매핑 기준</option>
          </select>
        </label>
        <label className="field checkbox-field">
          <span>raw_data 포함</span>
          <label className="inline-check inline-check-full">
            <input type="checkbox" name="includeRawData" checked={reviewTarget.includeRawData} onChange={handleReviewTargetChange} />
            <em>결과 JSON에 원본 문제 데이터 포함</em>
          </label>
        </label>
      </div>

      {selectedTargetMap ? (
        <div className="review-status-line map-summary-line">
          <strong>선택된 매핑</strong>
          <span>강좌명: {selectedTargetMap.course_name || "-"}</span>
          <span>세트명: {selectedTargetMap.set_name || "-"}</span>
          <span>과목명: {selectedTargetMap.subject_name || "-"}</span>
          <span>하위유형: {selectedTargetMap.subtype_name || "-"}</span>
          <span>시험 고유 번호: {selectedTargetMap.exam_unique_no || "-"}</span>
          <span>CD값: {selectedTargetMap.cd_value || "-"}</span>
        </div>
      ) : (
        <div className="review-status-line map-summary-line muted-line">
          <strong>매핑 미선택</strong>
          <span>엑셀의 검수대상매핑 시트를 업로드한 뒤 검수 대상을 선택해 주세요.</span>
        </div>
      )}

      {reviewJobInfo && (
        <div className="review-status-line">
          <strong>최근 작업</strong>
          <span>job_id: {reviewJobInfo.job_id || "-"}</span>
          <span>status: {reviewJobInfo.status || "-"}</span>
        </div>
      )}

      <div className="filter-actions">
        <button className="btn btn-primary" type="button" onClick={() => { fetchQuestions(); fetchTargetMaps(); }} disabled={reviewRunning}>DB 새로고침</button>
        <button className="btn btn-light" type="button" onClick={() => setReviewTarget(DEFAULT_REVIEW_TARGET)} disabled={reviewRunning}>입력 초기화</button>
        <button className="btn btn-success" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "uncheckedOrError")} disabled={reviewRunning}>{reviewRunning ? "검수 진행중" : "미검수/오류 문제 검수하기"}</button>
        <button className="btn btn-warning" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "errorOnly")} disabled={reviewRunning}>오류있음만 검수하기</button>
        <button className="btn btn-gray" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "holdOnly")} disabled={reviewRunning}>보류만 검수하기</button>
        <button className="btn btn-blue" type="button" onClick={() => runAiReview(reviewTarget.targetScope, "normalOnly")} disabled={reviewRunning}>정상만 최종검수하기</button>
        <button className="btn btn-light" type="button" onClick={() => runAiReview(reviewTarget.targetScope, null)} disabled={reviewRunning}>선택 매핑 전체 검수</button>
      </div>
    </section>
  );

  const renderSearchFilters = () => (
    <section className="filter-card">
      <div className="filter-section-title">문제 목록 검색 조건</div>
      <div className="filter-grid">
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
        <label className="field field-wide">
          <span>검색</span>
          <input name="search" value={filters.search} onChange={handleFilterChange} placeholder="IDX, 시험 고유 번호, CD값, 문제, 번호 검색" />
        </label>
        <label className="field">
          <span>페이지당 개수</span>
          <select name="pageSize" value={filters.pageSize} onChange={handleFilterChange}>
            <option value="20">20개</option>
            <option value="50">50개</option>
            <option value="100">100개</option>
          </select>
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

  const renderQuestionTable = ({ rowsToShow, title, showCount = false, emptyText = "조회된 문제가 없습니다." }) => {
    const allVisibleChecked = rowsToShow.length > 0 && rowsToShow.every((row) => selectedRows.includes(row.rowKey));

    return (
      <section className="table-card">
        <div className="table-top">
          <div className="table-title">
            {title}{showCount ? <> <strong>{rowsToShow.length.toLocaleString()}</strong>건</> : null}
          </div>
          <div className="table-actions">
            <button className="btn btn-light" type="button" onClick={() => handleBulkAction("정상 처리")}>선택 정상처리</button>
            <button className="btn btn-warning" type="button" onClick={() => handleBulkAction("보류")}>선택 보류</button>
            <button className="btn btn-danger" type="button" onClick={() => handleBulkAction("제외")}>선택 제외</button>
            <button className="btn btn-danger" type="button" onClick={() => handleBulkAction("삭제")}>선택 삭제</button>
            <button className="btn btn-success" type="button" onClick={() => handleBulkAction("검수완료 최종반영")}>검수완료 최종반영</button>
          </div>
        </div>

        {loadError && <div className="alert">{loadError}</div>}

        <div className="table-wrap">
          <table className="review-table compact-review-table">
            <thead>
              <tr>
                <th className="check-col"><input type="checkbox" checked={allVisibleChecked} onChange={(event) => toggleAll(event.target.checked, rowsToShow)} /></th>
                <th>IDX</th>
                <th>시험 고유 번호</th>
                <th>CD값</th>
                <th>번호</th>
                <th>문제</th>
                <th>검수상태</th>
                <th>오류유형</th>
                <th>기타사유</th>
                <th>검수자</th>
                <th>검수일</th>
                <th>반영상태</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan="13" className="empty-cell">데이터를 불러오는 중입니다.</td></tr>
              ) : rowsToShow.length === 0 ? (
                <tr><td colSpan="13" className="empty-cell">{emptyText}</td></tr>
              ) : rowsToShow.map((row) => {
                const errorTypes = splitErrorTypes(row.errorType);
                return (
                  <tr key={row.rowKey}>
                    <td className="check-col"><input type="checkbox" checked={selectedRows.includes(row.rowKey)} onChange={() => toggleRow(row.rowKey)} /></td>
                    <td>{row.id}</td>
                    <td>{row.examUniqueNo || "-"}</td>
                    <td>{row.cdValue || "-"}</td>
                    <td>{row.number}</td>
                    <td className="question-cell">{row.question}</td>
                    <td><div className="status-box"><span className={`badge ${getStatusClass(row.reviewStatus)}`}>{row.reviewStatus}</span>{row.statusMemo && <small>{row.statusMemo}</small>}</div></td>
                    <td><div className="pill-list">{errorTypes.length === 0 ? <span className="pill pill-muted">-</span> : errorTypes.map((type) => <span key={type} className="pill pill-error">{type}</span>)}</div></td>
                    <td className="reason-cell">{row.reason}</td>
                    <td>{row.reviewer}</td>
                    <td>{row.reviewedAt}</td>
                    <td><span className={`reflect ${getReflectClass(row.reflectStatus)}`}>{row.reflectStatus}</span></td>
                    <td><button className="btn btn-row" type="button" onClick={() => openReviewModal(row)}>검수하기</button></td>
                  </tr>
                );
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
          <h1>{pageMode === "review" ? "AI 검수 실행" : "문제 목록 검색"}</h1>
        </div>
        <div className="header-actions">
          <button className={`btn ${pageMode === "review" ? "btn-primary" : "btn-light"}`} type="button" onClick={() => setPageMode("review")}>검수 화면</button>
          <button className={`btn ${pageMode === "list" ? "btn-primary" : "btn-light"}`} type="button" onClick={() => setPageMode("list")}>문제 목록 검색</button>
          <input ref={fileInputRef} type="file" accept=".xlsx,.xls,.csv" style={{ display: "none" }} onChange={handleExcelUpload} />
          <button className="btn btn-primary" type="button" onClick={() => fileInputRef.current?.click()}>엑셀 업로드</button>
        </div>
      </header>

      {pageMode === "review" ? (
        <>
          {renderTargetForm()}
          {renderQuestionTable({ rowsToShow: reviewTargetRows, title: "검수 대상 문제 내역", showCount: false, emptyText: "선택한 검수 대상 매핑에 해당하는 문제가 없습니다. 매핑 DB와 문제 DB의 시험 고유 번호를 확인해 주세요." })}
        </>
      ) : (
        <>
          {renderStats()}
          {renderSearchFilters()}
          {renderQuestionTable({ rowsToShow: pageRows, title: "문제 목록 ", showCount: true, emptyText: "조회된 문제가 없습니다." })}
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
                <div className="info-grid">
                  <div><span>시험 고유 번호</span><strong>{editForm.exam_unique_no || "-"}</strong></div>
                  <div><span>CD값</span><strong>{editForm.cd_value || "-"}</strong></div>
                  <div><span>번호</span><strong>{editForm.question_no || "-"}</strong></div>
                  <div><span>검수상태</span><strong>{editForm.status || "-"}</strong></div>
                </div>
                <h3>문제</h3><div className="readonly-box">{editForm.question || "문제 없음"}</div>
                <h3>보기</h3><div className="readonly-box muted">{editForm.view_text || "보기 없음"}</div>
                <h3>보기 이미지</h3><div className="readonly-box muted">{editForm.image_url || "보기 이미지 없음"}</div>
                <h3>선지</h3>
                <div className="choice-list">
                  {[editForm.choice1, editForm.choice2, editForm.choice3, editForm.choice4].filter(Boolean).map((choice, index) => (
                    <div className="choice-item" key={`${choice}-${index}`}><span>{index + 1}</span><p>{choice}</p></div>
                  ))}
                </div>
                <h3>검수 사유</h3><div className="readonly-box">{editForm.reason || editForm.memo || "-"}</div>
              </section>
              <section className="review-panel edit-panel">
                <h3>수정</h3>
                <div className="edit-grid">
                  <label>시험 고유 번호<input name="exam_unique_no" value={editForm.exam_unique_no} onChange={handleEditChange} /></label>
                  <label>CD값<input name="cd_value" value={editForm.cd_value} onChange={handleEditChange} /></label>
                  <label>문제번호<input name="question_no" value={editForm.question_no} onChange={handleEditChange} /></label>
                </div>
                <label className="full-field">문제<textarea name="question" value={editForm.question} onChange={handleEditChange} /></label>
                <label className="full-field">보기<textarea name="view_text" value={editForm.view_text} onChange={handleEditChange} /></label>
                <label className="full-field">보기 이미지 URL<textarea name="image_url" value={editForm.image_url} onChange={handleEditChange} /></label>
                <div className="choice-edit-group">
                  <label className="full-field">선지1<textarea name="choice1" value={editForm.choice1} onChange={handleEditChange} /></label>
                  <label className="full-field">선지1 이미지 URL<textarea name="choice1_image_url" value={editForm.choice1_image_url} onChange={handleEditChange} /></label>
                  <label className="full-field">선지2<textarea name="choice2" value={editForm.choice2} onChange={handleEditChange} /></label>
                  <label className="full-field">선지2 이미지 URL<textarea name="choice2_image_url" value={editForm.choice2_image_url} onChange={handleEditChange} /></label>
                  <label className="full-field">선지3<textarea name="choice3" value={editForm.choice3} onChange={handleEditChange} /></label>
                  <label className="full-field">선지3 이미지 URL<textarea name="choice3_image_url" value={editForm.choice3_image_url} onChange={handleEditChange} /></label>
                  <label className="full-field">선지4<textarea name="choice4" value={editForm.choice4} onChange={handleEditChange} /></label>
                  <label className="full-field">선지4 이미지 URL<textarea name="choice4_image_url" value={editForm.choice4_image_url} onChange={handleEditChange} /></label>
                </div>
              </section>
              <aside className="review-panel side-panel">
                <label className="full-field">검수 상태<select name="status" value={editForm.status} onChange={handleEditChange}><option value="완료">완료</option><option value="정상">정상</option><option value="오류있음">오류있음</option><option value="보류">보류</option><option value="검수중">검수중</option></select></label>
                <h3>오류 유형 다중 선택</h3>
                <div className="error-type-columns">
                  <div className="error-type-box"><h4>내용 오류</h4><div className="error-check-list">{CONTENT_ERROR_TYPES.map((type) => <label key={type} className="error-check-item"><input type="checkbox" checked={editForm.error_types.includes(type)} onChange={() => toggleErrorType(type)} /><span>{type}</span></label>)}</div></div>
                  <div className="error-type-box"><h4>형식 오류</h4><div className="error-check-list">{FORMAT_ERROR_TYPES.map((type) => <label key={type} className="error-check-item"><input type="checkbox" checked={editForm.error_types.includes(type)} onChange={() => toggleErrorType(type)} /><span>{type}</span></label>)}</div></div>
                </div>
                <label className="full-field">기타 사유 / 검수 메모<textarea name="memo" value={editForm.memo} onChange={handleEditChange} placeholder="기타를 선택했거나 추가 설명이 필요하면 입력하세요." /></label>
                <div className="side-actions">
                  <button type="button" className="save-green" onClick={() => saveReview("정상")}>정상 처리 후 닫기</button>
                  <button type="button" className="save-dark" onClick={() => saveReview(editForm.status)}>저장 후 닫기</button>
                  <button type="button" className="save-yellow" onClick={() => saveReview("보류")}>보류 처리</button>
                  <button type="button" className="save-red" onClick={closeReviewModal}>닫기</button>
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
