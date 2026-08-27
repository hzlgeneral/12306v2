#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件处理模块"""

import os
import re
import json
import email
import imaplib
import zipfile
import tempfile
import hashlib
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr

from config import EMAIL_CONFIG, EMAIL_KEYWORDS, FOLDERS, EMAIL_SEARCH, SENDER_WHITELIST, ATTACH_EXT

_processed_hashes = set()

def log(msg): print(f"[INFO] {msg}")
def err(msg): print(f"[ERROR] {msg}")

def decode_str(val):
    if not val: return ""
    parts = decode_header(val)
    result = []
    for p, c in parts:
        if isinstance(p, bytes):
            try: result.append(p.decode(c) if c else p.decode('utf-8', errors='ignore'))
            except: result.append(p.decode('utf-8', errors='ignore'))
        else: result.append(str(p))
    return ''.join(result)

def has_keywords(text, kws=EMAIL_KEYWORDS):
    if not text: return False
    t = text.lower()
    return any(k.lower() in t for k in kws)

def is_allowed(sender, wl=SENDER_WHITELIST):
    if not wl: return True
    s = sender.lower()
    return any(s.endswith(w.lower()) if w.startswith('@') else s == w.lower() for w in wl)

def pdf_hash(path):
    try:
        import fitz
        doc = fitz.open(path)
        txt = "".join(p.get_text("text") for p in doc)
        doc.close()
        return hashlib.md5(txt.encode()).hexdigest()
    except: return None

def is_dup(path):
    h = pdf_hash(path)
    if not h: return False
    if h in _processed_hashes: return True
    _processed_hashes.add(h)
    return False

def scan_existing(folder):
    global _processed_hashes
    _processed_hashes = set()
    if not os.path.exists(folder): return
    for f in os.listdir(folder):
        if f.lower().endswith('.pdf'):
            h = pdf_hash(os.path.join(folder, f))
            if h: _processed_hashes.add(h)
    log(f"已有 {len(_processed_hashes)} 个PDF")

def extract_info(text):
    """提取火车票信息"""
    info = {'from': None, 'to': None, 'time': None, 'train': None}
    if not text: return info
    
    # 提取车次
    m = re.search(r'([GDCZTKYTL]\d{1,4})', text, re.I)
    if m: info['train'] = m.group(1).upper()
    
    # 提取车站
    m = re.search(r'([\u4e00-\u9fa5]{2,8})\s*[→\->]+\s*([\u4e00-\u9fa5]{2,8})', text)
    if m: info['from'], info['to'] = m.group(1).strip(), m.group(2).strip()
    
    if not info['from']:
        m = re.search(r'(?:发站|出发站|乘车站)[：:\s]*([\u4e00-\u9fa5]{2,8})', text)
        if m: info['from'] = m.group(1).strip()
    if not info['to']:
        m = re.search(r'(?:到站|到达站)[：:\s]*([\u4e00-\u9fa5]{2,8})', text)
        if m: info['to'] = m.group(1).strip()
    
    # 提取开车时间 - 多种格式
    # 关键：12306 电子客票中，出发日期与“HH:MM开”之间常夹有其他文字（如
    # “电子发票（铁路电子客票）”），因此日期与时间之间允许出现任意字符，
    # 否则会把开车时间提取成 None（回退成当前时间戳）。
    patterns = [
        # 出发日期(年-月-日) + 开车时间(HH:MM开)，中间允许夹其他文字
        r'(\d{4})年(\d{1,2})月(\d{1,2})日[\s\S]{0,60}?(\d{1,2}):(\d{2})\s*开',
        r'(\d{1,2})月(\d{1,2})日[\s\S]{0,60}?(\d{1,2}):(\d{2})\s*开',
        # 开车时间 标签形式
        r'开车时间[：:][\s\S]{0,30}?(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[\s\S]{0,20}?(\d{1,2}):(\d{2})',
        r'开车时间[：:][\s\S]{0,20}?(\d{1,2})月(\d{1,2})日[\s\S]{0,20}?(\d{1,2}):(\d{2})',
        # 兜底：日期与时间紧邻（无中间文字）的通用格式
        r'(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[日]?\s*(\d{1,2}):(\d{2})',
        r'(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})',
        r'(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[日]?\s*(\d{1,2})点(\d{1,2})分',
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                g = m.groups()
                if len(g) == 5:
                    info['time'] = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]))
                elif len(g) == 4:
                    if int(g[0]) > 12:  # 第一个是年份
                        info['time'] = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), 0)
                    else:  # 月日时分
                        info['time'] = datetime(datetime.now().year, int(g[0]), int(g[1]), int(g[2]), int(g[3]))
                if info['time']:
                    log(f"  提取时间: {info['time']}")
                    break
            except:
                continue
    
    return info

