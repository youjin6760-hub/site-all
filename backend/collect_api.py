import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin, parse_qs, parse_qsl, urlencode, urlunparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from typing import Any


ROOT = Path(os.getenv("APP_ROOT", Path(__file__).resolve().parent)).resolve()

JOBS_DIR = Path(os.getenv("JOBS_DIR", ROOT / "jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)

RAW_DIR = Path(os.getenv("RAW_DIR", ROOT / "raw")).resolve()

DEBUG_DIR = Path(os.getenv("DEBUG_DIR", ROOT / "debug")).resolve()
DEBUG_ENABLED = os.getenv("DEBUG_ENABLED", "false").lower() == "true"
DEBUG_SAVE_KEYWORDS = ("fail", "error", "not_found", "timeout", "failed")

VERBOSE_COLLECT = os.getenv("VERBOSE_COLLECT", "false").lower() == "true"
PROGRESS_LOG = os.getenv("PROGRESS_LOG", "true").lower() == "true"


def debug_log(message: str):
    """
    반복 디버그 로그용.
    VERBOSE_COLLECT=true일 때만 출력합니다.
    """
    if VERBOSE_COLLECT:
        print(message)


def progress_log(message: str):
    """
    진행 상황 로그용.
    PROGRESS_LOG=false이면 진행 로그도 숨깁니다.
    오류/경고/RAW 저장 로그는 기존 print 그대로 둡니다.
    """
    if PROGRESS_LOG:
        print(message)


IMG_DIR = Path(os.getenv("IMG_DIR", ROOT / "images")).resolve()

TARGET_MAIN_URL = "https://www.dataedupt.kr/sub/main/main.php"
ALLOWED_HOSTS = {
    "www.dataedupt.kr",
    "dataedupt.kr",
}


def load_config():
    with open(ROOT / "run_config.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        return data

    raise ValueError("run_config.json은 객체 또는 객체 리스트 형식이어야 합니다.")



def set_runtime_dirs(job_dir: str | Path | None = None):
    """
    API 실행 시 job_id별 작업 폴더를 사용하도록 전역 저장 경로를 변경합니다.
    기존 함수들이 RAW_DIR / DEBUG_DIR / IMG_DIR 전역값을 사용하므로, 실행 전에 한 번만 호출합니다.
    """
    global RAW_DIR, DEBUG_DIR, IMG_DIR

    if job_dir is None:
        RAW_DIR = Path(os.getenv("RAW_DIR", ROOT / "raw")).resolve()
        DEBUG_DIR = Path(os.getenv("DEBUG_DIR", ROOT / "debug")).resolve()
        IMG_DIR = Path(os.getenv("IMG_DIR", ROOT / "images")).resolve()
    else:
        job_dir = Path(job_dir).resolve()
        RAW_DIR = job_dir / "raw"
        DEBUG_DIR = job_dir / "debug"
        IMG_DIR = job_dir / "images"

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)


def normalize_target_configs(target: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    사이트에서 target 값을 한 번만 넘기면 collect.py가 처리할 config 리스트로 변환합니다.

    지원 형식:
    1) 기존 run_config.json과 같은 단일 객체
    2) 기존 run_config.json과 같은 객체 리스트
    3) {"targets": [...]} 또는 {"configs": [...]} 래핑 객체
    4) {"questions": [{"site_question_id": 501, "question_no": 41}, ...]} 형식
       - 이 경우 question_numbers에 번호 목록을 넣어 필요한 문제만 저장합니다.
    """
    if isinstance(target, list):
        return [dict(x) for x in target]

    if not isinstance(target, dict):
        raise ValueError("target은 객체 또는 객체 리스트 형식이어야 합니다.")

    if isinstance(target.get("targets"), list):
        return [dict(x) for x in target["targets"]]

    if isinstance(target.get("configs"), list):
        return [dict(x) for x in target["configs"]]

    cfg = dict(target)

    questions = cfg.get("questions")
    question_range = str(cfg.get("question_range") or "").strip().lower()

    # question_range가 all이면 questions가 있어도 직접 이동용 question_numbers로 변환하지 않습니다.
    # 즉, all 수집은 다음 버튼 순회 방식으로 처리합니다.
    if question_range != "all" and isinstance(questions, list) and questions:
        nums = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            qno = q.get("question_no") or q.get("no")
            if qno is None:
                continue
            nums.append(int(qno))

        if nums:
            cfg["question_numbers"] = sorted(set(nums))
            cfg["question_range"] = f"{min(nums)}-{max(nums)}"

    return [cfg]


def parse_question_selection(cfg: dict[str, Any]):
    """
    반환: (selected_set, start_no, end_no)
    - selected_set이 None이면 start~end 범위 전체 저장
    - selected_set이 set이면 해당 문제 번호만 저장
    """

    # 1순위: question_numbers가 있으면 선택 문제 수집
    # question_range가 all이어도 체크 선택 문제라면 question_numbers를 우선합니다.
    qnums = cfg.get("question_numbers")
    if qnums:
        nums = sorted({int(x) for x in qnums})
        return set(nums), nums[0], nums[-1]

    # 2순위: question_numbers가 없을 때만 question_range 사용
    question_range = str(cfg.get("question_range") or "all").strip().lower()

    if question_range == "all":
        return None, 1, 9999

    qrange = parse_question_range(question_range)
    if qrange is None:
        return None, 1, 9999

    start_no, end_no = qrange
    return None, start_no, end_no

def should_save_question(question_no: int, selected_set, start_no: int, end_no: int) -> bool:
    if selected_set is not None:
        return question_no in selected_set
    return start_no <= question_no <= end_no


def load_json_files_from_raw() -> list[dict[str, Any]]:
    files = sorted(RAW_DIR.glob("*.json"), key=question_no_from_filename_safe)
    result = []
    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            result.append(json.load(f))
    return result


def question_no_from_filename_safe(path: Path):
    try:
        return int(path.stem.split("_")[-1])
    except Exception:
        return 999999


EXPLANATION_BODY_SELECTORS = [
    "div.tg2g2 div.more-c div.t1",  # fallback
    "div.tg2g2 > div.t1",           # fallback
]

EXPLANATION_KEYWORD_SELECTORS = [
    "div.tg2g2 div.more-c div.t2 a.tag",  # fallback
    "div.tg2g2 div.t2 a.tag",             # fallback
    "div.tg2g2 a.tag",
]

PT_TEACHER_TIP_TITLE = "PT쌤 합격팁"
BIGIBOT_TITLE = "비기봇 해설"

PT_TEACHER_TIP_TITLE_VARIANTS = [
    "PT쌤 합격팁",
    "PT쌤합격팁",
]

BIGIBOT_TITLE_VARIANTS = [
    "비기봇 해설",
    "비기봇해설",
]

def make_empty_pt_teacher_tip() -> dict:
    return {
        "has_tip": False,
    }


def make_not_attempted_explanation_capture_meta() -> dict:
    return {
        "attempted": False,
        "zoom_applied": False,
        "fits_in_single_before_zoom": None,
        "fits_in_single_after_zoom": None,
        "needs_manual_review": False,
        "capture_mode": "not_attempted",
        "image_count": 0,
    }


def make_not_needed_explanation_capture_meta() -> dict:
    return {
        "attempted": False,
        "zoom_applied": False,
        "fits_in_single_before_zoom": None,
        "fits_in_single_after_zoom": None,
        "needs_manual_review": False,
        "capture_mode": "not_needed",
        "image_count": 0,
    }


def make_not_attempted_question_image_capture_meta() -> dict:
    return {
        "attempted": False,
        "needs_manual_review": False,
        "capture_mode": "not_attempted",
        "image_count": 0,
        "failed_indexes": [],
    }


def get_collect_options(cfg: dict[str, Any]) -> dict[str, Any]:
    options = cfg.get("options") or {}
    return (
        cfg.get("collect_options")
        or options.get("collect_options")
        or {}
    )
    

def normalize_card_text(value: str) -> str:
    value = value or ""
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def contains_any_title(text: str, titles: list[str]) -> bool:
    text = normalize_card_text(text)
    compact_text = re.sub(r"\s+", "", text)

    for title in titles:
        title = normalize_card_text(title)
        compact_title = re.sub(r"\s+", "", title)

        if title in text:
            return True

        if compact_title in compact_text:
            return True

    return False


def get_help_card_locator(page, title_variants):
    """
    div#m-help1 안의 div.tg2g2 카드 중
    PT쌤 합격팁 / 비기봇 해설 카드를 제목 기준으로 찾습니다.
    """
    if isinstance(title_variants, str):
        title_variants = [title_variants]

    try:
        cards = page.locator("div#m-help1 div.tg2g2")
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)

            try:
                card_text = normalize_card_text(card.inner_text())
            except Exception:
                card_text = ""

            if contains_any_title(card_text, title_variants):
                return card

    except Exception as e:
        print(f"[도움말 카드 탐색 오류] {title_variants}: {e}")

    return None


def get_bigibot_card_locator(page):
    return get_help_card_locator(page, BIGIBOT_TITLE_VARIANTS)


def get_pt_teacher_tip_card_locator(page):
    return get_help_card_locator(page, PT_TEACHER_TIP_TITLE_VARIANTS)


def get_explanation_body_locator(page):
    """
    비기봇 해설 본문만 반환합니다.
    PT쌤 합격팁의 분석 div.t1과 섞이지 않게 카드 제목 기준으로 먼저 분리합니다.
    """
    card = get_bigibot_card_locator(page)

    if card is not None:
        selectors = [
            "div.more-c > div.t1",
            "div.more-c div.t1",
            ":scope > div.t1",
            "div.t1",
        ]

        for sel in selectors:
            try:
                loc = card.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=1000):
                    return loc
            except Exception:
                pass

        for sel in selectors:
            try:
                loc = card.locator(sel).first
                if loc.count() > 0:
                    return loc
            except Exception:
                pass

    # 비기봇 제목을 못 찾았을 때만 기존 방식 fallback
    for sel in EXPLANATION_BODY_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible(timeout=1000):
                return loc
        except Exception:
            pass

    for sel in EXPLANATION_BODY_SELECTORS:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0:
                return loc
        except Exception:
            pass

    return page.locator(EXPLANATION_BODY_SELECTORS[0]).first


def sanitize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_text(locator):
    try:
        return sanitize_text(locator.inner_text())
    except Exception:
        return ""

def normalize_multiline_text(value: str) -> str:
    """
    문제/보기/선지 본문용 정리 함수입니다.
    <br>에서 만들어진 줄바꿈은 유지하고,
    같은 줄 안의 불필요한 공백만 정리합니다.
    """
    if not value:
        return ""

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ")

    # 줄 안의 공백만 정리
    lines = [
        re.sub(r"[ \t\f\v]+", " ", line).strip()
        for line in value.split("\n")
    ]

    text = "\n".join(lines)

    # 3줄 이상 빈 줄은 1줄 빈 줄로 제한
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def locator_text_with_br(locator) -> str:
    """
    Playwright locator에서 <br>을 실제 줄바꿈으로 보존해서 텍스트를 가져옵니다.
    """
    try:
        text = locator.evaluate("""
            (el) => {
                const read = (node) => {
                    if (node.nodeType === Node.TEXT_NODE) {
                        return node.textContent || "";
                    }

                    if (node.nodeType !== Node.ELEMENT_NODE) {
                        return "";
                    }

                    if (node.tagName && node.tagName.toLowerCase() === "br") {
                        return "\\n";
                    }

                    let result = "";
                    for (const child of node.childNodes) {
                        result += read(child);
                    }
                    return result;
                };

                return read(el);
            }
        """)

        return normalize_multiline_text(text)

    except Exception:
        try:
            return normalize_multiline_text(locator.inner_text())
        except Exception:
            return ""

def norm_id_text(x: str):
    x = (x or "").strip()
    x = re.sub(r"[^\w가-힣]+", "_", x)
    x = re.sub(r"_+", "_", x).strip("_")
    return x


def make_question_id(course_name, set_name, subject_name, question_no, sub_title=None):
    # 하위 카드가 있을 때만 sub_title 포함
    if sub_title:
        if subject_name:
            return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(subject_name)}_{norm_id_text(sub_title)}_{question_no}"
        return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(sub_title)}_{question_no}"

    # 하위 카드가 없을 때는 기존 형식 유지
    if subject_name:
        return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{norm_id_text(subject_name)}_{question_no}"
    return f"{norm_id_text(course_name)}_{norm_id_text(set_name)}_{question_no}"


def parse_question_range(question_range: str):
    if question_range == "all":
        return None
    m = re.match(r"(\d+)\s*-\s*(\d+)", question_range)
    if not m:
        raise ValueError("question_range는 '1-10' 또는 'all' 형식이어야 합니다.")
    return int(m.group(1)), int(m.group(2))


def is_allowed_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host in ALLOWED_HOSTS


def save_debug(page, name="debug"):
    # DEBUG_ENABLED=true이면 모든 debug를 저장합니다.
    # 기본값 false에서는 오류성 debug만 저장합니다.
    should_save = DEBUG_ENABLED or any(keyword in name for keyword in DEBUG_SAVE_KEYWORDS)

    if not should_save:
        return

    try:
        screenshot_path = DEBUG_DIR / f"{name}.png"
        html_path = DEBUG_DIR / f"{name}.html"

        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")

        print(f"[디버그 저장] screenshot={screenshot_path}")
        print(f"[디버그 저장] html={html_path}")
    except Exception as e:
        print(f"[디버그 저장 실패] {e}")


def handle_new_page(new_page):
    try:
        url = new_page.url or ""
        print(f"[새 페이지 감지] {url}")

        if url in ("", "about:blank"):
            print("[유지] 초기 빈 페이지는 닫지 않습니다.")
            return

        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        url = new_page.url or ""
        print(f"[새 페이지 최종 URL] {url}")

        if not is_allowed_url(url):
            print(f"[차단/닫기] 허용되지 않은 페이지라 닫습니다: {url}")
            try:
                new_page.close()
            except Exception:
                pass

    except Exception as e:
        print(f"[handle_new_page 오류] {e}")


def ensure_main_page(page):
    try:
        current = page.url or ""
        if current and not is_allowed_url(current):
            print(f"[복귀] 허용되지 않은 URL 감지: {current}")
            page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
    except Exception as e:
        print(f"[ensure_main_page 오류] {e}")


def click_by_text(page, text, exact=False, timeout=7000):
    locator = page.get_by_text(text, exact=exact)
    locator.first.wait_for(timeout=timeout)
    locator.first.scroll_into_view_if_needed()
    locator.first.click(timeout=3000)
    page.wait_for_timeout(1200)


def click_bottom_nav_mypt(page):
    try:
        btn = page.locator("a.a1[href*='mypt1.php'] span.t1")
        btn.first.wait_for(timeout=5000)
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 마이PT 클릭")
        return True
    except Exception as e:
        print(f"[오류] 마이PT 클릭 실패: {e}")
        save_debug(page, "mypt_click_fail")
        return False


def click_bottom_nav_study(page):
    try:
        btn = page.locator("li.m.study a.a1").first
        btn.wait_for(state="attached", timeout=5000)
        btn.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 하단 공부하기 클릭")
        return True
    except Exception as e:
        print(f"[오류] 하단 공부하기 클릭 실패: {e}")
        save_debug(page, "bottom_study_click_fail")
        return False


def handle_resume_popup(page):
    print("[진입] 이어서 보기 팝업 확인 중...")

    try:
        btn = page.locator("div.cp1write2 button.m-init1:visible").first

        try:
            btn.wait_for(state="visible", timeout=700)
        except Exception:
            print("[정보] 이어보기 팝업 없음 - 바로 문제 진입 케이스")
            return False

        btn.click(timeout=3000, force=True)
        wait_for_question_ready(page, timeout=8000)
        print("[성공] '1번부터 보기' 클릭")
        return True

    except Exception as e:
        print(f"[오류] 팝업 클릭 실패: {e}")
        save_debug(page, "resume_popup_fail")
        return False


def get_subject_targets(page, subject_name, subtype_name=None):
    """
    반환 규칙
    - 하위 카드가 없으면: 기존 방식용 target 1개 반환
    - 하위 카드가 있으면:
      - subtype_name 없으면 하위 카드 전부 반환(위에서 아래 순서)
      - subtype_name 있으면 해당 문자열 포함하는 하위 카드만 반환
    """
    results = []

    try:
        cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
        count = cards.count()

        for i in range(count):
            card = cards.nth(i)

            try:
                title = (card.locator(":scope > span.t1").first.text_content() or "").strip()
                title = re.sub(r"\s+", " ", title)
            except Exception:
                title = ""

            if subject_name not in title:
                continue

            sub_cards = card.locator(":scope ul.lst2 > li.li2")
            sub_count = sub_cards.count()

            # 하위 카드 없음 -> 기존 로직 유지
            if sub_count == 0:
                return [{
                    "subject_name": title,
                    "sub_title": None,
                    "card_index": i,
                    "sub_index": None,
                    "has_subcards": False,
                }]

            # 하위 카드 있음
            for j in range(sub_count):
                sub = sub_cards.nth(j)

                try:
                    sub_title = (sub.locator("span.t1").first.text_content() or "").strip()
                    sub_title = re.sub(r"\s+", " ", sub_title)
                except Exception:
                    sub_title = ""

                if subtype_name and subtype_name not in sub_title:
                    continue

                results.append({
                    "subject_name": title,
                    "sub_title": sub_title,
                    "card_index": i,
                    "sub_index": j,
                    "has_subcards": True,
                })

            return results

    except Exception as e:
        print(f"[오류] 과목 실행 대상 조회 실패: {e}")
        save_debug(page, f"subject_target_lookup_fail_{norm_id_text(subject_name)}")

    return results


def click_subject_target(page, target):
    """
    target 기준으로 실제 클릭
    - 하위 카드 없으면 기존 방식
    - 하위 카드 있으면 해당 하위 카드 안에서
      이어하기 우선 -> 공부하기 -> fallback a.b2
    """
    try:
        cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
        card = cards.nth(target["card_index"])

        # 하위 카드 없는 기존 구조
        if target["sub_index"] is None:
            btn = card.locator("a.b2").first
            btn.wait_for(state="attached", timeout=5000)

            btn_text = (btn.text_content() or "").strip()
            btn_text = re.sub(r"\s+", " ", btn_text)
            debug_log(f"[디버그] '{target['subject_name']}' 버튼 문구: {btn_text}")

            btn.click(timeout=3000, force=True)
            print(f"[성공] 상위 과목 클릭: {target['subject_name']}")
            handle_resume_popup(page)

            if not wait_for_question_ready(page, timeout=8000):
                print("[경고] 과목 클릭 후 문제 화면 준비 확인 실패")
                return False

            return True

        # 하위 카드 있는 구조
        sub = card.locator(":scope ul.lst2 > li.li2").nth(target["sub_index"])

        try:
            sub_title = (sub.locator("span.t1").first.text_content() or "").strip()
            sub_title = re.sub(r"\s+", " ", sub_title)
        except Exception:
            sub_title = target.get("sub_title") or ""

        btn = None

        try:
            candidate = sub.locator("a.b2:has-text('해설보며 이어하기')").first
            if candidate.count() > 0 and candidate.is_visible():
                btn = candidate
        except Exception:
            pass

        if btn is None:
            try:
                candidate = sub.locator("a.b2:has-text('해설보며 공부하기')").first
                if candidate.count() > 0 and candidate.is_visible():
                    btn = candidate
            except Exception:
                pass

        if btn is None:
            btn = sub.locator("a.b2").first

        btn.wait_for(state="attached", timeout=5000)

        btn_text = (btn.text_content() or "").strip()
        btn_text = re.sub(r"\s+", " ", btn_text)
        debug_log(f"[디버그] 하위 카드 '{sub_title}' 버튼 문구: {btn_text}")

        btn.click(timeout=3000, force=True)
        print(f"[성공] 하위 카드 클릭: {sub_title}")
        handle_resume_popup(page)

        if not wait_for_question_ready(page, timeout=8000):
            print("[경고] 과목 클릭 후 문제 화면 준비 확인 실패")
            return False

        return True

    except Exception as e:
        print(f"[오류] 대상 클릭 실패: {e}")
        save_debug(page, f"subject_target_click_fail_{norm_id_text(target.get('subject_name', 'unknown'))}")
        return False
    
    
def is_bottom_sheet_low_enough(page):
    """
    실제 축소 상태 판정:
    1) cp1answer1choice1 에 off 클래스가 붙었는지
    2) 내부 cont fscroll1-xy 높이가 0에 가까운지
    """
    try:
        root = page.locator("div.cp1answer1choice1").first
        if root.count() == 0:
            print("[정보] 하단 시트 루트 없음")
            return True

        class_attr = root.get_attribute("class") or ""
        is_off = "off" in class_attr.split()

        cont = root.locator("div.cont.fscroll1-xy").first
        cont_box = None
        cont_height = None

        if cont.count() > 0:
            try:
                cont_box = cont.bounding_box()
                cont_height = 0 if not cont_box else cont_box["height"]
            except Exception:
                cont_height = None

        low_enough = bool(is_off) or (cont_height is not None and cont_height <= 5)

        debug_log(
            f"[디버그] 축소 판정 class={class_attr}, "
            f"is_off={is_off}, cont_height={cont_height}, low_enough={low_enough}"
        )

        return low_enough

    except Exception as e:
        print(f"[하단 시트 위치 판정 오류] {e}")
        return False
    
    
# def ensure_bottom_sheet_collapsed(page, max_clicks=5):
#     """
#     해설 캡처 전용:
#     하단 시트가 실제로 내려간 상태가 될 때까지 클릭
#     """
#     try:
#         handle = page.locator("a.b1.handlebar").first

