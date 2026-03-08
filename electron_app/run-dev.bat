@echo off
chcp 65001 >nul
echo 启动 治未病·诊中助手 开发模式...
cd /d "%~dp0"
if not exist "node_modules" npm install
npx electron .