def gen_name(info):
    parts = []
    if info.get('from') and info.get('to'):
        parts.append(re.sub(r'[\\/:*?"<>|]', '', f"{info['from']}-{info['to']}"))
    elif info.get('train'): parts.append(info['train'])
    
    if info.get('time'): parts.append(info['time'].strftime('%Y%m%d_%H%M'))
    else: parts.append(datetime.now().strftime('%Y%m%d_%H%M%S'))
    return '_'.join(parts) + '.pdf'

def pdf_text(path):
    try:
        import fitz
        doc = fitz.open(path)
        txt = ""
        for p in doc:
            txt += p.get_text("text")
            for annot in p.annots() or []:
                if hasattr(annot, "info") and annot.info.get("content"):
                    txt += annot.info["content"] + "\n"
        doc.close()
        return txt
    except: return ""

def connect(pwd):
    try:
        log(f"连接 {EMAIL_CONFIG['imap_server']}...")
        m = imaplib.IMAP4_SSL(EMAIL_CONFIG['imap_server'], EMAIL_CONFIG['imap_port'])
        m.login(EMAIL_CONFIG['email_address'], pwd or EMAIL_CONFIG.get('password', ''))
        m.select('INBOX')
        log("登录成功")
        return m
    except Exception as e: err(f"连接失败: {e}"); return None

def search_emails(mail, date_from=None, date_to=None):
    """搜索邮件 - 支持日期范围筛选"""
    try:
        # IMAP日期格式: 01-Jan-2025 (必须大写月份)
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        def format_date(d):
            return f'{d.day:02d}-{month_names[d.month-1]}-{d.year}'
        
        criteria_list = []
        
        if date_from:
            try:
                d = datetime.strptime(date_from, '%Y-%m-%d')
                criteria_list.append(f'SINCE {format_date(d)}')
            except:
                err(f"无效的开始日期: {date_from}")
        
        if date_to:
            try:
                d = datetime.strptime(date_to, '%Y-%m-%d')
                # 包含结束日期当天
                criteria_list.append(f'BEFORE {format_date(d + timedelta(days=1))}')
            except:
                err(f"无效的结束日期: {date_to}")
        
        # 组合搜索条件
        if criteria_list:
            search_criteria = ' '.join(criteria_list)
        else:
            d = datetime.now() - timedelta(days=30)
            search_criteria = f'SINCE {format_date(d)}'
        
        log(f"IMAP搜索: {search_criteria}")
        
        status, ids = mail.search(None, search_criteria)
        if status != 'OK':
            err("搜索失败")
            return []
        
        id_list = ids[0].split()
        log(f"日期范围内共 {len(id_list)} 封邮件")
        
        # 筛选符合条件的邮件
        matched = []
        max_mail = EMAIL_SEARCH.get('max_emails', 50)
        
        for eid in reversed(id_list):
            if len(matched) >= max_mail: break
            try:
                status, data = mail.fetch(eid, '(RFC822)')
                if status != 'OK': continue
                
                msg = email.message_from_bytes(data[0][1])
                sender = parseaddr(msg.get('From', ''))[1]
                subj = decode_str(msg.get('Subject', ''))
                
                if is_allowed(sender) and has_keywords(subj):
                    matched.append(eid)
                    log(f"匹配: {subj}")
            except: continue
        
        log(f"找到 {len(matched)} 封相关邮件")
        return matched
    except Exception as e: 
        err(f"搜索失败: {e}")
        return []

def get_content(mail, eid):
    body, atts = "", []
    try:
        status, data = mail.fetch(eid, '(RFC822)')
        if status != 'OK': return body, atts
        
        msg = email.message_from_bytes(data[0][1])
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get('Content-Disposition', ''))
            
            if 'attachment' in cd:
                fn = part.get_filename()
                if fn:
                    fn = decode_str(fn)
                    data = part.get_payload(decode=True)
                    if data: atts.append((fn, data)); log(f"  附件: {fn}")
            elif ct in ['text/plain', 'text/html']:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body += payload.decode(charset, errors='ignore') + "\n"
                except: pass
    except Exception as e: err(f"获取内容失败: {e}")
    return body, atts

