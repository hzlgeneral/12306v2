#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报销凭证归集 · Mac 图形界面（.app 外壳）

仅做图形外壳：后台用子进程调用本机已装好 pymupdf 的受管 Python 运行
cloud/run_merge.py，实时显示日志，完成后自动打开结果文件夹。

本机测试默认值（如需分发给他人，请把这两个路径改为相对/外部可配置）：
  MANAGED_PY   受管 Python 解释器（含 pymupdf）
  RUNMERGE     报销归集主脚本 cloud/run_merge.py
"""
import os
import sys
import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ---------------- 本机路径（测试用默认值） ----------------
MANAGED_PY = "/Users/howell/.workbuddy/binaries/python/envs/default/bin/python"
PROJECT_ROOT = "/Users/howell/Desktop/AI项目新/12306v2"
RUNMERGE = os.path.join(PROJECT_ROOT, "cloud", "run_merge.py")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

APP_TITLE = "报销凭证归集"


def build_args(opts):
    """根据界面选项拼出 run_merge.py 的命令行。"""
    cmd = [MANAGED_PY, RUNMERGE]
    if opts.get("to_mail"):
        cmd += ["--to", opts["to_mail"]]
    mode = opts.get("mode", "days")
    if mode == "days":
        cmd += ["--days", str(opts.get("days", 90))]
    elif mode == "range":
        cmd += ["--from", opts["from"], "--to-date", opts["to"]]
    elif mode == "since":
        cmd += ["--since-last-run"]
    if opts.get("dry_run"):
        cmd += ["--dry-run"]
    if opts.get("copy_out"):
        cmd += ["--copy-out"]
    cmd += ["--amount-tol", str(opts.get("amount_tol", 0.01))]
    return cmd


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x560")
        try:
            self.root.tk.call("tk", "useTheme", "aqua")
        except Exception:
            pass

        self.running = False
        self._build_widgets()

    def _build_widgets(self):
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self.root)
        f.pack(fill="x", **pad)

        # 时间范围模式
        ttk.Label(f, text="时间范围").grid(row=0, column=0, sticky="w")
        self.mode = tk.StringVar(value="days")
        rb_days = ttk.Radiobutton(f, text="近 N 天", variable=self.mode, value="days", command=self._on_mode)
        rb_range = ttk.Radiobutton(f, text="指定起止", variable=self.mode, value="range", command=self._on_mode)
        rb_since = ttk.Radiobutton(f, text="上次运行起", variable=self.mode, value="since", command=self._on_mode)
        rb_days.grid(row=0, column=1, sticky="w")
        rb_range.grid(row=0, column=2, sticky="w")
        rb_since.grid(row=0, column=3, sticky="w")

        # 近 N 天
        ttk.Label(f, text="N =").grid(row=1, column=0, sticky="e")
        self.days_var = tk.IntVar(value=90)
        self.days_entry = ttk.Entry(f, textvariable=self.days_var, width=8)
        self.days_entry.grid(row=1, column=1, sticky="w")

        # 指定起止日期
        ttk.Label(f, text="起").grid(row=2, column=0, sticky="e")
        self.from_var = tk.StringVar()
        self.from_entry = ttk.Entry(f, textvariable=self.from_var, width=12)
        self.from_entry.grid(row=2, column=1, sticky="w")
        ttk.Label(f, text="止").grid(row=2, column=2, sticky="e")
        self.to_var = tk.StringVar()
        self.to_entry = ttk.Entry(f, textvariable=self.to_var, width=12)
        self.to_entry.grid(row=2, column=3, sticky="w")
        ttk.Label(f, text="(格式 YYYY-MM-DD)").grid(row=2, column=4, sticky="w")

        # 目标邮箱
        ttk.Label(f, text="接收邮箱").grid(row=3, column=0, sticky="e")
        self.to_mail = tk.StringVar(value="zlhhe@beckman.com")
        ttk.Entry(f, textvariable=self.to_mail, width=28).grid(row=3, column=1, columnspan=3, sticky="w")

        # 金额容差
        ttk.Label(f, text="金额容差(元)").grid(row=4, column=0, sticky="e")
        self.tol_var = tk.DoubleVar(value=0.01)
        ttk.Entry(f, textvariable=self.tol_var, width=8).grid(row=4, column=1, sticky="w")

        # 选项
        self.dry_var = tk.BooleanVar(value=False)
        self.copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="仅预览(不发送)", variable=self.dry_var).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(f, text="复制结果到 output/", variable=self.copy_var).grid(row=5, column=2, columnspan=2, sticky="w")

        self._on_mode()

        # 按钮行
        bf = ttk.Frame(self.root)
        bf.pack(fill="x", **pad)
        self.run_btn = ttk.Button(bf, text="开始归集", command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(bf, text="打开结果文件夹", command=self._open_output).pack(side="left")
        ttk.Button(bf, text="清空日志", command=self._clear_log).pack(side="left")
        self.status = tk.StringVar(value="就绪")
        ttk.Label(bf, textvariable=self.status).pack(side="right")

        # 日志
        ttk.Label(self.root, text="运行日志").pack(anchor="w", **pad)
        self.log = scrolledtext.ScrolledText(self.root, height=20, font=("Menlo", 10))
        self.log.pack(fill="both", expand=True, **pad)

        # 环境信息
        info = f"Python: {MANAGED_PY}\n脚本: {RUNMERGE}"
        self._append(f"[环境] {info}\n")

    def _on_mode(self):
        m = self.mode.get()
        state_days = "normal" if m == "days" else "disabled"
        state_range = "normal" if m == "range" else "disabled"
        self.days_entry.configure(state=state_days)
        self.from_entry.configure(state=state_range)
        self.to_entry.configure(state=state_range)

    def _append(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def _clear_log(self):
        self.log.delete("1.0", "end")

    def _open_output(self):
        if not os.path.isdir(OUTPUT_DIR):
            os.makedirs(OUTPUT_DIR, exist_ok=True)
        subprocess.run(["open", OUTPUT_DIR])

    def _collect_opts(self):
        m = self.mode.get()
        opts = {
            "mode": m,
            "to_mail": self.to_mail.get().strip(),
            "amount_tol": self.tol_var.get(),
            "dry_run": self.dry_var.get(),
            "copy_out": self.copy_var.get(),
        }
        if m == "days":
            opts["days"] = self.days_var.get()
        elif m == "range":
            opts["from"] = self.from_var.get().strip()
            opts["to"] = self.to_var.get().strip()
        return opts

    def _on_run(self):
        if self.running:
            return
        if not os.path.exists(MANAGED_PY):
            messagebox.showerror("环境错误", f"未找到受管 Python：\n{MANAGED_PY}")
            return
        if not os.path.exists(RUNMERGE):
            messagebox.showerror("环境错误", f"未找到脚本：\n{RUNMERGE}")
            return
        opts = self._collect_opts()
        if opts["mode"] == "range" and (not opts.get("from") or not opts.get("to")):
            messagebox.showwarning("提示", "指定起止模式需要填起、止日期")
            return
        cmd = build_args(opts)
        self._append("\n========== 开始 ==========\n")
        self._append("命令: " + " ".join(cmd) + "\n")
        self.running = True
        self.run_btn.configure(state="disabled")
        self.status.set("运行中…")
        t = threading.Thread(target=self._run, args=(cmd, opts), daemon=True)
        t.start()

    def _run(self, cmd, opts):
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=PROJECT_ROOT)
            last_line = ""
            for line in proc.stdout:
                last_line = line
                self.root.after(0, self._append, line)
            proc.wait()
            # 解析末尾 JSON 汇总
            summary = None
            if last_line.strip().startswith("{"):
                try:
                    summary = json.loads(last_line)
                except Exception:
                    summary = None
            self.root.after(0, self._on_done, proc.returncode, summary, opts)
        except Exception as e:
            self.root.after(0, self._append, f"[错误] {e}\n")
            self.root.after(0, self._on_done, -1, None, opts)

    def _on_done(self, rc, summary, opts):
        self.running = False
        self.run_btn.configure(state="normal")
        if rc == 0 and summary and summary.get("ok"):
            self.status.set("完成 ✅")
            self._append(f"\n[完成] {summary.get('detail','')}\n")
            if opts.get("copy_out"):
                self._open_output()
        elif summary:
            self.status.set("需确认/异常")
            self._append(f"\n[结束] ok={summary.get('ok')} step={summary.get('step')} "
                         f"detail={summary.get('detail')}\n")
            if summary.get("needs_decision"):
                self._append("[提示] 存在歧义/未匹配/需复核凭证，请查看日志后人工处理。\n")
        else:
            self.status.set("失败")
            self._append(f"\n[失败] 返回码 {rc}\n")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
