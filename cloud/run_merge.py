#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报销凭证归集 · 云电脑版（WorkBuddy 自动化调用 / 手动运行）

把邮箱附件里的【所有发票】与对应【水单 / 刷卡单】自动归集：
  - 拉取窗口内所有带附件邮件（BODY.PEEK 不标已读，按邮件分子目录，保留原文件名）
  - 分类：发票 / 水单 / 刷卡单（纯文本层，v1 无 OCR）
  - 按【金额 + 日期】自动配对：水单、刷卡单归到对应发票
  - 每组按固定顺序 发票 → 水单 → 刷卡单 生成独立 PDF
  - SMTP 发送（≤5 组多附件，否则 zip）

时间范围（用户每次可指定）：
  --days N                    近 N 天（默认 90）
  --from 2026-07-01 --to-date 2026-07-31   手动指定固定窗口
  --since-last-run            以上次成功运行的日期为起点（避免重复归集）

用法：
  python run_merge.py --to 同事@qq.com                       # 默认近 90 天
  python run_merge.py --to 同事@qq.com --from 2026-07-01 --to-date 2026-07-31
  python run_merge.py --to 同事@qq.com --days 30
  python run_merge.py --to 同事@qq.com --since-last-run
  python run_merge.py --to 同事@qq.com --dry-run             # 只处理不发送
  python run_merge.py --to 同事@qq.com --include-unmatched   # 未匹配凭证也单出 Z 桶
  python run_merge.py --to 同事@qq.com --copy-out            # 同时复制到 output/ 供预览

