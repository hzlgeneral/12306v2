#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报销凭证分组（cloud 版）：按『金额 + 日期』把水单/刷卡单归到对应发票。

组内顺序固定：发票 → 水单（按日期）→ 刷卡单（按日期）。
边界处理：
  - 同额同日多张发票              -> 标 ambiguous（无法判定凭证归属）
  - 一笔发票对应多张水单/刷卡单   -> 子集和匹配（R3）
  - 仅发票（无凭证）             -> invoice_only（仍出独立 PDF）
  - 未匹配上的凭证               -> unmatched_support（可单出 Z 桶）
  - 图片/扫描/无法判定           -> needs_review（人工复核桶）
"""

from datetime import datetime, date


def _parse_date(v):
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return datetime.strptime(v[:10], "%Y-%m-%d").date()
        except Exception:
            return None
    return None


def _ddiff(a, b):
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None:
        return None
    return abs((da - db).days)


def _cost(s, inv, amount_tol, day_window):
    """支持凭证 s 与发票 inv 的匹配代价；不可匹配返回 None。"""
    ad = abs(float(s["amount"]) - float(inv["amount"]))
    if ad > amount_tol:
        return None
    dd = _ddiff(s.get("match_date"), inv.get("match_date"))
    pen = ad * 1000.0
    if dd is None:
        pen += day_window          # 缺日期：轻惩罚（仅靠金额）
    else:
        pen += min(dd, day_window)
    return pen


def _subset_sum(pairs, target, amount_tol, day_window, max_n=6):
    """在 pairs[(i, doc)] 中找子集，使其金额之和 ≈ target（容差 amount_tol）。
    返回 [(i, doc)] 或 None。简单回溯，规模小。"""
    target = float(target)
    pairs = [(i, d) for i, d in pairs if abs(float(d["amount"]) - target) <= max(50.0, target)]
    # 限定参与元素数量，避免爆炸
    if len(pairs) > max_n:
        pairs = sorted(pairs, key=lambda x: abs(float(x[1]["amount"]) - target))[:max_n]

    def rec(start, cur, cur_sum):
        if abs(cur_sum - target) <= amount_tol and cur:
            return cur[:]
        if start >= len(pairs):
            return None
        # 剪枝
        if cur_sum - target > amount_tol:
            return None
        # 选
        r = rec(start + 1, cur + [pairs[start]], cur_sum + float(pairs[start][1]["amount"]))
        if r:
            return r
        # 不选
        return rec(start + 1, cur, cur_sum)

    return rec(0, [], 0.0)


def _sort_key(doc):
    d = _parse_date(doc.get("match_date") or doc.get("date"))
    return (d or date(2099, 1, 1), float(doc.get("amount") or 0))


def group_documents(docs, amount_tol=0.01, day_window=7, allow_sum=True):
    invoices = [d for d in docs
                if d.get("doc_type") == "invoice" and d.get("amount") is not None]
    supports = [d for d in docs
                if d.get("doc_type") in ("slip", "card") and d.get("amount") is not None]
    needs_review = [d for d in docs if d.get("doc_type") == "needs_review"]
    others = [d for d in docs if d.get("doc_type") == "other"]

    # 每个发票一个组
    groups = []
    group_by_inv = {}
    for inv in invoices:
        g = {
            "invoice": inv,
            "slips": [],
            "cards": [],
            "ambiguous": False,
        }
        group_by_inv[id(inv)] = g
        groups.append(g)

    used = set()  # supports 索引

    def attach(g, s):
        if s.get("doc_type") == "slip":
            g["slips"].append(s)
        else:
            g["cards"].append(s)

    # R1：唯一精确匹配（金额+日期，仅一个候选发票）
    for i, s in enumerate(supports):
        if i in used:
            continue
        cands = [(j, _cost(s, inv, amount_tol, day_window))
                 for j, inv in enumerate(invoices) if _cost(s, inv, amount_tol, day_window) is not None]
        if not cands:
            continue
        cands.sort(key=lambda x: x[1])
        if len(cands) == 1 or (cands[1][1] - cands[0][1] > 1e-6):
            j = cands[0][0]
            attach(group_by_inv[id(invoices[j])], s)
            used.add(i)

    # R2：剩余支持凭证 -> 贪心归到代价最小的发票（含并列时取第一个）
    for i, s in enumerate(supports):
        if i in used:
            continue
        cands = [(j, _cost(s, inv, amount_tol, day_window))
                 for j, inv in enumerate(invoices) if _cost(s, inv, amount_tol, day_window) is not None]
        if not cands:
            continue
        cands.sort(key=lambda x: x[1])
        j = cands[0][0]
        attach(group_by_inv[id(invoices[j])], s)
        used.add(i)

    # R3：子集和 —— 仍无凭证的发票，尝试用多张未匹配凭证凑出发票金额
    unmatched = [(i, s) for i, s in enumerate(supports) if i not in used]
    if allow_sum and unmatched:
        for g in groups:
            if g["slips"] or g["cards"]:
                continue
            inv = g["invoice"]
            subset = _subset_sum(unmatched, inv["amount"], amount_tol, day_window)
            if subset:
                for i, s in subset:
                    attach(g, s)
                    used.add(i)
                unmatched = [(i, s) for i, s in unmatched if i not in used]

    # R4：未吸收凭证
    unmatched_support = [s for i, s in enumerate(supports) if i not in used]

    # 组内排序 + 歧义检测
    for g in groups:
        g["slips"].sort(key=_sort_key)
        g["cards"].sort(key=_sort_key)

    # 同额同日多张发票 -> 歧义（凭证归属无法判定）
    from collections import defaultdict
    key_map = defaultdict(list)
    for g in groups:
        inv = g["invoice"]
        k = (round(float(inv["amount"]), 2),
             _parse_date(inv.get("match_date") or inv.get("date")))
        if k[1] is not None:
            key_map[k].append(g)
    ambiguous_ids = []
    for k, gs in key_map.items():
        if len(gs) > 1:
            for g in gs:
                g["ambiguous"] = True
            ambiguous_ids = [id(g["invoice"]) for g in gs]

    # 输出整理
    def label_of(g):
        inv = g["invoice"]
        d = _parse_date(inv.get("match_date") or inv.get("date"))
        ds = d.strftime("%Y-%m-%d") if d else "无日期"
        amt = inv.get("amount")
        amt_s = f"RMB{amt:.2f}" if amt is not None else "RMB0.00"
        return f"{ds}_{amt_s}"

    out_groups = []
    for idx, g in enumerate(groups, 1):
        inv = g["invoice"]
        out_groups.append({
            "group_id": f"G{idx:02d}",
            "label": label_of(g),
            "invoice": inv,
            "slips": g["slips"],
            "cards": g["cards"],
            "ambiguous": g["ambiguous"],
            "has_support": bool(g["slips"] or g["cards"]),
        })

    # 组排序：按(发票日期, 金额)
    out_groups.sort(key=lambda g: (_sort_key(g["invoice"])[0], float(g["invoice"].get("amount") or 0)))

    return {
        "groups": out_groups,
        "unmatched_support": unmatched_support,
        "needs_review": needs_review,
        "other": others,
        "ambiguous_groups": [g["group_id"] for g in out_groups if g["ambiguous"]],
        "stats": {
            "invoice_count": len(invoices),
            "support_count": len(supports),
            "group_count": len(out_groups),
            "group_with_support": sum(1 for g in out_groups if g["has_support"]),
            "invoice_only": sum(1 for g in out_groups if not g["has_support"]),
            "unmatched_support": len(unmatched_support),
            "needs_review": len(needs_review),
            "other": len(others),
            "ambiguous": len([g for g in out_groups if g["ambiguous"]]),
        },
    }


if __name__ == "__main__":
    # 分组逻辑单测
    def mk(dt, t, amt, **kw):
        d = {"doc_type": t, "amount": amt, "date": dt,
             "match_date": kw.get("match_date", dt), "full_path": f"{t}_{dt}_{amt}.pdf",
             "orig_name": f"{t}_{dt}_{amt}.pdf"}
        return d

    docs = [
        mk("2026-07-30", "invoice", 123.45),
        mk("2026-07-30", "slip", 123.45, match_date="2026-07-30"),
        mk("2026-07-30", "card", 123.45, match_date="2026-07-30"),
        mk("2026-08-01", "invoice", 88.0),
        mk("2026-08-02", "slip", 50.0, match_date="2026-08-02"),
        mk("2026-08-02", "slip", 38.0, match_date="2026-08-02"),  # 子集和=88
    ]
    res = group_documents(docs)
    print("stats:", res["stats"])
    for g in res["groups"]:
        print(g["group_id"], g["label"], "amb=", g["ambiguous"],
              "支持:", [s["doc_type"] for s in g["slips"] + g["cards"]])
    print("unmatched:", [s["orig_name"] for s in res["unmatched_support"]])
