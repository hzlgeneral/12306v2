#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件处理模块"""

import os
import re
import email
import imaplib
import zipfile
import hashlib
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr

from config import EMAIL_CONFIG, EMAIL_KEYWORDS, FOLDERS, EMAIL_SEARCH, SENDER_WHITELIST

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