#         if handle.count() == 0:
#             print("[정보] 하단 시트 핸들바 없음")
#             return False

#         handle.wait_for(state="attached", timeout=3000)

#         if is_bottom_sheet_low_enough(page):
#             print("[정보] 하단 시트 이미 축소 상태")
#             return True

#         prev_y = None

#         for i in range(max_clicks):
#             print(f"[디버그] 하단 시트 축소 시도 {i+1}/{max_clicks}")

#             try:
#                 cbox_before = get_bottom_sheet_container_box(page)
#                 before_y = cbox_before["y"] if cbox_before else None
#             except Exception:
#                 before_y = None

#             try:
#                 handle.click(force=True)
#             except Exception as e:
#                 print(f"[경고] 축소 버튼 클릭 실패: {e}")

#             page.wait_for_timeout(900)

#             if is_bottom_sheet_low_enough(page):
#                 print("[성공] 하단 시트 축소 확인 완료")
#                 return True

#             try:
#                 cbox_after = get_bottom_sheet_container_box(page)
#                 after_y = cbox_after["y"] if cbox_after else None
#             except Exception:
#                 after_y = None

#             if before_y is not None and after_y is not None:
#                 print(f"[디버그] container y: {before_y} -> {after_y}")

#             if prev_y is not None and after_y is not None and abs(after_y - prev_y) < 3:
#                 print("[경고] 축소 클릭 후 위치 변화 거의 없음")
#             prev_y = after_y

#         print("[경고] 하단 시트를 충분히 축소하지 못함")
#         return False

#     except Exception as e:
#         print(f"[하단 시트 축소 오류] {e}")
#         return False
    

def ensure_bottom_sheet_collapsed(page, max_clicks=5):
    """
    하단 시트를 실제 off 상태 또는 cont height 0 상태가 될 때까지 축소
    """
    try:
        btn = page.locator("a.b1.handlebar").first

        if btn.count() == 0:
            print("[정보] 하단 시트 핸들바 없음")
            return False

        btn.wait_for(state="attached", timeout=3000)

        if is_bottom_sheet_low_enough(page):
            debug_log("[정보] 하단 시트 이미 축소 상태")
            return True

        for i in range(max_clicks):
            debug_log(f"[디버그] 하단 시트 축소 시도 {i+1}/{max_clicks}")

            try:
                btn.click(force=True)
            except Exception as e:
                print(f"[경고] 축소 버튼 클릭 실패: {e}")

            page.wait_for_timeout(300)

            if is_bottom_sheet_low_enough(page):
                debug_log("[성공] 하단 시트 축소 확인 완료")
                return True

        print("[경고] 하단 시트를 충분히 축소하지 못함")
        return False

    except Exception as e:
        print(f"[하단 시트 오류] {e}")
        return False


def has_any_choice_image(page):
    """
    현재 화면 상태와 무관하게 DOM 안에 선지 이미지가 있는지 확인
    """
    try:
        return page.locator("ol.lst1 li.li1 img").count() > 0
    except Exception:
        return False


def first_four_choices_visible(page):
    try:
        choices = page.locator("ol.lst1 li.li1 span.t1t1")
        count = choices.count()
        if count < 4:
            return False

        for idx in range(4):
            if not choices.nth(idx).is_visible():
                return False
        return True
    except Exception:
        return False


def ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4):
    """
    확장 판정은 애매한 기본 상태를 믿지 않고,
    1) 먼저 축소 상태를 맞춘 뒤
    2) 버튼을 한 번 더 눌러
    3) 1~4번 선지가 모두 visible인지 확인
    """
    try:
        handle = page.locator("a.b1.handlebar").first
        if handle.count() == 0:
            print("[정보] 하단 시트 핸들바 없음")
            return False

        handle.wait_for(state="attached", timeout=3000)

        collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=max_clicks)
        page.wait_for_timeout(300)

        if not collapsed or not is_bottom_sheet_low_enough(page):
            print("[경고] 확장 전 축소 기준 상태 확보 실패")
            return False

        debug_log("[디버그] 축소 상태 확인 후 확장 시도")

        try:
            handle.click(force=True)
        except Exception as e:
            print(f"[경고] 확장 버튼 클릭 실패: {e}")
            return False

        page.wait_for_timeout(400)

        if first_four_choices_visible(page):
            debug_log("[성공] 축소 상태에서 한 번 더 눌러 1~4번 선지 visible 확인")
            return True

        print("[경고] 확장 후에도 1~4번 선지가 모두 보이지 않음")
        return False

    except Exception as e:
        print(f"[하단 시트 확장 오류] {e}")
        return False
    

