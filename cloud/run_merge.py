#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火车票发票自动合并 · 云电脑版（WorkBuddy 自动化调用）

工作流：
  1. 从本地 gitignored 的 mail_settings.json 读取 QQ 邮箱 + 授权码（不入库、不回显）
  2. 复用 email_handler 拉取 12306 发票 PDF（IMAP，按开车时间无需）
  3. 复用 ticket_core 按开车时间排序合并为单份 PDF
  4. 通过 SMTP 直接发送到指定邮箱（绕开 qq-mail 连接器的 1MB/确认限制，可无人值守）

用法：
  python run_merge.py --to 同事@qq.com                      # 默认：仅合并「开车时间在上个月」的发票
  python run_merge.py --to 同事@qq.com --dry-run            # 只筛选/合并并报告，不发送（验证用）
  python run_merge.py --to 同事@qq.com --from 2026-07-01 --to 2026-07-31  # 手动指定范围（不过滤开车月份）
  python run_merge.py --to 同事@qq.com --early include      # 把「当前月前3天开车」的发票也一并合并
  python run_merge.py --to 同事@qq.com --early exclude      # 明确忽略月初发票（不提示）

说明：默认月度模式下，按发票上的『开车时间』精确筛选，仅保留开车时间在上个月的发票；
      开车时间为上上个月及更早（或无法识别）的发票自动跳过，不纳入合并。
      额外：若检测到『开车时间在当前月前3天(1/2/3号)』的发票，默认会提示——
      交互模式直接询问；自动化/非交互模式在汇总里标 needs_early_decision 并暂不合并，由你确认是否一并整合。
