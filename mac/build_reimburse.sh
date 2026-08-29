#!/bin/bash
# ============================================================
#  Mac 一键打包：生成「报销凭证归集.app」
#  图形外壳(Tk) + 后台调用本机受管 Python 跑 cloud/run_merge.py
#  用法：终端 cd 到项目根目录，执行  bash mac/build_reimburse.sh
# ============================================================
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

APP_NAME="报销凭证归集"
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
python -m pip install --quiet pymupdf pillow pyinstaller

echo "==> 开始打包 PyInstaller（--windowed，macOS 标准 .app 包）"
echo "    注：GUI 仅做外壳，实际归集由子进程调用本机受管 Python 完成。"
rm -rf dist build
pyinstaller --windowed --name "$APP_NAME" $ICON_ARG --osx-bundle-identifier com.beckman.reimbursegui mac/reimburse_gui.py

echo ""
echo "✅ 完成！应用位于："
echo "   $PROJECT_ROOT/dist/$APP_NAME.app"
echo ""
echo "提示：首次打开未签名应用时，macOS 会拦截。右键点击 → 打开，或执行："
echo "   xattr -dr com.apple.quarantine \"$PROJECT_ROOT/dist/$APP_NAME.app\""
