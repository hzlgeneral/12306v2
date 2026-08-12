#!/bin/bash
# ============================================================
#  Mac 一键打包脚本：生成「火车票发票合并.app」
#  成品为独立应用，运行时无需安装 Python（依赖已打进包内）。
#  用法：在「终端」里 cd 到本项目根目录，执行  bash mac_app/build.sh
# ============================================================
set -e

# 回到项目根目录（无论在哪调用本脚本）
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

APP_NAME="火车票发票合并"
ICON="build_assets/AppIcon.icns"
VENV="build_assets/venv"

if [ ! -f "$ICON" ]; then
  echo "⚠️  未找到图标 $ICON，将打包无图标版本（不影响功能）。"
  ICON_ARG=""
else
  ICON_ARG="--icon $ICON"
fi

echo "==> 准备 Python 虚拟环境（$VENV）"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> 安装依赖（pymupdf / pillow / pyinstaller）"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r windows_app/requirements.txt
python -m pip install --quiet pyinstaller

echo "==> 开始打包 PyInstaller（--windowed，macOS 标准 .app 包）"
echo "    注：macOS 上 --onefile 与 .app 包不兼容，故用 onedir 生成自包含的 .app"
rm -rf dist build
pyinstaller --windowed --name "$APP_NAME" $ICON_ARG --paths . windows_app/main.py

echo ""
echo "✅ 完成！应用位于："
echo "   $PROJECT_ROOT/dist/$APP_NAME.app"
echo ""
echo "提示：首次打开未签名应用时， macOS 会拦截。右键点击 → 打开，或在终端执行："
echo "   xattr -dr com.apple.quarantine \"$PROJECT_ROOT/dist/$APP_NAME.app\""
