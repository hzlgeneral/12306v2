#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报销凭证 PDF 拼装（cloud 版，v1 无 OCR）。

- 用 pymupdf.insert_pdf 矢量直拼（保留文本层、体积小、可搜索）
- 图片型附件作为图片页插入留存（不丢信息）
- 组内顺序固定：发票 → 水单（按日期）→ 刷卡单（按日期）
- 放弃旧 render-to-image 拼版（位图不可搜索、体积大、质量降）
"""

import os
from datetime import datetime, date


A4 = (595.276, 841.890)  # pt


def _append_pdf(out, src_path):
    if not os.path.exists(src_path):
        return 0
    try:
        src = __import__("pymupdf").open(src_path)
        n = src.page_count
        out.insert_pdf(src)
        src.close()
        return n
    except Exception as e:
        print(f"[WARN] 插入PDF失败 {src_path}: {e}")
        return 0


def _append_image(out, img_path):
    """图片作为一页 A4 等比居中插入，保留原始 JPEG 流。"""
    try:
        page = out.new_page(width=A4[0], height=A4[1])
        page.insert_image(__import__("pymupdf").Rect(0, 0, A4[0], A4[1]),
                          filename=img_path, keep_proportion=True)
        return 1
    except Exception as e:
        print(f"[WARN] 插入图片失败 {img_path}: {e}")
        return 0


def _safe_name(s):
    return "".join(c for c in s if c not in '/\\:*?"<>|').strip() or "未命名"


def _doc_to_pdf(group_doc, out):
    """把一份文档（发票/水单/刷卡单）追加进 out。返回插入页数。"""
    p = group_doc.get("full_path")
    if not p or not os.path.exists(p):
        return 0
    ext = (group_doc.get("ext") or "").lower()
    if ext in ("png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp"):
        return _append_image(out, p)
    if ext == "ofd":
        # OFD 无 OCR/v1 不可读：占位页说明
        pg = out.new_page(width=A4[0], height=A4[1])
        pg.insert_text((40, 60), f"[OFD 原件，v1 未解析] {group_doc.get('orig_name','')}",
                       fontsize=10)
        return 1
    return _append_pdf(out, p)


def build_group_pdf(group, out_dir):
    """生成单个发票组 PDF：发票 → 水单 → 刷卡单。返回路径或 None。"""
    import pymupdf
    inv = group["invoice"]
    inv_d = inv.get("match_date") or inv.get("date") or ""
    amt = inv.get("amount")
    amt_s = f"RMB{amt:.2f}" if amt is not None else "RMB0.00"
    name = f"{group['group_id']}_{_safe_name(str(inv_d))}_{amt_s}"
    if group["ambiguous"]:
        name += "_待复核"
    # 组内有几张水单/刷卡单标注
    nslip = len(group["slips"])
    ncard = len(group["cards"])
    if nslip:
        name += f"_水{nslip}"
    if ncard:
        name += f"_卡{ncard}"
    name += ".pdf"
    out_path = os.path.join(out_dir, name)

    out = pymupdf.open()
    _doc_to_pdf(inv, out)
    for s in group["slips"]:
        _doc_to_pdf(s, out)
    for c in group["cards"]:
        _doc_to_pdf(c, out)
    if out.page_count == 0:
        out.close()
        return None
    os.makedirs(out_dir, exist_ok=True)
    out.save(out_path, garbage=4, deflate=True)
    out.close()
    return out_path


def build_bucket_pdf(items, out_dir, bucket_name, title):
    """把 needs_review / other 类附件汇总成一份 PDF（图片插页、PDF 直拼）。"""
    import pymupdf
    if not items:
        return None
    out = pymupdf.open()
    # 封面说明
    cover = out.new_page(width=A4[0], height=A4[1])
    cover.insert_text((40, 60), title, fontsize=16)
    cover.insert_text((40, 100), f"共 {len(items)} 份（需人工核对或已忽略）", fontsize=11)
    empty = True
    for it in items:
        n = _doc_to_pdf(it, out)
        if n:
            empty = False
    if empty:
        # 全是不可读/占位
        pass
    out_path = os.path.join(out_dir, f"{bucket_name}.pdf")
    os.makedirs(out_dir, exist_ok=True)
    out.save(out_path, garbage=4, deflate=True)
    out.close()
    return out_path


def build_all(grouping, out_dir, include_unmatched=False):
    """生成所有组 PDF + 需复核桶。返回 {group_pdfs:[...], review_pdf, unmatched_pdf}。"""
    os.makedirs(out_dir, exist_ok=True)
    group_pdfs = []
    for g in grouping["groups"]:
        p = build_group_pdf(g, out_dir)
        if p:
            group_pdfs.append(p)

    review_pdf = build_bucket_pdf(
        grouping["needs_review"], out_dir, "Z_需复核",
        "需人工复核（图片/扫描件/无法判定）")

    unmatched_pdf = None
    if include_unmatched and grouping["unmatched_support"]:
        unmatched_pdf = build_bucket_pdf(
            grouping["unmatched_support"], out_dir, "Z_未匹配凭证",
            "未匹配到发票的水单/刷卡单")

    return {
        "group_pdfs": group_pdfs,
        "review_pdf": review_pdf,
        "unmatched_pdf": unmatched_pdf,
    }