def wait_until_explanation_ready(page, timeout=15000):
    try:
        body = get_explanation_body_locator(page)
        body.wait_for(state="attached", timeout=timeout)

        max_try = max(1, timeout // 500)

        for _ in range(max_try):
            try:
                text = (body.inner_text() or "").strip()
                if text and "비기봇에게 문의중" not in text and len(text) >= 20:
                    debug_log("[성공] 비기봇 해설 본문 로딩 완료")
                    return True
            except Exception:
                pass

            page.wait_for_timeout(300)

        print("[경고] 비기봇 해설 본문 로딩 대기 시간 초과")
        save_debug(page, "wait_until_explanation_ready_timeout")
        return False

    except Exception as e:
        print(f"[경고] 비기봇 로딩 대기 실패: {e}")
        save_debug(page, "wait_until_explanation_ready_fail")
        return False


def set_page_zoom(page, zoom: float):
    try:
        page.evaluate(
            """(z) => { document.body.style.zoom = String(z); }""",
            zoom
        )
        page.wait_for_timeout(300)
        return True
    except Exception as e:
        print(f"[줌 설정 실패] {e}")
        return False


def explanation_fits_in_view(page, t1, viewport, bottom_margin=40, handle_overlap_guard=20):
    """
    현재 배율/현재 위치 기준으로 해설 전체가 안전 영역 안에 한 번에 들어오는지 판정
    handle_overlap_guard:
      하단 겹침 위험영역(px). fits_now / fits_after_zoom 에서 다르게 줄 수 있음.
    """
    try:
        box = t1.bounding_box()
        if not box:
            return False, None

        container_top = viewport["height"]
        try:
            container = page.locator("div.container").first
            if container.count() > 0:
                cbox = container.bounding_box()
                if cbox:
                    container_top = cbox["y"]
        except Exception:
            pass

        safe_bottom = min(container_top, viewport["height"] - bottom_margin) - handle_overlap_guard

        visible_top = max(box["y"], 0)
        visible_bottom = min(box["y"] + box["height"], safe_bottom)

        visible_start_in_t1 = max(0, visible_top - box["y"])
        visible_end_in_t1 = max(0, visible_bottom - box["y"])
        total_height = box["height"]

        hidden_bottom_px = total_height - visible_end_in_t1
        fits = visible_start_in_t1 <= 10 and hidden_bottom_px <= 5

        debug_log(
            f"[디버그] fits={fits}, guard={handle_overlap_guard}, "
            f"hidden_bottom_px={hidden_bottom_px}, "
            f"safe_bottom={safe_bottom}, "
            f"visible_start={visible_start_in_t1}, "
            f"visible_end={visible_end_in_t1}, "
            f"total_height={total_height}"
        )

        return fits, {
            "box": box,
            "safe_bottom": safe_bottom,
            "visible_top": visible_top,
            "visible_bottom": visible_bottom,
            "visible_start_in_t1": visible_start_in_t1,
            "visible_end_in_t1": visible_end_in_t1,
            "total_height": total_height,
        }

    except Exception as e:
        print(f"[한 화면 적합 여부 판정 실패] {e}")
        return False, None


def element_fits_above_container(page, locator, viewport, bottom_margin=40, handle_overlap_guard=25):
    try:
        box = locator.bounding_box()
        if not box:
            return False, None

        container_top = viewport["height"]
        container = page.locator("div.container").first
        if container.count() > 0:
            cbox = container.bounding_box()
            if cbox:
                container_top = cbox["y"]

        safe_bottom = min(container_top, viewport["height"] - bottom_margin) - handle_overlap_guard

        hidden_bottom_px = (box["y"] + box["height"]) - safe_bottom
        fits = box["y"] >= 0 and hidden_bottom_px <= 5

        debug_log(
            f"[디버그] 이미지 fits={fits}, "
            f"hidden_bottom_px={hidden_bottom_px}, "
            f"safe_bottom={safe_bottom}, "
            f"img_bottom={box['y'] + box['height']}"
        )

        return fits, {
            "box": box,
            "safe_bottom": safe_bottom,
        }

    except Exception as e:
        print(f"[이미지 적합 여부 판정 실패] {e}")
        return False, None


def prepare_element_capture_above_container(page, locator, top_margin=80):
    viewport = page.viewport_size
    if not viewport:
        return False

    box = locator.bounding_box()
    if not box:
        return False

    page.mouse.wheel(0, int(box["y"] - top_margin))
    page.wait_for_timeout(300)

    fits, info = element_fits_above_container(
        page,
        locator,
        viewport,
        bottom_margin=40,
        handle_overlap_guard=25
    )

    if fits:
        return True

    print("[정보] 이미지가 선지 container와 겹침 가능성 있음 -> 하단 시트 축소 시도")

    collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
    page.wait_for_timeout(300)

    if collapsed and is_bottom_sheet_low_enough(page):
        box = locator.bounding_box()
        if box:
            page.mouse.wheel(0, int(box["y"] - top_margin))
            page.wait_for_timeout(300)

        fits, info = element_fits_above_container(
            page,
            locator,
            viewport,
            bottom_margin=40,
            handle_overlap_guard=25
        )

        if fits:
            return True

    print("[정보] 하단 시트 축소 후에도 이미지가 안 들어옴 -> 0.85 → 0.8 배율 시도")

    for zoom in [0.85, 0.8]:
        if not set_page_zoom(page, zoom):
            continue

        page.wait_for_timeout(300)

        recollapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
        page.wait_for_timeout(300)

        if not recollapsed or not is_bottom_sheet_low_enough(page):
            continue

        box = locator.bounding_box()
        if box:
            page.mouse.wheel(0, int(box["y"] - top_margin))
            page.wait_for_timeout(300)

        fits, info = element_fits_above_container(
            page,
            locator,
            viewport,
            bottom_margin=40,
            handle_overlap_guard=60
        )

        if fits:
            print(f"[성공] {zoom} 배율에서 이미지가 선지 container와 겹치지 않음")
            return True

    print("[경고] 이미지가 축소 후에도 한 화면에 안전하게 들어오지 않음")
    return False


def capture_locator_render_screenshot(page, locator, question_id: str, label: str, location: str, near_text: str = "") -> dict | None:
    """
    LaTeX/수식 렌더링 확인용으로 특정 영역만 스크린샷 저장합니다.
    location은 기존 OpenAI 첨부 흐름을 타기 위해 question 또는 choice를 사용합니다.
    """
    try:
        if locator.count() == 0:
            return None

        locator.first.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(300)

        filename = f"{question_id}_{norm_id_text(label)}.png"
        filepath = IMG_DIR / filename

        locator.first.screenshot(path=str(filepath), timeout=5000)

        return {
            "type": "render_screenshot",
            "location": location,
            "caption_or_near_text": label,
            "ocr_or_extracted_text": near_text,
            "saved_path": str(filepath),
        }

    except Exception as e:
        print(f"[렌더링 스크린샷 실패] {label}: {e}")
        return None



MATHJAX_RENDER_ELEMENT_SELECTOR = (
    "mjx-container, mjx-container *, "
    "mjx-math, mjx-mrow, mjx-mi, mjx-mo, mjx-mn, mjx-msup, mjx-msub, mjx-mfrac, mjx-msqrt, mjx-mtable, "
    "math, mrow, mi, mo, mn, msup, msub, mfrac, msqrt, mtable, "
    ".MathJax, .MathJax_Display, .MathJax_Preview, "
    "[class*='MathJax'], [id^='MathJax'], "
    "script[type^='math/tex'], script[type='math/mml']"
)

QUESTION_RENDER_ELEMENT_SELECTOR = (
    f"{MATHJAX_RENDER_ELEMENT_SELECTOR}, "
    "table, thead, tbody, tr, td, th, svg, canvas"
)

CHOICE_RENDER_ELEMENT_SELECTOR = MATHJAX_RENDER_ELEMENT_SELECTOR

EXPLANATION_RENDER_ELEMENT_SELECTOR = (
    f"{MATHJAX_RENDER_ELEMENT_SELECTOR}, "
    "img, table, thead, tbody, tr, td, th, svg, canvas"
)


def explanation_has_render_elements(page) -> bool:
    """
    비기봇 해설 본문 안에 MathJax/이미지/표/렌더링 요소가 있는지 확인합니다.
    """
    try:
        root = get_explanation_body_locator(page)
        return locator_has_render_elements(root, EXPLANATION_RENDER_ELEMENT_SELECTOR)
    except Exception:
        return False


def get_question_text_root_locator(page):
    """
    문제 본문/보기/제시자료가 들어 있는 영역을 반환합니다.
    MathJax가 span.tt1t1 밖에 렌더링되는 경우도 있어서 fallback을 둡니다.
    """
    selectors = [
        "div.cp1question1 div.tg1 strong.tt1 span.tt1t1",
        "div.cp1question1 div.tg1 strong.tt1",
        "div.cp1question1 div.tg1",
        "div.cp1question1",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0:
                return loc
        except Exception:
            pass

    return page.locator("div.cp1question1").first


def locator_has_render_elements(locator, selector: str) -> bool:
    """
    특정 locator 내부에 MathJax/MathML/렌더링 요소가 있는지 확인합니다.
    """
    try:
        if locator.count() == 0:
            return False

        target = locator.first
        return target.locator(selector).count() > 0

    except Exception:
        return False
    

def question_has_render_elements(page) -> bool:
    """
    문제/보기 영역 안에 MathJax 표, HTML table, svg, canvas 등
    텍스트 추출만으로 행·열 경계가 깨질 수 있는 렌더링 요소가 있는지 확인합니다.
    """
    try:
        root = get_question_text_root_locator(page)
        return locator_has_render_elements(root, QUESTION_RENDER_ELEMENT_SELECTOR)

    except Exception:
        return False


def capture_question_render_element_image(page, question_id: str) -> dict | None:
    """
    img 태그는 아니지만 문제/보기 영역에 MathJax 표, HTML table, svg, canvas 등이 있으면
    문제 영역 전체를 스크린샷으로 저장합니다.
    """
    try:
        if not question_has_render_elements(page):
            return None

        root = get_question_text_root_locator(page)

        item = capture_locator_render_screenshot(
            page=page,
            locator=root,
            question_id=question_id,
            label="question_render_table_or_formula",
            location="question",
            near_text="문제/보기 표·수식·렌더링 요소 확인",
        )

        if item:
            print("[캡처] 문제/보기 렌더링 요소 스크린샷 저장")

        return item

    except Exception as e:
        print(f"[문제/보기 렌더링 요소 캡처 실패] {e}")
        return None


def capture_choice_render_element_images(page, question_id: str) -> list[dict]:
    """
    선지 안에 MathJax/MathML/수식 렌더링 요소가 있으면
    해당 선지 영역을 스크린샷으로 저장합니다.
    """
    image_elements: list[dict] = []

    try:
        try:
            ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4)
            page.wait_for_timeout(300)
        except Exception as e:
            print(f"[경고] 선지 MathJax 탐색 전 하단 시트 확장 실패: {e}")

        items = page.locator("ol.lst1 li.li1")
        count = min(items.count(), 4)

        choice_indexes: list[int] = []

        for idx in range(count):
            li = items.nth(idx)

            if locator_has_render_elements(li, CHOICE_RENDER_ELEMENT_SELECTOR):
                choice_indexes.append(idx)

        if not choice_indexes:
            return image_elements

        for idx in choice_indexes:
            try:
                li = items.nth(idx)
                text_area = li.locator("span.t1t1").first
                target = text_area if text_area.count() > 0 else li

                item = capture_locator_render_screenshot(
                    page=page,
                    locator=target,
                    question_id=question_id,
                    label=f"choice_{idx + 1}_mathjax_render",
                    location="choice",
                    near_text=f"선지 {idx + 1} MathJax/수식 렌더링 확인",
                )

                if item:
                    image_elements.append(item)
                    print(f"[캡처] 선지 {idx + 1} MathJax/수식 렌더링 스크린샷 저장")

            except Exception as e:
                print(f"[선지 MathJax 렌더링 캡처 실패] choice_{idx + 1}: {e}")

    except Exception as e:
        print(f"[선지 MathJax 렌더링 요소 탐색 실패] {e}")

    return image_elements


def capture_formula_render_images(
    page,
    question_id: str,
    body: str,
    extra_text: str,
    choices: list[str],
    skip_question_render: bool = False,
) -> list[dict]:
    image_elements: list[dict] = []

    # 문제/보기 DOM에 MathJax/table/svg/canvas가 있으면 렌더링 캡처
    if not skip_question_render and question_has_render_elements(page):
        item = capture_question_render_element_image(page, question_id)

        if item:
            image_elements.append(item)

    # DOM 렌더링 요소는 없지만 텍스트에 LaTeX/수식 패턴이 있으면 문제/보기 영역 캡처
    elif not skip_question_render and (
        has_latex_or_formula_text(body)
        or has_latex_or_formula_text(extra_text)
    ):
        root = get_question_text_root_locator(page)

        item = capture_locator_render_screenshot(
            page=page,
            locator=root,
            question_id=question_id,
            label="question_text_formula_render",
            location="question",
            near_text="문제/보기 수식 렌더링 확인",
        )

        if item:
            image_elements.append(item)

    # 선지 텍스트에 수식이 있는 경우, 해당 선지만 캡처합니다.
    choice_indexes = [
        idx
        for idx, choice_text in enumerate(choices)
        if has_latex_or_formula_text(str(choice_text or ""))
    ]

    if choice_indexes:
        try:
            ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4)
            page.wait_for_timeout(300)
        except Exception as e:
            print(f"[경고] 선지 수식 캡처 전 하단 시트 확장 실패: {e}")

        items = page.locator("ol.lst1 li.li1")

        for idx in choice_indexes:
            try:
                li = items.nth(idx)

                item = capture_locator_render_screenshot(
                    page=page,
                    locator=li,
                    question_id=question_id,
                    label=f"choice_{idx + 1}_formula_render",
                    location="choice",
                    near_text=f"선지 {idx + 1} 수식 렌더링 확인",
                )

                if item:
                    image_elements.append(item)

            except Exception as e:
                print(f"[선지 수식 렌더링 캡처 실패] choice_{idx + 1}: {e}")
                
    # 텍스트 추출 결과에 LaTeX 원문이 남지 않는 MathJax 렌더링 선지도 캡처합니다.
    dom_choice_render_images = capture_choice_render_element_images(page, question_id)

    existing_labels = {
        item.get("caption_or_near_text", "")
        for item in image_elements
    }

    for item in dom_choice_render_images:
        label = item.get("caption_or_near_text", "")
        if label not in existing_labels:
            image_elements.append(item)
            existing_labels.add(label)                
                

    return image_elements


def capture_explanation_images(page, question_id, already_ready=False):
    saved_paths = []
    meta = {
        "attempted": True,
        "zoom_applied": False,
        "fits_in_single_before_zoom": None,
        "fits_in_single_after_zoom": None,
        "needs_manual_review": False,
        "capture_mode": "not_started",   # single / too_long_after_zoom / skipped / failed / not_needed
        "image_count": 0,
    }

    try:
        if not already_ready:
            wait_until_explanation_ready(page)

        t1 = get_explanation_body_locator(page)
        t1.wait_for(state="visible", timeout=3000)

        viewport = page.viewport_size
        if not viewport:
            print("[오류] viewport 없음")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        top_margin = 80
        bottom_margin = 40
        clip_top_pad = 6

        collapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
        page.wait_for_timeout(300)

        if not collapsed or not is_bottom_sheet_low_enough(page):
            print("[경고] 해설 캡처 전 축소 상태 확인 실패 -> 해설 캡처 건너뜀")
            meta["capture_mode"] = "skipped"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        first_box = t1.bounding_box()
        if not first_box:
            print("[종료] 첫 bounding_box 없음")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        scroll_adjust = first_box["y"] - top_margin
        page.mouse.wheel(0, int(scroll_adjust))
        page.wait_for_timeout(300)

        fits_now, fit_info = explanation_fits_in_view(
            page,
            t1,
            viewport,
            bottom_margin=bottom_margin,
            handle_overlap_guard=25
        )
        
        meta["fits_in_single_before_zoom"] = bool(fits_now)

        if not fits_now:
            print("[정보] 긴 해설 감지 - 0.85 → 0.8 순차 배율 적용 시도")

            zoom_applied_success = False

            for zoom in [0.85, 0.8]:

                print(f"[디버그] 배율 시도: {zoom}")

                if not set_page_zoom(page, zoom):
                    continue

                meta["zoom_applied"] = True

                page.wait_for_timeout(300)

                # 배율 변경 후 다시 축소 상태 재확인
                recollapsed_after_zoom = ensure_bottom_sheet_collapsed(
                    page,
                    max_clicks=5
                )
                page.wait_for_timeout(300)

                if not recollapsed_after_zoom or not is_bottom_sheet_low_enough(page):
                    print(f"[경고] {zoom} 적용 후 축소 상태 확인 실패")
                    continue

                # 배율 적용 후 해설 시작 위치 재정렬
                zoomed_box = t1.bounding_box()
                if zoomed_box:
                    scroll_adjust = zoomed_box["y"] - top_margin
                    page.mouse.wheel(0, int(scroll_adjust))
                    page.wait_for_timeout(300)

                # 다시 한 화면 적합 여부 검사
                fits_after_zoom, fit_info = explanation_fits_in_view(
                    page,
                    t1,
                    viewport,
                    bottom_margin=bottom_margin,
                    handle_overlap_guard=60
                )

                bottom_guard_px = 0

                if fits_after_zoom and fit_info:
                    remaining_margin = fit_info["safe_bottom"] - (
                        fit_info["box"]["y"] + fit_info["total_height"]
                    )
                    print(f"[디버그] remaining_margin={remaining_margin}")

                    if remaining_margin < bottom_guard_px:
                        fits_after_zoom = False
                        print("[정보] 해설 하단 여유 부족 -> 더 작은 배율 시도")

                meta["fits_in_single_after_zoom"] = bool(fits_after_zoom)

                if fits_after_zoom:
                    print(f"[성공] {zoom} 배율에서 해설이 한 화면에 들어옴")
                    zoom_applied_success = True
                    break

            if not zoom_applied_success:
                print("[정보] 0.8까지 시도 후에도 한 화면에 안 들어옴")
                meta["capture_mode"] = "too_long_after_zoom"
                meta["needs_manual_review"] = True
                meta["image_count"] = 0

                return {
                    "images": saved_paths,
                    "meta": meta,
                }

        final_guard = 60 if meta["zoom_applied"] else 25

        fits_single, fit_info = explanation_fits_in_view(
            page,
            t1,
            viewport,
            bottom_margin=bottom_margin,
            handle_overlap_guard=final_guard
        )

        if not fits_single or not fit_info:
            print("[경고] 단일 캡처 조건 미충족 -> 사람 확인 필요")
            meta["capture_mode"] = "too_long_after_zoom" if meta["zoom_applied"] else "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        box = fit_info["box"]
        safe_bottom = fit_info["safe_bottom"]

        # 저장은 판정보다 조금 덜 보수적으로
        capture_guard = 25 if meta["zoom_applied"] else 15
        capture_safe_bottom = safe_bottom + (final_guard - capture_guard)

        clip_x = max(box["x"], 0)
        clip_width = min(box["width"], viewport["width"] - clip_x)
        clip_y = max(0, box["y"] - clip_top_pad)
        clip_bottom = min(
            capture_safe_bottom,
            box["y"] + box["height"]
        )
        clip_height = clip_bottom - clip_y

        if clip_width <= 0 or clip_height <= 50:
            print("[경고] 단일 캡처 clip 크기 부족 -> 사람 확인 필요")
            meta["capture_mode"] = "failed"
            meta["needs_manual_review"] = True
            return {
                "images": saved_paths,
                "meta": meta,
            }

        filepath = IMG_DIR / f"{question_id}_explanation_1.png"
        page.screenshot(
            path=str(filepath),
            clip={
                "x": clip_x,
                "y": clip_y,
                "width": clip_width,
                "height": clip_height,
            },
        )
        saved_paths.append(str(filepath))
        print(f"[캡처] {filepath}")
        print("[완료] 해설이 한 화면에 모두 들어와 1장만 저장")

        meta["capture_mode"] = "single"
        meta["image_count"] = 1

        return {
            "images": saved_paths,
            "meta": meta,
        }

    except Exception as e:
        print(f"[해설 캡처 실패] {e}")
        save_debug(page, f"explanation_capture_fail_{question_id}")

        meta["capture_mode"] = "failed"
        meta["needs_manual_review"] = True
        meta["image_count"] = len(saved_paths)

        return {
            "images": saved_paths,
            "meta": meta,
        }



            