输出：末尾打印一行 JSON 汇总，供自动化读取汇报。
"""
import os
import sys
import json
import argparse
import shutil
import tempfile
import traceback
from datetime import datetime, timedelta

# ---- 路径：脚本在 cloud/ 下，仓库根 = 上级目录 ----
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

import config
import email_handler
import ticket_core


def load_settings():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mail_settings.json")
    if not os.path.exists(p):
        raise FileNotFoundError(f"缺少凭据文件 {p}（请从 mail_settings.example.json 复制并填入真实授权码）")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def last_month_range():
    today = datetime.now().replace(day=1)
    first = today - timedelta(days=1)          # 上月最后一天
    start = first.replace(day=1)               # 上月 1 号
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def prev_month_boundaries():
    """返回 (上月1号 00:00, 本月1号 00:00)。
    用于按『开车时间』过滤：仅保留开车时间落在 [上月1号, 本月1号) 的发票，
    上上个月及更早（以及无法识别开车时间的）一律排除。"""
    today = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if today.month == 1:
        prev_start = today.replace(year=today.year - 1, month=12)
    else:
        prev_start = today.replace(month=today.month - 1)
    return prev_start, today


def early_this_month_range():
    """返回 (本月1号 00:00, 本月1号+3天 00:00)。
    用于识别『开车时间在当前月前3天(1/2/3号)』的发票，提示用户是否一并整合。"""
    today = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    early_end = today + timedelta(days=3)
    return today, early_end


def send_pdf_smtp(settings, pdf_path, to_email, month_label=None):
    """通过 SMTP_SSL 直接发送合并后的 PDF（无人值守，无需两步确认）。"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.mime.text import MIMEText

    smtp_server = settings.get("smtp_server", "smtp.qq.com")
    smtp_port = int(settings.get("smtp_port", 465))
    user = settings["email_address"]
    pwd = settings["password"]

    subject_month = month_label or datetime.now().strftime("%Y%m")
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = f"12306火车票发票合并_{subject_month}"
    msg.attach(MIMEText("附件为按开车时间排序合并后的 12306 电子客票发票，请查收。", "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
    part["Content-Disposition"] = f'attachment; filename="{os.path.basename(pdf_path)}"'
    msg.attach(part)

    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=60) as s:
        s.login(user, pwd)
        s.send_message(msg, to_addrs=[to_email])
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", help="接收合并 PDF 的邮箱（缺省读 mail_settings.json 的 default_recipient）")
    ap.add_argument("--from", dest="date_from", help="开始日期 YYYY-MM-DD（缺省=上月1号）")
    ap.add_argument("--to-date", dest="date_to", help="结束日期 YYYY-MM-DD（缺省=本月1号）")
    ap.add_argument("--dry-run", action="store_true", help="只拉取+筛选+合并并报告，不发送邮件（用于验证）")
    ap.add_argument("--early", choices=["ask", "include", "exclude"], default="ask",
                    help="当前月前3天开车的发票如何处理：ask=提示(默认) / include=一并合并 / exclude=忽略")
    args = ap.parse_args()

    settings = load_settings()
    to_email = args.to or settings.get("default_recipient")
    if not to_email:
        raise ValueError("未指定接收邮箱：请加 --to 或在 mail_settings.json 配 default_recipient")

    default_mode = not (args.date_from and args.date_to)
    if default_mode:
        # 默认月度模式：拉取范围放宽到「上月1号 ~ 今天」，避免上月发票的邮件迟发到本月而被漏掉；
        # 真正的筛选在下面按『开车时间』进行，仅保留上个月开车的发票。
        prev_start, cur_start = prev_month_boundaries()
        args.date_from = prev_start.strftime("%Y-%m-%d")
        args.date_to = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        month_label = prev_start.strftime("%Y-%m")
    else:
        prev_start = cur_start = None
        month_label = f"{args.date_from}_{args.date_to}"

    # 工作目录用 /tmp，避免污染仓库
    work = tempfile.mkdtemp(prefix="12306_merge_")
    inv_folder = os.path.join(work, "发票")

    summary = {"ok": False, "step": "", "detail": ""}
    try:
        # 1) 拉取
        config.EMAIL_CONFIG["email_address"] = settings["email_address"]
        summary["step"] = "fetch"
        total, msg = email_handler.fetch_emails_and_download_attachments(
            password=settings["password"], target_folder=inv_folder,
            date_from=args.date_from, date_to=args.date_to)
        summary["fetched"] = total
        if total == 0:
            summary["detail"] = msg or "未找到相关发票"
            print(json.dumps(summary, ensure_ascii=False))
            return

        # 1.5) 默认模式下按『开车时间』过滤：
        #   - 上月开车          → 自动保留
        #   - 当前月前3天开车   → 需用户确认（--early）
        #   - 上上个月及更早/无法识别 → 自动排除
        if default_mode:
            cur_start, early_end = early_this_month_range()
            orig_folder = inv_folder
            kept_folder = os.path.join(work, "发票_上月")
            os.makedirs(kept_folder, exist_ok=True)
            excluded, kept, early = [], [], []
            for f in os.listdir(orig_folder):
                if not f.lower().endswith(".pdf"):
                    continue
                src = os.path.join(orig_folder, f)
                dt = ticket_core.extract_departure_info(src)
                if dt and prev_start <= dt < cur_start:
                    shutil.copy(src, os.path.join(kept_folder, f))
                    kept.append((f, dt.strftime("%Y-%m-%d")))
                elif dt and cur_start <= dt < early_end:
                    early.append((f, dt.strftime("%Y-%m-%d %H:%M")))
                else:
                    reason = dt.strftime("%Y-%m") if dt else "无开车时间"
                    excluded.append((f, reason))
                    print(f"[FILTER] 排除（开车时间 {reason}）: {f}", file=sys.stderr)
            inv_folder = kept_folder
            summary["excluded_count"] = len(excluded)
            summary["excluded"] = [{"file": x[0], "month": x[1]} for x in excluded]
            summary["kept_count"] = len(kept)
            summary["early_count"] = len(early)
            summary["early"] = [{"file": x[0], "departure": x[1]} for x in early]

            # 处理「当前月前3天开车」的发票：是否一并整合
            early_decision = args.early
            if early and early_decision == "ask":
                if sys.stdin.isatty():
                    ans = input(
                        f"\n发现当前月前3天开车的发票 {len(early)} 张："
                        + ", ".join(x[0] for x in early)
                        + "\n是否一并合并进这份 PDF？(y/N) "
                    ).strip().lower()
                    early_decision = "include" if ans in ("y", "yes", "是", "1") else "exclude"
                else:
                    # 非交互（自动化）环境：不擅自合并，交由用户/助手确认
                    early_decision = "exclude"
                    summary["needs_early_decision"] = True
                    summary["early_note"] = "存在当前月前3天开车的发票，默认未合并，请确认是否一并整合"

            if early and early_decision == "include":
                for f, _ in early:
                    shutil.copy(os.path.join(orig_folder, f), os.path.join(kept_folder, f))
                summary["early_included"] = True
                month_label = f"{month_label}_含月初"

            if not kept and not (early and early_decision == "include"):
                summary["detail"] = (
                    f"拉取到 {total} 封邮件，但无『开车时间在上月({prev_start.strftime('%Y-%m')})』"
                    + (f"且无『当前月前3天』" if early else "")
                    + "的发票可合并"
                )
                print(json.dumps(summary, ensure_ascii=False))
                return

        # 2) 合并
        summary["step"] = "merge"
        os.makedirs(os.path.join(work, "output"), exist_ok=True)
        out_pdf = os.path.join(work, "output", f"火车票发票合并_{month_label}.pdf")
        res = ticket_core.process_pdf_files(inv_folder, out_pdf)
        if not res["success"]:
            summary["detail"] = res["error"]
            print(json.dumps(summary, ensure_ascii=False))
            return
        summary["merged_count"] = res["count"]
        summary["order"] = res["order"]

        # 3) 发送
        summary["step"] = "send"
        if args.dry_run:
            summary["dry_run"] = True
            summary["sent_to"] = to_email
            summary["note"] = "dry-run：仅筛选+合并，未实际发送"
        else:
            send_pdf_smtp(settings, out_pdf, to_email, month_label)
            summary["sent_to"] = to_email
        summary["pdf_path"] = out_pdf
        summary["pdf_size"] = os.path.getsize(out_pdf)
        summary["ok"] = True
        summary["detail"] = f"已合并 {res['count']} 张" + ("" if args.dry_run else f"并发送至 {to_email}")
    except Exception as e:
        summary["detail"] = f"{type(e).__name__}: {e}"
        summary["trace"] = traceback.format_exc()
    finally:
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