输出：末尾打印一行 JSON 汇总（供自动化读取汇报）。
"""

import os
import sys
import json
import argparse
import shutil
import tempfile
import traceback
from datetime import datetime, timedelta

# ---- 路径：脚本在 cloud/ 下；仓库根 = 上级目录；cloud 本身加入 path ----
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, CLOUD_DIR)
os.chdir(REPO_ROOT)

import config
import email_handler
import classify
import group
import build_pdf


def load_settings():
    p = os.path.join(CLOUD_DIR, "mail_settings.json")
    if not os.path.exists(p):
        raise FileNotFoundError(
            f"缺少凭据文件 {p}（请从 mail_settings.example.json 复制并填入真实授权码）")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


STATE_PATH = os.path.join(CLOUD_DIR, ".state.json")


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(d):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 状态保存失败: {e}", file=sys.stderr)


def resolve_window(args):
    """返回 (date_from, date_to, label)。date_to 含当天。"""
    today = datetime.now()
    if args.from_date and args.to_date:
        return args.from_date, args.to_date, f"{args.from_date}_{args.to_date}"
    if args.since_last_run:
        st = load_state()
        last = st.get("last_window_from")
        if last:
            return last, today.strftime("%Y-%m-%d"), f"since_{last}"
        # 退化：无记录则用默认天数
    days = args.days or config.REIMBURSE.get("default_days", 90)
    df = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    return df, today.strftime("%Y-%m-%d"), f"近{days}天"


def send_files_smtp(settings, paths, to_email, subject, body_text):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.mime.text import MIMEText

    smtp_server = settings.get("smtp_server", "smtp.qq.com")
    smtp_port = int(settings.get("smtp_port", 465))
    user = settings["email_address"]
    pwd = settings["password"]

    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    for p in paths:
        with open(p, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(p))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(p)}"'
        msg.attach(part)

    with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=90) as s:
        s.login(user, pwd)
        s.send_message(msg, to_addrs=[to_email])
    return True


def make_summary_body(grouping, window_label):
    lines = ["报销凭证归集结果：", ""]
    lines.append(f"窗口：{window_label}")
    lines.append(f"发票组：{grouping['stats']['group_count']} 个 "
                 f"（含凭证 {grouping['stats']['group_with_support']} / 仅发票 {grouping['stats']['invoice_only']}）")
    if grouping["ambiguous_groups"]:
        lines.append(f"⚠ 歧义组（同额同日多张发票，凭证归属待确认）：{', '.join(grouping['ambiguous_groups'])}")
    if grouping["unmatched_support"]:
        lines.append(f"⚠ 未匹配凭证：{len(grouping['unmatched_support'])} 份")
    if grouping["needs_review"]:
        lines.append(f"⚠ 需复核（图片/扫描/无法判定）：{len(grouping['needs_review'])} 份")
    lines.append("")
    lines.append("分组清单：")
    for g in grouping["groups"]:
        sup = []
        if g["slips"]:
            sup.append(f"水单{len(g['slips'])}")
        if g["cards"]:
            sup.append(f"刷卡{len(g['cards'])}")
        tag = "[" + "/".join(sup) + "]" if sup else "[仅发票]"
        amb = " ⚠歧义" if g["ambiguous"] else ""
        lines.append(f"  {g['group_id']} {g['label']} {tag}{amb}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", help="接收邮箱（缺省读 mail_settings.json 的 default_recipient）")
    ap.add_argument("--days", type=int, default=None, help="近 N 天（默认 90）")
    ap.add_argument("--from", dest="from_date", help="开始日期 YYYY-MM-DD")
    ap.add_argument("--to-date", dest="to_date", help="结束日期 YYYY-MM-DD（含当天）")
    ap.add_argument("--since-last-run", action="store_true", help="以上次成功运行日期为起点")
    ap.add_argument("--dry-run", action="store_true", help="只拉取+分类+分组+合并并报告，不发送")
    ap.add_argument("--amount-tol", type=float, default=config.REIMBURSE.get("amount_tol", 0.01),
                    help="金额容差（元），默认 0.01")
    ap.add_argument("--day-window", type=int, default=config.REIMBURSE.get("day_window", 7),
                    help="凭证与发票日期邻近窗口（天），默认 7")
    ap.add_argument("--send-mode", choices=["auto", "zip", "multi"], default="auto",
                    help="发送方式：auto=≤5组多附件否则zip / zip / multi")
    ap.add_argument("--include-unmatched", action="store_true", help="未匹配凭证也单出 Z 桶")
    ap.add_argument("--copy-out", action="store_true", help="同时复制到已 gitignore 的 output/ 供预览")
    ap.add_argument("--json-out", help="把 JSON 汇总写到该路径")
    ap.add_argument("--show-ignored", action="store_true", help="汇总中列出被忽略(other)的附件")
    ap.add_argument("--max-emails", type=int, default=config.REIMBURSE.get("default_max_emails", 200),
                    help="单次最多处理邮件数")
    args = ap.parse_args()

    settings = load_settings()
    to_email = args.to or settings.get("default_recipient")
    if not to_email:
        raise ValueError("未指定接收邮箱：请加 --to 或在 mail_settings.json 配 default_recipient")

    date_from, date_to, window_label = resolve_window(args)
    work = tempfile.mkdtemp(prefix="reimburse_")
    out_dir = os.path.join(work, "output")
    os.makedirs(out_dir, exist_ok=True)

    summary = {"ok": False, "step": "", "detail": "",
               "window": {"date_from": date_from, "date_to": date_to, "label": window_label}}

    try:
        # 1) 拉取
        summary["step"] = "fetch"
        manifest, err_msg = email_handler.fetch_all_attachments(
            password=settings["password"], work_dir=work,
            email_address=settings["email_address"],
            date_from=date_from, date_to=date_to, max_emails=args.max_emails)
        if err_msg:
            summary["detail"] = err_msg
            print(json.dumps(summary, ensure_ascii=False))
            return
        summary["email_count"] = manifest["email_count"]
        summary["item_count"] = manifest["item_count"]

        # 2) 分类 + 字段抽取
        summary["step"] = "classify"
        docs = []
        for it in manifest["items"]:
            docs.append(classify.analyze_attachment(it, work, email_date=it.get("email_date")))

        cls = {"invoice": 0, "slip": 0, "card": 0, "other": 0, "needs_review": 0}
        for d in docs:
            cls[d["doc_type"]] = cls.get(d["doc_type"], 0) + 1
        summary["classified"] = cls

        # 2.1) 同邮件内 OFD/图片 与 PDF 同名 -> 视为同一凭证的副本，忽略（如 12306 同封邮件发 PDF+OFD）
        from collections import defaultdict
        by_email = defaultdict(list)
        for d in docs:
            by_email[d.get("email_idx")].append(d)
        for d in docs:
            if d.get("ext") == "ofd" or d.get("is_image"):
                stem = os.path.splitext(d.get("orig_name", ""))[0]
                for o in by_email.get(d.get("email_idx"), []):
                    if o is d:
                        continue
                    if o.get("ext") == "pdf" and os.path.splitext(o.get("orig_name", ""))[0] == stem:
                        d["doc_type"] = "other"
                        d.setdefault("flags", []).append("dup_of_pdf_in_email")
                        cls["needs_review"] = max(0, cls.get("needs_review", 0) - 1)
                        cls["other"] = cls.get("other", 0) + 1
                        break

        # 3) 分组
        summary["step"] = "group"
        grouping = group.group_documents(
            docs, amount_tol=args.amount_tol, day_window=args.day_window, allow_sum=True)
        summary["stats"] = grouping["stats"]

        # 4) 拼装 PDF
        summary["step"] = "build"
        built = build_pdf.build_all(grouping, out_dir, include_unmatched=args.include_unmatched)
        summary["group_pdfs"] = [os.path.basename(p) for p in built["group_pdfs"]]
        summary["review_pdf"] = os.path.basename(built["review_pdf"]) if built["review_pdf"] else None
        if built["unmatched_pdf"]:
            summary["unmatched_pdf"] = os.path.basename(built["unmatched_pdf"])

        # 组明细（供汇报）
        groups_info = []
        for g in grouping["groups"]:
            groups_info.append({
                "group_id": g["group_id"], "label": g["label"],
                "amount": g["invoice"].get("amount"),
                "date": g["invoice"].get("match_date") or g["invoice"].get("date"),
                "has_support": g["has_support"], "ambiguous": g["ambiguous"],
                "slips": [s.get("orig_name") for s in g["slips"]],
                "cards": [c.get("orig_name") for c in g["cards"]],
                "invoice_name": g["invoice"].get("orig_name"),
            })
        summary["groups"] = groups_info
        summary["unmatched_support"] = [s.get("orig_name") for s in grouping["unmatched_support"]]
        summary["needs_review"] = [s.get("orig_name") for s in grouping["needs_review"]]
        if args.show_ignored:
            summary["ignored"] = [s.get("orig_name") for s in grouping["other"]]

        # 是否需要人工决策（条件确认）
        needs_decision = (
            grouping["stats"]["ambiguous"] > 0
            or len(grouping["unmatched_support"]) > 0
            or len(grouping["needs_review"]) > 0
            or grouping["stats"]["group_count"] == 0
        )
        summary["needs_decision"] = needs_decision

        # 5) 发送 or dry-run
        summary["step"] = "send"
        send_paths = list(built["group_pdfs"])
        if built["review_pdf"]:
            send_paths.append(built["review_pdf"])
        if built["unmatched_pdf"]:
            send_paths.append(built["unmatched_pdf"])

        if args.dry_run:
            summary["dry_run"] = True
            summary["note"] = "dry-run：已拉取/分类/分组/合并，未发送"
        else:
            if not send_paths:
                summary["detail"] = "无可导出的 PDF（窗口内无可归集凭证）"
            else:
                subject = f"报销凭证归集_{window_label}_{datetime.now().strftime('%Y%m%d')}"
                body = make_summary_body(grouping, window_label)
                send_files_smtp(settings, send_paths, to_email, subject, body)
                summary["sent_to"] = to_email

        # 复制到 output/ 预览（gitignored）
        if args.copy_out:
            out_repo = os.path.join(REPO_ROOT, "output")
            os.makedirs(out_repo, exist_ok=True)
            for p in send_paths:
                shutil.copy(p, os.path.join(out_repo, os.path.basename(p)))
            summary["copied_to"] = "output/"

        # 更新状态（仅正式发送成功时）
        if not args.dry_run and send_paths:
            st = load_state()
            st["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st["last_window_from"] = date_from
            save_state(st)

        summary["pdf_count"] = len(send_paths)
        summary["ok"] = True
        summary["detail"] = (
            f"发票组 {grouping['stats']['group_count']} 个"
            + ("" if args.dry_run else f"，已发送至 {to_email}")
        )
    except Exception as e:
        summary["detail"] = f"{type(e).__name__}: {e}"
        summary["trace"] = traceback.format_exc()
    finally:
        if args.json_out:
            try:
                with open(args.json_out, "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
