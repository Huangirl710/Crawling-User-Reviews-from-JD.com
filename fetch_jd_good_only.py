# -*- coding: utf-8 -*-

from dataclasses import dataclass
import os
import random
import sys
import time
import traceback

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import fetch_jd as core


GOOD_SCORE_NAME = "好评"
GOOD_SCORE_VALUE = 1


@dataclass
class RuntimeConfig:
    csv_file: str
    progress_file: str
    debug_dir: str
    endpoint_log: str
    profile_dir: str
    blocked_profile_dir: str
    use_latest_sort: bool = False


def build_runtime_config():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return RuntimeConfig(
        csv_file=os.path.join(base_dir, "jd_comments_good_only.csv"),
        progress_file=os.path.join(base_dir, "jd_good_only_progress.json"),
        debug_dir=os.path.join(base_dir, "jd_good_only_debug"),
        endpoint_log=os.path.join(base_dir, "jd_good_only_endpoints.jsonl"),
        profile_dir=os.path.join(base_dir, "dp_browser_profile_good_only"),
        blocked_profile_dir=os.path.join(base_dir, "dp_browser_profile"),
        use_latest_sort=False,
    )


def apply_runtime_config(cfg):
    core.CSV_FILE = cfg.csv_file
    core.PROGRESS_FILE = cfg.progress_file
    core.DEBUG_DIR = cfg.debug_dir
    core.ENDPOINT_LOG = cfg.endpoint_log
    core.PROFILE_DIR = cfg.profile_dir
    core.BLOCKED_PROFILE_DIR = cfg.blocked_profile_dir


def click_non_latest_sort(page):
    options = [
        ("推荐", "推荐排序"),
        ("默认", "默认排序"),
        ("综合", "综合排序"),
    ]
    for text, label in options:
        if core.js_click_in_rate_list(page, text, "latest", label):
            return True
        if core.safe_click(
            page,
            ['xpath://div[@id="rateList"]//*[contains(normalize-space(),"%s")]' % text],
            label,
            timeout_each=2,
        ):
            return True
    return False


def prepare_good_context(page):
    if not core.click_score_tag(page, GOOD_SCORE_NAME):
        print("⚠️ 未找到分类按钮：%s" % GOOD_SCORE_NAME)
        return False

    core.sleep_pair(core.WAIT_AFTER_TAG, core.FAST_WAIT_AFTER_TAG, False, "%s 分类切换稳定" % GOOD_SCORE_NAME)
    page.listen.clear()

    if click_non_latest_sort(page):
        core.sleep_pair(core.WAIT_AFTER_SORT, core.FAST_WAIT_AFTER_SORT, False, "非最新排序切换稳定")
        page.listen.clear()
        print("✅ 已切换为非最新排序，继续抓取好评。")
    else:
        print("ℹ️ 不点击“最新”，按页面当前默认排序抓取好评。")
        page.listen.clear()

    return True


def bootstrap_good_scroll_resume(page, progress, state):
    target_page_index = int(state.get("page_index", 0) or 0)
    if target_page_index <= 0:
        return False

    if state.get("completed"):
        return True

    print("⏩ %s 普通评论断点：目标 pageIndex=%s，开始快速追平。" % (GOOD_SCORE_NAME, target_page_index))
    current_page_index = 0
    stale_hits = 0

    for step_index in range(1, core.MAX_FAST_SCROLL_CATCHUP_STEPS + 1):
        data, infos, url = core.fetch_resume_packet(page, GOOD_SCORE_NAME, step_index)
        if url == "__OVERLAY_LOST__":
            return False
        if url == "__NO_MORE__":
            return current_page_index >= target_page_index or not state.get("has_next_page", True)
        if not infos:
            stale_hits += 1
            if stale_hits >= 2:
                return False
            continue

        rows = core.build_rows(infos, GOOD_SCORE_VALUE)
        page_index = core.extract_comment_page_index(data, infos)
        if page_index > current_page_index:
            current_page_index = page_index
            stale_hits = 0
        else:
            stale_hits += 1
            if stale_hits >= 2:
                return False

        core.update_progress_from_capture(
            state,
            GOOD_SCORE_NAME,
            int(state.get("rounds_done", 0) or 0),
            url,
            len(rows),
            data=data,
            comment_infos=infos,
        )
        core.save_progress(progress)

        if current_page_index >= target_page_index:
            print("⏩ %s 已快速追平到 pageIndex %s，将直接继续新轮次。" % (GOOD_SCORE_NAME, current_page_index))
            return True

    print("⚠️ %s 未能在限定步数内追平到 pageIndex %s。" % (GOOD_SCORE_NAME, target_page_index))
    return False