def close_main_popup_today(page):
    """
    메인 진입 시 뜨는 이벤트 팝업에서
    '오늘은 그만 보기'를 우선 클릭한다.
    """
    selectors = [
        "a[onclick*='closePop'][onclick*='checked']",
        "a[href^='#pop'][onclick*='checked']",
        "a.b1",
        "a:has(span:has-text('오늘은 그만 보기'))",
        "text=오늘은 그만 보기",
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=1500):
                loc.click(force=True, timeout=2000)
                page.wait_for_timeout(300)
                print(f"[팝업 처리] 오늘은 그만 보기 클릭 성공: {selector}")
                return True
        except Exception:
            pass

    print("[팝업 처리] 오늘은 그만 보기 버튼을 찾지 못함")
    return False


def click_hamburger_menu(page):
    try:
        btn = page.locator("a.b1.toggle")
        btn.first.wait_for(state="attached", timeout=5000)
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1000)
        print("[성공] 햄버거 메뉴 클릭")
        return True
    except Exception as e:
        print(f"[오류] 햄버거 클릭 실패: {e}")
        save_debug(page, "hamburger_click_fail")
        return False


def click_login_entry(page) -> bool:
    try:
        btn = page.locator("a.a1[href*='login1.php']")
        btn.first.click(timeout=3000)
        page.wait_for_timeout(1500)
        print("[성공] 로그인 클릭")
        return True
    except Exception as e:
        print(f"[실패] 로그인 클릭 실패: {e}")
        save_debug(page, "login_entry_fail")
        return False


def submit_login(page) -> bool:
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button",
    ]

    for sel in selectors:
        try:
            items = page.locator(sel)
            count = items.count()

            for i in range(count):
                el = items.nth(i)
                txt = safe_text(el)

                if "로그인" in txt or "LOGIN" in txt or "Login" in txt:
                    el.click(timeout=3000)
                    page.wait_for_timeout(3000)
                    print(f"[성공] 로그인 제출: {sel}")
                    return True
        except Exception:
            continue

    save_debug(page, "login_submit_failed")
    return False


def login(page, user_id, password):
    page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    ensure_main_page(page)
    save_debug(page, "before_login_attempt")

    close_main_popup_today(page)
    page.wait_for_timeout(400)

    if not click_hamburger_menu(page):
        raise RuntimeError("햄버거 메뉴를 찾지 못했습니다.")

    save_debug(page, "after_hamburger_click")

    if not click_login_entry(page):
        raise RuntimeError("로그인 버튼 클릭에 실패했습니다.")

    save_debug(page, "after_login_entry_click")

    try:
        page.locator("input").nth(0).wait_for(state="visible", timeout=5000)
        page.locator("input").nth(1).wait_for(state="visible", timeout=5000)
    except Exception:
        save_debug(page, "login_inputs_not_found")
        raise RuntimeError("로그인 입력창을 찾지 못했습니다.")

    try:
        page.locator("input").nth(0).fill(user_id)
        page.locator("input").nth(1).fill(password)
        print("[성공] 로그인 정보 입력 완료")
    except Exception:
        save_debug(page, "login_fill_failed")
        raise RuntimeError("로그인 입력값 입력에 실패했습니다.")

    if not submit_login(page):
        raise RuntimeError("로그인 제출에 실패했습니다.")

    page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded", timeout=15000)

    page.locator("a.a1[href*='mypt1.php'] span.t1").first.wait_for(
        state="attached",
        timeout=10000
    )
    ensure_main_page(page)
    save_debug(page, "after_login_main_reload")



def extract_bigibot_keyword_texts_from_card(card) -> list[str]:
    """
    비기봇 해설 more-c 안의 키워드 태그만 추출합니다.
    같은 도움말 영역 안에 있는 핵심쇼츠강의 영상 태그(.m-viewvideo)는 제외합니다.
    """
    try:
        values = card.evaluate(
            """
            (el, titleVariants) => {
                const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
                const compact = (value) => normalize(value).replace(/\\s+/g, "");

                const matchesTitle = (text) => {
                    const normalized = normalize(text);
                    const compactText = compact(text);

                    return titleVariants.some((title) => {
                        const normalizedTitle = normalize(title);
                        const compactTitle = compact(title);

                        return (
                            normalized.includes(normalizedTitle) ||
                            compactText.includes(compactTitle)
                        );
                    });
                };

                const moreBlocks = Array.from(el.querySelectorAll("div.more-c"));

                let target = moreBlocks.find((block) => {
                    const titleEl = block.querySelector(":scope > strong.tt1, strong.tt1");
                    return titleEl && matchesTitle(titleEl.textContent || "");
                });

                if (!target) {
                    target = el;
                }

                const tags = Array.from(target.querySelectorAll("div.t2 a.tag"));

                return tags
                    .filter((a) => {
                        const cls = a.getAttribute("class") || "";
                        const href = a.getAttribute("href") || "";
                        const dataTag = a.getAttribute("data-tag") || "";

                        if (cls.split(/\\s+/).includes("m-viewvideo")) return false;
                        if (dataTag) return false;
                        if (href.startsWith("#cplview")) return false;
                        if (href.toLowerCase().includes("video")) return false;

                        const nearestMore = a.closest("div.more-c");
                        const titleEl = nearestMore ? nearestMore.querySelector(":scope > strong.tt1, strong.tt1") : null;
                        const titleText = titleEl ? normalize(titleEl.textContent || "") : "";

                        if (titleText.includes("핵심쇼츠강의")) return false;

                        return true;
                    })
                    .map((a) => normalize(a.textContent || "").replace(/^#/, "").trim())
                    .filter(Boolean);
            }
            """,
            BIGIBOT_TITLE_VARIANTS,
        )

        result = []
        for value in values or []:
            txt = sanitize_text(str(value)).lstrip("#").strip()
            if txt and txt not in result:
                result.append(txt)

        return result

    except Exception as e:
        print(f"[비기봇 키워드 전용 추출 오류] {e}")
        return []


def extract_keywords(page, wait_ready=True):
    keywords = []

    try:
        if wait_ready:
            wait_until_explanation_ready(page)

        # 1순위: 비기봇 해설 more-c 안의 키워드만 가져오기
        # 핵심쇼츠강의 영상 태그도 a.tag를 사용하므로 반드시 제외합니다.
        card = get_bigibot_card_locator(page)

        if card is not None:
            for txt in extract_bigibot_keyword_texts_from_card(card):
                if txt and txt not in keywords:
                    keywords.append(txt)

            if keywords:
                return keywords

        # 2순위 fallback: 기존 방식
        # fallback에서도 핵심쇼츠강의 영상 태그(.m-viewvideo/data-tag)는 제외합니다.
        for sel in EXPLANATION_KEYWORD_SELECTORS:
            items = page.locator(sel)
            count = items.count()

            if count == 0:
                continue

            for i in range(count):
                item = items.nth(i)

                raw = item.text_content() or ""
                txt = re.sub(r"\s+", " ", raw).strip()
                txt = txt.lstrip("#").strip()

                try:
                    class_attr = item.get_attribute("class") or ""
                    href = item.get_attribute("href") or ""
                    data_tag = item.get_attribute("data-tag") or ""
                except Exception:
                    class_attr = ""
                    href = ""
                    data_tag = ""

                if "m-viewvideo" in class_attr.split():
                    continue

                if data_tag:
                    continue

                if href.startswith("#cplview") or "video" in href.lower():
                    continue

                # PT쌤 합격팁 태그는 키워드에서 제외
                if any(label in txt for label in ["개념 난이도", "정답률", "유형"]):
                    continue

                # 핵심쇼츠강의 제목은 키워드가 아니므로 제외
                if "핵심쇼츠강의" in txt:
                    continue

                if txt and txt not in keywords:
                    keywords.append(txt)

            if keywords:
                break

    except Exception as e:
        print(f"[keywords 추출 오류] {e}")
        save_debug(page, "extract_keywords_fail")

    return keywords


def extract_section_tags(page):
    tags = []

    try:
        container = page.locator("div.cp1question1 div.w1").first
        container.wait_for(state="attached", timeout=5000)

        items = container.locator("span.g1")
        count = items.count()

        for i in range(count):
            raw = items.nth(i).text_content() or ""
            txt = re.sub(r"\s+", " ", raw).strip()
            if txt:
                tags.append(txt)

    except Exception as e:
        print(f"[section_tags 추출 오류] {e}")
        save_debug(page, "extract_section_tags_fail")

    return tags


def get_image_name_from_li(li, question_id, num):
    """
    선지 이미지의 원본 파일명 추출
    우선순위:
    1) a href 의 img 파라미터
    2) img src 파일명
    3) fallback
    """
    try:
        img = li.locator("img").first
        if img.count() > 0:
            original_name = get_original_image_name(img)
            if original_name:
                base_name = re.sub(r"\.\w+$", ".png", original_name)
                base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                return base_name
    except Exception as e:
        print(f"[선지 원본 파일명 추출 오류] num={num}, err={e}")

    return f"{question_id}_choice_{num}.png"


def get_original_image_name(img_locator):
    """
    이미지의 원본 파일명을 최대한 보존해서 추출
    우선순위:
    1) 부모 a 태그 href의 ?img= 파라미터
    2) img src 파일명
    3) 실패 시 빈 문자열
    """
    try:
        parent_a = img_locator.locator("xpath=ancestor::a[1]").first

        if parent_a.count() > 0:
            href = parent_a.get_attribute("href") or ""
            if href:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                img_param = qs.get("img", [])
                if img_param and img_param[0].strip():
                    return img_param[0].strip()
    except Exception:
        pass

    try:
        src = img_locator.get_attribute("src") or ""
        if src:
            return Path(urlparse(src).path).name
    except Exception:
        pass

    return ""


def capture_question_and_choice_images(page, question_id, recollapse_after_choice_capture=False):
    image_elements = []
    expanded_for_choice_capture = False

    question_image_capture_meta = {
        "attempted": True,
        "needs_manual_review": False,
        "capture_mode": "not_needed",
        "image_count": 0,
        "failed_indexes": [],
    }
    
    # 문제 이미지
    try:
        q_items = page.locator("div.tg1 img")
        q_count = q_items.count()

        if q_count > 0:
            question_image_capture_meta["capture_mode"] = "single"
            
        for i in range(q_count):
            img = q_items.nth(i)

            try:
                src = img.get_attribute("src") or ""
                alt = img.get_attribute("alt") or ""
                original_name = get_original_image_name(img)

                if original_name:
                    base_name = re.sub(r"\.\w+$", ".png", original_name)
                    base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                else:
                    base_name = f"{question_id}_question_img_{i+1}.png"

                filepath = IMG_DIR / base_name

                if filepath.exists():
                    stem = Path(base_name).stem
                    suffix = Path(base_name).suffix or ".png"
                    filename = f"{stem}_{i+1}{suffix}"
                    filepath = IMG_DIR / filename

                prepared = prepare_element_capture_above_container(page, img, top_margin=80)

                if not prepared:
                    print(f"[경고] 문제 이미지가 선지 container와 겹칠 수 있어 저장 건너뜀: idx={i}")
                    question_image_capture_meta["needs_manual_review"] = True
                    question_image_capture_meta["capture_mode"] = "overlap_or_too_long_after_zoom"
                    question_image_capture_meta["failed_indexes"].append(i + 1)
                    continue

                img.screenshot(path=str(filepath))
                question_image_capture_meta["image_count"] += 1

                image_elements.append({
                    "type": "screenshot",
                    "location": "question",
                    "caption_or_near_text": sanitize_text(alt),
                    "ocr_or_extracted_text": original_name or (Path(urlparse(src).path).name if src else Path(filepath).name),
                    "saved_path": str(filepath)
                })

            except Exception as e:
                print(f"[문제 이미지 저장 실패] idx={i}, err={e}")
                question_image_capture_meta["needs_manual_review"] = True
                question_image_capture_meta["capture_mode"] = "question_image_capture_failed"
                question_image_capture_meta["failed_indexes"].append(i + 1)

    except Exception as e:
        print(f"[문제 이미지 탐색 실패] {e}")

    # img 태그가 아닌 MathJax 표/HTML table/svg/canvas도 문제 풀이 자료이므로
    # 문제/보기 영역 전체를 스크린샷으로 저장합니다.
    try:
        render_item = capture_question_render_element_image(page, question_id)

        if render_item:
            image_elements.append(render_item)
            question_image_capture_meta["image_count"] += 1

            if question_image_capture_meta["capture_mode"] == "not_needed":
                question_image_capture_meta["capture_mode"] = "render_screenshot"
            elif "render_screenshot" not in question_image_capture_meta["capture_mode"]:
                question_image_capture_meta["capture_mode"] = (
                    f"{question_image_capture_meta['capture_mode']}+render_screenshot"
                )

    except Exception as e:
        print(f"[문제/보기 렌더링 요소 탐색 실패] {e}")
        question_image_capture_meta["needs_manual_review"] = True
        question_image_capture_meta["capture_mode"] = "render_capture_failed"

    # 선지 이미지
    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        has_choice_image = has_any_choice_image(page)

        if has_choice_image:
            expanded = ensure_bottom_sheet_expanded_from_collapsed(page, max_clicks=4)
            page.wait_for_timeout(400)

            if not expanded:
                print("[경고] 선지 이미지용 확장 상태를 확인하지 못해 이번 문제의 선지 이미지 캡처를 건너뜁니다.")
                return {
                    "image_elements": image_elements,
                    "question_image_capture_meta": question_image_capture_meta,
                }

            expanded_for_choice_capture = True

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            imgs = li.locator("img")
            img_count = imgs.count()

            for j in range(img_count):
                img = imgs.nth(j)

                try:
                    if not img.is_visible():
                        print(f"[디버그] 선지 이미지 비가시 상태 skip: num={num}, idx={j}")
                        continue

                    src = img.get_attribute("src") or ""
                    alt = img.get_attribute("alt") or ""
                    original_name = get_original_image_name(img)

                    if original_name:
                        base_name = re.sub(r"\.\w+$", ".png", original_name)
                        base_name = re.sub(r"[^\w가-힣\.]+", "_", base_name)
                    else:
                        base_name = f"{question_id}_choice_{num}.png"

                    filepath = IMG_DIR / base_name

                    if filepath.exists():
                        stem = Path(base_name).stem
                        suffix = Path(base_name).suffix or ".png"
                        filename = f"{stem}_{num}_{j+1}{suffix}"
                        filepath = IMG_DIR / filename

                    img.screenshot(path=str(filepath))

                    image_elements.append({
                        "type": "screenshot",
                        "location": "choice",
                        "caption_or_near_text": f"choice_{num}",
                        "ocr_or_extracted_text": original_name or (Path(urlparse(src).path).name if src else Path(filepath).name),
                        "saved_path": str(filepath)
                    })

                except Exception as e:
                    print(f"[선지 이미지 저장 실패] num={num}, err={e}")

    except Exception as e:
        print(f"[선지 이미지 탐색 실패] {e}")


    finally:
        if expanded_for_choice_capture and recollapse_after_choice_capture:
            try:
                print("[디버그] 해설 이미지 캡처 예정이므로 선지 캡처 후 재축소 시도")
                recollapsed = ensure_bottom_sheet_collapsed(page, max_clicks=5)
                page.wait_for_timeout(400)

                if recollapsed and is_bottom_sheet_low_enough(page):
                    print("[성공] 해설 이미지 캡처 전 하단 시트 재축소 완료")
                else:
                    print("[경고] 해설 이미지 캡처 전 하단 시트 재축소 확인 실패")
            except Exception as e:
                print(f"[경고] 선지 캡처 후 재축소 오류: {e}")

    return {
        "image_elements": image_elements,
        "question_image_capture_meta": question_image_capture_meta,
    }


