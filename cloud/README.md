# 火车票发票自动合并 · 云电脑版（WorkBuddy 自动化）

把「同事装软件」变成「设个时间，云电脑自动跑完把 PDF 发到指定邮箱」。

## 原理
- 复用现有核心：`email_handler.py`（拉 12306 发票）+ `ticket_core.py`（排序合并），全部纯 Python，云电脑直接跑。
- **自动发送走 SMTP 脚本**，不是 qq-mail 连接器 —— 因为连接器发邮件有「两步确认弹卡」且附件限 1MB/封，自动化无人值守时无法弹卡、合并 PDF 常超 1MB。SMTP 脚本带本地授权码可无人值守发送。
- 凭据只存在本机 `mail_settings.json`（已被 `.gitignore` 忽略），**不进 GitHub、不回显**。

## 部署步骤
1. 复制模板并填入真实信息（**只在本机/云电脑，不要提交**）：
   ```bash
   cp cloud/mail_settings.example.json cloud/mail_settings.json
   # 编辑 mail_settings.json：email_address / password(授权码) / default_recipient
   ```
2. 依赖（PyMuPDF + Pillow）已装在受管 venv：
   `/Users/howell/.workbuddy/binaries/python/envs/default/bin/python`
3. 手动试运行（验证无误后再交给自动化）：
   ```bash
   /Users/howell/.workbuddy/binaries/python/envs/default/bin/python cloud/run_merge.py --to 同事@qq.com
   ```
   默认模式（不指定日期）按**发票上的「开车时间」精确筛选**：仅合并开车时间在上个月的发票；
   开车时间为上上个月及更早、或无法识别开车时间的，自动跳过不合并。
   指定范围则按邮件日期不过滤开车月份（用于全量补发）：
   `--from 2026-07-01 --to 2026-07-31`
   仅验证筛选/合并效果、不发送邮件：`--dry-run`

## 自动化
在 WorkBuddy 里建一个定时自动化（已建好，名称「12306发票合并并发送」，每月 1 号 09:00），
prompt 类似：
> 运行火车票发票合并：用受管 Python 执行
> `/Users/howell/Desktop/AI项目新/12306v2/cloud/run_merge.py --to zlhhe@beckman.com`，
> 拉取 12306 发票邮件，按开车时间筛选仅保留上个月开车的发票，排序合并，SMTP 发送到目标邮箱。
> 完成后汇报保留/排除张数及发送结果。

## 隐私说明
- `mail_settings.json` 存授权码，已被 git 忽略，永不进仓库。
- 发票 PDF、合并结果只在运行时生成于 `/tmp`，不入库。
- 邮箱与授权码仅运行时由脚本使用，源码/配置中无真实凭据。
