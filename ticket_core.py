#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火车票发票核心逻辑（无 Flask 依赖，供 Web 版与 Windows 桌面版共用）

职责：
  1. 从 PDF 中提取火车开车时间（12306 电子客票）
  2. 将多张发票渲染为图片并按开车时间排序
  3. 合并为单页/多页 PDF 输出
"""

import os
import re
from datetime import datetime

import fitz
from PIL import Image


def _default_log(msg):
    print(msg)


def extract_departure_info(pdf_path, log=_default_log):
    """从 PDF 中提取火车开车时间（datetime），失败返回 None。"""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None

        text = ""
        for page in doc:
            text += page.get_text("text")
            for annot in page.annots() or []:
                if hasattr(annot, "info") and annot.info.get("content"):
                    text += annot.info["content"] + "\n"
        doc.close()

        log(f"[INFO] PDF文本长度: {len(text)}")

        # 开车时间提取模式 - 多种格式
        # 关键：12306 电子客票中，出发日期与“HH:MM开”之间常夹有其他文字
        # （如“电子发票（铁路电子客票）”），因此日期与时间之间允许出现任意字符，
        # 不再要求紧邻（仅空白），否则会把开车时间提取成 None，导致排序排到末尾。
        patterns = [
            # 出发日期(年-月-日) + 开车时间(HH:MM开)，中间允许夹其他文字
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日[\s\S]{0,60}?(\d{1,2}):(\d{2})\s*开', 5),
            # 仅有月-日 + 开车时间(HH:MM开)
            (r'(\d{1,2})月(\d{1,2})日[\s\S]{0,60}?(\d{1,2}):(\d{2})\s*开', 4),
            # 开车时间 标签形式（年-月-日）
            (r'开车时间[：:][\s\S]{0,30}?(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[\s\S]{0,20}?(\d{1,2}):(\d{2})', 5),
            # 开车时间 标签形式（月-日）
            (r'开车时间[：:][\s\S]{0,20}?(\d{1,2})月(\d{1,2})日[\s\S]{0,20}?(\d{1,2}):(\d{2})', 4),
            # 兜底：日期与时间紧邻（无中间文字）的通用格式
            (r'(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})[日]?\s*(\d{1,2}):(\d{2})', 5),
            (r'(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})', 4),
        ]

        for pattern, groups in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    g = match.groups()
                    if groups == 5:
                        dt = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]))
                        log(f"[INFO] 提取时间: {dt}")
                        return dt
                    elif groups == 4:
                        if int(g[0]) > 12:  # 第一个是年份
                            dt = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), 0)
                        else:  # 月日时分
                            dt = datetime(datetime.now().year, int(g[0]), int(g[1]), int(g[2]), int(g[3]))
                        log(f"[INFO] 提取时间: {dt}")
                        return dt
                except Exception as e:
                    log(f"[ERROR] 解析时间失败: {e}")
                    continue

        log("[INFO] 未找到开车时间")
        return None

    except Exception as e:
        log(f"[ERROR] 提取失败: {e}")
        return None


def render_pdf_to_image(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(3.0, 3.0), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        doc.close()
        return img
    except Exception:
        return None


def process_pdf_files(input_folder, output_file, log=_default_log, per_page=8):
    """
    处理 PDF 文件并按开车时间排序后合并为 PDF。

    返回 dict:
        success : bool
        count   : int   参与合并的发票数量
        order   : list  排序后的文件名列表（便于校验）
        error   : str   失败原因
    """
    result = {'success': False, 'count': 0, 'order': [], 'error': ''}
    try:
        if not os.path.exists(input_folder):
            result['error'] = f'文件夹不存在: {input_folder}'
            log(f"[ERROR] {result['error']}")
            return result

        pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
        if not pdf_files:
            result['error'] = '文件夹内无 PDF 文件'
            log("[ERROR] 无 PDF 文件")
            return result

        log(f"[INFO] 找到 {len(pdf_files)} 个PDF文件")

        # 提取每个 PDF 的开车时间
        pdf_info = []
        for f in pdf_files:
            path = os.path.join(input_folder, f)
            dt = extract_departure_info(path, log)
            pdf_info.append({'file': f, 'path': path, 'time': dt})
            if dt:
                log(f"[INFO]   {f} -> {dt}")
            else:
                log(f"[INFO]   {f} -> 无时间(将排最后)")

        # 按开车时间排序（无时间的排最后）
        pdf_info.sort(key=lambda x: x['time'] if x['time'] else datetime.max)

        log("[INFO] 排序结果:")
        for i, info in enumerate(pdf_info):
            t = info['time'].strftime('%Y-%m-%d %H:%M') if info['time'] else '无时间'
            log(f"[INFO]   {i + 1}. {info['file']} [{t}]")

        # 渲染 PDF 为图像
        images = []
        for info in pdf_info:
            img = render_pdf_to_image(info['path'])
            if img:
                images.append(img)

        if not images:
            result['error'] = 'PDF 渲染失败'
            log("[ERROR] 渲染失败")
            return result

        log(f"[INFO] 渲染 {len(images)} 个图像")

        # 按每页 per_page 张拼版
        pages = []
        for i in range(0, len(images), per_page):
            canvas = Image.new('RGB', (2480, 3508), 'white')
            page_imgs = images[i:i + per_page]
            for j, img in enumerate(page_imgs):
                row, col = j // 2, j % 2
                x = 50 + col * 1215
                y = 50 + row * 872
                w, h = img.size
                ratio = min(1165 / w, 822 / h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
                canvas.paste(img, (x + (1165 - img.width) // 2, y + (822 - img.height) // 2))
            pages.append(canvas)

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        if len(pages) == 1:
            pages[0].save(output_file, "PDF", resolution=300)
        else:
            pages[0].save(output_file, "PDF", resolution=300, save_all=True, append_images=pages[1:])

        log(f"[INFO] 保存完成: {output_file}")
        result.update({
            'success': True,
            'count': len(images),
            'order': [i['file'] for i in pdf_info],
        })
        return result
    except Exception as e:
        result['error'] = str(e)
        log(f"[ERROR] 处理失败: {e}")
        return result