def extract_zip(path, to):
    files = []
    try:
        with zipfile.ZipFile(path, 'r') as z:
            for name in z.namelist():
                if name.endswith('/'): continue
                if name.lower().endswith('.ofd'): log(f"  跳过OFD: {name}"); continue
                if not name.lower().endswith('.pdf'): continue
                
                target = os.path.join(to, os.path.basename(name))
                with z.open(name) as src, open(target, 'wb') as dst: dst.write(src.read())
                log(f"  解压: {name}")
                files.append(target)
    except Exception as e: err(f"解压失败: {e}")
    return files

def save_att(fn, data, folder, body=""):
    count = 0
    try:
        os.makedirs(folder, exist_ok=True)
        fl = fn.lower()
        
        if fl.endswith('.ofd'): log(f"跳过OFD: {fn}"); return 0
        
        if fl.endswith('.zip'):
            log(f"解压ZIP: {fn}")
            tz = os.path.join(folder, f"_temp_{fn}")
            with open(tz, 'wb') as f: f.write(data)
            files = extract_zip(tz, folder)
            if os.path.exists(tz): os.remove(tz)
            
            for p in files:
                if os.path.exists(p):
                    if is_dup(p): log(f"跳过重复: {p}"); os.remove(p); continue
                    info = extract_info(body + "\n" + pdf_text(p))
                    new_name = gen_name(info)
                    new_path = os.path.join(folder, new_name)
                    
                    c = 1
                    while os.path.exists(new_path):
                        new_name = f"{os.path.splitext(new_name)[0]}_{c}.pdf"
                        new_path = os.path.join(folder, new_name)
                        c += 1
                    
                    if new_path != p: os.rename(p, new_path)
                    log(f"保存: {new_name}")
                    count += 1
        
        elif fl.endswith('.pdf'):
            tp = os.path.join(folder, f"_temp_{fn}")
            with open(tp, 'wb') as f: f.write(data)
            
            if is_dup(tp): log(f"跳过重复: {fn}"); os.remove(tp); return 0
            
            info = extract_info(body + "\n" + pdf_text(tp))
            new_name = gen_name(info)
            new_path = os.path.join(folder, new_name)
            
            c = 1
            while os.path.exists(new_path):
                new_name = f"{os.path.splitext(new_name)[0]}_{c}.pdf"
                new_path = os.path.join(folder, new_name)
                c += 1
            
            os.rename(tp, new_path)
            log(f"保存: {new_name}")
            count = 1
    except Exception as e: err(f"保存失败: {e}")
    return count

def fetch_emails_and_download_attachments(password=None, target_folder=None, date_from=None, date_to=None):
    if target_folder is None: target_folder = FOLDERS.get('invoices', '发票')
    
    log("=" * 50)
    log(f"开始获取发票 | 日期: {date_from or '不限'} ~ {date_to or '不限'}")
    log("=" * 50)
    
    # 清空发票文件夹
    if os.path.exists(target_folder):
        for f in os.listdir(target_folder):
            if f.lower().endswith('.pdf'):
                try:
                    os.remove(os.path.join(target_folder, f))
                    log(f"已删除旧发票: {f}")
                except Exception as e:
                    log(f"删除失败 {f}: {e}")
        log(f"已清空发票文件夹: {target_folder}")
    else:
        os.makedirs(target_folder, exist_ok=True)
    
    scan_existing(target_folder)
    
    mail = connect(password)
    if not mail: return 0, "无法连接邮箱"
    
    try:
        ids = search_emails(mail, date_from, date_to)
        if not ids: return 0, "未找到相关邮件"
        
        total = 0
        for i, eid in enumerate(ids):
            log(f"\n处理 {i+1}/{len(ids)}...")
            body, atts = get_content(mail, eid)
            if not atts: log("  无附件"); continue
            for fn, data in atts: total += save_att(fn, data, target_folder, body)
        
        log(f"\n完成！保存 {total} 个PDF")
        return total, f"成功获取 {total} 个发票"
    except Exception as e: err(f"处理失败: {e}"); return 0, str(e)
    finally:
        try: mail.close(); mail.logout()
        except: pass