def restore_good_context(page, progress, state=None, stage_label=""):
    current_url = core.get_page_url_safe(page)
    if not core.is_target_product_url(current_url) or not core.review_overlay_exists(page):
        page = core.open_product_page(page, stage_label or "恢复商品页")
        core.conservative_sleep(core.WAIT_PAGE_OPEN[0], core.WAIT_PAGE_OPEN[1], "%s 后等待商品页稳定" % (stage_label or "恢复商品页"))
        core.ensure_product_page_not_blocked(page, stage_label or "恢复商品页")
        if not core.wait_for_login_ready(page):
            raise RuntimeError("恢复评论上下文时等待登录超时。")
        if not core.enter_review_overlay(page):
            raise RuntimeError("恢复评论上下文时未能重新进入评论弹层。")
        core.conservative_sleep(core.WAIT_AFTER_OVERLAY[0], core.WAIT_AFTER_OVERLAY[1], "%s 后等待评价弹层稳定" % (stage_label or "恢复评论上下文"))

    if not prepare_good_context(page):
        raise RuntimeError("恢复评论上下文时未能重新切到 %s。" % GOOD_SCORE_NAME)

    if not state or state.get("completed"):
        return page

    if state.get("last_mode") == "fold" and int(state.get("fold_offset", 0) or 0) > 0:
        if not core.bootstrap_fold_resume(page, GOOD_SCORE_NAME, state):
            raise RuntimeError("恢复 %s 时未能追平折叠评论断点。" % GOOD_SCORE_NAME)
    elif int(state.get("page_index", 0) or 0) > 0:
        if not bootstrap_good_scroll_resume(page, progress, state):
            raise RuntimeError("恢复 %s 时未能追平 pageIndex 断点。" % GOOD_SCORE_NAME)

    page.listen.clear()
    return page


def wait_for_good_risk_recovery(page, progress, reason, state=None, stage_label=""):
    print("⚠️ 检测到风险提示：%s" % reason)
    print("⏸️ 请在已打开的浏览器里完成人工验证。验证完成后，脚本会自动恢复到当前商品评论并继续。")
    deadline = time.time() + core.RISK_RECOVERY_WAIT_SECONDS
    last_print = 0

    while time.time() < deadline:
        current_reason = core.detect_risk_state(page)
        if current_reason:
            now = time.time()
            if now - last_print >= 10:
                print("⏳ 仍在等待人工验证完成：%s" % current_reason)
                last_print = now
            time.sleep(2)
            continue

        try:
            page = restore_good_context(page, progress, state=state, stage_label=stage_label or ("%s 风险恢复" % GOOD_SCORE_NAME))
            print("✅ 风险验证已恢复，继续执行。")
            return page
        except Exception as e:
            now = time.time()
            if now - last_print >= 10:
                print("⚠️ 验证已结束，但恢复评论上下文仍未成功：%s" % core.normalize_text(e))
                last_print = now
            time.sleep(3)

    raise RuntimeError("等待人工验证恢复超时，脚本已停止。")


def risk_check_good(page, progress, state=None, stage_label=""):
    reason = core.detect_risk_state(page)
    if reason:
        return wait_for_good_risk_recovery(page, progress, reason, state=state, stage_label=stage_label)
    return page


