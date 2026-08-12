#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火车票发票合并工具 - Windows 桌面版（单文件 GUI）

功能：
  1. 从邮箱拉取 12306 电子客票 PDF 发票（按日期范围）
  2. 将多张发票按「火车开车时间」排序后合并为一页/多页 PDF
  3. 「合并下载」= 拉取 + 合并 全自动一步完成
  4. 「发送到邮箱」= 把合并好的 PDF 通过 SMTP 发到指定邮箱
  5. 邮箱/授权码/收件人可保存至本地，下次自动填入
  6. 录入邮箱后自动匹配 IMAP/SMTP 服务器与端口，无需手填

依赖：tkinter(内置) / pymupdf / pillow / 项目根目录的 ticket_core.py、email_handler.py、config.py
打包：见同目录 build.bat（PyInstaller 一键生成 .exe）
"""

import os
import sys
import json
import webbrowser
import threading
import datetime
import calendar
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ---- 让程序既能单独运行，也能 import 到项目根目录的共享模块 ----
HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, 'frozen', False):
    ROOT = getattr(sys, '_MEIPASS', HERE)
else:
    ROOT = os.path.dirname(HERE)
for p in (HERE, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from ticket_core import process_pdf_files
from email_handler import fetch_emails_and_download_attachments

try:
    import config
    _CFG = config.EMAIL_CONFIG
except Exception:
    _CFG = {}

# ===================== 邮箱服务商自动匹配 =====================
# (imap_server, imap_port, smtp_server, smtp_port, provider_key)
PROVIDER_TABLE = {
    "qq.com":       ("imap.qq.com", 993, "smtp.qq.com", 465, "qq.com"),
    "foxmail.com":  ("imap.qq.com", 993, "smtp.qq.com", 465, "qq.com"),
    "163.com":      ("imap.163.com", 993, "smtp.163.com", 465, "163.com"),
    "126.com":      ("imap.126.com", 993, "smtp.126.com", 465, "126.com"),
    "yeah.net":     ("imap.yeah.net", 993, "smtp.yeah.net", 465, "yeah.net"),
    "139.com":      ("imap.139.com", 993, "smtp.139.com", 465, "139.com"),
    "sina.com":     ("imap.sina.com", 993, "smtp.sina.com", 25, "sina.com"),
    "sina.cn":      ("imap.sina.cn", 993, "smtp.sina.cn", 25, "sina.cn"),
    "aliyun.com":   ("imap.aliyun.com", 993, "smtp.aliyun.com", 465, "aliyun.com"),
    "gmail.com":    ("imap.gmail.com", 993, "smtp.gmail.com", 465, "gmail.com"),
    "outlook.com":  ("imap-mail.outlook.com", 993, "smtp-mail.outlook.com", 587, "outlook.com"),
    "hotmail.com":  ("imap-mail.outlook.com", 993, "smtp-mail.outlook.com", 587, "hotmail.com"),
    "live.com":     ("imap-mail.outlook.com", 993, "smtp-mail.outlook.com", 587, "live.com"),
    "icloud.com":   ("imap.mail.me.com", 993, "smtp.mail.me.com", 587, "icloud.com"),
}

# 各服务商的「如何获取授权码」帮助页（点击标签跳转）
AUTH_HELP = {
    "qq.com":      "https://service.mail.qq.com/cgi-bin/help?subtype=1&&id=28&&no=1001256",
    "foxmail.com": "https://service.mail.qq.com/cgi-bin/help?subtype=1&&id=28&&no=1001256",
    "163.com":     "https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e6f3b6c",
    "126.com":     "https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e6f3b6c",
    "gmail.com":   "https://myaccount.google.com/apppasswords",
    "outlook.com": "https://support.microsoft.com/zh-cn/account-billing-outlook-com-%E4%B8%AD%E4%BD%BF%E7%94%A8%E5%BA%94%E7%94%A8%E7%A8%8B%E5%BA%8F%E5%AF%86%E7%A0%81-085bd02b-a9e2-0b1e-0b8b-7a5e0b3e7e8e",
}
AUTH_HELP_DEFAULT = "https://service.mail.qq.com/cgi-bin/help?subtype=1&&id=28&&no=1001256"


def detect_servers(email):
    """根据邮箱域名自动匹配 IMAP/SMTP 服务器与端口。返回元组。"""
    email = (email or "").strip().lower()
    if "@" in email:
        domain = email.split("@")[-1]
        if domain in PROVIDER_TABLE:
            return PROVIDER_TABLE[domain]
        # 通用猜测：imap.<domain> / smtp.<domain>
        return (f"imap.{domain}", 993, f"smtp.{domain}", 465, domain)
    # 未填邮箱时的默认（QQ 最常见）
    return ("imap.qq.com", 993, "smtp.qq.com", 465, "qq.com")


# ---- 工作目录 ----
# 开发态：指向项目根目录（仓库根的 发票/ 在此）。
# 打包后：
#   Windows 用 exe 同级目录（持久、用户可控）；
#   macOS 的 --onefile 会把 exe 解压到 /private/var/folders 临时目录，
#   若仍用 exe 同级，发票/输出/设置会随进程退出被清除，
#   因此 macOS 改用用户「文稿」下的固定目录，保证数据持久、用户可见。
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        BASE_DIR = os.path.join(os.path.expanduser("~"), "Documents", "火车票发票合并")
    else:
        BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICE_DIR = os.path.join(BASE_DIR, "发票")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "火车票发票排列结果.pdf")
SETTINGS_PATH = os.path.join(BASE_DIR, "mail_settings.json")
for d in (INVOICE_DIR, OUTPUT_DIR):
    os.makedirs(d, exist_ok=True)

# ===================== 配色方案 =====================
C_BG = "#EEF2F8"          # 应用背景（浅蓝灰）
C_PANEL = "#FFFFFF"       # 面板背景（白）
C_HEADER = "#1F4E79"      # 顶部标题栏（深蓝）
C_HEADER2 = "#2E6DA4"     # 标题栏装饰条
C_TEXT = "#22303F"        # 主文字
C_SUB = "#6B7C8F"         # 次要文字
C_LINE = "#D6DEE8"        # 分隔线

C_PRIMARY = "#2563EB"     # 主按钮（蓝）
C_PRIMARY_H = "#1D4ED8"
C_TEAL = "#0D9488"        # 次按钮（青）
C_TEAL_H = "#0B7C72"
C_SUCCESS = "#16A34A"     # 成功/打开（绿）
C_SUCCESS_H = "#128A3C"
C_ACCENT = "#7C3AED"      # 发送按钮（紫）
C_ACCENT_H = "#6D28D9"

FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_SUB = ("Microsoft YaHei UI", 10)
FONT_LABEL = ("Microsoft YaHei UI", 10)
FONT_BTN = ("Microsoft YaHei UI", 10, "bold")
FONT_LOG = ("Consolas", 10)


# 彩色按钮：用 ttk.Button + 自定义样式，确保在 macOS(Aqua) 上背景色也能生效
# （经典 tk.Button 在 Mac 会被系统强制覆盖背景，导致白字配浅灰「看不清」）。
def _btn_style(bg, hover, fg="white"):
    st = ttk.Style()
    name = "TB_%s_%s.TButton" % (bg.replace("#", ""), hover.replace("#", ""))
    st.configure(name, background=bg, foreground=fg, font=FONT_BTN,
                 borderwidth=0, relief="flat", padding=(12, 6))
    st.map(name, background=[("active", hover), ("pressed", hover)],
           foreground=[("active", fg), ("pressed", fg)])
    return name

def make_button(parent, text, bg, hover, fg="white", w=22, h=2, cmd=None):
    return ttk.Button(parent, text=text, style=_btn_style(bg, hover, fg),
                      width=w, command=cmd)


# ===================== 日历选择器 =====================
class DatePicker(tk.Frame):
    """点击输入框或 📅 按钮，弹出日历选择日期，回填 'YYYY-MM-DD'。"""

    def __init__(self, master, label, var, **kw):
        super().__init__(master, **kw)
        self.var = var
        row = tk.Frame(self, bg=C_PANEL)
        row.pack(fill="x")
        tk.Label(row, text=label, bg=C_PANEL, fg=C_TEXT, font=FONT_LABEL).pack(side="left")
        self.entry = tk.Entry(row, textvariable=var, width=14, font=FONT_LABEL,
                              bg="#FBFDFF", fg=C_TEXT, relief="solid", bd=1,
                              highlightthickness=1, highlightcolor=C_PRIMARY,
                              highlightbackground=C_LINE)
        self.entry.pack(side="left", padx=4)
        # 点击输入框或 📅 都弹出日历
        self.entry.bind("<Button-1>", lambda e: self._popup())
        btn = ttk.Button(row, text="📅", width=3,
                        style=_btn_style(C_TEAL, C_TEAL_H, "white"),
                        command=self._popup)
        btn.pack(side="left", padx=2)

    def _popup(self):
        CalendarDialog(self, self.var)


class CalendarDialog(tk.Toplevel):
    def __init__(self, parent, var):
        super().__init__(parent)
        self.var = var
        self.title("选择日期")
        self.configure(bg=C_PANEL)
        self.resizable(False, False)
        try:
            y, m, d = [int(x) for x in var.get().split("-")]
            self.date = datetime.date(y, m, d)
        except Exception:
            self.date = datetime.date.today()
        self._build()
        self.transient(parent)
        self.grab_set()
        parent.update_idletasks()
        px = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        py = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_reqheight()) // 2, 0)
        self.geometry("+%d+%d" % (px, py))

    def _build(self):
        nav = tk.Frame(self, bg=C_HEADER)
        nav.pack(fill="x")
        ttk.Button(nav, text="◀", width=3, style=_btn_style(C_HEADER, C_HEADER2, "white"),
                   command=self._prev).pack(side="left", padx=6, pady=4)
        self.title_var = tk.StringVar(value=self.date.strftime("%Y年%m月"))
        tk.Label(nav, textvariable=self.title_var, bg=C_HEADER, fg="white",
                 font=FONT_BTN).pack(side="left", expand=True)
        ttk.Button(nav, text="▶", width=3, style=_btn_style(C_HEADER, C_HEADER2, "white"),
                   command=self._next).pack(side="right", padx=6, pady=4)

        wk = tk.Frame(self, bg=C_PANEL)
        wk.pack(fill="x", padx=6)
        for i, w in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            tk.Label(wk, text=w, bg=C_PANEL, fg=C_SUB, font=FONT_LABEL, width=4).grid(row=0, column=i)

        self.grid_frame = tk.Frame(self, bg=C_PANEL)
        self.grid_frame.pack(padx=6, pady=4)
        self._fill_grid()

        bottom = tk.Frame(self, bg=C_PANEL)
        bottom.pack(fill="x", pady=(0, 6))
        ttk.Button(bottom, text="今天", style=_btn_style(C_TEAL, C_TEAL_H, "white"),
                   command=self._today).pack(side="left", padx=14)
        ttk.Button(bottom, text="确定", style=_btn_style(C_SUCCESS, C_SUCCESS_H, "white"),
                   command=self._ok).pack(side="right", padx=14)

    def _fill_grid(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        year, month = self.date.year, self.date.month
        self.title_var.set("%d年%02d月" % (year, month))
        cal = calendar.monthcalendar(year, month)
        for r, week in enumerate(cal):
            for c, day in enumerate(week):
                if day == 0:
                    tk.Label(self.grid_frame, text="", width=4, bg=C_PANEL).grid(row=r, column=c)
                    continue
                if day == self.date.day:
                    st = _btn_style(C_PRIMARY, C_PRIMARY_H, "white")
                else:
                    st = _btn_style(C_PANEL, C_LINE, C_TEXT)
                ttk.Button(self.grid_frame, text=str(day), width=4, style=st,
                           command=lambda d=day: self._select(d)
                           ).grid(row=r, column=c, padx=1, pady=1)

    def _select(self, day):
        self.date = datetime.date(self.date.year, self.date.month, day)
        self._fill_grid()

    def _prev(self):
        y, m = self.date.year, self.date.month
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        self.date = datetime.date(y, m, 1)
        self._fill_grid()

    def _next(self):
        y, m = self.date.year, self.date.month
        m += 1
        if m == 13:
            y, m = y + 1, 1
        self.date = datetime.date(y, m, 1)
        self._fill_grid()

    def _today(self):
        self.date = datetime.date.today()
        self._fill_grid()

    def _ok(self):
        self.var.set(self.date.strftime("%Y-%m-%d"))
        self.destroy()


def load_settings(path):
    """读取本地保存的邮箱/SMTP 设置（不存在或损坏则返回空 dict）。"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_settings(data, path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def send_pdf_via_smtp(smtp_server, smtp_port, email_addr, auth_code, to_addr, pdf_path):
    """通过 SMTP 把合并好的 PDF 发出去。返回 (ok, message)。"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders
    if not all([smtp_server, email_addr, auth_code, to_addr, os.path.exists(pdf_path)]):
        return False, "缺少发信参数或PDF不存在"
    msg = MIMEMultipart()
    msg["From"] = email_addr
    msg["To"] = to_addr
    msg["Subject"] = "火车票发票合并结果"
    msg.attach(MIMEText("附件为按开车时间排序合并后的火车票发票PDF。", "plain", "utf-8"))
    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment",
                    filename="火车票发票排列结果.pdf")
    msg.attach(part)
    try:
        with smtplib.SMTP_SSL(smtp_server, int(smtp_port), timeout=30) as s:
            s.login(email_addr, auth_code)
            s.send_message(msg)
        return True, "已发送至 " + to_addr
    except Exception as e:
        return False, f"发信失败: {e}"


class RedirectText:
    """把 print 输出实时回显到文本框（线程安全）。"""
    def __init__(self, widget):
        self.widget = widget

    def write(self, s):
        if s:
            self.widget.after(0, self._append, s)

    def _append(self, s):
        self.widget.configure(state="normal")
        self.widget.insert("end", s)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("火车票发票合并工具")
        root.geometry("780x660")
        root.configure(bg=C_BG)
        root.minsize(740, 620)
        # 关键：macOS 默认 Aqua 主题会忽略 tk/ttk 按钮的自定义背景色，
        # 导致原本的白字被画在浅灰背景上而「看不清」。切到 clam 主题后背景色生效。
        try:
            ttk.Style().theme_use("clam")
        except Exception:
            pass
        try:
            root.iconbitmap()
        except Exception:
            pass

        # 启动时尝试载入已保存的设置
        self._saved = load_settings(SETTINGS_PATH)
        self._settings_saved = bool(self._saved)  # 已有存档则视为已保存，不再弹窗询问
        self.auth_url = AUTH_HELP_DEFAULT

        self._build_header(root)
        self._build_input(root)
        self._build_buttons(root)
        self._build_log(root)
        self._build_statusbar(root)

        self._old_stdout = None

    # ---------- 顶部标题栏 ----------
    def _build_header(self, parent):
        hdr = tk.Frame(parent, bg=C_HEADER, height=88)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Frame(hdr, bg=C_HEADER2, width=6).pack(side="left", fill="y")
        inner = tk.Frame(hdr, bg=C_HEADER)
        inner.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(inner, text="🚄  火车票发票合并工具", bg=C_HEADER,
                 fg="white", font=FONT_TITLE, anchor="w").pack(fill="x")
        tk.Label(inner, text="按开车时间自动排序 · 合并为单份 PDF · 支持邮件发送",
                 bg=C_HEADER, fg="#C9DCF0", font=FONT_SUB, anchor="w").pack(fill="x")
        tk.Label(inner, text="作者：何志亮", bg=C_HEADER, fg="#9FD0F0",
                 font=FONT_SUB, anchor="w").pack(fill="x")

    # ---------- 输入区 ----------
    def _build_input(self, parent):
        frm = tk.Frame(parent, bg=C_PANEL, bd=1, relief="solid")
        frm.pack(fill="x", padx=12, pady=(12, 6))

        title = "邮箱配置（仅用于从 12306 拉取发票并发信；可保存供下次自动填入）"
        if self._settings_saved:
            title += "  ✔ 已载入上次保存"
        tk.Label(frm, text=title, bg=C_PANEL, fg=C_HEADER,
                 font=("Microsoft YaHei UI", 11, "bold"), anchor="w")\
            .grid(row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 8))

        s = self._saved
        self.email_var = tk.StringVar(value=s.get("email", ""))
        self.pwd_var = tk.StringVar(value=s.get("password", ""))
        self.recipient_var = tk.StringVar(value=s.get("recipient", ""))
        self.autosend_var = tk.BooleanVar(value=bool(s.get("autosend", False)))
        self.dfrom_var = tk.StringVar()
        self.dto_var = tk.StringVar()

        def _lbl(t, r, c):
            tk.Label(frm, text=t, bg=C_PANEL, fg=C_TEXT, font=FONT_LABEL)\
                .grid(row=r, column=c, sticky="e", padx=(12, 4), pady=5)

        def _entry(var, w=34):
            e = tk.Entry(frm, textvariable=var, width=w, font=FONT_LABEL,
                         bg="#FBFDFF", fg=C_TEXT, relief="solid", bd=1,
                         highlightthickness=1, highlightcolor=C_PRIMARY,
                         highlightbackground=C_LINE)
            return e

        # 邮箱地址
        _lbl("邮箱地址:", 1, 0)
        em = _entry(self.email_var, 34)
        em.grid(row=1, column=1, sticky="w", padx=4, pady=5)
        self.email_var.trace_add("write", self._on_email_change)

        # 授权码（标签可点击跳转申请教程）
        auth_lbl = tk.Label(frm, text="授权码(如何获取?)", bg=C_PANEL, fg="#2563EB",
                            font=FONT_LABEL, cursor="hand2", underline=True)
        auth_lbl.grid(row=1, column=2, sticky="e", padx=(12, 4), pady=5)
        auth_lbl.bind("<Button-1>", self._open_auth_help)
        self.pwd_entry = _entry(self.pwd_var, 22)
        self.pwd_entry.config(show="*")
        self.pwd_entry.grid(row=1, column=3, sticky="w", padx=4, pady=5)

        # 收件人邮箱 + 合并后自动发信
        _lbl("收件人邮箱:", 2, 0)
        _entry(self.recipient_var, 34).grid(row=2, column=1, sticky="w", padx=4, pady=5)
        cb = tk.Checkbutton(frm, text="合并后自动发信", variable=self.autosend_var,
                            bg=C_PANEL, fg=C_TEXT, font=FONT_LABEL,
                            activebackground=C_PANEL, selectcolor=C_PRIMARY, cursor="hand2")
        cb.grid(row=2, column=2, columnspan=2, sticky="w", padx=4, pady=5)

        # 日期范围（点击输入框或 📅 弹出日历选择）
        DatePicker(frm, "开始日期:", self.dfrom_var).grid(
            row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(6, 2))
        DatePicker(frm, "结束日期:", self.dto_var).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 6))

        # 说明：IMAP/SMTP 已自动匹配
        imap_s, imap_p, smtp_s, smtp_p, _ = detect_servers(self.email_var.get())
        note = (f"IMAP/SMTP 服务器已按邮箱自动匹配（无需填写）："
                f"{imap_s}:{imap_p} / {smtp_s}:{smtp_p}")
        self.note_var = tk.StringVar(value=note)
        tk.Label(frm, textvariable=self.note_var, bg=C_PANEL, fg=C_SUB,
                 font=("Microsoft YaHei UI", 9), anchor="w").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 4))
        # 日期默认说明
        tk.Label(frm, text="※ 日期不填则默认拉取「近 30 天」（今天往前 30 天 至 今天）。",
                 bg=C_PANEL, fg=C_SUB, font=("Microsoft YaHei UI", 9), anchor="w").grid(
            row=6, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 10))

    # ---------- 按钮区 ----------
    def _build_buttons(self, parent):
        bf = tk.Frame(parent, bg=C_BG)
        bf.pack(fill="x", padx=12, pady=6)
        make_button(bf, "合并下载（拉取+合并）", C_PRIMARY, C_PRIMARY_H,
                    w=26, cmd=self.task_fetch).pack(side="left", padx=4)
        make_button(bf, "发送到邮箱", C_ACCENT, C_ACCENT_H,
                    w=18, cmd=self.task_send).pack(side="left", padx=4)

        bf2 = tk.Frame(parent, bg=C_BG)
        bf2.pack(fill="x", padx=12, pady=(0, 6))
        make_button(bf2, "合并「发票」文件夹", C_TEAL, C_TEAL_H,
                    w=22, cmd=self.task_merge_local).pack(side="left", padx=4)
        make_button(bf2, "选本地PDF文件夹合并", C_TEAL, C_TEAL_H,
                    w=22, cmd=self.task_pick_folder).pack(side="left", padx=4)
        make_button(bf2, "打开输出PDF", C_SUCCESS, C_SUCCESS_H,
                    w=16, cmd=self.open_output).pack(side="left", padx=4)

    # ---------- 日志区 ----------
    def _build_log(self, parent):
        tk.Label(parent, text="运行日志", bg=C_BG, fg=C_SUB,
                 font=("Microsoft YaHei UI", 10, "bold"), anchor="w")\
            .pack(anchor="w", padx=14, pady=(8, 2))
        log_frame = tk.Frame(parent, bg=C_PANEL, bd=1, relief="solid")
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.log = scrolledtext.ScrolledText(log_frame, height=14, state="disabled",
                                             font=FONT_LOG, bg="#FBFCFE", fg="#2A2A2A",
                                             relief="flat", bd=0, padx=8, pady=6)
        self.log.pack(fill="both", expand=True, padx=2, pady=2)

    # ---------- 底部状态栏 ----------
    def _build_statusbar(self, parent):
        self.status_var = tk.StringVar(value="就绪")
        sb = tk.Frame(parent, bg=C_HEADER, height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        tk.Label(sb, textvariable=self.status_var, bg=C_HEADER, fg="#D6E4F5",
                 font=FONT_SUB, anchor="w").pack(side="left", padx=12)

    def set_status(self, msg):
        self.status_var.set(msg)

    # ---------- 日志 ----------
    def _start_redirect(self):
        self._old_stdout = sys.stdout
        sys.stdout = RedirectText(self.log)

    def _stop_redirect(self):
        if self._old_stdout:
            sys.stdout = self._old_stdout

    def log_msg(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- 邮箱变化：自动匹配服务器 + 更新申请链接 ----------
    def _on_email_change(self, *a):
        imap_s, imap_p, smtp_s, smtp_p, provider = detect_servers(self.email_var.get())
        self.note_var.set(
            f"IMAP/SMTP 服务器已按邮箱自动匹配（无需填写）：{imap_s}:{imap_p} / {smtp_s}:{smtp_p}")
        self.auth_url = AUTH_HELP.get(provider, AUTH_HELP_DEFAULT)
        if self.email_var.get().strip():
            self.set_status("已自动匹配邮箱服务器")

    def _open_auth_help(self, e=None):
        webbrowser.open(self.auth_url)

    # ---------- 任务（均在线程中执行，避免界面卡死） ----------
    def _run(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _collect_settings(self):
        """汇总设置；IMAP/SMTP 服务器与端口按邮箱自动匹配。"""
        imap_s, imap_p, smtp_s, smtp_p, _ = detect_servers(self.email_var.get().strip())
        return {
            "email": self.email_var.get().strip(),
            "password": self.pwd_var.get().strip(),
            "imap_server": imap_s,
            "imap_port": imap_p,
            "smtp_server": smtp_s,
            "smtp_port": smtp_p,
            "recipient": self.recipient_var.get().strip(),
            "autosend": bool(self.autosend_var.get()),
        }

    def _save_now(self):
        """直接保存设置（不弹窗），用于发送成功后的永久保存。"""
        if save_settings(self._collect_settings(), SETTINGS_PATH):
            self._settings_saved = True
            print("[INFO] 设置已保存，下次自动填入")

    def _prompt_save_if_needed(self):
        """首次成功运行后，在主线程弹窗询问是否保存设置。"""
        if self._settings_saved:
            return
        result = {}
        ev = threading.Event()

        def ask():
            result["v"] = messagebox.askyesno(
                "保存设置",
                "是否保存邮箱与服务器设置，以便下次自动填入？\n\n"
                "（将明文保存在程序目录的 mail_settings.json，仅本机可用，请勿随 exe 一起分享）")
            ev.set()

        self.root.after(0, ask)
        ev.wait()
        if result.get("v"):
            self._save_now()
        else:
            print("[INFO] 本次未保存设置")

    def task_fetch(self):
        password = self.pwd_var.get().strip()
        email = self.email_var.get().strip()
        if not email:
            messagebox.showwarning("提示", "请填写邮箱地址。")
            return
        if not password:
            messagebox.showwarning("提示", "请填写邮箱授权码（不是登录密码）。\n点击「授权码(如何获取?)」查看获取方法。")
            return
        self._password = password
        self._run(self._do_fetch)

    def _do_fetch(self):
        self._start_redirect()
        self.set_status("正在拉取邮件…")
        try:
            # 动态覆盖 IMAP 配置（按邮箱自动匹配）
            import config as _c
            imap_s, imap_p, _, _, _ = detect_servers(self.email_var.get().strip())
            _c.EMAIL_CONFIG["imap_server"] = imap_s
            _c.EMAIL_CONFIG["imap_port"] = imap_p
            _c.EMAIL_CONFIG["email_address"] = self.email_var.get().strip()

            count, msg = fetch_emails_and_download_attachments(
                password=self._password,
                target_folder=INVOICE_DIR,
                date_from=self.dfrom_var.get().strip(),
                date_to=self.dto_var.get().strip(),
            )
            print(f"[RESULT] {msg}")
            if count > 0:
                res = process_pdf_files(INVOICE_DIR, OUTPUT_FILE, log=_safe_print)
                if res.get("success"):
                    print(f"[DONE] 已生成合并PDF：{OUTPUT_FILE}")
                    # 可选：合并后自动发信
                    if self.autosend_var.get():
                        to = self.recipient_var.get().strip()
                        if to:
                            _, _, smtp_s, smtp_p, _ = detect_servers(self.email_var.get().strip())
                            ok, sm = send_pdf_via_smtp(
                                smtp_s, smtp_p, self.email_var.get().strip(),
                                self._password, to, OUTPUT_FILE)
                            print(f"[SMTP] {sm}")
                            self.set_status("完成 · 已合并" + ("并发送" if ok else "（发信失败）"))
                        else:
                            print("[SMTP] 未填写收件人，跳过发信")
                    else:
                        self.set_status(f"完成 · 已合并 {res['count']} 张发票")
                    # 首次成功 → 询问是否保存设置
                    self._prompt_save_if_needed()
                    self.root.after(0, lambda: messagebox.showinfo(
                        "完成", f"已拉取 {count} 张发票，按开车时间合并完成。\n保存至：{OUTPUT_FILE}"))
                else:
                    print(f"[ERROR] 合并失败：{res.get('error')}")
                    self.set_status("合并失败")
            else:
                print("[WARN] 未获取到发票，请检查日期范围 / 授权码 / 邮箱白名单。")
                self.set_status("未获取到发票")
        except Exception as e:
            print(f"[ERROR] {e}")
            self.set_status("出错，详见日志")
        finally:
            self._stop_redirect()

    def task_send(self):
        email = self.email_var.get().strip()
        password = self.pwd_var.get().strip()
        to = self.recipient_var.get().strip()
        if not email:
            messagebox.showwarning("提示", "请先填写邮箱地址。")
            return
        if not password:
            messagebox.showwarning("提示", "请填写邮箱授权码（不是登录密码）。")
            return
        if not to:
            messagebox.showwarning("提示", "请填写收件人邮箱。")
            return
        if not os.path.exists(OUTPUT_FILE):
            messagebox.showwarning("提示", "尚未生成合并PDF，请先执行合并。")
            return
        self._password = password
        self._run(self._do_send)

    def _do_send(self):
        self._start_redirect()
        self.set_status("正在发送…")
        try:
            email = self.email_var.get().strip()
            to = self.recipient_var.get().strip()
            _, _, smtp_s, smtp_p, _ = detect_servers(email)
            ok, sm = send_pdf_via_smtp(
                smtp_s, smtp_p, email, self._password, to, OUTPUT_FILE)
            print(f"[SMTP] {sm}")
            if ok:
                self.set_status("已发送至 " + to)
                # 发送成功 → 永久保存（含收件人）
                self._save_now()
                self.root.after(0, lambda: messagebox.showinfo("完成", f"已发送至 {to}"))
            else:
                self.set_status("发送失败")
                self.root.after(0, lambda: messagebox.showerror("失败", sm))
        except Exception as e:
            print(f"[ERROR] {e}")
            self.set_status("发送出错")
        finally:
            self._stop_redirect()

    def task_merge_local(self):
        self._run(lambda: self._do_merge(INVOICE_DIR))

    def task_pick_folder(self):
        folder = filedialog.askdirectory(title="选择包含发票PDF的文件夹")
        if folder:
            self._run(lambda: self._do_merge(folder))

    def _do_merge(self, folder):
        self._start_redirect()
        self.set_status("正在合并…")
        try:
            res = process_pdf_files(folder, OUTPUT_FILE, log=_safe_print)
            if res.get("success"):
                print(f"[DONE] 合并完成，共 {res['count']} 张，已保存：{OUTPUT_FILE}")
                self.set_status(f"完成 · 已合并 {res['count']} 张发票")
                self.root.after(0, lambda: messagebox.showinfo(
                    "完成", f"合并完成（{res['count']} 张），按开车时间排序。\n保存至：{OUTPUT_FILE}"))
            else:
                print(f"[ERROR] 合并失败：{res.get('error')}")
                self.root.after(0, lambda: messagebox.showerror("失败", res.get("error") or "合并失败"))
                self.set_status("合并失败")
        finally:
            self._stop_redirect()

    def open_output(self):
        if os.path.exists(OUTPUT_FILE):
            try:
                os.startfile(OUTPUT_FILE) if os.name == "nt" else os.system(f'open "{OUTPUT_FILE}"')
            except Exception as e:
                self.log_msg(f"打开失败: {e}")
        else:
            messagebox.showinfo("提示", "尚未生成输出PDF，请先执行合并。")


def _safe_print(msg):
    """供 ticket_core 回调使用（直接打印，由 sys.stdout 重定向到界面）。"""
    print(msg)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