# ============================================================
# 报销凭证归集：全量附件拉取（cloud 版，追加函数，不改动上方旧逻辑）
# ============================================================

def _sanitize(name, maxlen=60):
    """清洗文件名中的非法字符，过长截断，保留原中文名。"""
    if not name:
        return "未命名"
    name = name.strip().replace("\u3000", " ")
    # 去除路径分隔与系统保留字符
    for ch in '/\\:*?"<>|\t\n\r':
        name = name.replace(ch, "_")
    name = name.strip().strip(".")
    if not name:
        name = "未命名"
    if len(name) > maxlen:
        base, ext = os.path.splitext(name)
        name = base[:maxlen - len(ext) - 1] + "_" + ext if ext else base[:maxlen]
    return name


def _ext_of(fn):
    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
    return ATTACH_EXT.get(ext, "other"), ext


def _sha1_bytes(data):
    return hashlib.sha1(data).hexdigest()


def _save_one_attachment(fn, data, subdir, seen, items, email_idx, email_date, subject, sender):
    """保存单个附件（含 ZIP 解内 PDF / 图片 / OFD）。返回落盘清单。"""
    saved = []
    fl = fn.lower()
    is_zip = fl.endswith(".zip")
    target = os.path.join(subdir, _sanitize(fn))
    i = 1
    while os.path.exists(target):
        base, ext = os.path.splitext(target)
        target = f"{base}_{i}{ext}"; i += 1
    with open(target, "wb") as f:
        f.write(data)
    sha = _sha1_bytes(data)

    if is_zip:
        # 解压内部 PDF（跳过 OFD）；图片不解压，原样保留 zip 的 PDF 内容
        try:
            with zipfile.ZipFile(target, "r") as z:
                for name in z.namelist():
                    if name.endswith("/"):
                        continue
                    nm = name.rsplit("/", 1)[-1]
                    kind, ext = _ext_of(nm)
                    if kind == "pdf":
                        try:
                            with z.open(name) as src:
                                inner = src.read()
                            inner_sha = _sha1_bytes(inner)
                            ipath = os.path.join(subdir, _sanitize(nm))
                            j = 1
                            while os.path.exists(ipath):
                                b2, e2 = os.path.splitext(ipath)
                                ipath = f"{b2}_{j}{e2}"; j += 1
                            with open(ipath, "wb") as d:
                                d.write(inner)
                            saved.append((ipath, inner_sha, "pdf", nm))
                        except Exception as e:
                            err(f"ZIP内PDF读取失败 {nm}: {e}")
                    elif kind in ("image", "ofd"):
                        # 原样保留在 zip 内：记录但不额外落盘（避免重复）
                        pass
        except Exception as e:
            err(f"ZIP解压失败 {fn}: {e}")
        # 删掉临时 zip 文件本身（里面的 PDF 已解压）
        try:
            os.remove(target)
        except Exception:
            pass
        for ipath, inner_sha, kind, nm in saved:
            if inner_sha not in seen:
                seen.add(inner_sha)
                items.append({
                    "email_idx": email_idx, "orig_name": nm, "saved_path": ipath,
                    "ext": "pdf", "is_image": False, "email_date": email_date,
                    "sha1": inner_sha, "size": os.path.getsize(ipath),
                    "subject": subject, "sender": sender,
                })
        return

    kind, ext = _ext_of(fn)
    if kind in ("pdf", "ofd", "image"):
        if sha not in seen:
            seen.add(sha)
            items.append({
                "email_idx": email_idx, "orig_name": fn, "saved_path": target,
                "ext": ext, "is_image": (kind == "image"), "email_date": email_date,
                "sha1": sha, "size": len(data),
                "subject": subject, "sender": sender,
            })
    else:
        # 不支持的附件类型：不纳入归集（如 docx/xlsx 等），仅记录跳过
        log(f"  跳过不支持的附件类型: {fn}")
        try:
            os.remove(target)
        except Exception:
            pass


