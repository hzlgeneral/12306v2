# 火车票发票识别与排列工具

> 从邮箱自动拉取 12306 火车票电子发票 PDF，按开车时间筛选、去重、重命名并合并为单份 PDF。

## 三种使用方式（导航）

```
┌─────────────────────────────────────────────────────────────────────┐
│                      火车票发票合并工具 12306v2                        │
├───────────────┬───────────────────────┬─────────────────────────────┤
│   🐳 Docker   │      🪟 Windows        │         🍎 macOS             │
│  （网页版/NAS）│     （桌面版 exe）      │      （桌面版 .app）          │
├───────────────┼───────────────────────┼─────────────────────────────┤
│ 适合：NAS、    │ 适合：本机直接双击运行 │ 适合：Mac 本机打包运行        │
│ 服务器常驻运行 │ ，无需装 Python        │ ，无需装 Python              │
│               │                       │                             │
│ 入口：        │ 入口：                │ 入口：                       │
│ docker/       │ windows/             │ mac/                        │
│               │                       │                             │
│ 命令：        │ 命令：                │ 命令：                       │
│ cd docker &&   │ 跑 build.bat 打包，   │ bash mac/build.sh           │
│ docker compose │ 或直接运行            │                             │
│ up -d --build │ windows/main.py       │                             │
│               │                       │                             │
│ 访问：        │ 产物：                │ 产物：                       │
│ http://IP:5100│ dist/火车票发票合并.exe│ dist/火车票发票合并.app        │
└───────────────┴───────────────────────┴─────────────────────────────┘
        ↑ 三类共用同一套核心代码（根目录 app.py / config.py / email_handler.py / ticket_core.py / templates/）
```

- **想常驻后台、多人/跨设备访问** → 选 Docker（网页版）
- **想在 Windows 上双击就用** → 选 Windows（桌面 exe）
- **想在 Mac 上打包成 app** → 选 Mac（桌面 app）

---

## 功能
- 从邮箱获取 12306 发票 PDF
- 支持日期范围筛选
- PDF 内容去重
- 自动命名：出发站-到达站_开车时间.pdf
- 合并 PDF 按开车时间排序

## 部署

### 方式一：Docker（网页版，推荐 NAS / 服务器常驻）
```bash
cd docker && docker compose up -d --build
```
访问 `http://NAS_IP:5100`（首次在网页上填写邮箱与授权码）。

### 方式二：Windows 桌面版
1. 安装 Python 3.10+
2. 打包 exe：`windows/build.bat`（产物在 `windows/dist/火车票发票合并.exe`）
3. 或直接运行源码：`python windows/main.py`
4. 在弹出的窗口里填写邮箱与授权码，选日期范围后开始

### 方式三：macOS 桌面版
```bash
bash mac/build.sh
```
产物在 `dist/火车票发票合并.app`，双击运行，在窗口里填写邮箱与授权码。

### 配置邮箱（Docker 网页版首次使用）
编辑 `config.py` 设置白名单发件人（默认已含 12306 官方发件地址）；邮箱地址与授权码**在网页界面填写**，不写进任何文件：
```python
EMAIL_CONFIG = {
    'email_address': '你的QQ邮箱@qq.com',   # 示例占位，运行时在网页填写
    'password': '邮箱授权码',                # 示例占位，运行时在网页填写
}
```

## 日期筛选
在网页上选择开始日期和结束日期，只获取该时间段内的邮件。不选则搜索最近 30 天。

## 目录结构
```
12306v2/
├── app.py / config.py / email_handler.py / ticket_core.py   # 共享核心代码（三类部署共用）
├── templates/                                  # 网页版前端模板（Docker / 网页版用）
├── build_assets/                               # 图标等资源（Windows / Mac 打包共用）
├── docker/                                     # 🐳 Docker 部署：Dockerfile + docker-compose.yml
├── windows/                                    # 🪟 Windows 桌面版：main.py + build.bat + requirements.txt
├── mac/                                        # 🍎 macOS 桌面版：build.sh（打包 windows/main.py）
├── .github/workflows/build-windows.yml         # 云端自动打包 Windows exe
├── 发票/                                        # （本地忽略，不上传）下载的发票 PDF
└── output/                                      # （本地忽略，不上传）合并后的 PDF
```

> ⚠️ 隐私说明：`发票/`、`output/`、`mail_settings.json` 已被 `.gitignore` 忽略，**不会上传到 GitHub**；邮箱与授权码仅在程序运行时由界面输入，源码与配置中无真实凭据。

## 维护
- 改完代码发布：`git add -A && git commit -m "说明" && git push`
- 远程仓库：https://github.com/hzlgeneral/12306v2
