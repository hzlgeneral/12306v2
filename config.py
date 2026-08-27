#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置文件"""

EMAIL_CONFIG = {
    'imap_server': 'imap.qq.com',
    'imap_port': 993,
    'email_address': '',  # 用户在程序界面自行填写，不要在此硬编码
    'password': '',       # 邮箱授权码（非登录密码），由用户在界面输入
    'use_ssl': True,
}

SENDER_WHITELIST = ['12306@rails.com.cn']

EMAIL_KEYWORDS = ['电子发票', '12306', '火车票']

FOLDERS = {'uploads': 'uploads', 'output': 'output', 'invoices': '发票'}

EMAIL_SEARCH = {'max_emails': 50, 'days_back': 30}

# ===== 报销凭证归集（cloud 版，全发票+水单+刷卡单） =====
ATTACH_EXT = {
    'pdf': 'pdf', 'ofd': 'ofd',
    'zip': 'zip',
    'jpg': 'image', 'jpeg': 'image', 'png': 'image',
    'bmp': 'image', 'gif': 'image', 'tif': 'image', 'tiff': 'image',
    'webp': 'image',
}

# 报销归集默认窗口（天）/ 单次最多处理邮件数
REIMBURSE = {
    'default_days': 90,
    'default_max_emails': 200,
    'amount_tol': 0.01,        # 金额绝对容差（元）
    'day_window': 7,           # 凭证与发票日期邻近窗口（天）
    'send_max_multi': 5,       # 直接多附件的最大组数
    'send_max_size_mb': 25,    # 超过则改用 zip
}