#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火车票发票识别与排列工具"""

import os
import fitz
from PIL import Image
import re
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for, flash, jsonify
import tempfile
import shutil

from email_handler import fetch_emails_and_download_attachments
from config import EMAIL_CONFIG, FOLDERS
from ticket_core import extract_departure_info, render_pdf_to_image, process_pdf_files

app = Flask(__name__)
app.config['SECRET_KEY'] = 'train_ticket_secret_2025'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['INVOICE_FOLDER'] = FOLDERS.get('invoices', '发票')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER'], app.config['INVOICE_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

def print_info(msg): print(f"[INFO] {msg}")
def print_error(msg): print(f"[ERROR] {msg}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('files')
        if files and files[0].filename:
            temp_dir = tempfile.mkdtemp()
            try:
                for f in files:
                    if f and f.filename.endswith('.pdf'):
                        f.save(os.path.join(temp_dir, f.filename))
                output = os.path.join(app.config['OUTPUT_FOLDER'], '火车票发票排列结果.pdf')
                if process_pdf_files(temp_dir, output).get('success'):
                    return redirect(url_for('download_file'))
                flash('处理失败')
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        return redirect(request.url)
    return render_template('index.html')

@app.route('/download')
def download_file():
    output = os.path.join(app.config['OUTPUT_FOLDER'], '火车票发票排列结果.pdf')
    if os.path.exists(output):
        return send_file(output, as_attachment=True, download_name='火车票发票排列结果.pdf')
    flash('文件不存在')
    return redirect(url_for('index'))

@app.route('/clear')
def clear_files():
    for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
        if os.path.exists(folder):
            for f in os.listdir(folder):
                os.remove(os.path.join(folder, f))
    flash('已清理')
    return redirect(url_for('index'))

@app.route('/fetch_emails', methods=['POST'])
def fetch_emails():
    try:
        password = request.form.get('password', '') or EMAIL_CONFIG.get('password', '')
        date_from = request.form.get('date_from', '')
        date_to = request.form.get('date_to', '')
        
        if not password:
            return jsonify({'success': False, 'message': '未配置邮箱授权码'})
        
        count, msg = fetch_emails_and_download_attachments(
            password=password,
            target_folder=app.config['INVOICE_FOLDER'],
            date_from=date_from,
            date_to=date_to
        )
        return jsonify({'success': count > 0, 'count': count, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/process_invoices', methods=['POST'])
def process_invoices():
    try:
        invoice_folder = app.config['INVOICE_FOLDER']
        output = os.path.join(app.config['OUTPUT_FOLDER'], '火车票发票排列结果.pdf')
        
        if not os.path.exists(invoice_folder):
            return jsonify({'success': False, 'message': '发票文件夹不存在'})
        
        pdfs = [f for f in os.listdir(invoice_folder) if f.lower().endswith('.pdf')]
        if not pdfs:
            return jsonify({'success': False, 'message': '无PDF文件'})
        
        res = process_pdf_files(invoice_folder, output)
        if res.get('success'):
            return jsonify({'success': True, 'message': f'处理 {len(pdfs)} 个发票', 'download_url': '/download'})
        return jsonify({'success': False, 'message': res.get('error') or '处理失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/fetch_and_process', methods=['POST'])
def fetch_and_process():
    try:
        password = request.form.get('password', '') or EMAIL_CONFIG.get('password', '')
        date_from = request.form.get('date_from', '')
        date_to = request.form.get('date_to', '')
        
        if not password:
            return jsonify({'success': False, 'message': '未配置邮箱授权码'})
        
        count, msg = fetch_emails_and_download_attachments(
            password=password,
            target_folder=app.config['INVOICE_FOLDER'],
            date_from=date_from,
            date_to=date_to
        )
        
        if count == 0:
            return jsonify({'success': False, 'message': msg})
        
        output = os.path.join(app.config['OUTPUT_FOLDER'], '火车票发票排列结果.pdf')
        if process_pdf_files(app.config['INVOICE_FOLDER'], output).get('success'):
            return jsonify({'success': True, 'count': count, 'message': f'获取 {count} 个发票并生成PDF', 'download_url': '/download'})
        return jsonify({'success': False, 'message': '获取成功但处理失败'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5100, debug=False)