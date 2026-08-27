#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报销归集自测 / 校准工具（cloud 版）

用途：
  把真实样例 PDF（发票/水单/刷卡单/无关附件）放进 cloud/tests/fixtures/ 后运行本脚本，
  即可看到分类与字段抽取的混淆情况，用于校准关键词与正则，提升准确率。

用法：
  python selftest.py                # 扫描 fixtures/ 下所有 PDF + 图片，打印分类/抽取/分组结果
  python selftest.py --build        # 额外把分组结果生成到 fixtures/_out/

注意：
  - fixtures/ 已被 .gitignore 忽略，样例不会入库。
  - v1 无 OCR，图片型会进入 needs_review（仅供人工核对）。
"""

import os
import sys
import glob
import json
import argparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, CLOUD_DIR)

import classify
import group
import build_pdf

FIXTURES = os.path.join(CLOUD_DIR, "tests", "fixtures")


def collect():
    files = []
    for ext in ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff", "*.webp", "*.ofd"):
        files += glob.glob(os.path.join(FIXTURES, "**", ext), recursive=True)
    return sorted(set(files))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="额外生成分组 PDF 到 fixtures/_out/")
    ap.add_argument("--amount-tol", type=float, default=0.01)
    ap.add_argument("--day-window", type=int, default=7)
    args = ap.parse_args()

    files = collect()
    if not files:
        print(f"[INFO] fixtures 目录为空：{FIXTURES}")
        print("[INFO] 请把真实样例 PDF/图片放进去，再运行本脚本校准。")
        print("[INFO] 建议：发票、水单、刷卡单 各 1 份 + 1 封三者齐全的邮件 + 2~3 份无关附件。")
        return

    print(f"[INFO] 共 {len(files)} 个测试文件\n")
    docs = []
    for f in files:
        item = {
            "email_idx": 0, "orig_name": os.path.basename(f),
            "saved_path": f, "ext": f.rsplit(".", 1)[-1].lower(),
            "is_image": f.rsplit(".", 1)[-1].lower() in ("png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp"),
            "email_date": None, "sha1": "", "size": os.path.getsize(f),
            "subject": "", "sender": "",
        }
        rec = classify.analyze_attachment(item, os.path.dirname(f) or ".", email_date=None)
        docs.append(rec)
        print(f"  {os.path.basename(f):32s} -> {rec['doc_type']:12s} "
              f"金额={rec.get('amount')} 日期={rec.get('date')} 复核={rec.get('reason','')}")

    print("\n[分组结果]")
    g = group.group_documents(docs, amount_tol=args.amount_tol, day_window=args.day_window)
    print("  stats:", json.dumps(g["stats"], ensure_ascii=False))
    for grp in g["groups"]:
        sup = ([f"水单×{len(grp['slips'])}"] if grp["slips"] else []) + \
              ([f"刷卡×{len(grp['cards'])}"] if grp["cards"] else [])
        print(f"  {grp['group_id']} {grp['label']} [{(', '.join(sup) or '仅发票')}]"
              + (" ⚠歧义" if grp["ambiguous"] else ""))
    if g["unmatched_support"]:
        print(f"  ⚠ 未匹配凭证: {[s['orig_name'] for s in g['unmatched_support']]}")
    if g["needs_review"]:
        print(f"  ⚠ 需复核: {[s['orig_name'] for s in g['needs_review']]}")

    if args.build:
        out = os.path.join(FIXTURES, "_out")
        built = build_pdf.build_all(g, out, include_unmatched=True)
        print(f"\n[已生成] {built['group_pdfs']} + 复核={built['review_pdf']} -> {out}")


if __name__ == "__main__":
    main()
