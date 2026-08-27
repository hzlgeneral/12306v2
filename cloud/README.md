# 报销凭证归集 · 云电脑版（WorkBuddy 自动化）

把「同事装软件」变成「指定时间范围，云电脑自动拉邮件、识别发票、配对水单/刷卡单、合并 PDF 发到指定邮箱」。

## 能力
- **全发票识别**：不再只认 12306，邮箱附件里所有发票都纳入（增值税电子发票 / 全电发票 / 铁路电子客票 等）。
- **水单 + 刷卡单配对**：按「金额 + 日期」自动把银行电子回单（水单）、POS 签购单（刷卡单）归到对应发票。
- **每发票一个独立 PDF**，组内固定顺序：**发票 → 水单 → 刷卡单**。
- **时间范围每次可指定**：近 N 天 / 手动起止日期 / 以上次运行为起点。

## 原理
- 核心模块：`email_handler.py`（全量拉附件）、`classify.py`（分类+字段抽取）、`group.py`（金额日期分组）、`build_pdf.py`（矢量拼 PDF），`run_merge.py` 串联。
- **分类/抽取纯文本层（v1 无 OCR）**：处理 PDF（含 ZIP 内 PDF）与 OFD 文本层；图片型附件无法自动识别 → 进「需复核」桶留存，由人工核对（架构预留 OCR 接口，后续可接 Mac Vision / rapidocr）。
- **自动发送走 SMTP 脚本**，不是 qq-mail 连接器（连接器有两步确认弹卡、附件限 1MB，无人值守时不可用）。
- 凭据只在本机 `mail_settings.json`（`.gitignore` 忽略），不进仓库、不回显。

## 文件
| 文件 | 作用 |
|------|------|
| `email_handler.py` | 追加 `fetch_all_attachments`：窗口内所有带附件邮件，BODY.PEEK 不标已读，按邮件分子目录保留原文件名，写 `manifest.json` |
| `classify.py` | 分类（发票/水单/刷卡单/其他/需复核）+ 抽金额/日期/发票号 |
| `group.py` | 按金额容差+日期邻近分组（唯一/贪心/子集和/未匹配四轮 + 歧义检测） |
| `build_pdf.py` | 用 pymupdf 矢量直拼，组内顺序 发票→水单→刷卡单；图片插页；需复核桶 |
| `run_merge.py` | 主流程；末行打 JSON 汇总 |
| `run_merge_12306.py` | 旧版「仅 12306 按月」逻辑回滚副本 |
| `selftest.py` | 把样例 PDF 放进 `tests/fixtures/` 后运行，校准分类准确率 |
| `requirements-cloud.txt` | 依赖（pymupdf） |

## 用法
```bash
PY=/Users/howell/.workbuddy/binaries/python/envs/default/bin/python

# 默认近 90 天
$PY cloud/run_merge.py --to 同事@qq.com
# 手动指定固定时间范围（用户每次可指定）
$PY cloud/run_merge.py --to 同事@qq.com --from 2026-07-01 --to-date 2026-07-31
# 近 30 天
$PY cloud/run_merge.py --to 同事@qq.com --days 30
# 以上次成功运行日期为起点（避免重复归集）
$PY cloud/run_merge.py --to 同事@qq.com --since-last-run
# 只处理不发送（验证）
$PY cloud/run_merge.py --to 同事@qq.com --dry-run
# 未匹配凭证也单出 Z 桶 + 复制到 output/ 预览
$PY cloud/run_merge.py --to 同事@qq.com --include-unmatched --copy-out
```
分组阈值可调：`--amount-tol 0.01`（金额容差元）、`--day-window 7`（日期邻近天）。

## 校准分类准确率
把真实样例（发票/水单/刷卡单/无关附件各若干）放进 `cloud/tests/fixtures/`（已 gitignore），运行：
```bash
$PY cloud/selftest.py --build
```
查看分类/字段/分组结果，据此调整 `classify.py` 关键词表。

## 自动化
已建定时自动化（名称「12306发票合并并发送」→ 现已升级为报销归集），保留每月 1 号 09:00 + 手动运行。
prompt 要点：先 `--dry-run` 读 JSON → 仅当出现「歧义/未匹配/需复核/0 组」时用 AskUserQuestion 问用户，否则直接正式发送 → 用 `--copy-out` 生成产物并以 present_files 交付预览。

## 隐私
- `mail_settings.json`、`cloud/.state.json`、`cloud/tests/fixtures/` 均被 git 忽略。
- 附件默认落 `/tmp`，跑完即弃；`--copy-out` 才进已 gitignore 的 `output/`。
