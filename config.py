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