def detect_images(page, question_id, recollapse_after_choice_capture=False):
    image_elements = []

    capture_result = capture_question_and_choice_images(
        page,
        question_id,
        recollapse_after_choice_capture=recollapse_after_choice_capture
    )

    image_elements.extend(capture_result.get("image_elements", []))
    question_image_capture_meta = capture_result.get("question_image_capture_meta", {})

    saved_choice_nums = set()
    for item in image_elements:
        if item.get("location") == "choice":
            caption = item.get("caption_or_near_text", "")
            m = re.search(r"choice_(\d+)", caption or "")
            if m:
                saved_choice_nums.add(m.group(1))

    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            if num in saved_choice_nums:
                continue

            text_val = ""
            try:
                text_locator = li.locator("span.t1t1").first
                text_val = locator_text_with_br(text_locator)
            except Exception:
                text_val = ""
    
            # 기존 코드 삭제
            # text_val = re.sub(r"^\d+\.\s*", "", text_val).strip()

            # 선택지 번호가 붙은 경우만 제거
            text_val = re.sub(rf"^{re.escape(num)}[.)]\s+", "", text_val).strip()

            # 텍스트 선지면 이미지 저장 안 함
            if text_val:
                continue

            filename = get_image_name_from_li(li, question_id, num)
            filepath = IMG_DIR / filename

            if filepath.exists():
                stem = Path(filename).stem
                suffix = Path(filename).suffix or ".png"
                filename = f"{stem}_{num}{suffix}"
                filepath = IMG_DIR / filename

            captured = False

            # 1) 선지 영역 안의 img 직접 캡처
            if not captured:
                try:
                    target = li.locator("span.t1t1 img").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 2) 선지 영역 전체 캡처
            if not captured:
                try:
                    target = li.locator("span.t1t1").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 3) li 내부 div.t1 캡처
            if not captured:
                try:
                    target = li.locator("div.t1").first
                    if target.count() > 0:
                        target.screenshot(path=str(filepath))
                        captured = True
                except Exception:
                    pass

            # 4) li 전체 캡처
            if not captured:
                try:
                    li.screenshot(path=str(filepath))
                    captured = True
                except Exception:
                    pass

            if captured:
                image_elements.append({
                    "type": "screenshot",
                    "location": "choice",
                    "caption_or_near_text": f"choice_{num}",
                    "ocr_or_extracted_text": Path(filepath).name,
                    "saved_path": str(filepath)
                })
                saved_choice_nums.add(num)
                print(f"[선지 fallback 저장] num={num}, file={filepath}")
            else:
                print(f"[선지 이미지 캡처 실패] num={num} - 저장 대상 못 찾음")
                try:
                    print(f"[디버그] 선지 {num} HTML:")
                    print(li.inner_html())
                except Exception as debug_e:
                    print(f"[디버그] 선지 {num} HTML 출력 실패: {debug_e}")

    except Exception as e:
        print(f"[선지 이미지 탐지 오류] {e}")

    return {
        "image_elements": image_elements,
        "question_image_capture_meta": question_image_capture_meta,
    }

def wait_for_question_ready(page, timeout=10000) -> bool:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)

        page.locator("div.cp1question1").first.wait_for(
            state="attached",
            timeout=timeout,
        )

        selectors = [
            "div.cp1question1 div.tg1 strong.tt1 span.tt1t1",
            "div.cp1question1 div.tg1 strong.tt1",
            "div.cp1question1 div.tg1",
            "div.cp1question1",
        ]

        for selector in selectors:
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="attached", timeout=2000)

                text = (loc.inner_text(timeout=2000) or "").strip()
                if text:
                    return True
            except Exception:
                continue

        print("[경고] 문제 컨테이너는 있으나 본문 텍스트가 비어 있습니다.")
        save_debug(page, "question_ready_empty_text")
        return False

    except Exception as e:
        print(f"[경고] 문제 화면 준비 대기 실패: {e}")
        save_debug(page, "question_ready_fail")
        return False


def wait_for_list_ready(page, timeout=10000) -> bool:
    try:
        page.locator("div.cp1flist1 strong.t1, div.cp1flist2 strong.t1, li.li1 a.a1").first.wait_for(
            state="attached",
            timeout=timeout,
        )
        return True
    except Exception as e:
        print(f"[경고] 목록 화면 준비 대기 실패: {e}")
        return False
    

def extract_question_number(page):
    try:
        # 문제 본문 화면이 아니면 번호를 읽지 않습니다.
        if page.locator("div.cp1question1").count() == 0:
            return None
    except Exception:
        return None

    try:
        el = page.locator("div.cp1question1 div.tg1 strong.tt1 span.tt1n").first
        el.wait_for(state="attached", timeout=5000)

        raw = el.text_content() or ""
        num = re.sub(r"\D+", "", raw).strip()

        if num:
            return int(num)

    except Exception:
        pass

    try:
        text = page.locator("text=/\\d+\\s*/\\s*\\d+/").first.inner_text()
        m = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if m:
            return int(m.group(1))
    except Exception:
        pass

    return None


def extract_body_and_extra(page):
    body = ""
    extra_text = ""

    try:
        root = get_question_text_root_locator(page)
        root.wait_for(state="attached", timeout=7000)

        result = root.evaluate(r"""
            (el) => {
                const normalize = (value) => (value || "")
                    .replace(/\u00a0/g, " ")
                    .replace(/[ \t\f\v]+/g, " ")
                    .trim();

                const read = (node) => {
                    if (!node) return "";

                    if (node.nodeType === Node.TEXT_NODE) {
                        return node.textContent || "";
                    }

                    if (node.nodeType !== Node.ELEMENT_NODE) {
                        return "";
                    }

                    const tag = (node.tagName || "").toLowerCase();

                    if (tag === "br") {
                        return "\n";
                    }

                    // MathJax는 보이는 DOM의 textContent가 비어 있거나 붙을 수 있으므로
                    // assistive MathML이 있으면 그 구조를 우선 사용합니다.
                    if (tag === "mjx-container") {
                        const math = node.querySelector("mjx-assistive-mml math");
                        if (math) return read(math);
                    }

                    // 표 계열: 행은 줄바꿈, 열은 | 로 구분합니다.
                    if (["table", "tbody", "thead", "mtable", "mjx-mtable"].includes(tag)) {
                        return Array.from(node.children)
                            .map(read)
                            .map(normalize)
                            .filter(Boolean)
                            .join("\n") + "\n";
                    }

                    if (["tr", "mtr", "mlabeledtr", "mjx-mtr"].includes(tag)) {
                        return Array.from(node.children)
                            .map(read)
                            .map(normalize)
                            .filter(Boolean)
                            .join(" | ") + "\n";
                    }

                    if (["td", "th", "mtd", "mjx-mtd"].includes(tag)) {
                        return Array.from(node.childNodes)
                            .map(read)
                            .join("")
                            .trim();
                    }

                    if (["p", "div", "li", "ul", "ol", "section", "article"].includes(tag)) {
                        const inner = Array.from(node.childNodes)
                            .map(read)
                            .join("")
                            .trim();

                        return inner ? inner + "\n" : "";
                    }

                    return Array.from(node.childNodes)
                        .map(read)
                        .join("");
                };

                const directParts = [];
                const nestedParts = [];

                for (const node of el.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        directParts.push(node.textContent || "");
                        continue;
                    }

                    if (
                        node.nodeType === Node.ELEMENT_NODE &&
                        node.matches("span.tt1t1")
                    ) {
                        nestedParts.push(read(node));
                        continue;
                    }

                    if (
                        node.nodeType === Node.ELEMENT_NODE &&
                        node.tagName &&
                        node.tagName.toLowerCase() === "br"
                    ) {
                        directParts.push("\n");
                        continue;
                    }

                    if (node.nodeType === Node.ELEMENT_NODE) {
                        directParts.push(read(node));
                    }
                }

                return {
                    body: directParts.join(""),
                    extra_text: nestedParts.join("\n\n")
                };
            }
        """)

        body = normalize_multiline_text(result.get("body", ""))
        extra_text = normalize_multiline_text(result.get("extra_text", ""))

        debug_log(f"[디버그] body: {repr(body)}")
        debug_log(f"[디버그] extra_text:\n{extra_text}")

    except Exception as e:
        print(f"[body/extra_text 추출 오류] {e}")
        save_debug(page, "extract_body_and_extra_fail")

    return body, extra_text


def extract_explanation(page):
    try:
        wait_until_explanation_ready(page)
        page.wait_for_timeout(300)

        el = get_explanation_body_locator(page)
        el.wait_for(state="attached", timeout=5000)

        text = locator_text_with_br(el)

        debug_log(f"[디버그] 해설(<br> 줄바꿈 유지):\n{text[:300]}")
        return text

    except Exception as e:
        print(f"[해설 추출 오류] {e}")
        save_debug(page, "extract_explanation_fail")
        return ""


def _extract_tag_value(text: str, label: str) -> str:
    text = sanitize_text(text)

    if label not in text:
        return ""

    value = text.replace(label, "", 1)

    # 사이트에서 | 대신 한글 세로획 ㅣ 또는 전각 ｜가 들어가는 경우까지 제거
    value = value.replace("|", " ")
    value = value.replace("ㅣ", " ")
    value = value.replace("｜", " ")

    value = re.sub(r"\s+", " ", value).strip()

    return value


def has_em_highlight(locator) -> bool:
    """
    초록색 강조 표시 여부 확인.
    예: <em class="em">3번</em>, <em class="em">73%</em>
    """
    try:
        return locator.locator("em.em").count() > 0
    except Exception:
        return False


def get_em_text(locator) -> str:
    """
    em.em 안의 텍스트만 가져옵니다.
    없으면 빈 문자열을 반환합니다.
    """
    try:
        em = locator.locator("em.em").first
        if em.count() > 0:
            return sanitize_text(em.inner_text())
    except Exception:
        pass

    return ""


def clean_pt_teacher_tip(result: dict) -> dict:
    """
    PT쌤 합격팁 결과에서 실제 필요한 값만 남깁니다.
    빈 문자열, 빈 배열, None 값은 저장하지 않습니다.
    """
    if not result or not result.get("has_tip"):
        return {"has_tip": False}

    cleaned = {
        "has_tip": True,
    }

    for key in ["tip_type", "title", "difficulty", "answer_rate"]:
        value = result.get(key)
        if value not in ("", None, [], {}):
            cleaned[key] = value

    tip_type = result.get("tip_type")

    if tip_type == "choice_rate_table":
        question_type = result.get("question_type")
        if question_type:
            cleaned["question_type"] = question_type

        rates = []
        for item in result.get("choice_answer_rates", []) or []:
            choice = item.get("choice")
            rate = item.get("rate")
            index = item.get("index")

            row = {}
            if choice:
                row["choice"] = choice
            if rate:
                row["rate"] = rate
            if index is not None:
                row["index"] = index

            if row:
                rates.append(row)

        if rates:
            cleaned["choice_answer_rates"] = rates

        for key in ["highlighted_choice", "highlighted_rate", "highlighted_index"]:
            value = result.get(key)
            if value not in ("", None, [], {}):
                cleaned[key] = value

    elif tip_type == "trend_analysis":
        trend = result.get("trend")
        if trend:
            cleaned["trend"] = trend

    else:
        # 예외 구조가 생겼을 때만 값이 있는 필드를 최소 저장
        for key in [
            "question_type",
            "trend",
            "choice_answer_rates",
            "highlighted_choice",
            "highlighted_rate",
            "highlighted_index",
        ]:
            value = result.get(key)
            if value not in ("", None, [], {}):
                cleaned[key] = value

    analysis = result.get("analysis")
    if analysis:
        cleaned["analysis"] = analysis

    return cleaned


def extract_pt_teacher_tip(page) -> dict:
    """
    PT쌤 합격팁을 비기봇 해설과 분리해서 추출합니다.

    지원 구조:
    1) 개념 난이도 + 정답률 + 출제 경향 + 분석
       -> tip_type = trend_analysis

    2) 개념 난이도 + 정답률 + 유형 + 선지별 선택률 표 + 분석
       -> tip_type = choice_rate_table
    """
    result = make_empty_pt_teacher_tip()

    try:
        card = get_pt_teacher_tip_card_locator(page)

        if card is None:
            return result

        raw_text = locator_text_with_br(card)

        if not contains_any_title(raw_text, PT_TEACHER_TIP_TITLE_VARIANTS):
            print(f"[경고] PT쌤 합격팁 카드 후보를 찾았지만 제목 확인 실패: {raw_text[:200]}")
            return make_empty_pt_teacher_tip()

        result["has_tip"] = True
        result["title"] = PT_TEACHER_TIP_TITLE

        # 난이도 / 정답률 / 유형 태그
        try:
            tags = card.locator("a.tag")
            tag_count = tags.count()

            for i in range(tag_count):
                txt = sanitize_text(tags.nth(i).inner_text())

                if "개념 난이도" in txt:
                    result["difficulty"] = _extract_tag_value(txt, "개념 난이도")
                elif "정답률" in txt:
                    result["answer_rate"] = _extract_tag_value(txt, "정답률")
                elif "유형" in txt:
                    result["question_type"] = _extract_tag_value(txt, "유형")

        except Exception as e:
            print(f"[PT쌤 합격팁 태그 추출 오류] {e}")

        # 선지별 선택률 표 + 초록색 강조 정답 추출
        try:
            table = card.locator("table.tb1").first

            if table.count() > 0:
                ths = table.locator("thead th")
                tds = table.locator("tbody td")

                choice_answer_rates = []

                max_count = min(ths.count(), tds.count())

                for i in range(max_count):
                    th = ths.nth(i)
                    td = tds.nth(i)

                    choice_text = sanitize_text(th.inner_text())
                    rate_text = sanitize_text(td.inner_text())

                    choice_em_text = get_em_text(th)
                    rate_em_text = get_em_text(td)

                    is_choice_highlighted = has_em_highlight(th)
                    is_rate_highlighted = has_em_highlight(td)
                    is_highlighted = is_choice_highlighted or is_rate_highlighted

                    item = {
                        "choice": choice_text,
                        "rate": rate_text,
                        "index": i + 1,
                    }

                    choice_answer_rates.append(item)

                    # 초록색 표시된 선지/정답률을 별도 필드에도 저장
                    if is_highlighted:
                        result["highlighted_choice"] = choice_em_text or choice_text
                        result["highlighted_rate"] = rate_em_text or rate_text
                        result["highlighted_index"] = i + 1

                result["choice_answer_rates"] = choice_answer_rates

        except Exception as e:
            print(f"[PT쌤 합격팁 선택률 표 추출 오류] {e}")

        # 출제 경향 / 분석
        try:
            items = card.locator("ul.bu > li")
            item_count = items.count()

            for i in range(item_count):
                li = items.nth(i)

                title = ""
                body = ""

                try:
                    title = sanitize_text(
                        li.locator(":scope > strong.tt2").first.inner_text()
                    )
                except Exception:
                    pass

                try:
                    body = locator_text_with_br(
                        li.locator(":scope > div.t1").first
                    )
                except Exception:
                    pass

                if "출제 경향" in title:
                    result["trend"] = body
                elif "분석" in title:
                    result["analysis"] = body

        except Exception as e:
            print(f"[PT쌤 합격팁 출제경향/분석 추출 오류] {e}")

        # 유형 구분
        has_choice_rate_table = bool(result.get("choice_answer_rates"))
        has_trend = bool(result.get("trend"))
        has_question_type = bool(result.get("question_type"))
        has_analysis = bool(result.get("analysis"))

        if has_choice_rate_table:
            result["tip_type"] = "choice_rate_table"
        elif has_trend:
            result["tip_type"] = "trend_analysis"
        elif has_question_type:
            result["tip_type"] = "type_analysis"
        elif has_analysis:
            result["tip_type"] = "analysis_only"
        else:
            result["tip_type"] = "unknown"

        debug_log(
            "[디버그] PT쌤 합격팁 추출: "
            f"has_tip={result.get('has_tip')}, "
            f"tip_type={result.get('tip_type', '')}, "
            f"difficulty={result.get('difficulty', '')}, "
            f"answer_rate={result.get('answer_rate', '')}, "
            f"question_type={result.get('question_type', '')}"
        )
        
        return clean_pt_teacher_tip(result)

    except Exception as e:
        print(f"[PT쌤 합격팁 추출 오류] {e}")
        save_debug(page, "extract_pt_teacher_tip_fail")
        return make_empty_pt_teacher_tip()