def process_good_reviews(page, progress, seen_ids, session_start, total_new_so_far):
    print("\n===== 开始处理 %s（非最新） =====" % GOOD_SCORE_NAME)
    state = progress[GOOD_SCORE_NAME]
    resume_rounds = int(state.get("rounds_done", 0) or 0)
    if resume_rounds > 0:
        print("🔁 %s 断点续传：已完成 %s 轮。" % (GOOD_SCORE_NAME, resume_rounds))

    if not core.is_target_product_url(core.get_page_url_safe(page)) or not core.review_overlay_exists(page):
        page = core.open_product_page(page, "%s 开始前重开商品页" % GOOD_SCORE_NAME)
        core.conservative_sleep(core.WAIT_PAGE_OPEN[0], core.WAIT_PAGE_OPEN[1], "%s 开始前等待商品页稳定" % GOOD_SCORE_NAME)
        core.ensure_product_page_not_blocked(page, "%s 开始前重开商品页" % GOOD_SCORE_NAME)
        if not core.wait_for_login_ready(page):
            raise RuntimeError("%s 开始前等待登录超时。" % GOOD_SCORE_NAME)
        if not core.enter_review_overlay(page):
            raise RuntimeError("%s 开始前未能重新进入评论弹层。" % GOOD_SCORE_NAME)
        core.conservative_sleep(core.WAIT_AFTER_OVERLAY[0], core.WAIT_AFTER_OVERLAY[1], "%s 开始前等待评价弹层稳定" % GOOD_SCORE_NAME)

    if not prepare_good_context(page):
        return page, 0, 0

    start_round = 1
    if state.get("last_mode") == "fold" and int(state.get("fold_offset", 0) or 0) > 0 and not state.get("completed"):
        if core.bootstrap_fold_resume(page, GOOD_SCORE_NAME, state):
            start_round = max(1, resume_rounds + 1)
            resume_rounds = 0
            core.save_progress(progress)
    elif int(state.get("page_index", 0) or 0) > 0 and not state.get("completed"):
        if bootstrap_good_scroll_resume(page, progress, state):
            start_round = max(1, resume_rounds + 1)
            resume_rounds = 0
            core.save_progress(progress)

    parsed_total = 0
    new_total = 0
    duplicate_rounds = 0
    no_packet_rounds = 0
    last_signature = ""
    no_packet_limit = int(core.MAX_NO_PACKET_ROUNDS_BY_SCORE.get(GOOD_SCORE_NAME, core.MAX_NO_PACKET_ROUNDS) or core.MAX_NO_PACKET_ROUNDS)
    round_index = start_round

    while round_index <= core.MAX_ROUNDS_PER_SCORE:
        if time.time() - session_start > core.MAX_SESSION_SECONDS:
            print("⏰ 已达到本次会话时长上限，结束。")
            break

        if total_new_so_far + new_total >= core.MAX_TOTAL_NEW_ROWS:
            print("⏰ 已达到本次会话新增上限，结束。")
            break

        page = risk_check_good(page, progress, state=state, stage_label="%s 第 %s 轮前" % (GOOD_SCORE_NAME, round_index))

        is_resume_round = round_index <= resume_rounds
        if round_index == resume_rounds + 1:
            duplicate_rounds = 0
            last_signature = ""

        data, comment_infos, url = core.fetch_round_packet(
            page=page,
            score_name=GOOD_SCORE_NAME,
            round_index=round_index,
            fast_mode=is_resume_round,
        )

        if url == "__OVERLAY_LOST__":
            print("⚠️ %s 第 %s 轮检测到评论弹层丢失，准备恢复后重试。" % (GOOD_SCORE_NAME, round_index))
            page = restore_good_context(page, progress, state=state, stage_label="%s 第 %s 轮恢复" % (GOOD_SCORE_NAME, round_index))
            core.save_progress(progress)
            continue

        if url == "__NO_MORE__":
            print("⏹️ %s 已检测到“没有更多了”，本次抓取结束。" % GOOD_SCORE_NAME)
            state["completed"] = True
            core.save_progress(progress)
            break

        page = risk_check_good(page, progress, state=state, stage_label="%s 第 %s 轮后" % (GOOD_SCORE_NAME, round_index))

        if not comment_infos:
            no_packet_rounds += 1
            print("⚠️ %s 第 %s 轮未捕获到评论包。" % (GOOD_SCORE_NAME, round_index))
            if not is_resume_round and no_packet_rounds >= no_packet_limit:
                print("⏹️ %s 连续未捕获达到阈值，本次先停止。" % GOOD_SCORE_NAME)
                break
            core.sleep_pair(core.WAIT_AFTER_WRITE, core.FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮未命中，进入短冷却" % GOOD_SCORE_NAME)
            round_index += 1
            continue

        no_packet_rounds = 0
        rows = core.build_rows(comment_infos, GOOD_SCORE_VALUE)
        parsed_total += len(rows)
        signature = core.batch_signature(rows)

        core.update_progress_from_capture(
            state,
            GOOD_SCORE_NAME,
            round_index,
            url,
            len(rows),
            data=data,
            comment_infos=comment_infos,
        )
        core.save_progress(progress)

        new_rows = []
        for row in rows:
            row_key = core.make_row_key(row)
            if row_key in seen_ids:
                continue
            seen_ids.add(row_key)
            new_rows.append(row)

        if is_resume_round:
            print("↪️ %s 第 %s 轮为断点快进，接口返回 %s 条，自动跳过已抓取部分。" % (
                GOOD_SCORE_NAME,
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
                GOOD_SCORE_NAME,
                round_index,
                len(rows),
                len(new_rows),
            ))

            if new_rows:
                core.append_rows(new_rows)
                new_total += len(new_rows)
                print("✅ %s 第 %s 轮写入 %s 条，新累计 %s 条。" % (
                    GOOD_SCORE_NAME,
                    round_index,
                    len(new_rows),
                    new_total,
                ))
            else:
                print("⚠️ 本轮评论全部重复，没有新增数据。")

            if duplicate_rounds >= core.MAX_DUPLICATE_ROUNDS:
                print("⏹️ %s 连续重复达到阈值，本次先停止。" % GOOD_SCORE_NAME)
                break

            no_more_visible = core.detect_no_more_state(page)
            has_next_page = state.get("has_next_page")
            if core.should_stop_category_round(GOOD_SCORE_NAME, len(rows), url, no_more_visible) or has_next_page is False:
                print("⏹️ %s 已触达分类末尾，本次抓取结束。" % GOOD_SCORE_NAME)
                state["completed"] = True
                core.save_progress(progress)
                break

        last_signature = signature or last_signature
        core.sleep_pair(core.WAIT_AFTER_WRITE, core.FAST_WAIT_AFTER_WRITE, is_resume_round, "%s 本轮结束冷却" % GOOD_SCORE_NAME)
        round_index += 1

    return page, parsed_total, new_total


def main():
    random.seed()
    cfg = build_runtime_config()
    apply_runtime_config(cfg)

    core.ensure_output_files()
    progress = core.restore_progress_from_debug_dir(core.restore_progress_from_endpoint_log(core.load_progress()))
    core.save_progress(progress)
    seen_ids = core.load_existing_ids()
    has_profile_data = core.profile_dir_has_data(core.PROFILE_DIR)

    print("🚀 启动京东好评旁路采集器（非最新排序）")
    print("商品 ID: %s" % core.PRODUCT_ID)
    print("CSV 输出: %s" % core.CSV_FILE)
    print("调试目录: %s" % core.DEBUG_DIR)
    if has_profile_data:
        print("📂 尝试复用当前登录态目录: %s" % core.PROFILE_DIR)
    else:
        print("🆕 将使用独立登录态目录: %s" % core.PROFILE_DIR)
    print("ℹ️ 本脚本不会点击“最新”，会优先尝试切到推荐/默认排序。")

    page = None
    total_parsed = 0
    total_new = 0
    session_start = time.time()

    try:
        page = core.build_page()
        print("✅ 浏览器启动成功，资料目录就绪: %s" % core.PROFILE_DIR)
        page.listen.start()

        page = core.open_product_page(page, "首次打开商品页")
        core.conservative_sleep(core.WAIT_PAGE_OPEN[0], core.WAIT_PAGE_OPEN[1], "等待商品页完全稳定")
        core.ensure_product_page_not_blocked(page, "首次打开商品页后")

        if not core.wait_for_login_ready(page):
            raise RuntimeError("等待登录超时，请确认账号已完成登录。")

        page = risk_check_good(page, progress, stage_label="登录后风险检查")

        page = core.open_product_page(page, "登录后重新打开商品页")
        core.conservative_sleep(core.WAIT_PAGE_OPEN[0], core.WAIT_PAGE_OPEN[1], "登录后重新打开商品页")
        core.ensure_product_page_not_blocked(page, "登录后重新打开商品页后")

        if not core.enter_review_overlay(page):
            raise RuntimeError("未能进入全部评价弹层，请检查页面结构是否变化。")

        core.conservative_sleep(core.WAIT_AFTER_OVERLAY[0], core.WAIT_AFTER_OVERLAY[1], "等待评价弹层稳定")
        page = risk_check_good(page, progress, stage_label="评论弹层后风险检查")

        if progress[GOOD_SCORE_NAME].get("completed"):
            print("\n⏭️ %s 已确认抓取完毕，跳过。" % GOOD_SCORE_NAME)
        else:
            page, parsed_count, new_count = process_good_reviews(
                page=page,
                progress=progress,
                seen_ids=seen_ids,
                session_start=session_start,
                total_new_so_far=total_new,
            )
            total_parsed += parsed_count
            total_new += new_count

        print("\n🎉 采集结束")
        print("原始解析条数: %s" % total_parsed)
        print("实际新增条数: %s" % total_new)
        print("CSV 文件: %s" % core.CSV_FILE)
        print("接口日志: %s" % core.ENDPOINT_LOG)
        print("原始包目录: %s" % core.DEBUG_DIR)

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
