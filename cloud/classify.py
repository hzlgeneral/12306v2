#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报销凭证分类与字段抽取（cloud 版，v1 无 OCR，纯文本层）

文档类型：
  invoice : 发票（增值税电子发票 / 全电发票 / 铁路电子客票 等）
  slip    : 水单（银行电子回单 / 汇款凭证 / 入账回执）
  card    : 刷卡单（POS 签购单 / 消费凭条 / 银联交易凭证）
  other   : 明显非报销凭证（验证码/营销/广告/账单 等），直接忽略
  needs_review : 图片型、扫描件或无法判定，交由人工核对

抽取字段：amount（金额/元，float）、date（文档日期 date）、
         match_date（用于配对的水单/刷卡单日期）、invoice_no（发票号）。
"""

import os
import re
from datetime import datetime, date


# ---------- 关键词打分表 ----------
# weight: 强信号 3 / 中信号 1
KEYWORDS = {
    "invoice": {
        "发票号码": 3, "电子发票": 3, "全电发票": 3, "数电发票": 3,
        "增值税": 3, "价税合计": 3, "购买方": 3, "销售方": 3,
        "普通发票": 3, "专用发票": 3, "电子普通发票": 3, "铁路电子客票": 3,
        "发票代码": 3, "校验码": 2, "开票日期": 1, "纳税人识别号": 2,
        "机器编号": 1, "金额（小写）": 2, "收款人": 1, "开票人": 1,
        "税额": 2, "不含税": 1, "税率": 1,
    },
    "slip": {
        "电子回单": 3, "网上银行电子回单": 3, "回单编号": 3, "客户回单": 3,
        "业务回单": 3, "入账回执": 3, "转账凭证": 3, "汇款凭证": 3,
        "电子缴税": 3, "付款人": 2, "收款人": 2, "付款方": 2, "收款方": 2,
        "开户银行": 2, "开户行": 2, "交易流水": 2, "流水号": 2,
        "用途": 1, "附言": 1, "汇款": 1, "交易时间": 1, "记账日期": 1,
        "借贷方": 1, "账号": 1,
    },
    "card": {
        "签购单": 3, "pos签购单": 3, "pos": 2, "商户名称": 3, "商户编号": 3,
        "持卡人": 3, "持卡人签名": 3, "消费凭条": 3, "交易凭证": 3,
        "银联": 2, "刷卡消费": 3, "终端号": 2, "批次号": 2, "授权号": 2,
        "凭证号": 2, "参考号": 2, "发卡行": 1, "收单行": 1,
        "交易类型": 1, "卡号": 1, "消费金额": 2, "受理方": 1,
    },
}

# 明确非报销凭证（出现且无任何正向信号 -> other）
NEGATIVE = ["验证码", "营销", "广告", "推广", "订阅", "对账单", "账单"]

# 金额标签（优先取这些标签后的金额）
AMOUNT_LABELS = ["价税合计", "合计金额", "交易金额", "消费金额", "实付金额",
                 "付款金额", "汇款金额", "应收金额", "小写金额", "金额（小写）",
                 "消费金额（元）", "金额"]

# 日期标签（优先取这些标签后的日期）
DATE_LABELS = ["开票日期", "交易日期", "付款日期", "消费日期", "记账日期",
               "日期", "业务日期", "发生日期"]


def pdf_to_text(path):
    """读取 PDF 文本层；返回 (text, scanned)。scanned=True 表示文本极少（疑似扫描件）。"""
    try:
        import pymupdf
        doc = pymupdf.open(path)
        if len(doc) == 0:
            doc.close()
            return "", True
        parts = []
        needs_pass = False
        for page in doc:
            try:
                t = page.get_text("text")
            except Exception:
                t = ""
            if "所有者" in t or "加密" in t[:50]:
                needs_pass = True
            parts.append(t)
            for annot in page.annots() or []:
                if hasattr(annot, "info") and annot.info.get("content"):
                    parts.append(annot.info["content"])
        doc.close()
        text = "\n".join(parts)
        # 文本量极少（如每张仅几个字符）判定为扫描件/图片型
        scanned = (len(text.strip()) < 25)
        return text, (scanned or needs_pass)
    except Exception as e:
        return "", True


def _clean_num(s):
    s = s.replace(",", "").replace("，", "").replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None


def extract_amount(text):
    """抽取金额（元）。优先带标签的金额，否则取 ¥ 金额 / 带两位小数金额。"""
    if not text:
        return None
    # 1) 带标签的金额
    for label in AMOUNT_LABELS:
        # 标签后可跨换行，取其后 40 字符内的第一个金额
        m = re.search(re.escape(label) + r"[\s:：]*([0-9][0-9,]{0,15}(?:\.[0-9]{1,2})?)",
                      text, re.I)
        if m:
            v = _clean_num(m.group(1))
            if v is not None:
                return round(v, 2)
    # 2) ¥ / ￥ 后的金额
    for sym in ("¥", "￥", "RMB", "rmb"):
        m = re.search(re.escape(sym) + r"\s*([0-9][0-9,]{0,15}(?:\.[0-9]{1,2})?)", text)
        if m:
            v = _clean_num(m.group(1))
            if v is not None:
                return round(v, 2)
    # 3) 兜底：带两位小数的裸金额，取最大值（更接近“金额”）
    nums = re.findall(r"(?<![0-9])([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{2}))(?![0-9])", text)
    vals = [_clean_num(n) for n in nums]
    vals = [v for v in vals if v is not None]
    if vals:
        return round(max(vals), 2)
    return None


def _norm_year(d, ref_year=None):
    """MM月DD日 缺年份时，按参考年或当前年补全。"""
    y = ref_year or datetime.now().year
    try:
        return date(y, d.month, d.day)
    except Exception:
        return None


def extract_date(text, ref_year=None):
    """抽取文档日期（date）。优先带标签的日期，否则取第一个完整日期。返回 date 或 None。"""
    if not text:
        return None
    # 1) 带标签的日期
    for label in DATE_LABELS:
        m = re.search(
            re.escape(label) + r"[\s:：]*"
            r"(\d{4})[年\-/.\s]*(\d{1,2})[月\-/.\s]*(\d{1,2})?",
            text)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            da = int(m.group(3)) if m.group(3) else 1
            try:
                return date(y, mo, da)
            except Exception:
                pass
        # 仅有月日
        m2 = re.search(re.escape(label) + r"[\s:：]*(\d{1,2})[月\-/.\s]*(\d{1,2})[日]?", text)
        if m2:
            try:
                return _norm_year(date(2000, int(m2.group(1)), int(m2.group(2))), ref_year)
            except Exception:
                pass
    # 2) 完整日期 YYYY年MM月DD日 / YYYY-MM-DD / YYYY/MM/DD
    for pat in (r"(\d{4})[年\-/.\s]+(\d{1,2})[月\-/.\s]+(\d{1,2})",
                r"(\d{4})[年\-/.\s]+(\d{1,2})[月]"):
        m = re.search(pat, text)
        if m:
            y, mo = int(m.group(1)), int(m.group(2))
            da = int(m.group(3)) if m.lastindex >= 3 and m.group(3) else 1
            try:
                return date(y, mo, da)
            except Exception:
                pass
    # 3) 仅有月日
    m = re.search(r"(\d{1,2})[月\-/.\s]+(\d{1,2})[日]?", text)
    if m:
        try:
            return _norm_year(date(2000, int(m.group(1)), int(m.group(2))), ref_year)
        except Exception:
            pass
    return None


def extract_invoice_no(text):
    """抽取发票号码（20 位/8-20 位数字）。"""
    if not text:
        return None
    m = re.search(r"(?:发票号码|发票代码|No\.?|NO\.?)\D{0,6}([0-9]{8,20})", text)
    if m:
        return m.group(1)
    m = re.search(r"\b([0-9]{20})\b", text)
    if m:
        return m.group(1)
    return None


def classify(text):
    """返回 (doc_type, score_detail)。doc_type ∈ invoice/slip/card/other/needs_review。"""
    if not text or not text.strip():
        return "needs_review", {"reason": "无文本"}
    tl = text.lower()
    scores = {"invoice": 0, "slip": 0, "card": 0}
    hits = {"invoice": [], "slip": [], "card": []}
    for cat, kws in KEYWORDS.items():
        for kw, w in kws.items():
            if kw.lower() in tl:
                scores[cat] += w
                hits[cat].append(kw)
    # 负向：出现且无任何正向信号 -> other
    neg = any(n in text for n in NEGATIVE)
    if neg and max(scores.values()) == 0:
        return "other", {"reason": "负向关键词且无可识别凭证特征", "neg": True}
    best = max(scores, key=scores.get)
    best_v = scores[best]
    second = sorted(scores.values(), reverse=True)[1]
    if best_v == 0:
        return "needs_review", {"reason": "无可识别凭证特征"}
    if best_v - second >= 1 and best_v >= 1:
        return best, {"score": scores, "hits": hits[best]}
    # 平局/弱信号：交人工
    return "needs_review", {"reason": "分类置信度不足", "score": scores}


def analyze_attachment(item, work_dir, email_date=None):
    """统一出口：对 manifest 中的一个 item 做分类与字段抽取。
    返回 dict（在 item 基础上追加 doc_type/amount/date/match_date/invoice_no/flags）。"""
    rec = dict(item)
    saved = item.get("saved_path")
    full = saved if os.path.isabs(saved) else os.path.join(work_dir, saved)
    rec["full_path"] = full
    rec.setdefault("flags", [])

    is_image = item.get("is_image") or item.get("ext") in ("png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp")
    is_ofd = item.get("ext") == "ofd"

    if is_image or is_ofd:
        rec["doc_type"] = "needs_review"
        rec["amount"] = None
        rec["date"] = None
        rec["match_date"] = None
        rec["invoice_no"] = None
        rec["flags"].append("image_or_ofd_no_ocr")
        rec["reason"] = "图片/OFD 型附件，v1 无 OCR，需人工核对"
        return rec

    text, scanned = pdf_to_text(full)
    rec["_text_len"] = len(text)
    if scanned:
        rec["doc_type"] = "needs_review"
        rec["amount"] = None
        rec["date"] = None
        rec["match_date"] = None
        rec["invoice_no"] = None
        rec["flags"].append("scanned")
        rec["reason"] = "疑似扫描件/加密，文本层不可读"
        return rec

    doc_type, detail = classify(text)
    rec["doc_type"] = doc_type
    rec["classify_detail"] = detail

    ref_year = None
    if email_date:
        try:
            ref_year = datetime.strptime(email_date, "%Y-%m-%d").year
        except Exception:
            pass

    amount = extract_amount(text)
    d = extract_date(text, ref_year)
    rec["amount"] = amount
    rec["date"] = d.isoformat() if d else None

    # 火车票子类：用开车日期作为配对日期（付款≈乘车）
    if doc_type == "invoice" and ("铁路电子客票" in text or "12306" in text or "电子客票" in text):
        try:
            import ticket_core
            dep = ticket_core.extract_departure_info(full)
            if dep:
                rec["departure"] = dep.isoformat()
                rec["match_date"] = dep.date().isoformat()
                rec["subtype"] = "train"
            else:
                rec["match_date"] = rec["date"]
        except Exception:
            rec["match_date"] = rec["date"]
    else:
        rec["match_date"] = rec["date"]

    rec["invoice_no"] = extract_invoice_no(text)
    return rec


if __name__ == "__main__":
    # 文本单测（无需 PDF）：验证分类与字段抽取逻辑
    samples = [
        ("增值税电子发票 发票号码 24417000000123456789 价税合计 ¥123.45 开票日期 2026年07月30日 购买方 销售方", "invoice"),
        ("网上银行电子回单 付款人 张三 收款人 李四 交易金额 ¥123.45 交易日期 2026-07-30 账号 6222", "slip"),
        ("POS签购单 商户名称 星巴克 持卡人 王五 消费金额 ¥123.45 交易日期 2026-07-30 终端号 001", "card"),
        ("您的验证码是 123456，请勿泄露", "other"),
        ("电子发票 价税合计 ¥88.00 开票日期 2026年08月01日", "invoice"),
    ]
    for txt, expect in samples:
        dt, det = classify(txt)
        amt = extract_amount(txt)
        dd = extract_date(txt)
        ok = "OK" if dt == expect else "XX"
        print(f"[{ok}] expect={expect:7s} got={dt:7s} amt={amt} date={dd}  {txt[:24]}")
