@echo off
chcp 65001 >nul
echo ============================================
echo  治未病·诊中助手 桌面版 — 构建脚本
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] 检查依赖...
if not exist "node_modules" (
    echo 安装依赖中（首次运行需要联网）...
    npm install
    if errorlevel 1 (
        echo 依赖安装失败！请检查网络连接。
        pause
        exit /b 1
    )
)

echo [2/3] 开始构建...
echo 输出目录: dist\
echo.
set CSC_IDENTITY_AUTO_DISCOVERY=false
npm run build

if errorlevel 1 (
    echo.
    echo 构建失败！请查看上方错误信息。
    pause
    exit /b 1
)

echo.
echo [3/3] 构建成功！
echo.
echo 输出文件在 dist\ 目录：
echo   - 安装版: 治未病·诊中助手 Setup x.x.x.exe  （双击安装）
echo   - 便携版: 治未病·诊中助手 x.x.x.exe         （无需安装，直接运行）
echo.
explorer dist
pause
