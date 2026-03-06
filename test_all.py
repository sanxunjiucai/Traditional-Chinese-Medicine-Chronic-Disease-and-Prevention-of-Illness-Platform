#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量功能测试脚本"""
import asyncio
import httpx
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8001"
client = None

async def test_login():
    """测试登录"""
    global client
    client = httpx.AsyncClient()
    resp = await client.post(f"{BASE_URL}/tools/auth/login", json={
        "phone": "admin@tcm",
        "password": "Demo@123456"
    })
    print(f"✓ 登录测试: {resp.status_code}")
    return resp.status_code == 200

async def test_api(method, path, name, json_data=None):
    """测试API端点"""
    try:
        if method == "GET":
            resp = await client.get(f"{BASE_URL}{path}", timeout=10)
        elif method == "POST":
            resp = await client.post(f"{BASE_URL}{path}", json=json_data, timeout=10)
        elif method == "PATCH":
            resp = await client.patch(f"{BASE_URL}{path}", json=json_data, timeout=10)

        status = "✓" if resp.status_code in [200, 201] else "✗"
        print(f"{status} {name}: {resp.status_code}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"✗ {name}: {str(e)[:50]}")
        return False

async def main():
    print("=" * 60)
    print("中医慢病平台 - 全量功能测试")
    print("=" * 60)

    # 1. 认证模块
    print("\n【1. 认证模块】")
    await test_login()

    # 2. 档案管理
    print("\n【2. 档案管理】")
    await test_api("GET", "/tools/archive/archives", "档案列表")
    await test_api("GET", "/tools/archive/archives/1", "档案详情")
    await test_api("GET", "/tools/label/labels", "标签列表")

    # 3. 体质评估
    print("\n【3. 体质评估】")
    await test_api("GET", "/tools/constitution/assessments", "体质评估列表")

    # 4. 健康评估
    print("\n【4. 健康评估】")
    await test_api("GET", "/tools/admin/health-assess", "健康评估列表")

    # 5. 量表管理
    print("\n【5. 量表管理】")
    await test_api("GET", "/tools/scale/scales", "量表列表")
    await test_api("GET", "/tools/scale/records", "量表记录")

    # 6. 干预管理
    print("\n【6. 干预管理】")
    await test_api("GET", "/tools/intervention/interventions", "干预列表")
    await test_api("GET", "/tools/intervention/templates", "干预模板")

    # 7. 宣教管理
    print("\n【7. 宣教管理】")
    await test_api("GET", "/tools/education/records", "宣教列表")
    await test_api("GET", "/tools/education/templates", "宣教模板")

    # 8. 指导管理
    print("\n【8. 指导管理】")
    await test_api("GET", "/tools/guidance/records", "指导列表")
    await test_api("GET", "/tools/guidance/templates", "指导模板")

    # 9. 随访管理
    print("\n【9. 随访管理】")
    await test_api("GET", "/tools/followup/plans", "随访计划")

    # 10. 预警管理
    print("\n【10. 预警管理】")
    await test_api("GET", "/tools/alerts/", "预警列表")
    await test_api("GET", "/tools/alerts/admin", "预警规则")

    # 11. 统计分析
    print("\n【11. 统计分析】")
    await test_api("GET", "/tools/stats/archive-overview", "档案统计")
    await test_api("GET", "/tools/stats/constitution-distribution", "体质统计")

    # 12. 系统管理
    print("\n【12. 系统管理】")
    await test_api("GET", "/tools/mgmt/orgs", "机构列表")
    await test_api("GET", "/tools/mgmt/roles", "角色列表")
    await test_api("GET", "/tools/admin/users", "用户列表")
    await test_api("GET", "/tools/mgmt/menus", "菜单列表")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