def has_latex_or_formula_text(text: str) -> bool:
    """
    텍스트 안에 LaTeX/수식 렌더링 확인이 필요한 표현이 있는지 판단합니다.

    주의:
    - SQL 컬럼명/식별자에서 자주 쓰는 M_SAL, EMP_NO, ORDER_ID 같은 언더스코어는
      수식 첨자로 보지 않습니다.
    - SQL의 일반 =, *, /, _ 만으로는 True를 반환하지 않습니다.
    """
    text = text or ""

    if not text.strip():
        return False

    # SQL/DB 식별자에서 흔한 대문자_대문자 패턴 제거
    # 예: M_SAL, EMP_NO, ORDER_ID, USER_ID
    text_for_check = re.sub(
        r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b",
        "",
        text,
    )

    patterns = [
        r"\$[^$\n]+\$",                 # $...$
        r"\$\$[\s\S]+?\$\$",            # $$...$$
        r"\\[a-zA-Z]+",                 # \frac, \sqrt, \text, \left 등
        r"\\\(",                        # \(
        r"\\\)",                        # \)
        r"\\\[",                        # \[
        r"\\\]",                        # \]
        r"\\begin\{",
        r"\\end\{",
        r"\^\{[^}]+\}",                 # x^{2}
        r"_\{[^}]+\}",                  # x_{i}
        r"\b[a-z]\s*_[a-z0-9]\b",       # x_i, a_n 같은 소문자 수식 첨자만 허용
        r"\b[a-z]\s*\^\s*[0-9a-z]\b",   # x^2, a^n
        r"[∑√≤≥±×÷∞≈≠→←↔∫∂∆πθαβγμσΩ]",
        r"MathJax",
        r"mjx-container",
        r"<math",
        r"<mjx-",
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]",
    ]

    return any(re.search(pattern, text_for_check) for pattern in patterns)


def should_capture_explanation(page, text):
    """
    해설에 LaTeX/수식/MathJax/표/이미지가 있으면 해설 이미지를 캡처합니다.
    일반 SQL의 =, *, / 만으로는 캡처하지 않습니다.
    """
    text = text or ""

    if explanation_has_render_elements(page):
        print("[판단] 해설에 이미지/표/MathJax/수식 렌더링 요소 존재 -> 해설 이미지 캡처")
        return True

    if has_latex_or_formula_text(text):
        print("[판단] 해설에 LaTeX/수식 패턴 감지 -> 해설 이미지 캡처")
        return True

    return False


def dedupe_image_elements(image_elements: list[dict]) -> list[dict]:
    """
    같은 이미지 또는 같은 렌더링 캡처는 한 번만 남깁니다.
    render_screenshot은 saved_path가 달라도 location + caption 기준으로 중복 제거합니다.
    """
    result = []
    seen = set()

    for item in image_elements:
        img_type = item.get("type", "")
        location = item.get("location", "")
        caption = item.get("caption_or_near_text", "")
        saved_path = item.get("saved_path", "")

        if img_type == "render_screenshot":
            key = (img_type, location, caption)
        else:
            key = (location, caption, saved_path)

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def extract_choices(page, question_id, image_elements=None):
    choices = []
    choice_image_map = {}

    if image_elements:
        for item in image_elements:
            if item.get("location") == "choice":
                saved_name = Path(item.get("saved_path", "")).name
                caption = item.get("caption_or_near_text", "")
                m = re.search(r"choice_(\d+)", caption or "")
                if m:
                    choice_image_map[m.group(1)] = saved_name

    try:
        items = page.locator("ol.lst1 li.li1")
        count = items.count()

        for i in range(count):
            li = items.nth(i)

            num_raw = li.locator("i.t1n").first.text_content() or ""
            num = re.sub(r"\D+", "", num_raw).strip()
            if not num:
                num = str(i + 1)

            text_val = ""
            try:
                text_locator = li.locator("span.t1t1").first
                text_val = locator_text_with_br(text_locator)
            except Exception:
                text_val = ""

            text_val = re.sub(rf"^{re.escape(num)}[.)]\s+", "", text_val).strip()

            if text_val:
                choices.append(f"{num}. {text_val}")
                continue

            if num in choice_image_map:
                choices.append(f"{num}. [이미지 선지: {choice_image_map[num]}]")
            else:
                filename = get_image_name_from_li(li, question_id, num)
                choices.append(f"{num}. [이미지 선지: {filename}]")

    except Exception as e:
        print(f"[선지 추출 오류] {e}")
        save_debug(page, "extract_choices_fail")

    return choices[:4]


def extract_answer_from_dom(page):
    try:
        correct_item = page.locator("ol.lst1 li.li1.correct").first

        if correct_item.count() == 0:
            correct_item = page.locator("ol.lst1 li.li1.on.correct").first

        if correct_item.count() == 0:
            return ""

        num_text = correct_item.locator("i.t1n").first.text_content() or ""
        num_text = re.sub(r"\D+", "", num_text).strip()

        if num_text:
            debug_log(f"[성공] 정답 추출: {num_text}")
            return num_text

    except Exception as e:
        print(f"[정답 추출 오류] {e}")
        save_debug(page, "answer_dom_fail")

    return ""


def normalize_subject_text(txt: str):
    txt = sanitize_text(txt)
    txt = re.sub(r"\[\d+과목\]\s*", "", txt)
    return txt.strip()


def get_subjects(page, cfg):
    subject_mode = cfg.get("subject_mode", "none")
    subject_name = cfg.get("subject_name")
    subject_start_index = cfg.get("subject_start_index", 1)
    subject_end_index = cfg.get("subject_end_index")

    if subject_mode == "none":
        return ["__single__"]

    if subject_mode == "specific" and subject_name:
        return [subject_name]

    found = []

    cards = page.locator("div.cp1flist2 ul.lst1 > li.li1")
    count = cards.count()

    for i in range(count):
        try:
            title = (cards.nth(i).locator(":scope > span.t1").first.text_content() or "").strip()
            title = normalize_subject_text(title)
            if title and title not in found:
                found.append(title)
        except Exception:
            continue

    print(f"[정제된 과목 목록] {found}")

    if subject_mode == "first":
        return found[:1] if found else []

    if subject_mode == "all":
        if not found:
            return []
        if subject_end_index is None:
            subject_end_index = len(found)

        start_idx = max(subject_start_index - 1, 0)
        end_idx = min(subject_end_index, len(found))
        return found[start_idx:end_idx]

    return found


def is_text_visible(page, text, timeout=2000):
    try:
        loc = page.get_by_text(text, exact=False).first
        loc.wait_for(timeout=timeout)
        return loc.is_visible()
    except Exception:
        return False


def scroll_target_above_bottom_nav(page, locator, extra_margin=170):
    try:
        locator.evaluate("""
            (el) => {
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
            }
        """)
        page.wait_for_timeout(400)

        box = locator.bounding_box()
        viewport = page.viewport_size

        if not box or not viewport:
            return False

        safe_bottom = viewport["height"] - extra_margin
        element_bottom = box["y"] + box["height"]

        if element_bottom > safe_bottom:
            move_up = element_bottom - safe_bottom + 40
            page.mouse.wheel(0, move_up)
            page.wait_for_timeout(300)

        return True

    except Exception as e:
        print(f"[스크롤 보정 실패] {e}")
        return False


def collect_visible_set_cards(page):
    results = []
    cards = page.locator("div.cp1flist1 li.li1 a.a1, div.cp1flist2 li.li1 a.a1")
    count = cards.count()

    for i in range(count):
        try:
            card = cards.nth(i)
            title_el = card.locator("strong.t1").first
            if title_el.count() == 0:
                continue

            title = sanitize_text(title_el.text_content() or "")
            if not title:
                continue

            results.append((i, card, title))
        except Exception:
            continue

    return results


def click_set_card(page, set_name):
    try:
        page.locator("div.cp1flist1 strong.t1, div.cp1flist2 strong.t1").first.wait_for(
            state="attached", timeout=10000
        )

        target_norm = sanitize_text(set_name)
        seen_titles = set()
        prev_last_title = ""
        max_scroll_try = 12

        for attempt in range(max_scroll_try):
            found_cards = collect_visible_set_cards(page)
            debug_log(f"[디버그] 세트 카드 개수(시도 {attempt + 1}): {len(found_cards)}")

            current_titles = []

            for idx, card, title in found_cards:
                current_titles.append(title)
                debug_log(f"[디버그] 세트 카드 제목[{idx}]: {title}")
                seen_titles.add(title)

                if title != target_norm:
                    continue

                href = card.get_attribute("href") or ""
                onclick = card.get_attribute("onclick") or ""
                debug_log(f"[디버그] 클릭 대상 href[{idx}]: {href}")
                debug_log(f"[디버그] 클릭 대상 onclick[{idx}]: {onclick}")

                scroll_target_above_bottom_nav(page, card)
                page.wait_for_timeout(300)

                try:
                    card.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    print(f"[성공] 세트 클릭: {title}")
                    print(f"[디버그] 세트 클릭 후 URL: {page.url}")
                    return True
                except Exception as click_err:
                    print(f"[경고] 직접 클릭 실패: {click_err}")

                if href:
                    try:
                        full_url = urljoin(page.url, href)
                        print(f"[디버그] 직접 이동 URL[{idx}]: {full_url}")
                        page.goto(full_url, wait_until="domcontentloaded")
                        page.wait_for_timeout(2000)
                        print(f"[성공] 세트 직접 이동: {title}")
                        print(f"[디버그] 세트 직접 이동 후 URL: {page.url}")
                        return True
                    except Exception as goto_err:
                        print(f"[경고] href 직접 이동 실패: {goto_err}")

                raise RuntimeError(f"세트 '{title}' 클릭/이동 모두 실패")

            last_title = current_titles[-1] if current_titles else ""

            if last_title and last_title == prev_last_title:
                print("[정보] 추가 스크롤해도 새 세트 카드가 나타나지 않습니다.")
                break
            prev_last_title = last_title

            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)

        print(f"[실패] 세트 '{set_name}'를 찾지 못했습니다.")
        print(f"[디버그] 지금까지 본 세트들: {sorted(seen_titles)}")
        save_debug(page, "set_card_not_found_after_scroll")
        return False

    except Exception as e:
        print(f"[오류] 세트 카드 클릭 실패: {e}")
        save_debug(page, "set_card_click_fail")
        return False


def click_course_card(page, course_name):
    try:
        target_norm = sanitize_text(course_name)
        prev_last_title = ""
        max_scroll_try = 10

        for attempt in range(max_scroll_try):
            cards = page.locator("li.li1 a.a1")
            count = cards.count()
            current_titles = []

            for i in range(count):
                try:
                    card = cards.nth(i)
                    title_el = card.locator("strong.t1, span.t1").first
                    if title_el.count() == 0:
                        continue

                        # noqa: unreachable
                    title = title_el.evaluate("""
                        (el) => {
                            const clone = el.cloneNode(true);
                            clone.querySelectorAll('em.em5').forEach(e => e.remove());
                            return (clone.textContent || '').replace(/\\s+/g, ' ').trim();
                        }
                    """)
                    title = sanitize_text(title)

                    if not title:
                        continue

                    current_titles.append(title)
                    debug_log(f"[디버그] 강좌 카드[{i}]: {title}")

                    if title != target_norm:
                        continue

                    scroll_target_above_bottom_nav(page, card)
                    page.wait_for_timeout(300)
                    card.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    print(f"[성공] 강좌 클릭: {title}")
                    return True

                except Exception as inner_e:
                    print(f"[경고] 강좌 카드[{i}] 처리 실패: {inner_e}")
                    continue

            last_title = current_titles[-1] if current_titles else ""
            if last_title and last_title == prev_last_title:
                print("[정보] 추가 스크롤해도 새 강좌 카드가 없습니다.")
                break
            prev_last_title = last_title

            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)

        print(f"[실패] 강좌 '{course_name}'를 찾지 못했습니다.")
        save_debug(page, f"course_card_not_found_{norm_id_text(course_name)}")
        return False

    except Exception as e:
        print(f"[오류] 강좌 카드 클릭 실패: {e}")
        save_debug(page, "course_card_click_fail")
        return False


def navigate_to_target(page, cfg):
    ensure_main_page(page)
    save_debug(page, "before_mypt_click")

    if not click_bottom_nav_mypt(page):
        save_debug(page, "mypt_not_found")
        raise RuntimeError("마이PT를 찾지 못했습니다.")
    page.wait_for_timeout(3000)
    save_debug(page, "after_mypt_click")

    course_name = cfg.get("course_name", "")
    if course_name:
        if not click_course_card(page, course_name):
            save_debug(page, "course_not_found")
            raise RuntimeError(f"강좌 '{course_name}'를 찾지 못했습니다.")
        save_debug(page, "after_course_click")

    if not click_bottom_nav_study(page):
        save_debug(page, "bottom_study_not_found")
        raise RuntimeError("하단 공부하기 버튼을 찾지 못했습니다.")

    page.locator("div.cp1flist1 strong.t1, div.cp1flist2 strong.t1").first.wait_for(
        state="attached", timeout=10000
    )
    page.wait_for_timeout(1000)
    save_debug(page, "after_study_click")
    
    if not click_set_card(page, cfg["set_name"]):
        save_debug(page, "set_not_found")
        raise RuntimeError(f"세트 '{cfg['set_name']}'를 찾지 못했습니다.")

    wait_for_list_ready(page)
    save_debug(page, "after_set_click")

    if cfg.get("exam_round"):
        if not is_text_visible(page, str(cfg["exam_round"]), timeout=5000):
            save_debug(page, "round_not_found")
            raise RuntimeError(f"회차 '{cfg['exam_round']}'를 찾지 못했습니다.")

        click_by_text(page, str(cfg["exam_round"]), exact=False)
        wait_for_question_ready(page)
        save_debug(page, "after_round_click")

    subjects = get_subjects(page, cfg)
    print(f"[과목 목록] {subjects}")
    return subjects


def get_question_number_fast(page):
    """
    wait_for 없이 현재 DOM에서 문제 번호만 빠르게 읽습니다.
    go_next_question 내부용입니다.
    """
    try:
        value = page.evaluate("""
            () => {
                const el = document.querySelector(
                    "div.cp1question1 div.tg1 strong.tt1 span.tt1n"
                );
                if (!el) return null;

                const text = el.textContent || "";
                const match = text.match(/\\d+/);
                return match ? Number(match[0]) : null;
            }
        """)
        return value
    except Exception:
        return None
    
    
def replace_qnum_in_url(url: str, target_no: int) -> str | None:
    """
    현재 문제 URL에서 qNum 값만 target_no로 교체합니다.
    """
    if not url:
        return None

    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)

    if not query_items:
        return None

    has_qnum = False
    new_query_items = []

    for key, value in query_items:
        if key == "qNum":
            new_query_items.append((key, str(target_no)))
            has_qnum = True
        else:
            new_query_items.append((key, value))

    if not has_qnum:
        return None

    new_query = urlencode(new_query_items, doseq=True)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def to_question_view_url(url: str | None) -> str | None:
    """
    문제 번호 이동 화면 URL(exam1numberX.php)을
    실제 문제 화면 URL(exam1viewX.php)로 변환합니다.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        new_path = re.sub(
            r"exam1number(\d+)\.php",
            r"exam1view\1.php",
            parsed.path,
        )

        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                new_path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )

    except Exception:
        return url



def find_qnum_base_url_from_page(page, target_no: int) -> str | None:
    """
    현재 페이지의 문제 이동 링크를 기준으로 qNum만 바꾼 URL을 만듭니다.
    우선순위:
    1) 이전/다음 문제 링크: .cp1control1 a.btn-move
    2) 상단 현재 문제 번호 링크: .cp1body1head1 a.b2
    3) fallback: 기존 전체 qNum 링크 검색
    """
    try:
        raw_url = page.evaluate(
            """
            () => {
                const preferredSelectors = [
                    ".cp1control1 a.btn-move[href*='qNum='][href*='exam1view']",
                    ".cp1body1head1 a.b2[href*='qNum='][href*='exam1number']",
                    ".cp1body1head1 a.b2[href*='qNum=']"
                ];

                for (const sel of preferredSelectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const href = el.getAttribute("href") || "";
                        if (href) return href;
                    }
                }

                const els = Array.from(document.querySelectorAll("a[href*='qNum=']"));

                for (const el of els) {
                    const href = el.getAttribute("href") || "";
                    if (href.includes("exam1view")) return href;
                }

                for (const el of els) {
                    const href = el.getAttribute("href") || "";
                    if (href.includes("exam1number")) return href;
                }

                return "";
            }
            """
        )

        if not raw_url:
            return None

        full_url = urljoin(page.url, raw_url)
        target_url = replace_qnum_in_url(full_url, target_no)
        return to_question_view_url(target_url)

    except Exception as e:
        print(f"[경고] qNum base URL 탐색 실패: {e}")
        return None

def normalize_exam_unique_no(value: Any) -> str:
    """
    DB/프론트에서 넘어온 시험 고유번호를 문자열로 정리합니다.
    """
    if value in (None, "", [], {}):
        return ""

    text = str(value).strip()

    try:
        return str(int(float(text)))
    except Exception:
        return text


def get_cfg_exam_unique_no(cfg: dict[str, Any]) -> str:
    """
    cfg 또는 cfg.questions 안에서 시험 고유번호를 찾습니다.
    우선순위:
    1) cfg["exam_unique_no"]
    2) cfg["exam"]
    3) questions 안의 exam_unique_no
    """
    direct = normalize_exam_unique_no(
        cfg.get("exam_unique_no") or cfg.get("exam")
    )

    if direct:
        return direct

    questions = cfg.get("questions") or []

    if isinstance(questions, list):
        exam_values = []

        for q in questions:
            if not isinstance(q, dict):
                continue

            exam = normalize_exam_unique_no(
                q.get("exam_unique_no") or q.get("exam")
            )

            if exam:
                exam_values.append(exam)

        unique_values = sorted(set(exam_values))

        if len(unique_values) == 1:
            return unique_values[0]

    return ""


def extract_source_identity_from_url(page) -> dict:
    """
    현재 문제 URL에서 exam, qNum을 추출합니다.
    DB 반영 시 exam_unique_no + question_no 매칭용으로 사용합니다.
    """
    try:
        parsed = urlparse(page.url)
        qs = parse_qs(parsed.query)

        exam = normalize_exam_unique_no(
            (qs.get("exam") or [""])[0]
        )

        qnum = (qs.get("qNum") or [""])[0]
        qnum_int = int(qnum) if str(qnum).isdigit() else None

        return {
            "exam_unique_no": exam,
            "site_question_no": qnum_int,
            "source_url": page.url,
        }

    except Exception:
        return {
            "exam_unique_no": "",
            "site_question_no": None,
            "source_url": page.url if hasattr(page, "url") else "",
        }

def go_to_question_number(page, target_no: int) -> bool:
    """
    현재 URL 또는 현재 화면의 qNum 링크를 기준으로
    실제 문제 화면(exam1viewX.php)으로 바로 이동합니다.
    """
    target_no = int(target_no)

    try:
        current_no = extract_question_number(page)

        if current_no is not None and int(current_no) == target_no:
            print(f"[정보] 이미 지정 문제 위치입니다: {target_no}")
            return True
    except Exception:
        pass

    # 1순위: 현재 URL에서 qNum만 바꾸고, 반드시 exam1view URL로 보정
    target_url = replace_qnum_in_url(page.url, target_no)
    target_url = to_question_view_url(target_url)

    # 2순위: 현재 화면 안의 qNum 링크를 찾아서 qNum만 바꾸고, 반드시 exam1view URL로 보정
    if not target_url:
        target_url = find_qnum_base_url_from_page(page, target_no)
        target_url = to_question_view_url(target_url)

    if not target_url:
        print(f"[경고] qNum 이동 URL을 만들지 못했습니다: {target_no}")
        save_debug(page, f"qnum_url_not_found_{target_no}")
        return False

    try:
        print(f"[이동] qNum 기반 실제 문제 화면 직접 이동: {target_no} / {target_url}")

        page.goto(target_url, wait_until="domcontentloaded", timeout=15000)

        ready = wait_for_question_ready(page, timeout=8000)

        if not ready:
            print(
                f"[경고] qNum 이동 후 문제 화면 DOM을 찾지 못했습니다: "
                f"target={target_no}, url={page.url}"
            )
            save_debug(page, f"qnum_question_not_ready_{target_no}")
            return False

        current_no = extract_question_number(page)

        if current_no is not None and int(current_no) == target_no:
            print(f"[성공] qNum 기반 지정 문제 이동: {target_no}")
            return True

        print(
            f"[경고] qNum 이동 후 문제 번호 불일치: "
            f"target={target_no}, current={current_no}"
        )
        save_debug(page, f"qnum_mismatch_target_{target_no}_current_{current_no}")
        return False

    except Exception as e:
        print(f"[qNum 지정 문제 이동 오류] target={target_no}, err={e}")
        save_debug(page, f"qnum_go_to_question_fail_{target_no}")
        return False
    
  
def collect_selected_questions_direct(
    page,
    selected_questions,
    cfg: dict[str, Any],
    real_subject,
    sub_title=None,
    collect_options=None,
    cancel_checker=None,
):
    """
    question_numbers가 지정된 경우:
    현재 URL 또는 현재 화면 안의 qNum 링크를 기준으로
    실제 문제 화면(exam1viewX.php)의 qNum만 바꿔 선택 문제를 직접 수집합니다.

    예:
    현재 URL이 exam1view2.php?exam=375&qNum=1일 때
    [6, 18]
    → exam1view2.php?exam=375&qNum=6 이동 → 6번 수집/저장
    → exam1view2.php?exam=375&qNum=18 이동 → 18번 수집/저장
    """
    
    collect_options = collect_options or {}

    for target_no in sorted(selected_questions):
        check_cancel(cancel_checker)

        moved = go_to_question_number(page, target_no)

        if not moved:
            print(f"[경고] {target_no}번 qNum 직접 이동 실패 - 이 문제는 건너뜁니다.")
            continue

        q = extract_question(
            page,
            cfg["course_name"],
            cfg["set_name"],
            real_subject,
            capture_assets=True,
            sub_title=sub_title,
            collect_options=collect_options,
        )
        
        expected_exam = get_cfg_exam_unique_no(cfg)
        actual_exam = str(q.get("exam_unique_no") or "").strip()

        if expected_exam and actual_exam and expected_exam != actual_exam:
            print(
                f"[경고] DB 시험 고유번호와 실제 수집 URL의 exam 값이 다릅니다. "
                f"expected={expected_exam}, actual={actual_exam}, target_no={target_no}"
            )
            save_debug(page, f"exam_mismatch_expected_{expected_exam}_actual_{actual_exam}_q_{target_no}")
            continue        

        collected_no = q.get("question_no")

        if collected_no is None or int(collected_no) != int(target_no):
            print(
                f"[경고] 요청한 문제와 실제 수집 문제가 다릅니다. "
                f"target={target_no}, collected={q.get('question_no')}"
            )
            save_debug(page, f"selected_question_mismatch_{target_no}")
            continue

        save_raw_question_if_valid(
            q,
            page=page,
            debug_name=f"empty_collected_question_{target_no}",
        )

    print("[완료] 선택 문제 직접 수집 종료")
    

def go_next_question(page, current_no):
    old_no = current_no

    try:
        btn = page.locator("a.b1.next.btn-move")

        if btn.count() == 0:
            print("[완료] 마지막 문제까지 도달했습니다. 다음 버튼 없음")
            return None

        btn.first.click(timeout=3000)
        progress_log("[클릭] 다음 문제 버튼 클릭")

        try:
            page.wait_for_function(
                """
                (oldNo) => {
                    const el = document.querySelector(
                        "div.cp1question1 div.tg1 strong.tt1 span.tt1n"
                    );
                    if (!el) return false;

                    const text = el.textContent || "";
                    const match = text.match(/\\d+/);
                    if (!match) return false;

                    return Number(match[0]) !== oldNo;
                }
                """,
                arg=old_no,
                timeout=5000
            )

            new_no = get_question_number_fast(page)

            if new_no is None:
                new_no = extract_question_number(page)

            progress_log(f"[성공] 다음 문제 이동: {old_no} -> {new_no}")
            return True

        except PlaywrightTimeoutError:
            print("[실패] 클릭했지만 문제 번호 안 바뀜")
            return False

    except Exception as e:
        print(f"[오류] 다음 문제 클릭 실패: {e}")
        save_debug(page, "next_click_fail")

    return False

def has_collected_content(q: dict[str, Any]) -> bool:
    data = q.get("data", {}) or {}

    has_question_material = bool(
        str(data.get("body") or "").strip()
        or str(data.get("extra_text") or "").strip()
        or (data.get("image_elements") or [])
    )

    has_review_material = bool(
        (data.get("choices") or [])
        or str(data.get("answer") or "").strip()
        or str(data.get("explanation") or "").strip()
        or (data.get("keywords") or [])
        or bool((data.get("pt_teacher_tip") or {}).get("has_tip"))
        or (data.get("explanation_images") or [])
    )

    return has_question_material and has_review_material


def save_raw_question_if_valid(q: dict[str, Any], page=None, debug_name: str = "") -> bool:
    if not has_collected_content(q):
        print(
            f"[경고] 수집 결과가 비어 있어 RAW 저장을 건너뜁니다. "
            f"question_no={q.get('question_no')}, url={q.get('source_url', '')}"
        )

        if page is not None:
            save_debug(page, debug_name or f"empty_collected_question_{q.get('question_no', 'unknown')}")

        return False

    save_raw_question(q)
    return True


def save_raw_question(q: dict[str, Any]) -> Path:
    file_path = RAW_DIR / f"{q['question_id']}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)

    print(f"[RAW 저장] {file_path.name}")
    return file_path


def extract_question(
    page,
    course_name,
    set_name,
    subject_name,
    capture_assets=True,
    sub_title=None,
    collect_options=None,
):
    collect_options = collect_options or {}

    collect_body = collect_options.get("collect_body", True)
    collect_choices = collect_options.get("collect_choices", True)
    collect_answer = collect_options.get("collect_answer", True)
    collect_section_tags = collect_options.get("collect_section_tags", True)
    collect_explanation = collect_options.get("collect_explanation", True)
    collect_keywords = collect_options.get("collect_keywords", True)
    collect_pt_teacher_tip = collect_options.get("collect_pt_teacher_tip", True)
    collect_question_images = collect_options.get("collect_question_images", True)
    collect_explanation_images = collect_options.get("collect_explanation_images", True)
    collect_render_images = collect_options.get("collect_render_images", True)
    
    question_no = extract_question_number(page)
    source_identity = extract_source_identity_from_url(page)

    qid = make_question_id(
        course_name,
        set_name,
        subject_name,
        question_no,
        sub_title=sub_title
    )

    if not capture_assets:
        return {
            "question_id": qid,
            "exam_unique_no": source_identity.get("exam_unique_no", ""),
            "site_question_no": source_identity.get("site_question_no"),
            "source_url": source_identity.get("source_url", ""),
            "course_name": course_name,
            "set_name": set_name,
            "subject_name": subject_name,
            "sub_title": sub_title,
            "question_no": question_no,
            "data": {
                "body": "",
                "extra_text": "",
                "choices": [],
                "answer": "",
                "explanation": "",
                "pt_teacher_tip": make_empty_pt_teacher_tip(),
                "explanation_images": [],
                "section_tags": [],
                "keywords": [],
                "has_image": False,
                "has_question_image": False,
                "has_choice_image": False,
                "image_elements": [],
                "explanation_capture_meta": {
                    "attempted": False,
                    "zoom_applied": False,
                    "fits_in_single_before_zoom": None,
                    "fits_in_single_after_zoom": None,
                    "needs_manual_review": False,
                    "capture_mode": "not_attempted",
                    "image_count": 0,
                },
                "question_image_capture_meta": {
                    "attempted": False,
                    "needs_manual_review": False,
                    "capture_mode": "not_attempted",
                    "image_count": 0,
                    "failed_indexes": [],
                },
            }
        }

    body = ""
    extra_text = ""
    choices = []
    answer = ""
    explanation = ""
    pt_teacher_tip = make_empty_pt_teacher_tip()
    section_tags = []
    keywords = []

    image_elements = []
    question_image_capture_meta = make_not_attempted_question_image_capture_meta()

    explanation_images = []
    explanation_capture_meta = make_not_needed_explanation_capture_meta()

    if collect_body:
        body, extra_text = extract_body_and_extra(page)

    if collect_answer:
        answer = extract_answer_from_dom(page)

    if collect_section_tags:
        section_tags = extract_section_tags(page)

    # 해설 영역 로딩이 필요한 경우
    need_help_area = (
        collect_explanation
        or collect_keywords
        or collect_pt_teacher_tip
        or collect_explanation_images
    )

    help_ready = False

    if need_help_area:
        if collect_explanation or collect_keywords or collect_explanation_images:
            explanation = extract_explanation(page)
            help_ready = True
        elif collect_pt_teacher_tip:
            # PT쌤 합격팁만 검수할 때는 해설 텍스트 저장 없이 도움말 영역 로딩만 확인
            help_ready = wait_until_explanation_ready(page)

    if collect_pt_teacher_tip:
        pt_teacher_tip = extract_pt_teacher_tip(page)

    if collect_keywords:
        keywords = extract_keywords(page, wait_ready=not help_ready)

    should_capture_expl = False

    if collect_explanation_images:
        should_capture_expl = should_capture_explanation(page, explanation)

    if collect_question_images:
        image_result = detect_images(
            page,
            qid,
            recollapse_after_choice_capture=should_capture_expl
        )

        image_elements = image_result.get("image_elements", [])
        question_image_capture_meta = image_result.get(
            "question_image_capture_meta",
            make_not_attempted_question_image_capture_meta()
        )

    if collect_choices:
        choices = extract_choices(page, qid, image_elements)

    if collect_render_images:
        already_has_question_render = any(
            item.get("type") == "render_screenshot"
            and item.get("location") == "question"
            for item in image_elements
        )

        render_image_elements = capture_formula_render_images(
            page=page,
            question_id=qid,
            body=body,
            extra_text=extra_text,
            choices=choices,
            skip_question_render=already_has_question_render,
        )

        if render_image_elements:
            image_elements.extend(render_image_elements)
    image_elements = dedupe_image_elements(image_elements)


    if should_capture_expl:
        explanation_capture_result = capture_explanation_images(
            page,
            qid,
            already_ready=True
        )
        explanation_images = explanation_capture_result.get("images", [])
        explanation_capture_meta = explanation_capture_result.get(
            "meta",
            explanation_capture_meta
        )

    has_question_image = any(
        img.get("location") == "question"
        and img.get("type") == "screenshot"
        for img in image_elements
    )

    has_choice_image = any(
        img.get("location") == "choice"
        and img.get("type") == "screenshot"
        for img in image_elements
    )

    has_render_image = any(
        img.get("type") == "render_screenshot"
        for img in image_elements
    )


    return {
        "question_id": qid,
        "exam_unique_no": source_identity.get("exam_unique_no", ""),
        "site_question_no": source_identity.get("site_question_no"),
        "source_url": source_identity.get("source_url", ""),
        "course_name": course_name,
        "set_name": set_name,
        "subject_name": subject_name,
        "sub_title": sub_title,
        "question_no": question_no,
        "data": {
            "body": body,
            "extra_text": extra_text,
            "choices": choices,
            "answer": answer,
            "explanation": explanation,
            "pt_teacher_tip": pt_teacher_tip,
            "explanation_images": explanation_images,
            "explanation_capture_meta": explanation_capture_meta,
            "section_tags": section_tags,
            "keywords": keywords,
            "has_image": bool(image_elements or explanation_images),
            "has_question_image": has_question_image,
            "question_image_capture_meta": question_image_capture_meta,
            "has_choice_image": has_choice_image,
            "image_elements": image_elements,
            "has_render_image": has_render_image,
        }
    }

              
def check_cancel(cancel_checker=None):
    if cancel_checker is not None:
        cancel_checker()
        

def run_collect_configs(
    configs: list[dict[str, Any]],
    headless: bool | None = None,
    cancel_checker=None,
) -> list[dict[str, Any]]:
    print("[확인] 최신 collect_api.py 실행 중")
    load_dotenv(ROOT / ".env")

    user_id = os.getenv("DATAEDU_ID")
    password = os.getenv("DATAEDU_PW")
    if not user_id or not password:
        raise RuntimeError("환경변수 DATAEDU_ID, DATAEDU_PW가 필요합니다.")

    if headless is None:
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() not in ("0", "false", "no")

    collect_errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--window-size=900,980"]
        )

        context = browser.new_context(
            viewport={"width": 900, "height": 900}
        )

        page = context.new_page()
        context.on("page", handle_new_page)

        login(page, user_id, password)
        check_cancel(cancel_checker)

        for cfg_idx, cfg in enumerate(configs, start=1):
            check_cancel(cancel_checker)

            try:
                print(f"\n[설정 시작 {cfg_idx}/{len(configs)}] "
                    f"{cfg['course_name']} / {cfg['set_name']}")

                selected_questions, start_no_global, end_no_global = parse_question_selection(cfg)

                page.goto(TARGET_MAIN_URL, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                ensure_main_page(page)

                subjects = navigate_to_target(page, cfg)
                save_debug(page, f"set_screen_ready_{cfg_idx}")

                set_screen_url = page.url
                print(f"[정보] 세트 화면 URL: {set_screen_url}")
                print(f"[정보] subjects: {subjects}")

                subtype_name = cfg.get("subtype_name")

                for idx, subject in enumerate(subjects):
                    try:
                        print(f"[과목 시작] cfg={cfg_idx}, idx={idx}, subject={subject}")

                        if idx > 0:
                            page.goto(set_screen_url, wait_until="domcontentloaded")
                            wait_for_list_ready(page)
                            save_debug(page, f"back_to_set_screen_{cfg_idx}_{idx}")

                        start_no, end_no = start_no_global, end_no_global

                        if subject not in [None, "__single__", "__FIRST__"]:
                            targets = get_subject_targets(page, subject, subtype_name=subtype_name)

                            if not targets:
                                save_debug(page, f"subject_start_not_found_{cfg_idx}_{norm_id_text(str(subject))}")
                                raise RuntimeError(f"'{subject}' 실행 대상을 찾지 못했습니다.")

                            print(f"[디버그] 실행 대상 수: {len(targets)}")

                            for t_idx, target in enumerate(targets):
                                check_cancel(cancel_checker)
                                try:
                                    print(f"[하위 실행 시작] cfg={cfg_idx}, idx={idx}, t_idx={t_idx}, target={target}")

                                    if t_idx > 0:
                                        page.goto(set_screen_url, wait_until="domcontentloaded")
                                        wait_for_list_ready(page)
                                        save_debug(page, f"back_to_set_screen_{cfg_idx}_{idx}_{t_idx}")

                                        # 다시 과목 화면의 동일 과목/하위카드 구조를 기준으로 타겟 재계산
                                        targets = get_subject_targets(page, subject, subtype_name=subtype_name)
                                        if t_idx >= len(targets):
                                            raise RuntimeError("재진입 후 실행 대상 인덱스가 맞지 않습니다.")
                                        target = targets[t_idx]

                                    if not click_subject_target(page, target):
                                        save_debug(page, f"subject_target_click_fail_{cfg_idx}_{idx}_{t_idx}")
                                        print(f"[경고] 실행 대상 클릭 실패: {target}")
                                        continue

                                    if not wait_for_question_ready(page, timeout=3000):
                                        print(f"[경고] 문제 화면 준비 실패 - 실행 대상을 건너뜁니다: {target}")
                                        save_debug(page, f"question_not_ready_after_subject_click_{cfg_idx}_{idx}_{t_idx}")
                                        continue

                                    save_debug(page, f"after_start_question_{cfg_idx}_{idx}")

                                    real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None

                                    # question_numbers가 있으면 선택 문제만 직접 이동해서 수집하고,
                                    # 기존 while True + 다음 버튼 순회는 타지 않습니다.
                                    if selected_questions is not None:
                                        collect_selected_questions_direct(
                                            page=page,
                                            selected_questions=selected_questions,
                                            cfg=cfg,
                                            real_subject=real_subject,
                                            sub_title=target["sub_title"] if target["has_subcards"] else None,
                                            collect_options=get_collect_options(cfg),
                                            cancel_checker=cancel_checker,
                                        )
                                        continue
                                                                        
                                    while True:
                                        check_cancel(cancel_checker)
                                        current_question_no = -1
                                        try:
                                            current_question_no = extract_question_number(page)

                                            if current_question_no is None:
                                                print("[경고] 현재 문제 번호를 읽지 못해 수집을 중단합니다.")
                                                save_debug(page, f"question_no_missing_cfg_{cfg_idx}_subject_{idx}_target_{t_idx}")
                                                break

                                            if current_question_no > end_no:
                                                break

                                            real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None
                                            capture_assets = should_save_question(current_question_no, selected_questions, start_no, end_no)

                                            q = extract_question(
                                                page,
                                                cfg["course_name"],
                                                cfg["set_name"],
                                                real_subject,
                                                capture_assets=capture_assets,
                                                sub_title=target["sub_title"] if target["has_subcards"] else None,
                                                collect_options=get_collect_options(cfg),
                                            )
                                        
                                            collected_no = q.get("question_no")

                                            if collected_no is None:
                                                print("[경고] 수집 후 문제 번호가 없어 RAW 저장을 건너뜁니다.")
                                                save_debug(page, f"collected_question_no_missing_cfg_{cfg_idx}_subject_{idx}_target_{t_idx}")
                                                break

                                            if should_save_question(collected_no, selected_questions, start_no, end_no):
                                                save_raw_question_if_valid(
                                                    q,
                                                    page=page,
                                                    debug_name=f"empty_collected_question_{collected_no}",
                                                )


                                            if collected_no >= end_no:
                                                break

                                            next_result = go_next_question(page, collected_no)

                                            if next_result is None:
                                                print("[완료] 현재 과목/하위 카드의 마지막 문제까지 수집했습니다.")
                                                break

                                            if next_result is False:
                                                print("[종료] 다음 문제 이동 실패")
                                                break

                                        except PlaywrightTimeoutError:
                                            print("[종료] 문제 처리 중 타임아웃")
                                            break
                                        except Exception as e:
                                            print(f"[수집 오류] {e}")
                                            save_debug(page, f"collect_error_cfg_{cfg_idx}_subject_{idx}_target_{t_idx}_q_{current_question_no}")
                                            break

                                except Exception as e:
                                    print(f"[하위 실행 처리 오류] cfg={cfg_idx}, subject={subject}, t_idx={t_idx} / {e}")
                                    save_debug(page, f"subject_target_error_cfg_{cfg_idx}_{idx}_{t_idx}")
                                    continue

                        else:
                            try:
                                click_by_text(page, "해설보며 이어하기", exact=False)
                            except Exception:
                                click_by_text(page, "해설보며 공부하기", exact=False)

                            page.wait_for_timeout(1500)
                            handle_resume_popup(page)

                            if not wait_for_question_ready(page):
                                print(f"[경고] 문제 화면 준비 실패 - 과목을 건너뜁니다: {subject}")
                                save_debug(page, f"question_not_ready_after_start_{cfg_idx}_{idx}")
                                continue

                            save_debug(page, f"after_start_question_{cfg_idx}_{idx}")

                            real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None

                            # question_numbers가 있으면 선택 문제만 직접 이동해서 수집하고,
                            # 기존 while True + 다음 버튼 순회는 타지 않습니다.
                            if selected_questions is not None:
                                collect_selected_questions_direct(
                                    page=page,
                                    selected_questions=selected_questions,
                                    cfg=cfg,
                                    real_subject=real_subject,
                                    sub_title=None,
                                    collect_options=get_collect_options(cfg),
                                    cancel_checker=cancel_checker,
                                )
                                continue
                                                                                            
                            while True:
                                check_cancel(cancel_checker)
                                current_question_no = -1
                                try:
                                    current_question_no = extract_question_number(page)

                                    if current_question_no is None:
                                        print("[경고] 현재 문제 번호를 읽지 못해 수집을 중단합니다.")
                                        save_debug(page, f"question_no_missing_cfg_{cfg_idx}_subject_{idx}")
                                        break

                                    if current_question_no > end_no:
                                        break

                                    real_subject = subject if isinstance(subject, str) and not subject.startswith("__") else None
                                    capture_assets = should_save_question(current_question_no, selected_questions, start_no, end_no)

                                    q = extract_question(
                                        page,
                                        cfg["course_name"],
                                        cfg["set_name"],
                                        real_subject,
                                        capture_assets=capture_assets,
                                        sub_title=None,
                                        collect_options=get_collect_options(cfg),
                                    )

                                    collected_no = q.get("question_no")

                                    if collected_no is None:
                                        print("[경고] 수집 후 문제 번호가 없어 RAW 저장을 건너뜁니다.")
                                        save_debug(page, f"collected_question_no_missing_cfg_{cfg_idx}_subject_{idx}")
                                        break

                                    if should_save_question(collected_no, selected_questions, start_no, end_no):
                                        save_raw_question_if_valid(
                                            q,
                                            page=page,
                                            debug_name=f"empty_collected_question_{collected_no}",
                                        )
                                        
                                    if collected_no >= end_no:
                                        break

                                    next_result = go_next_question(page, collected_no)

                                    if next_result is None:
                                        print("[완료] 현재 과목의 마지막 문제까지 수집했습니다.")
                                        break

                                    if next_result is False:
                                        print("[종료] 다음 문제 이동 실패")
                                        break

                                except PlaywrightTimeoutError:
                                    print("[종료] 문제 처리 중 타임아웃")
                                    break
                                except Exception as e:
                                    print(f"[수집 오류] {e}")
                                    save_debug(page, f"collect_error_cfg_{cfg_idx}_subject_{idx}_q_{current_question_no}")
                                    break

                    except Exception as e:
                        print(f"[과목 처리 오류] cfg={cfg_idx}, subject={subject} / {e}")
                        save_debug(page, f"subject_error_cfg_{cfg_idx}_{norm_id_text(str(subject))}")
                        continue

            except Exception as e:
                message = f"[설정 처리 오류] cfg={cfg_idx} / {e}"
                print(message)
                collect_errors.append(message)
                save_debug(page, f"config_error_{cfg_idx}")
                continue

        try:
            context.close()
        except Exception as e:
            print(f"[경고] context.close 실패 - 무시하고 계속 진행: {e}")

        try:
            browser.close()
        except Exception as e:
            print(f"[경고] browser.close 실패 - 무시하고 계속 진행: {e}")

    collected = load_json_files_from_raw()

    if not collected:
        if collect_errors:
            raise RuntimeError(
                "문제가 하나도 수집되지 않았습니다.\n\n"
                + "\n".join(collect_errors)
            )

        raise RuntimeError(
            "문제가 하나도 수집되지 않았습니다. "
            "강좌명, 세트명, 과목명, 하위유형, 문제 범위를 확인해 주세요."
        )

    return collected

def collect_from_target(
    target: dict[str, Any] | list[dict[str, Any]],
    job_id: str | None = None,
    job_dir: str | Path | None = None,
    headless: bool | None = None,
    cancel_checker=None,
) -> list[dict[str, Any]]:
    """
    사이트 API에서 받은 target 값을 한 번만 받아 수집을 실행합니다.
    job_dir를 넘기면 raw/debug/images가 해당 작업 폴더 아래에 저장됩니다.
    """
    if job_dir is None and job_id:
        job_dir = JOBS_DIR / job_id

    set_runtime_dirs(job_dir)
    configs = normalize_target_configs(target)
    return run_collect_configs(
        configs,
        headless=headless,
        cancel_checker=cancel_checker,
    )


def main():
    # 기존 로컬 실행 호환: run_config.json을 읽어 수집합니다.
    set_runtime_dirs(None)
    configs = load_config()
    run_collect_configs(configs)


if __name__ == "__main__":
    main()
