@echo off
chcp 65001 >nul
REM =========================================================
REM  火车票发票合并工具 - Windows 打包脚本
REM  用法：双击本文件（需已安装 Python 3.10+ 并加入 PATH）
REM  产物：dist\火车票发票合并.exe  （单文件，可单独拷贝使用）
REM =========================================================
setlocal

echo [1/3] 安装依赖...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [2/3] 使用 PyInstaller 打包为单文件 exe...
pyinstaller --onefile --windowed ^
    --name "火车票发票合并" ^
    --paths ".." ^
    main.py

echo [3/3] 完成。exe 位于 dist\ 目录。
echo 将 dist\火车票发票合并.exe 拷贝到任意位置双击即可运行。
pause