def fetch_all_attachments(password=None, work_dir=None, email_address=None,
                          date_from=None, date_to=None, max_emails=200):
    """
    拉取『窗口内所有带附件邮件』的附件，用于报销凭证归集（全发票+水单+刷卡单）。

    与旧 fetch_emails_and_download_attachments 的区别：
      - 不限定 12306 发件/主题关键词，拉取任意带附件邮件；
      - 用 BODY.PEEK[] 取信，不会把收件箱标记为已读；
      - 按邮件分子目录保留【原始中文文件名】与邮件日期/主题/发件人；
      - 支持 PDF / ZIP(内PDF) / 图片 / OFD；字节 sha1 去重；
      - 写出 manifest.json 清单供下游分类/分组/合并。

    返回 (manifest, error_msg)：manifest 为 dict；失败返回 (None, msg)。
    """
    from email.utils import parsedate_to_datetime

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="reimburse_")
    inbox_dir = os.path.join(work_dir, "inbox")
    os.makedirs(inbox_dir, exist_ok=True)

    if email_address:
        EMAIL_CONFIG["email_address"] = email_address

    # 日期范围解析（沿用旧 search_emails 的 IMAP 格式）
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def fmt(d):
        return f'{d.day:02d}-{month_names[d.month - 1]}-{d.year}'

    criteria = []
    if date_from:
        try:
            criteria.append(f'SINCE {fmt(datetime.strptime(date_from, "%Y-%m-%d"))}')
        except Exception:
            err(f"无效开始日期: {date_from}")
    if date_to:
        try:
            d2 = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            criteria.append(f'BEFORE {fmt(d2)}')
        except Exception:
            err(f"无效结束日期: {date_to}")
    if not criteria:
        criteria.append(f'SINCE {fmt(datetime.now() - timedelta(days=30))}')
    search_criteria = " ".join(criteria)

    mail = connect(password)
    if not mail:
        return None, "无法连接邮箱"
    try:
        status, ids = mail.search(None, search_criteria)
        if status != "OK":
            return None, "搜索失败"
        id_list = ids[0].split()
        log(f"窗口内共 {len(id_list)} 封邮件，开始筛选带附件的（上限 {max_emails}）")

        seen = set()
        items = []
        emails_meta = []
        kept = 0
        for eid in reversed(id_list):
            if kept >= max_emails:
                break
            try:
                # BODY.PEEK[]：取信不置已读
                status, data = mail.fetch(eid, "(BODY.PEEK[])")
                if status != "OK" or not data or not data[0]:
                    continue
                raw = data[0][1] if isinstance(data[0], tuple) else None
                if not raw:
                    continue
                msg = email.message_from_bytes(raw)
                sender = parseaddr(msg.get("From", ""))[1]
                subj = decode_str(msg.get("Subject", "")) or "(无主题)"
                dt = parsedate_to_datetime(msg.get("Date"))
                email_date = dt.strftime("%Y-%m-%d") if dt else None

                atts = []
                for part in msg.walk():
                    cd = str(part.get("Content-Disposition", ""))
                    if "attachment" in cd or part.get_filename():
                        fn = part.get_filename()
                        if not fn:
                            continue
                        fn = decode_str(fn)
                        payload = part.get_payload(decode=True)
                        if payload:
                            atts.append((fn, payload))
                if not atts:
                    continue

                kept += 1
                subdir = os.path.join(inbox_dir, f"{kept:03d}_{_sanitize(subj)[:40]}")
                os.makedirs(subdir, exist_ok=True)
                emails_meta.append({
                    "idx": kept - 1, "date": email_date, "subject": subj,
                    "sender": sender, "dir": subdir, "attachment_count": len(atts),
                })
                for fn, payload in atts:
                    _save_one_attachment(fn, payload, subdir, seen, items,
                                         kept - 1, email_date, subj, sender)
                log(f"  邮件#{kept} [{email_date}] {subj} -> {len(atts)} 附件")
            except Exception as e:
                err(f"处理邮件失败: {e}")
                continue

        manifest = {
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "window": {"date_from": date_from, "date_to": date_to,
                       "search_criteria": search_criteria,
                       "max_emails": max_emails},
            "emails": emails_meta,
            "items": items,
            "item_count": len(items),
            "email_count": len(emails_meta),
        }
        with open(os.path.join(work_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        log(f"完成：{len(emails_meta)} 封邮件，{len(items)} 个待处理附件 -> {work_dir}/manifest.json")
        return manifest, None
    except Exception as e:
        err(f"拉取失败: {e}")
        return None, str(e)
    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass