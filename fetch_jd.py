# -*- coding: utf-8 -*-

from DrissionPage import ChromiumPage, ChromiumOptions
import csv
import hashlib
import json
import os
import random
import re
import socket
import time
import traceback
from urllib.parse import parse_qs, unquote, urlparse


PRODUCT_ID = "100127936932"

MAX_ROUNDS_PER_SCORE = 40
MAX_TOTAL_NEW_ROWS = 500
MAX_DUPLICATE_ROUNDS = 3
MAX_NO_PACKET_ROUNDS = 3
MAX_TRIGGER_ATTEMPTS_PER_ROUND = 2
MAX_FAST_SEEK_STEPS = 14
MAX_FAST_FOLD_CATCHUP = 12
MAX_FAST_SCROLL_CATCHUP_STEPS = 40
MAX_SESSION_SECONDS = 60 * 60
LOGIN_WAIT_SECONDS = 300
RISK_RECOVERY_WAIT_SECONDS = 900

WAIT_PAGE_OPEN = (12, 20)
WAIT_AFTER_OVERLAY = (10, 16)
WAIT_AFTER_TAG = (12, 18)
WAIT_AFTER_SORT = (12, 20)
WAIT_AFTER_TRIGGER = (10, 18)
WAIT_SCROLL_STEP_1 = (8, 14)
WAIT_SCROLL_STEP_2 = (6, 10)
WAIT_SCROLL_STEP_3 = (8, 14)
WAIT_AFTER_WRITE = (6, 12)
WAIT_AFTER_CATEGORY = (20, 35)
WAIT_AFTER_EXPAND = (10, 18)
RISK_COOLDOWN = (180, 300)

FAST_WAIT_AFTER_TAG = (3, 5)
FAST_WAIT_AFTER_SORT = (3, 5)
FAST_WAIT_AFTER_TRIGGER = (2, 4)
FAST_WAIT_SCROLL_STEP_1 = (1.0, 2.0)
FAST_WAIT_SCROLL_STEP_2 = (0.8, 1.6)
FAST_WAIT_SCROLL_STEP_3 = (1.0, 2.0)
FAST_WAIT_AFTER_EXPAND = (1.5, 3.0)
FAST_WAIT_AFTER_WRITE = (0.6, 1.2)

MAX_NO_PACKET_ROUNDS_BY_SCORE = {
    "差评": 3,
    "中评": 3,
    "好评": 8,
}

RISK_TEXTS = [
    "访问过于频繁",
    "操作过于频繁",
    "安全验证",
    "请完成验证",
    "验证失败",
    "系统繁忙",
    "网络开小差",
    "休息一下再来",
]

LOW_VALUE_HINTS = [
    "已为您过滤了参考价值不大的评价",
    "已为您过滤了参考价值不大的评论",
    "参考价值不大",
]

NO_MORE_HINTS = [
    "没有更多了",
    "没有更多",
]

SCORE_MAP = {
    "差评": {"value": -1},
    "中评": {"value": 0},
    "好评": {"value": 1},
}

FOLD_TYPE_MAP = {
    "差评": "1",
    "中评": "2",
    "好评": "3",
}

CSV_FIELDS = [
    "commentId",
    "creationTime",
    "nickname",
    "referenceName",
    "userLevelId",
    "isPlus",
    "score",
    "content",
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "jd_comments_debug.csv")
PROGRESS_FILE = os.path.join(BASE_DIR, "jd_progress.json")
DEBUG_DIR = os.path.join(BASE_DIR, "jd_comment_debug")
ENDPOINT_LOG = os.path.join(BASE_DIR, "jd_found_endpoints.jsonl")
BLOCKED_PROFILE_DIR = os.path.join(BASE_DIR, "dp_browser_profile")
PROFILE_DIR = os.path.join(BASE_DIR, "dp_browser_profile_new_account")


def conservative_sleep(min_seconds, max_seconds, reason=""):
    seconds = random.uniform(min_seconds, max_seconds)
    if reason:
        print("⏳ %s，等待 %.1f 秒..." % (reason, seconds))
    else:
        print("⏳ 等待 %.1f 秒..." % seconds)
    time.sleep(seconds)


def sleep_pair(normal_pair, fast_pair, fast_mode, reason):
    pair = fast_pair if fast_mode else normal_pair
    conservative_sleep(pair[0], pair[1], reason)


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_browser_path():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        return value
    return ""


def normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_text(value):
    return normalize_text(value).replace(" ", "")


def sanitize_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return safe[:120]


def is_low_value_hint_text(text):
    text = compact_text(text)
    if not text or len(text) > 20:
        return False
    return any(hint in text for hint in LOW_VALUE_HINTS)


def is_no_more_text(text):
    text = compact_text(text)
    if not text or len(text) > 10:
        return False
    return any(hint in text for hint in NO_MORE_HINTS)


def parse_json_from_body(body):
    if body is None:
        return None
    if isinstance(body, (dict, list)):
        return body

    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="ignore")
    else:
        text = str(body)

    text = text.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    return None


def coerce_json_like(value):
    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")

    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    return value


def parse_label_round(label):
    match = re.match(r"(.+)_round_(\d+)$", normalize_text(label))
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        text = normalize_text(value)
        if text == "":
            return default
        return int(float(text))
    except Exception:
        return default


def safe_bool(value, default=False):
    if isinstance(value, bool):
        return value
    text = normalize_text(value).lower()
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    return default


def parse_url_body(url):
    url = normalize_text(url)
    if not url:
        return {}, ""

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
    except Exception:
        return {}, ""

    function_id = normalize_text(first_non_empty(
        query.get("functionId", [""])[0],
        query.get("fid", [""])[0],
    ))

    raw_body = first_non_empty(query.get("body", [""])[0], "")
    if not raw_body:
        return {}, function_id

    try:
        body = json.loads(unquote(raw_body))
        if isinstance(body, dict):
            return body, function_id
    except Exception:
        pass
    return {}, function_id


def extract_function_id(url):
    _body, function_id = parse_url_body(url)
    return function_id


def extract_fold_offset(url):
    body, function_id = parse_url_body(url)
    if function_id != "getFoldCommentList":
        return 0
    try:
        return int(body.get("offset", 0) or 0)
    except Exception:
        return 0


def extract_fold_type(url):
    body, function_id = parse_url_body(url)
    if function_id != "getFoldCommentList":
        return ""
    return normalize_text(body.get("type"))


def expected_fold_type(score_name):
    return normalize_text(FOLD_TYPE_MAP.get(score_name))


def is_valid_packet_url_for_score(score_name, url):
    function_id = extract_function_id(url)
    if function_id != "getFoldCommentList":
        return True

    expected_type = expected_fold_type(score_name)
    actual_type = extract_fold_type(url)
    if expected_type and actual_type != expected_type:
        return False
    return True


def looks_like_comment_dict(obj):
    if not isinstance(obj, dict):
        return False

    has_id = "commentId" in obj or "id" in obj
    has_content = any(k in obj for k in ["commentData", "commentContent", "content", "tagCommentContent"])
    has_meta = any(k in obj for k in ["commentDate", "creationTime", "commentTime", "userNickName", "nickname", "userName"])
    return has_id and has_content and has_meta


def extract_comment_infos_from_floor_data(floor_data):
    if not isinstance(floor_data, list):
        return []

    rows = []
    for item in floor_data:
        if not isinstance(item, dict):
            continue
        comment_info = item.get("commentInfo")
        if isinstance(comment_info, dict):
            rows.append(comment_info)
    return rows


def extract_direct_comment_list(value):
    if not isinstance(value, list) or not value:
        return []

    matched = [item for item in value if looks_like_comment_dict(item)]
    if matched and len(matched) >= max(1, len(value) // 2):
        return matched
    return []


def search_comment_infos(obj, depth=0):
    if depth > 10:
        return []

    obj = coerce_json_like(obj)

    if isinstance(obj, dict):
        if looks_like_comment_dict(obj):
            return [obj]

        floors = obj.get("floors")
        if isinstance(floors, list):
            for floor in floors:
                if not isinstance(floor, dict):
                    continue
                mid = normalize_text(floor.get("mId"))
                if "commentlist-list" in mid:
                    rows = extract_comment_infos_from_floor_data(floor.get("data"))
                    if rows:
                        return rows

        direct_keys = [
            "commentList",
            "commentInfoList",
            "foldCommentList",
            "directCommentList",
            "resultList",
            "list",
            "data",
            "items",
        ]
        for key in direct_keys:
            rows = extract_direct_comment_list(obj.get(key))
            if rows:
                return rows

        comment_info = obj.get("commentInfo")
        if isinstance(comment_info, dict):
            return [comment_info]

        for value in obj.values():
            rows = search_comment_infos(value, depth + 1)
            if rows:
                return rows

    elif isinstance(obj, list):
        rows = extract_direct_comment_list(obj)
        if rows:
            return rows

        for item in obj:
            rows = search_comment_infos(item, depth + 1)
            if rows:
                return rows

    return []


def extract_comment_infos(data):
    if data is None:
        return []
    data = coerce_json_like(data)
    return search_comment_infos(data)


def extract_page_info_data(obj, depth=0):
    if depth > 8:
        return {}

    obj = coerce_json_like(obj)
    if isinstance(obj, dict):
        page_info = obj.get("pageInfo")
        if isinstance(page_info, dict):
            data = page_info.get("data")
            if isinstance(data, dict):
                return data

        for value in obj.values():
            found = extract_page_info_data(value, depth + 1)
            if found:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = extract_page_info_data(item, depth + 1)
            if found:
                return found

    return {}


def extract_comment_page_index(data, comment_infos=None):
    comment_infos = comment_infos or extract_comment_infos(data)
    for info in comment_infos[:5]:
        if not isinstance(info, dict):
            continue
        page_index = safe_int(
            first_non_empty(
                info.get("pageIndex"),
                info.get("pageNum"),
                info.get("page"),
            ),
            0,
        )
        if page_index > 0:
            return page_index
    return 0


def extract_page_max(data):
    page_info = extract_page_info_data(data)
    return safe_int(page_info.get("maxPage"), 0)


def extract_has_next_page(data):
    page_info = extract_page_info_data(data)
    if "hasNextPage" not in page_info:
        return None
    return safe_bool(page_info.get("hasNextPage"), False)


def get_comment_first_time(rows):
    if not rows:
        return ""
    return normalize_text(rows[0].get("creationTime"))


def is_not_earlier_time(left, right):
    left = normalize_text(left)
    right = normalize_text(right)
    if not left or not right:
        return True
    return left >= right


def validate_latest_rows(score_name, rows, before_click_time=""):
    if not rows:
        return True

    first_time = get_comment_first_time(rows)
    last_time = normalize_text(rows[min(len(rows), 10) - 1].get("creationTime"))
    descending_ok = is_descending_creation_times(rows)
    not_earlier_ok = is_not_earlier_time(first_time, before_click_time)

    if descending_ok and not_earlier_ok:
        if before_click_time:
            print("✅ %s 首批时间已确认降序，且不早于点击前：%s -> %s（点击前首条：%s）" % (
                score_name,
                first_time,
                last_time,
                before_click_time,
            ))
        else:
            print("✅ %s 首批时间已确认降序：%s -> %s" % (score_name, first_time, last_time))
        return True

    if not descending_ok:
        print("⚠️ %s 首批时间未呈降序：%s -> %s" % (score_name, first_time, last_time))
    if before_click_time and not not_earlier_ok:
        print("⚠️ %s 首批首条时间早于点击前首条：点击前=%s，点击后=%s" % (
            score_name,
            before_click_time,
            first_time,
        ))
    return False


def detect_plus(comment):
    if comment.get("isPlus") in (1, True, "1", "true", "True"):
        return "是"
    if comment.get("plusAvailable") == 1:
        return "是"

    plus_text = normalize_text(
        first_non_empty(
            comment.get("plusTagText"),
            comment.get("plusTag"),
            comment.get("plusUserTag"),
        )
    )
    if "PLUS" in plus_text.upper():
        return "是"
    return "否"


def extract_after_comment(comment):
    after = first_non_empty(
        comment.get("afterComment"),
        comment.get("afterCommentInfo"),
        comment.get("afterUserComment"),
        comment.get("appendComment"),
    )

    if isinstance(after, list):
        if after and isinstance(after[0], dict):
            after = after[0]
        else:
            after = {}

    if not isinstance(after, dict):
        return "", ""

    after_text = normalize_text(
        first_non_empty(
            after.get("commentData"),
            after.get("content"),
            after.get("commentContent"),
            after.get("afterCommentContent"),
            after.get("text"),
        )
    )
    after_time = normalize_text(
        first_non_empty(
            after.get("commentDate"),
            after.get("created"),
            after.get("creationTime"),
        )
    )
    return after_text, after_time


def build_rows(comment_infos, score_value):
    rows = []
    for comment in comment_infos:
        if not isinstance(comment, dict):
            continue

        main_content = normalize_text(
            first_non_empty(
                comment.get("commentData"),
                comment.get("commentContent"),
                comment.get("content"),
                comment.get("tagCommentContent"),
            )
        )
        if not main_content:
            main_content = "无内容"

        after_text, after_time = extract_after_comment(comment)
        if after_text:
            if after_time:
                main_content = "%s | [追评 %s]: %s" % (main_content, after_time, after_text)
            else:
                main_content = "%s | [追评]: %s" % (main_content, after_text)

        row = {
            "commentId": normalize_text(first_non_empty(comment.get("commentId"), comment.get("id"))),
            "creationTime": normalize_text(
                first_non_empty(
                    comment.get("commentDate"),
                    comment.get("creationTime"),
                    comment.get("commentTime"),
                )
            ),
            "nickname": normalize_text(
                first_non_empty(
                    comment.get("userNickName"),
                    comment.get("nickname"),
                    comment.get("userName"),
                )
            ),
            "referenceName": normalize_text(
                first_non_empty(
                    comment.get("referenceName"),
                    comment.get("wareAttribute"),
                    comment.get("skuInfo"),
                )
            ),
            "userLevelId": normalize_text(
                first_non_empty(
                    comment.get("userLevelId"),
                    comment.get("userLevelName"),
                )
            ),
            "isPlus": detect_plus(comment),
            "score": score_value,
            "content": main_content,
        }
        rows.append(row)
    return rows


def make_row_key(row):
    comment_id = normalize_text(row.get("commentId"))
    if comment_id:
        return "id:%s" % comment_id

    raw = "%s|%s|%s" % (
        normalize_text(row.get("creationTime")),
        normalize_text(row.get("nickname")),
        normalize_text(row.get("content"))[:120],
    )
    return "hash:%s" % hashlib.md5(raw.encode("utf-8")).hexdigest()


def batch_signature(rows):
    if not rows:
        return ""

    parts = []
    for row in rows[:12]:
        parts.append(make_row_key(row))
    payload = "%s|len=%s" % ("|".join(parts), len(rows))
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def ensure_output_files():
    os.makedirs(DEBUG_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()


def profile_dir_has_data(profile_dir):
    try:
        return any(os.scandir(profile_dir))
    except Exception:
        return False


def load_existing_ids():
    seen = set()
    if not os.path.exists(CSV_FILE):
        return seen

    with open(CSV_FILE, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            seen.add(make_row_key(row))
    return seen


def append_rows(rows):
    if not rows:
        return

    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerows(rows)


def default_progress():
    return {
        key: {
            "rounds_done": 0,
            "completed": False,
            "last_mode": "",
            "fold_offset": 0,
            "fold_type": "",
            "last_item_count": 0,
            "last_url": "",
            "page_index": 0,
            "max_page": 0,
            "has_next_page": True,
            "last_first_time": "",
        }
        for key in SCORE_MAP.keys()
    }


def reset_progress_state(state):
    state["rounds_done"] = 0
    state["completed"] = False
    state["last_mode"] = ""
    state["fold_offset"] = 0
    state["fold_type"] = ""
    state["last_item_count"] = 0
    state["last_url"] = ""
    state["page_index"] = 0
    state["max_page"] = 0
    state["has_next_page"] = True
    state["last_first_time"] = ""


def sanitize_progress(progress):
    for score_name in SCORE_MAP.keys():
        state = progress.get(score_name) or {}
        last_url = normalize_text(state.get("last_url"))
        function_id = extract_function_id(last_url)
        actual_type = ""

        if function_id == "getFoldCommentList":
            actual_type = extract_fold_type(last_url)
            if actual_type:
                state["fold_type"] = actual_type
        else:
            actual_type = normalize_text(state.get("fold_type"))

        expected_type = expected_fold_type(score_name)
        if expected_type and actual_type and actual_type != expected_type:
            print("提示：%s 发现串类折叠断点(type=%s，期望=%s)，已清空该分类错误进度。" % (
                score_name,
                actual_type,
                expected_type,
            ))
            reset_progress_state(state)

    return progress


def load_progress():
    progress = default_progress()
    if not os.path.exists(PROGRESS_FILE):
        return progress

    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return progress

    if not isinstance(data, dict):
        return progress

    for key in SCORE_MAP.keys():
        value = data.get(key)
        if isinstance(value, dict):
            state = progress[key]
            state["rounds_done"] = int(value.get("rounds_done", 0) or 0)
            state["completed"] = bool(value.get("completed", False))
            state["last_mode"] = normalize_text(value.get("last_mode"))
            state["fold_offset"] = int(value.get("fold_offset", 0) or 0)
            state["fold_type"] = normalize_text(value.get("fold_type"))
            state["last_item_count"] = int(value.get("last_item_count", 0) or 0)
            state["last_url"] = normalize_text(value.get("last_url"))
            state["page_index"] = int(value.get("page_index", 0) or 0)
            state["max_page"] = int(value.get("max_page", 0) or 0)
            state["has_next_page"] = bool(value.get("has_next_page", True))
            state["last_first_time"] = normalize_text(value.get("last_first_time"))
        elif isinstance(value, list):
            progress[key]["rounds_done"] = len(value)

    return sanitize_progress(progress)


def save_progress(progress):
    sanitized = {}
    for key in SCORE_MAP.keys():
        state = progress.get(key) or {}
        sanitized[key] = {
            "rounds_done": int(state.get("rounds_done", 0) or 0),
            "completed": bool(state.get("completed", False)),
            "last_mode": normalize_text(state.get("last_mode")),
            "fold_offset": int(state.get("fold_offset", 0) or 0),
            "fold_type": normalize_text(state.get("fold_type")),
            "last_item_count": int(state.get("last_item_count", 0) or 0),
            "last_url": normalize_text(state.get("last_url")),
            "page_index": int(state.get("page_index", 0) or 0),
            "max_page": int(state.get("max_page", 0) or 0),
            "has_next_page": bool(state.get("has_next_page", True)),
            "last_first_time": normalize_text(state.get("last_first_time")),
        }

    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(sanitized, f, ensure_ascii=False, indent=2)


def restore_progress_from_endpoint_log(progress):
    if not os.path.exists(ENDPOINT_LOG):
        return progress

    latest = {}
    try:
        with open(ENDPOINT_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                label = normalize_text(record.get("label"))
                score_name, round_index = parse_label_round(label)
                if score_name not in SCORE_MAP or round_index <= 0:
                    continue

                url = normalize_text(record.get("url"))
                if not is_valid_packet_url_for_score(score_name, url):
                    continue

                prev = latest.get(score_name)
                if not prev or round_index >= prev["round_index"]:
                    latest[score_name] = {
                        "round_index": round_index,
                        "url": url,
                        "item_count": int(record.get("item_count", 0) or 0),
                    }
    except Exception:
        return progress

    for score_name, info in latest.items():
        state = progress[score_name]
        state["rounds_done"] = max(state["rounds_done"], info["round_index"])
        state["last_url"] = info["url"]
        state["last_item_count"] = info["item_count"]

        function_id = extract_function_id(info["url"])
        if function_id == "getFoldCommentList":
            state["last_mode"] = "fold"
            state["fold_offset"] = max(state.get("fold_offset", 0), extract_fold_offset(info["url"]))
            state["fold_type"] = extract_fold_type(info["url"])
            if 0 < info["item_count"] < 10:
                state["completed"] = True
        elif info["url"]:
            state["last_mode"] = state["last_mode"] or "scroll"

    return sanitize_progress(progress)


def restore_progress_from_debug_dir(progress):
    if not os.path.isdir(DEBUG_DIR):
        return progress

    latest = {}
    for name in os.listdir(DEBUG_DIR):
        if not name.lower().endswith(".json"):
            continue

        stem = os.path.splitext(name)[0]
        match = re.match(r"^\d{8}_\d{6}_(.+)$", stem)
        if not match:
            continue

        label = match.group(1)
        score_name, round_index = parse_label_round(label)
        if score_name not in SCORE_MAP or round_index <= 0:
            continue

        path = os.path.join(DEBUG_DIR, name)
        prev = latest.get(score_name)
        if not prev or round_index > prev["round_index"] or (
            round_index == prev["round_index"] and os.path.getmtime(path) >= prev["mtime"]
        ):
            latest[score_name] = {
                "path": path,
                "round_index": round_index,
                "mtime": os.path.getmtime(path),
            }

    for score_name, info in latest.items():
        try:
            with open(info["path"], "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        comment_infos = extract_comment_infos(data)
        if not comment_infos:
            continue

        page_index = extract_comment_page_index(data, comment_infos)
        max_page = extract_page_max(data)
        has_next_page = extract_has_next_page(data)
        state = progress[score_name]
        state["rounds_done"] = max(int(state.get("rounds_done", 0) or 0), info["round_index"])
        state["last_item_count"] = max(int(state.get("last_item_count", 0) or 0), len(comment_infos))
        state["last_first_time"] = normalize_text(
            first_non_empty(
                comment_infos[0].get("creationTime"),
                comment_infos[0].get("commentDate"),
                comment_infos[0].get("commentTime"),
            )
        )
        if page_index > 0:
            state["page_index"] = max(int(state.get("page_index", 0) or 0), page_index)
            state["last_mode"] = state.get("last_mode") or "scroll"
        if max_page > 0:
            state["max_page"] = max(int(state.get("max_page", 0) or 0), max_page)
        if has_next_page is not None:
            state["has_next_page"] = has_next_page

    return sanitize_progress(progress)


def update_progress_from_capture(state, score_name, round_index, url, row_count, completed=False, data=None, comment_infos=None):
    if not is_valid_packet_url_for_score(score_name, url):
        print("⚠️ %s 捕获到串类折叠包，已拒绝写入断点：%s" % (score_name, url))
        return False

    state["rounds_done"] = max(int(state.get("rounds_done", 0) or 0), int(round_index))
    state["last_url"] = normalize_text(url)
    state["last_item_count"] = int(row_count or 0)
    if completed:
        state["completed"] = True

    function_id = extract_function_id(url)
    if function_id == "getFoldCommentList":
        state["last_mode"] = "fold"
        state["fold_offset"] = max(int(state.get("fold_offset", 0) or 0), extract_fold_offset(url))
        state["fold_type"] = extract_fold_type(url)
    elif normalize_text(url):
        state["last_mode"] = "scroll"

    comment_infos = comment_infos or []
    page_index = extract_comment_page_index(data, comment_infos)
    if page_index > 0:
        state["page_index"] = max(int(state.get("page_index", 0) or 0), page_index)

    max_page = extract_page_max(data)
    if max_page > 0:
        state["max_page"] = max(int(state.get("max_page", 0) or 0), max_page)

    has_next_page = extract_has_next_page(data)
    if has_next_page is not None:
        state["has_next_page"] = has_next_page

    if comment_infos:
        state["last_first_time"] = normalize_text(
            first_non_empty(
                comment_infos[0].get("creationTime"),
                comment_infos[0].get("commentDate"),
                comment_infos[0].get("commentTime"),
            )
        )

    return True


def dump_debug_json(label, data):
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = "%s_%s.json" % (ts, sanitize_filename(label))
    path = os.path.join(DEBUG_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_endpoint(label, url, item_count):
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
        "url": url,
        "item_count": item_count,
    }
    with open(ENDPOINT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_page():
    co = ChromiumOptions()
    browser_path = find_browser_path()
    if browser_path:
        co.set_browser_path(browser_path)
        print("🌐 使用浏览器: %s" % browser_path)
    else:
        print("🌐 未显式指定浏览器路径，交给 DrissionPage 自动处理。")

    co.set_user_data_path(PROFILE_DIR)
    co.set_local_port(get_free_port())
    return ChromiumPage(co)


def detect_risk_state(page):
    for text in RISK_TEXTS:
        try:
            ele = page.ele('xpath://*[contains(text(), "%s")]' % text, timeout=0.2)
            if ele:
                return text
        except Exception:
            pass
    return ""


def handle_risk_state(page, reason):
    print("⚠️ 检测到风险提示：%s" % reason)
    seconds = random.uniform(RISK_COOLDOWN[0], RISK_COOLDOWN[1])
    print("⏸️ 为降低继续触发异常的概率，进入冷却 %.1f 分钟后结束本次任务。" % (seconds / 60.0))
    time.sleep(seconds)
    raise RuntimeError("触发风险提示，脚本已停止。")


def wait_for_login_ready(page, timeout_seconds=LOGIN_WAIT_SECONDS):
    deadline = time.time() + timeout_seconds
    last_print = 0

    while time.time() < deadline:
        ensure_product_page_not_blocked(page, "登录检测阶段")
        reason = detect_risk_state(page)
        if reason:
            page = wait_for_risk_recovery(page, reason, stage_label="登录检测阶段")

        login_prompt = None
        try:
            login_prompt = page.ele('xpath://a[contains(text(), "请登录")]', timeout=0.3)
        except Exception:
            login_prompt = None

        if not login_prompt:
            print("✅ 登录状态已就绪，继续执行。")
            return True

        now = time.time()
        if now - last_print > 10:
            print("如果页面提示登录，请在打开的浏览器里完成登录，程序会自动检测。")
            last_print = now
        time.sleep(2)

    return False


def get_product_url():
    return "https://item.jd.com/%s.html#comment" % PRODUCT_ID


def is_target_product_url(url):
    return ("item.jd.com/%s.html" % PRODUCT_ID) in normalize_text(url).lower()


def get_page_url_safe(page):
    try:
        return normalize_text(page.url)
    except Exception:
        return ""


def is_product_page_blocked_url(url):
    text = normalize_text(url).lower()
    if not text:
        return False
    if "from=pc_item" in text and "reason=403" in text:
        return True
    if "jd.com/?" in text and "reason=403" in text:
        return True
    return False


def ensure_product_page_not_blocked(page, stage_label=""):
    url = get_page_url_safe(page)
    if is_product_page_blocked_url(url):
        prefix = "%s：" % stage_label if stage_label else ""
        raise RuntimeError("%s京东将商品页重定向到了 403 页面，不是脚本改了商品。当前地址：%s" % (prefix, url))
    return url


def review_overlay_exists(page):
    try:
        return bool(page.run_js('return !!document.querySelector("#rateList");'))
    except Exception:
        return False


def get_visible_comment_times(page, limit=5):
    js = r"""
const root = document.querySelector('#rateList');
if (!root) return [];
const text = (root.innerText || '');
const matches = Array.from(text.matchAll(/\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}/g)).map(m => (m[0] || '').trim());
return Array.from(new Set(matches));
"""
    try:
        times = page.run_js(js)
    except Exception:
        times = []

    if isinstance(times, str):
        times = [times] if times else []
    if not isinstance(times, list):
        return []
    return [normalize_text(item) for item in times[:max(1, int(limit or 1))] if normalize_text(item)]


def get_first_visible_comment_time(page):
    times = get_visible_comment_times(page, limit=1)
    return times[0] if times else ""


def rebuild_page(page):
    try:
        if page:
            page.quit()
    except Exception:
        pass

    new_page = build_page()
    new_page.listen.start()
    print("🔄 已重建浏览器页面连接。")
    return new_page


def open_product_page(page, stage_label, retries=3):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            page.get(get_product_url(), timeout=60)
            ensure_product_page_not_blocked(page, stage_label)
            return page
        except Exception as e:
            last_error = e
            message = normalize_text(e)
            print("⚠️ %s 打开商品页失败，第 %s/%s 次：%s" % (stage_label, attempt, retries, message or type(e).__name__))

            if "连接已断开" in message or "PageDisconnectedError" in type(e).__name__:
                page = rebuild_page(page)

            if attempt < retries:
                conservative_sleep(4, 8, "%s 后重试商品页" % stage_label)
                continue

    raise last_error


def find_first(page, selectors, timeout_each=1):
    for selector in selectors:
        try:
            ele = page.ele(selector, timeout=timeout_each)
            if ele:
                return ele
        except Exception:
            continue
    return None


def safe_click(page, selectors, label, timeout_each=1):
    ele = find_first(page, selectors, timeout_each=timeout_each)
    if not ele:
        return False

    try:
        page.run_js('arguments[0].scrollIntoView({block:"center"});', ele)
    except Exception:
        pass

    try:
        ele.click(by_js=True)
        print("🖱️ 已点击：%s" % label)
        return True
    except Exception:
        try:
            page.run_js("arguments[0].click();", ele)
            print("🖱️ 已点击：%s" % label)
            return True
        except Exception:
            return False


def js_click_in_rate_list(page, target_text, mode, label):
    js = r"""
const target = (arguments[0] || '').replace(/\s+/g, '');
const mode = arguments[1] || '';
const root = document.querySelector('#rateList');
if (!root) return '';

const clean = s => (s || '').replace(/\s+/g, '');
const visible = el => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const buttonLike = el => {
  const tag = (el.tagName || '').toLowerCase();
  const cls = (el.className || '').toString();
  return tag === 'button' || tag === 'a' || tag === 'span' || tag === 'div' || /tag|sort|item|btn|tab|label/i.test(cls);
};

let candidates = Array.from(root.querySelectorAll('*')).filter(el => visible(el));

if (mode === 'score') {
  let tagged = candidates.filter(el => {
    const cls = (el.className || '').toString();
    const text = clean(el.innerText);
    return /tag/i.test(cls) && text.includes(target);
  });
  if (tagged.length) {
    candidates = tagged;
  } else {
    candidates = candidates.filter(el => {
      const text = clean(el.innerText);
      return text.includes(target) && text.length <= 16;
    });
  }
} else if (mode === 'latest') {
  candidates = candidates.filter(el => {
    const text = clean(el.innerText);
    return text === target || text.includes(target);
  });
} else {
  candidates = candidates.filter(el => clean(el.innerText).includes(target));
}

if (!candidates.length) return '';

candidates.sort((a, b) => {
  const al = clean(a.innerText).length;
  const bl = clean(b.innerText).length;
  if (al !== bl) return al - bl;
  return a.getBoundingClientRect().top - b.getBoundingClientRect().top;
});

for (const el of candidates) {
  let node = el;
  for (let i = 0; i < 4 && node; i += 1, node = node.parentElement) {
    if (!visible(node) || !buttonLike(node)) continue;
    try {
      node.scrollIntoView({block: 'center'});
      node.click();
      return clean(node.innerText) || clean(el.innerText) || target;
    } catch (e) {}
  }
  try {
    el.scrollIntoView({block: 'center'});
    el.click();
    return clean(el.innerText) || target;
  } catch (e) {}
}
return '';
"""
    try:
        result = page.run_js(js, target_text, mode)
    except Exception:
        result = ""

    result = normalize_text(result)
    if result:
        print("🖱️ 已点击：%s" % label)
        return True
    return False


def enter_review_overlay(page):
    try:
        page.run_js(
            'document.querySelector("#comment-root") && '
            'document.querySelector("#comment-root").scrollIntoView({block:"center"});'
        )
    except Exception:
        pass

    conservative_sleep(4, 8, "等待评论区域渲染")

    ok = safe_click(
        page,
        [
            'xpath://div[@id="comment-root"]//div[contains(@class,"all-btn")]',
            'xpath://div[@id="comment-root"]//*[contains(text(),"全部评价")]',
        ],
        "评论入口",
        timeout_each=8,
    )
    if not ok:
        return False

    for _ in range(20):
        try:
            exists = page.run_js('return !!document.querySelector("#rateList");')
        except Exception:
            exists = False
        if exists:
            return True
        time.sleep(1)
    return False


def click_score_tag(page, score_name):
    if js_click_in_rate_list(page, score_name, "score", score_name):
        return True

    return safe_click(
        page,
        [
            'xpath://div[@id="rateList"]//*[contains(@class,"_tag_") and contains(normalize-space(),"%s")]'
            % score_name,
            'xpath://div[@id="rateList"]//*[contains(normalize-space(),"%s")]' % score_name,
        ],
        score_name,
        timeout_each=4,
    )


def click_latest_sort(page):
    if js_click_in_rate_list(page, "最新", "latest", "最新排序"):
        return True

    return safe_click(
        page,
        [
            'xpath://div[@id="rateList"]//*[contains(normalize-space(),"最新")]',
        ],
        "最新排序",
        timeout_each=4,
    )


def get_latest_sort_indicator_text(page):
    js = r"""
const root = document.querySelector('#rateList');
if (!root) return '';
const clean = s => (s || '').replace(/\s+/g, '');
const visible = el => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const scored = [];
for (const el of root.querySelectorAll('*')) {
  if (!visible(el)) continue;
  const text = clean(el.innerText);
  if (!text || text.indexOf('最新') < 0) continue;
  let score = 0;
  if (text === '最新') score += 4;
  if (text.indexOf('最新') >= 0) score += 1;
  const cls = clean(el.className || '');
  if (/(active|current|selected|cur|on|checked)/i.test(cls)) score += 4;
  const ariaSelected = el.getAttribute('aria-selected') || '';
  const ariaPressed = el.getAttribute('aria-pressed') || '';
  const dataSelected = el.getAttribute('data-selected') || el.getAttribute('data-active') || '';
  if (ariaSelected === 'true' || ariaPressed === 'true') score += 4;
  if (dataSelected === 'true' || dataSelected === '1') score += 2;
  scored.push([score, text]);
}
if (!scored.length) return '';
scored.sort((a, b) => b[0] - a[0]);
return scored[0][0] >= 4 ? scored[0][1] : '';
"""
    try:
        text = page.run_js(js)
    except Exception:
        text = ""

    text = normalize_text(text)
    if "最新" in text:
        return text
    return ""


def wait_for_latest_sort_selected(page, timeout_seconds=8):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        text = get_latest_sort_indicator_text(page)
        if text:
            return text
        time.sleep(0.5)
    return ""


def prepare_score_context(page, score_name):
    before_sort_first_time = ""

    if not click_score_tag(page, score_name):
        print("⚠️ 未找到分类按钮：%s" % score_name)
        return False, before_sort_first_time
    sleep_pair(WAIT_AFTER_TAG, FAST_WAIT_AFTER_TAG, False, "%s 分类切换稳定" % score_name)
    page.listen.clear()

    before_sort_first_time = get_first_visible_comment_time(page)
    if click_latest_sort(page):
        sleep_pair(WAIT_AFTER_SORT, FAST_WAIT_AFTER_SORT, False, "排序切换稳定")
        page.listen.clear()
        latest_sort_text = wait_for_latest_sort_selected(page)
        if latest_sort_text:
            print("✅ 已确认“最新”排序激活：%s" % latest_sort_text)
        else:
            print("⚠️ 未能确认“最新”排序激活，将在首批结果中继续校验。")
    else:
        print("⚠️ 未能自动命中“最新”按钮，继续按当前排序抓取。")
        page.listen.clear()

    return True, before_sort_first_time


def click_load_more_if_present(page):
    return safe_click(
        page,
        [
            'xpath://div[@id="rateList"]//*[contains(normalize-space(),"加载更多")]',
        ],
        "加载更多",
        timeout_each=1,
    )


def get_low_value_hint_text(page):
    js = r"""
const root = document.querySelector('#rateList');
if (!root) return '';
const clean = s => (s || '').replace(/\s+/g, '');
const visible = el => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const nodes = Array.from(root.querySelectorAll('*')).filter(el => visible(el));
const hits = nodes.filter(el => {
  const text = clean(el.innerText);
  if (!text || text.length > 20) return false;
  return text.includes('已为您过滤了参考价值不大的评价')
      || text.includes('已为您过滤了参考价值不大的评论')
      || text === '参考价值不大';
});
if (!hits.length) return '';
hits.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
return clean(hits[0].innerText);
"""
    try:
        text = page.run_js(js)
    except Exception:
        text = ""

    text = normalize_text(text)
    if is_low_value_hint_text(text):
        return text
    return ""


def detect_no_more_state(page):
    js = r"""
const root = document.querySelector('#rateList');
if (!root) return '';
const clean = s => (s || '').replace(/\s+/g, '');
const visible = el => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};
const nodes = Array.from(root.querySelectorAll('*')).filter(el => visible(el));
const hits = nodes.filter(el => {
  const text = clean(el.innerText);
  return !!text && text.length <= 10 && (text.includes('没有更多了') || text.includes('没有更多'));
});
if (!hits.length) return '';
hits.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
return clean(hits[0].innerText);
"""
    try:
        text = page.run_js(js)
    except Exception:
        text = ""

    return is_no_more_text(text)


def is_descending_creation_times(rows, limit=10):
    times = []
    for row in rows[:limit]:
        text = normalize_text(row.get("creationTime"))
        if text:
            times.append(text)
    if len(times) < 2:
        return True

    for idx in range(1, len(times)):
        if times[idx] > times[idx - 1]:
            return False
    return True


def try_expand_low_value_reviews(page, fast_mode=False):
    js = r"""
const root = document.querySelector('#rateList');
if (!root) return '';

const clean = s => (s || '').replace(/\s+/g, '');
const visible = el => {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
};

const nodes = Array.from(root.querySelectorAll('*')).filter(el => visible(el));
let candidates = nodes.filter(el => {
  const text = clean(el.innerText);
  if (!text || text.length > 20) return false;
  return text.includes('已为您过滤了参考价值不大的评价')
      || text.includes('已为您过滤了参考价值不大的评论');
});

if (!candidates.length) {
  candidates = nodes.filter(el => {
    const text = clean(el.innerText);
    return !!text && text.length <= 20 && text.includes('参考价值不大');
  });
}

if (!candidates.length) return '';

candidates.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);

for (const el of candidates) {
  const text = clean(el.innerText);
  if (!text) continue;
  try {
    el.scrollIntoView({block: 'center'});
    ['mousedown', 'mouseup', 'click'].forEach(type => {
      el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
    });
    return text;
  } catch (e) {}

  let node = el.parentElement;
  for (let i = 0; i < 2 && node; i += 1, node = node.parentElement) {
    const nodeText = clean(node.innerText);
    if (!visible(node) || !nodeText || nodeText.length > 20) continue;
    try {
      node.scrollIntoView({block: 'center'});
      ['mousedown', 'mouseup', 'click'].forEach(type => {
        node.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
      });
      return nodeText;
    } catch (e) {}
  }
}
return '';
"""
    try:
        clicked_text = page.run_js(js)
    except Exception:
        clicked_text = ""

    clicked_text = normalize_text(clicked_text)
    if not is_low_value_hint_text(clicked_text):
        return False

    print("🖱️ 已尝试展开低参考价值评价：%s" % clicked_text)
    sleep_pair(WAIT_AFTER_EXPAND, FAST_WAIT_AFTER_EXPAND, fast_mode, "等待低价值入口响应")
    if get_low_value_hint_text(page):
        print("⚠️ 低价值评价入口仍然可见，本次点击未确认生效。")
        return False

    sleep_pair(WAIT_AFTER_EXPAND, FAST_WAIT_AFTER_EXPAND, fast_mode, "等待隐藏评价展开")
    return True


def find_scroll_container(page):
    container = find_first(
        page,
        [
            'xpath://div[@id="rateList"]//*[contains(@class,"rateListContainer")]',
            'xpath://div[@id="rateList"]//*[contains(@class,"_rateListContainer_")]',
        ],
        timeout_each=1,
    )
    if container:
        return container

    js = r"""
const root = document.querySelector('#rateList');
if (!root) return null;
let best = null;
let bestGap = -1;
for (const el of root.querySelectorAll('*')) {
  const sh = el.scrollHeight || 0;
  const ch = el.clientHeight || 0;
  if (sh > ch + 80) {
    const gap = sh - ch;
    if (gap > bestGap) {
      bestGap = gap;
      best = el;
    }
  }
}
return best;
"""
    try:
        return page.run_js(js)
    except Exception:
        return None


def get_scroll_metrics(page, container):
    try:
        metrics = page.run_js(
            "return {"
            "top: arguments[0].scrollTop || 0,"
            "height: arguments[0].scrollHeight || 0,"
            "client: arguments[0].clientHeight || 0"
            "};",
            container,
        )
    except Exception:
        metrics = None

    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = None

    if not isinstance(metrics, dict):
        return {"top": 0, "height": 0, "client": 0}

    return {
        "top": int(metrics.get("top", 0) or 0),
        "height": int(metrics.get("height", 0) or 0),
        "client": int(metrics.get("client", 0) or 0),
    }


def set_scroll_top(page, container, target):
    try:
        page.run_js(
            "const el = arguments[0];"
            "const target = Math.max(0, Number(arguments[1]) || 0);"
            "el.scrollTop = target;",
            container,
            int(target),
        )
        return True
    except Exception:
        return False


def should_stop_category_round(score_name, row_count, source_url, no_more_visible):
    source_text = normalize_text(source_url).lower()
    if no_more_visible:
        return True
    if score_name == "差评":
        return False
    if (
        "getfoldcommentlist" in source_text
        and is_valid_packet_url_for_score(score_name, source_url)
        and 0 < int(row_count or 0) < 10
    ):
        return True
    return False


def trigger_overlay_load(page, fast_mode=False):
    if not review_overlay_exists(page):
        print("⚠️ 评论弹层不存在，可能已回到首页或验证页。")
        return {"low_value_expanded": False, "no_more_visible": False, "overlay_missing": True}

    click_load_more_if_present(page)

    container = find_scroll_container(page)
    if not container:
        if not review_overlay_exists(page):
            print("⚠️ 评论弹层已丢失，停止当前轮触发。")
            return {"low_value_expanded": False, "no_more_visible": False, "overlay_missing": True}
        print("   未识别到独立评论容器，已尝试滚动整个页面。")
        try:
            page.run_js("window.scrollBy(0, 1200);")
            sleep_pair(WAIT_SCROLL_STEP_1, FAST_WAIT_SCROLL_STEP_1, fast_mode, "等待页面滚动后稳定")
        except Exception:
            pass
        return {"low_value_expanded": False, "no_more_visible": detect_no_more_state(page), "overlay_missing": False}

    try:
        page.run_js("arguments[0].click();", container)
    except Exception:
        pass

    metrics = get_scroll_metrics(page, container)
    print("   评论容器状态: %s" % json.dumps(metrics, ensure_ascii=False))

    max_top = max(0, metrics["height"] - metrics["client"])
    if max_top <= 0:
        return {"low_value_expanded": False, "no_more_visible": detect_no_more_state(page), "overlay_missing": False}

    current_top = metrics["top"]
    near_bottom = max(0, max_top - max(480, int(metrics["client"] * 1.4)))
    if current_top < near_bottom:
        first_target = near_bottom
    else:
        first_target = max(0, current_top - 220)

    second_target = max_top
    bounce_target = max(0, max_top - max(180, int(metrics["client"] * 0.4)))

    set_scroll_top(page, container, first_target)
    sleep_pair(WAIT_SCROLL_STEP_1, FAST_WAIT_SCROLL_STEP_1, fast_mode, "等待瀑布流触发")

    set_scroll_top(page, container, second_target)
    sleep_pair(WAIT_SCROLL_STEP_2, FAST_WAIT_SCROLL_STEP_2, fast_mode, "等待触底稳定")

    if detect_no_more_state(page):
        return {"low_value_expanded": False, "no_more_visible": True, "overlay_missing": False}

    low_value_expanded = try_expand_low_value_reviews(page, fast_mode=fast_mode)
    if low_value_expanded:
        return {"low_value_expanded": True, "no_more_visible": detect_no_more_state(page), "overlay_missing": False}

    set_scroll_top(page, container, bounce_target)
    sleep_pair(WAIT_SCROLL_STEP_2, FAST_WAIT_SCROLL_STEP_2, fast_mode, "等待回弹稳定")

    set_scroll_top(page, container, second_target)
    sleep_pair(WAIT_SCROLL_STEP_3, FAST_WAIT_SCROLL_STEP_3, fast_mode, "等待末段加载")

    metrics_after = get_scroll_metrics(page, container)
    if metrics_after["height"] > metrics["height"] + 80:
        max_top_after = max(0, metrics_after["height"] - metrics_after["client"])
        set_scroll_top(page, container, max_top_after)
        sleep_pair((5, 9), (1.0, 2.0), fast_mode, "新内容已追加，继续压到新底部")

    return {"low_value_expanded": False, "no_more_visible": detect_no_more_state(page), "overlay_missing": False}


def safe_wait_packet(page, timeout_seconds):
    try:
        return page.listen.wait(timeout=timeout_seconds)
    except Exception:
        return None


def packet_priority(url):
    text = normalize_text(url).lower()
    if "getfoldcommentlist" in text:
        return 3
    if "client.action" in text:
        return 1
    return 0


def capture_comment_packet(page, score_name, label, timeout_seconds=25, quiet_gap=2.5):
    deadline = time.time() + timeout_seconds
    last_valid = None
    last_valid_time = 0
    last_priority = -1
    printed_candidates = set()

    while time.time() < deadline:
        packet = safe_wait_packet(page, 1.2 if timeout_seconds <= 10 else 1.5)
        if packet:
            url = normalize_text(getattr(packet, "url", ""))
            if url and "client.action" in url.lower() and url not in printed_candidates:
                print("   [候选] %s" % url)
                printed_candidates.add(url)

            try:
                body = packet.response.body
            except Exception:
                body = None

            data = parse_json_from_body(body)
            try:
                comment_infos = extract_comment_infos(data)
            except Exception as e:
                print("⚠️ 评论包结构异常，已跳过：%s" % e)
                comment_infos = []

            if comment_infos:
                if not is_valid_packet_url_for_score(score_name, url):
                    print("⚠️ %s 忽略串类折叠包(type=%s，期望=%s)：%s" % (
                        score_name,
                        extract_fold_type(url),
                        expected_fold_type(score_name),
                        url,
                    ))
                    continue

                priority = packet_priority(url)
                if last_valid is None or priority >= last_priority:
                    last_valid = (data, comment_infos, url)
                    last_priority = priority
                last_valid_time = time.time()

        if last_valid and time.time() - last_valid_time >= quiet_gap:
            break

    if last_valid:
        dump_debug_json(label, last_valid[0])
        log_endpoint(label, last_valid[2], len(last_valid[1]))
        print("✅ %s 捕获评论包：%s" % (label, last_valid[2]))
        return last_valid

    return None, [], ""


def restore_score_context(page, score_name, state=None, stage_label=""):
    current_url = get_page_url_safe(page)
    if not is_target_product_url(current_url) or not review_overlay_exists(page):
        page = open_product_page(page, stage_label or "恢复商品页")
        conservative_sleep(WAIT_PAGE_OPEN[0], WAIT_PAGE_OPEN[1], "%s 后等待商品页稳定" % (stage_label or "恢复商品页"))
        ensure_product_page_not_blocked(page, stage_label or "恢复商品页")
        if not wait_for_login_ready(page):
            raise RuntimeError("恢复评论上下文时等待登录超时。")
        if not enter_review_overlay(page):
            raise RuntimeError("恢复评论上下文时未能重新进入评论弹层。")
        conservative_sleep(WAIT_AFTER_OVERLAY[0], WAIT_AFTER_OVERLAY[1], "%s 后等待评价弹层稳定" % (stage_label or "恢复评论上下文"))

    ok, _before_sort_first_time = prepare_score_context(page, score_name)
    if not ok:
        raise RuntimeError("恢复评论上下文时未能重新切到 %s。" % score_name)

    if not state or state.get("completed"):
        return page

    if state.get("last_mode") == "fold" and int(state.get("fold_offset", 0) or 0) > 0:
        if not bootstrap_fold_resume(page, score_name, state):
            raise RuntimeError("恢复 %s 时未能追平折叠评论断点。" % score_name)
    elif int(state.get("page_index", 0) or 0) > 0:
        if not bootstrap_scroll_resume(page, score_name, state):
            raise RuntimeError("恢复 %s 时未能追平 pageIndex 断点。" % score_name)

    page.listen.clear()
    return page


def wait_for_risk_recovery(page, reason, score_name="", state=None, stage_label=""):
    print("⚠️ 检测到风险提示：%s" % reason)
    print("⏸️ 请在已打开的浏览器里完成人工验证。验证完成后，脚本会自动恢复到当前商品评论并继续。")
    deadline = time.time() + RISK_RECOVERY_WAIT_SECONDS
    last_print = 0

    while time.time() < deadline:
        current_reason = detect_risk_state(page)
        if current_reason:
            now = time.time()
            if now - last_print >= 10:
                print("⏳ 仍在等待人工验证完成：%s" % current_reason)
                last_print = now
            time.sleep(2)
            continue

        try:
            if score_name:
                page = restore_score_context(page, score_name, state=state, stage_label=stage_label or ("%s 风险恢复" % score_name))
            else:
                page = open_product_page(page, stage_label or "风险恢复后重开商品页")
                conservative_sleep(WAIT_PAGE_OPEN[0], WAIT_PAGE_OPEN[1], "风险恢复后等待商品页稳定")
                ensure_product_page_not_blocked(page, stage_label or "风险恢复后重开商品页")
            print("✅ 风险验证已恢复，继续执行。")
            return page
        except Exception as e:
            now = time.time()
            if now - last_print >= 10:
                print("⚠️ 验证已结束，但恢复评论上下文仍未成功：%s" % normalize_text(e))
                last_print = now
            time.sleep(3)

    raise RuntimeError("等待人工验证恢复超时，脚本已停止。")


def risk_check(page, score_name="", state=None, stage_label=""):
    reason = detect_risk_state(page)
    if reason:
        return wait_for_risk_recovery(page, reason, score_name=score_name, state=state, stage_label=stage_label)
    return page


def fetch_resume_packet(page, score_name, step_index):
    if not review_overlay_exists(page):
        return None, [], "__OVERLAY_LOST__"
    if detect_no_more_state(page):
        return None, [], "__NO_MORE__"

    page.listen.clear()
    print("⬇️ %s 快速追平 pageIndex，第 %s 步..." % (score_name, step_index))
    trigger_state = trigger_overlay_load(page, fast_mode=True)
    if trigger_state.get("overlay_missing"):
        return None, [], "__OVERLAY_LOST__"
    if trigger_state.get("no_more_visible") and not trigger_state.get("low_value_expanded"):
        return None, [], "__NO_MORE__"

    sleep_pair(WAIT_AFTER_TRIGGER, FAST_WAIT_AFTER_TRIGGER, True, "等待评论接口返回")
    data, comment_infos, url = capture_comment_packet(
        page,
        score_name,
        "%s_resume_scroll_%s" % (score_name, step_index),
        timeout_seconds=8,
        quiet_gap=1.0,
    )
    if comment_infos:
        return data, comment_infos, url

    if not review_overlay_exists(page):
        return None, [], "__OVERLAY_LOST__"
    if detect_no_more_state(page):
        return None, [], "__NO_MORE__"
    return None, [], ""


def fast_forward_to_low_value_zone(page, score_name):
    if get_low_value_hint_text(page):
        return True

    print("⚡ %s 已有折叠评论断点，快速定位到低价值评价入口..." % score_name)
    for step in range(1, MAX_FAST_SEEK_STEPS + 1):
        state = trigger_overlay_load(page, fast_mode=True)
        if state.get("low_value_expanded"):
            return True
        if get_low_value_hint_text(page):
            return True
        if state.get("no_more_visible"):
            return False
    return False


def bootstrap_scroll_resume(page, score_name, state, before_sort_first_time=""):
    target_page_index = int(state.get("page_index", 0) or 0)
    if target_page_index <= 0:
        return False

    if state.get("completed"):
        return True

    print("⏩ %s 普通评论断点：目标 pageIndex=%s，开始快速追平。" % (score_name, target_page_index))
    current_page_index = 0
    stale_hits = 0
    validated = False

    for step_index in range(1, MAX_FAST_SCROLL_CATCHUP_STEPS + 1):
        data, infos, url = fetch_resume_packet(page, score_name, step_index)
        if url == "__OVERLAY_LOST__":
            return False
        if url == "__NO_MORE__":
            return current_page_index >= target_page_index or not state.get("has_next_page", True)
        if not infos:
            stale_hits += 1
            if stale_hits >= 2:
                return False
            continue

        rows = build_rows(infos, SCORE_MAP[score_name]["value"])
        if not validated:
            validate_latest_rows(score_name, rows, before_sort_first_time)
            validated = True

        page_index = extract_comment_page_index(data, infos)
        if page_index > current_page_index:
            current_page_index = page_index
            stale_hits = 0
        else:
            stale_hits += 1
            if stale_hits >= 2:
                return False

        update_progress_from_capture(
            state,
            score_name,
            int(state.get("rounds_done", 0) or 0),
            url,
            len(rows),
            data=data,
            comment_infos=infos,
        )

        if current_page_index >= target_page_index:
            print("⏩ %s 已快速追平到 pageIndex %s，将直接继续新轮次。" % (score_name, current_page_index))
            return True

    print("⚠️ %s 未能在限定步数内追平到 pageIndex %s，将回退到旧的轮次快进方案。" % (
        score_name,
        target_page_index,
    ))
    return False


def bootstrap_fold_resume(page, score_name, state):
    target_offset = int(state.get("fold_offset", 0) or 0)
    if target_offset <= 0:
        return False

    if state.get("completed"):
        return True

    if not fast_forward_to_low_value_zone(page, score_name):
        print("⚠️ 未能快速定位到低价值评价入口，将回退到普通断点续传。")
        return False

    current_offset = 0
    stale_hits = 0

    if get_low_value_hint_text(page):
        page.listen.clear()
        if try_expand_low_value_reviews(page, fast_mode=True):
            data, infos, url = capture_comment_packet(
                page,
                score_name,
                "%s_resume_fold_bootstrap" % score_name,
                timeout_seconds=8,
                quiet_gap=1.0,
            )
            if infos:
                current_offset = extract_fold_offset(url)

    while current_offset < target_offset:
        page.listen.clear()
        trigger_state = trigger_overlay_load(page, fast_mode=True)
        if trigger_state.get("no_more_visible"):
            return current_offset >= target_offset

        sleep_pair(WAIT_AFTER_TRIGGER, FAST_WAIT_AFTER_TRIGGER, True, "快速追平折叠评论游标")
        data, infos, url = capture_comment_packet(
            page,
            score_name,
            "%s_resume_fold_sync_%s" % (score_name, current_offset + 1),
            timeout_seconds=8,
            quiet_gap=1.0,
        )
        if not infos:
            stale_hits += 1
            if stale_hits >= 2:
                return False
            continue

        next_offset = extract_fold_offset(url)
        if next_offset > current_offset:
            current_offset = next_offset
            stale_hits = 0
        else:
            stale_hits += 1
            if stale_hits >= 2:
                return False

        if current_offset >= MAX_FAST_FOLD_CATCHUP + target_offset:
            return False

    print("⚡ %s 已快速追平到折叠评论 offset %s，将直接继续新轮次。" % (score_name, target_offset))
    return True


def fetch_round_packet(page, score_name, round_index, fast_mode=False):
    label = "%s_round_%s" % (score_name, round_index)
    attempts = 1 if fast_mode else MAX_TRIGGER_ATTEMPTS_PER_ROUND
    timeout_seconds = 8 if fast_mode else 25
    quiet_gap = 1.0 if fast_mode else 2.5

    if not review_overlay_exists(page):
        return None, [], "__OVERLAY_LOST__"

    if round_index == 1 and not fast_mode:
        page.listen.clear()
        data, comment_infos, url = capture_comment_packet(
            page,
            score_name,
            label,
            timeout_seconds=timeout_seconds,
            quiet_gap=quiet_gap,
        )
        if comment_infos:
            return data, comment_infos, url

    for attempt in range(1, attempts + 1):
        if detect_no_more_state(page):
            return None, [], "__NO_MORE__"

        page.listen.clear()
        prefix = "快速追平" if fast_mode else "开始触发"
        print("⬇️ %s %s第 %s 轮瀑布流加载，第 %s 次尝试..." % (score_name, prefix, round_index, attempt))
        trigger_state = trigger_overlay_load(page, fast_mode=fast_mode)
        if trigger_state.get("overlay_missing"):
            return None, [], "__OVERLAY_LOST__"
        if trigger_state.get("no_more_visible") and not trigger_state.get("low_value_expanded"):
            return None, [], "__NO_MORE__"

        sleep_pair(WAIT_AFTER_TRIGGER, FAST_WAIT_AFTER_TRIGGER, fast_mode, "等待评论接口返回")
        data, comment_infos, url = capture_comment_packet(
            page,
            score_name,
            label,
            timeout_seconds=timeout_seconds,
            quiet_gap=quiet_gap,
        )
        if comment_infos:
            return data, comment_infos, url

        if not review_overlay_exists(page):
            return None, [], "__OVERLAY_LOST__"
        if detect_no_more_state(page):
            return None, [], "__NO_MORE__"

    return None, [], ""


def process_score(page, score_name, score_config, progress, seen_ids, session_start, total_new_so_far):
    print("\n===== 开始处理 %s =====" % score_name)
    state = progress[score_name]
    resume_rounds = int(state.get("rounds_done", 0) or 0)
    if resume_rounds > 0:
        print("🔁 %s 断点续传：已完成 %s 轮。" % (score_name, resume_rounds))

    if not click_score_tag(page, score_name):
        print("⚠️ 未找到分类按钮：%s" % score_name)
        return 0, 0
    sleep_pair(WAIT_AFTER_TAG, FAST_WAIT_AFTER_TAG, False, "%s 分类切换稳定" % score_name)
    page.listen.clear()

    if click_latest_sort(page):
        sleep_pair(WAIT_AFTER_SORT, FAST_WAIT_AFTER_SORT, False, "排序切换稳定")
        page.listen.clear()
        latest_sort_text = wait_for_latest_sort_selected(page)
        if latest_sort_text:
            print("✅ 已确认“最新”排序激活：%s" % latest_sort_text)
        else:
            print("⚠️ 未能确认“最新”排序激活，将在首批结果中继续校验。")
    else:
        print("⚠️ 未能自动命中“最新”按钮，继续按当前排序抓取。")
        page.listen.clear()

    if state.get("last_mode") == "fold" and int(state.get("fold_offset", 0) or 0) > 0 and not state.get("completed"):
        if bootstrap_fold_resume(page, score_name, state):
            start_round = resume_rounds + 1
            resume_rounds = 0
        else:
            start_round = 1
    else:
        start_round = 1

    parsed_total = 0
    new_total = 0
    duplicate_rounds = 0
    no_packet_rounds = 0
    last_signature = ""
    last_tail_signature = ""
    no_packet_limit = int(MAX_NO_PACKET_ROUNDS_BY_SCORE.get(score_name, MAX_NO_PACKET_ROUNDS) or MAX_NO_PACKET_ROUNDS)

    for round_index in range(start_round, MAX_ROUNDS_PER_SCORE + 1):
        if time.time() - session_start > MAX_SESSION_SECONDS:
            print("⏹️ 已达到本次会话时长上限，结束。")
            break

        if total_new_so_far + new_total >= MAX_TOTAL_NEW_ROWS:
            print("⏹️ 已达到本次会话新增上限，结束。")
            break

        risk_check(page)

        is_resume_round = round_index <= resume_rounds
        if round_index == resume_rounds + 1:
            duplicate_rounds = 0
            last_signature = ""

        _data, comment_infos, _url = fetch_round_packet(
            page=page,
            score_name=score_name,
            round_index=round_index,
            fast_mode=is_resume_round,
        )

        if _url == "__NO_MORE__":
            print("⏹️ %s 已检测到“没有更多了”，切换到下一分类。" % score_name)
            state["completed"] = True
            save_progress(progress)
            break

        reason = detect_risk_state(page)
        if reason:
            handle_risk_state(page, reason)

        if not comment_infos:
            no_packet_rounds += 1
            print("⚠️ %s 第 %s 轮未捕获到评论包。" % (score_name, round_index))
            if not is_resume_round and no_packet_rounds >= no_packet_limit:
                print("⏹️ %s 连续未捕获达到阈值，本次先停止该分类。" % score_name)
                break
            sleep_pair(WAIT_AFTER_WRITE, FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮未命中，进入短冷却" % score_name)
            continue

        no_packet_rounds = 0
        rows = build_rows(comment_infos, score_config["value"])
        parsed_total += len(rows)
        signature = batch_signature(rows)

        update_progress_from_capture(state, score_name, round_index, _url, len(rows))
        save_progress(progress)

        if round_index == 1 and rows:
            if is_descending_creation_times(rows):
                first_time = normalize_text(rows[0].get("creationTime"))
                last_time = normalize_text(rows[min(len(rows), 10) - 1].get("creationTime"))
                print("✅ %s 首批时间已确认降序：%s -> %s" % (score_name, first_time, last_time))
            else:
                print("⚠️ %s 首批时间未呈降序，已继续抓取，但结果校验未通过。" % score_name)

        new_rows = []
        for row in rows:
            row_key = make_row_key(row)
            if row_key in seen_ids:
                continue
            seen_ids.add(row_key)
            new_rows.append(row)

        if is_resume_round:
            print("↪️ %s 第 %s 轮为断点快进，接口返回 %s 条，自动跳过已抓取部分。" % (score_name, round_index, len(rows)))
        else:
            if signature and signature == last_signature:
                duplicate_rounds += 1
                print("⚠️ 本轮数据签名与上一轮相同，疑似没有加载出新评论。")
            elif new_rows:
                duplicate_rounds = 0
            else:
                duplicate_rounds += 1

            print("ℹ️ %s 第 %s 轮接口返回 %s 条，去重后新增 %s 条。" % (score_name, round_index, len(rows), len(new_rows)))

            if new_rows:
                append_rows(new_rows)
                new_total += len(new_rows)
                print("✅ %s 第 %s 轮写入 %s 条，新累计 %s 条。" % (score_name, round_index, len(new_rows), new_total))
            else:
                print("⚠️ 本轮评论全部重复，没有新增数据。")

            if duplicate_rounds >= MAX_DUPLICATE_ROUNDS:
                print("⏹️ %s 连续重复达到阈值，本次先停止该分类。" % score_name)
                break

            if score_name == "差评":
                is_tail_candidate = (
                    "getfoldcommentlist" in normalize_text(_url).lower()
                    and 0 < len(rows) < 10
                )
                if is_tail_candidate:
                    tail_signature = "%s|%s|%s" % (extract_fold_offset(_url), len(rows), signature)
                    if detect_no_more_state(page):
                        print("⏹️ 差评 已同时满足末页条数和“没有更多了”，判定完成。")
                        state["completed"] = True
                        save_progress(progress)
                        break
                    if last_tail_signature and tail_signature == last_tail_signature:
                        print("⏹️ 差评 已连续两次命中同一末页，判定完成。")
                        state["completed"] = True
                        save_progress(progress)
                        break
                    last_tail_signature = tail_signature
                else:
                    last_tail_signature = ""
            else:
                if should_stop_category_round(score_name, len(rows), _url, detect_no_more_state(page)):
                    print("⏹️ %s 已触达分类末尾，切换到下一分类。" % score_name)
                    state["completed"] = True
                    save_progress(progress)
                    break

        last_signature = signature or last_signature
        sleep_pair(WAIT_AFTER_WRITE, FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮结束冷却" % score_name)

    return parsed_total, new_total


def process_score_v2(page, score_name, score_config, progress, seen_ids, session_start, total_new_so_far):
    print("\n===== 开始处理 %s =====" % score_name)
    state = progress[score_name]
    resume_rounds = int(state.get("rounds_done", 0) or 0)
    if resume_rounds > 0:
        print("🔁 %s 断点续传：已完成 %s 轮。" % (score_name, resume_rounds))

    if not is_target_product_url(get_page_url_safe(page)) or not review_overlay_exists(page):
        page = open_product_page(page, "%s 开始前重开商品页" % score_name)
        conservative_sleep(WAIT_PAGE_OPEN[0], WAIT_PAGE_OPEN[1], "%s 开始前等待商品页稳定" % score_name)
        ensure_product_page_not_blocked(page, "%s 开始前重开商品页" % score_name)
        if not wait_for_login_ready(page):
            raise RuntimeError("%s 开始前等待登录超时。" % score_name)
        if not enter_review_overlay(page):
            raise RuntimeError("%s 开始前未能重新进入评论弹层。" % score_name)
        conservative_sleep(WAIT_AFTER_OVERLAY[0], WAIT_AFTER_OVERLAY[1], "%s 开始前等待评价弹层稳定" % score_name)

    ok, before_sort_first_time = prepare_score_context(page, score_name)
    if not ok:
        return page, 0, 0

    start_round = 1
    latest_validation_done = False
    if state.get("last_mode") == "fold" and int(state.get("fold_offset", 0) or 0) > 0 and not state.get("completed"):
        if bootstrap_fold_resume(page, score_name, state):
            start_round = max(1, resume_rounds + 1)
            resume_rounds = 0
            save_progress(progress)
    elif int(state.get("page_index", 0) or 0) > 0 and not state.get("completed"):
        if bootstrap_scroll_resume(page, score_name, state, before_sort_first_time=before_sort_first_time):
            start_round = max(1, resume_rounds + 1)
            resume_rounds = 0
            latest_validation_done = True
            save_progress(progress)

    parsed_total = 0
    new_total = 0
    duplicate_rounds = 0
    no_packet_rounds = 0
    last_signature = ""
    last_tail_signature = ""
    no_packet_limit = int(MAX_NO_PACKET_ROUNDS_BY_SCORE.get(score_name, MAX_NO_PACKET_ROUNDS) or MAX_NO_PACKET_ROUNDS)
    round_index = start_round

    while round_index <= MAX_ROUNDS_PER_SCORE:
        if time.time() - session_start > MAX_SESSION_SECONDS:
            print("⏰ 已达到本次会话时长上限，结束。")
            break

        if total_new_so_far + new_total >= MAX_TOTAL_NEW_ROWS:
            print("⏰ 已达到本次会话新增上限，结束。")
            break

        page = risk_check(page, score_name=score_name, state=state, stage_label="%s 第 %s 轮前" % (score_name, round_index))

        is_resume_round = round_index <= resume_rounds
        if round_index == resume_rounds + 1:
            duplicate_rounds = 0
            last_signature = ""

        _data, comment_infos, _url = fetch_round_packet(
            page=page,
            score_name=score_name,
            round_index=round_index,
            fast_mode=is_resume_round,
        )

        if _url == "__OVERLAY_LOST__":
            print("⚠️ %s 第 %s 轮检测到评论弹层丢失，准备恢复后重试。" % (score_name, round_index))
            page = restore_score_context(page, score_name, state=state, stage_label="%s 第 %s 轮恢复" % (score_name, round_index))
            save_progress(progress)
            continue

        if _url == "__NO_MORE__":
            print("⏹️ %s 已检测到“没有更多了”，切换到下一分类。" % score_name)
            state["completed"] = True
            save_progress(progress)
            break

        page = risk_check(page, score_name=score_name, state=state, stage_label="%s 第 %s 轮后" % (score_name, round_index))

        if not comment_infos:
            no_packet_rounds += 1
            print("⚠️ %s 第 %s 轮未捕获到评论包。" % (score_name, round_index))
            if not is_resume_round and no_packet_rounds >= no_packet_limit:
                print("⏹️ %s 连续未捕获达到阈值，本次先停止该分类。" % score_name)
                break
            sleep_pair(WAIT_AFTER_WRITE, FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮未命中，进入短冷却" % score_name)
            round_index += 1
            continue

        no_packet_rounds = 0
        rows = build_rows(comment_infos, score_config["value"])
        parsed_total += len(rows)
        signature = batch_signature(rows)

        update_progress_from_capture(
            state,
            score_name,
            round_index,
            _url,
            len(rows),
            data=_data,
            comment_infos=comment_infos,
        )
        save_progress(progress)

        if rows and not latest_validation_done:
            validate_latest_rows(score_name, rows, before_sort_first_time)
            latest_validation_done = True

        new_rows = []
        for row in rows:
            row_key = make_row_key(row)
            if row_key in seen_ids:
                continue
            seen_ids.add(row_key)
            new_rows.append(row)

        if is_resume_round:
            print("↪️ %s 第 %s 轮为断点快进，接口返回 %s 条，自动跳过已抓取部分。" % (
                score_name,
                round_index,
                len(rows),
            ))
        else:
            if signature and signature == last_signature:
                duplicate_rounds += 1
                print("⚠️ 本轮数据签名与上一轮相同，疑似没有加载出新评论。")
            elif new_rows:
                duplicate_rounds = 0
            else:
                duplicate_rounds += 1

            print("ℹ️ %s 第 %s 轮接口返回 %s 条，去重后新增 %s 条。" % (
                score_name,
                round_index,
                len(rows),
                len(new_rows),
            ))

            if new_rows:
                append_rows(new_rows)
                new_total += len(new_rows)
                print("✅ %s 第 %s 轮写入 %s 条，新累计 %s 条。" % (
                    score_name,
                    round_index,
                    len(new_rows),
                    new_total,
                ))
            else:
                print("⚠️ 本轮评论全部重复，没有新增数据。")

            if duplicate_rounds >= MAX_DUPLICATE_ROUNDS:
                print("⏹️ %s 连续重复达到阈值，本次先停止该分类。" % score_name)
                break

            if score_name == "差评":
                is_tail_candidate = (
                    "getfoldcommentlist" in normalize_text(_url).lower()
                    and 0 < len(rows) < 10
                )
                if is_tail_candidate:
                    tail_signature = "%s|%s|%s" % (extract_fold_offset(_url), len(rows), signature)
                    if detect_no_more_state(page):
                        print("⏹️ 差评 已同时满足末页条数和“没有更多了”，判定完成。")
                        state["completed"] = True
                        save_progress(progress)
                        break
                    if last_tail_signature and tail_signature == last_tail_signature:
                        print("⏹️ 差评 已连续两次命中同一末页，判定完成。")
                        state["completed"] = True
                        save_progress(progress)
                        break
                    last_tail_signature = tail_signature
                else:
                    last_tail_signature = ""
            else:
                no_more_visible = detect_no_more_state(page)
                has_next_page = state.get("has_next_page")
                if should_stop_category_round(score_name, len(rows), _url, no_more_visible) or has_next_page is False:
                    print("⏹️ %s 已触达分类末尾，切换到下一分类。" % score_name)
                    state["completed"] = True
                    save_progress(progress)
                    break

        last_signature = signature or last_signature
        sleep_pair(WAIT_AFTER_WRITE, FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮结束冷却" % score_name)
        round_index += 1

    return page, parsed_total, new_total


def main():
    random.seed()
    ensure_output_files()
    progress = restore_progress_from_debug_dir(restore_progress_from_endpoint_log(load_progress()))
    save_progress(progress)
    seen_ids = load_existing_ids()
    has_profile_data = profile_dir_has_data(PROFILE_DIR)

    print("🚀 启动京东评论保守低频采集器")
    print("商品 ID: %s" % PRODUCT_ID)
    print("CSV 输出: %s" % CSV_FILE)
    print("调试目录: %s" % DEBUG_DIR)
    if has_profile_data:
        print("📂 尝试复用当前登录态目录: %s" % PROFILE_DIR)
    else:
        print("🆕 将使用全新登录态目录: %s" % PROFILE_DIR)
        print("📦 旧的被封账号目录已保留不动: %s" % BLOCKED_PROFILE_DIR)

    page = None
    total_parsed = 0
    total_new = 0
    session_start = time.time()

    try:
        page = build_page()
        print("✅ 浏览器启动成功，资料目录就绪: %s" % PROFILE_DIR)
        page.listen.start()

        page = open_product_page(page, "首次打开商品页")
        conservative_sleep(WAIT_PAGE_OPEN[0], WAIT_PAGE_OPEN[1], "等待商品页完全稳定")
        ensure_product_page_not_blocked(page, "首次打开商品页后")

        if not wait_for_login_ready(page):
            raise RuntimeError("等待登录超时，请确认账号已完成登录。")

        page = risk_check(page, stage_label="登录后风险检查")

        page = open_product_page(page, "登录后重新打开商品页")
        conservative_sleep(WAIT_PAGE_OPEN[0], WAIT_PAGE_OPEN[1], "登录后重新打开商品页")
        ensure_product_page_not_blocked(page, "登录后重新打开商品页后")

        if not enter_review_overlay(page):
            raise RuntimeError("未能进入全部评价弹层，请检查页面结构是否变化。")

        conservative_sleep(WAIT_AFTER_OVERLAY[0], WAIT_AFTER_OVERLAY[1], "等待评价弹层稳定")
        page = risk_check(page, stage_label="评论弹层后风险检查")

        for score_name, score_config in SCORE_MAP.items():
            if progress[score_name].get("completed"):
                print("\n⏭️ %s 已确认抓取完毕，跳过。" % score_name)
                continue

            page, parsed_count, new_count = process_score_v2(
                page=page,
                score_name=score_name,
                score_config=score_config,
                progress=progress,
                seen_ids=seen_ids,
                session_start=session_start,
                total_new_so_far=total_new,
            )
            total_parsed += parsed_count
            total_new += new_count

            if total_new >= MAX_TOTAL_NEW_ROWS:
                print("⏹️ 达到本次会话新增上限，停止后续分类。")
                break

            conservative_sleep(WAIT_AFTER_CATEGORY[0], WAIT_AFTER_CATEGORY[1], "%s 分类结束冷却" % score_name)

        print("\n🎉 采集结束")
        print("原始解析条数: %s" % total_parsed)
        print("实际新增条数: %s" % total_new)
        print("CSV 文件: %s" % CSV_FILE)
        print("接口日志: %s" % ENDPOINT_LOG)
        print("原始包目录: %s" % DEBUG_DIR)

    except Exception as exc:
        print("❌ 脚本终止: %s" % exc)
        traceback.print_exc()
    finally:
        if page:
            try:
                page.quit()
                print("\n浏览器已关闭。下次如果要复用登录态，请尽量正常结束脚本。")
            except Exception:
                pass


if __name__ == "__main__":
    main()
