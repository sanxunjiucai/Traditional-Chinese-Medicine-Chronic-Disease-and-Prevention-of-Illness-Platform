"""测试 Assistant API - 简化版"""
import requests
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8010"

def test_simple():
    session = requests.Session()
    session.post(f"{BASE_URL}/tools/auth/login", json={
        "phone": "admin@tcm",
        "password": "Demo@123456"
    })
    print("登录成功\n")

    # 用例1: 新建儿童档案
    print("=== 用例1: 新建儿童档案 ===")
    resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
        "query": "为王小宝创建儿童档案，2022年6月1日出生，男孩",
        "context": {}
    })
    r1 = resp.json()
    if r1.get("success"):
        plan1 = r1["data"]
        print(f"✓ 计划生成成功: {plan1['intent']}")

        resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
            "plan": plan1,
            "dry_run": False
        })
        result1 = resp.json()["data"]
        if result1['status'] == 'success':
            print(f"✓ 执行成功: {result1['created_entities']}\n")
        else:
            print(f"✗ 执行失败: {result1['summary']}\n")
    else:
        print(f"✗ 计划失败\n")

    # 用例3: 生成中医方案（使用已存在的患者）
    print("=== 用例3: 为张伟生成中医调理方案 ===")
    # 先搜索张伟的档案ID
    resp = session.get(f"{BASE_URL}/tools/archive/archives?name=张伟&page=1&page_size=1")
    archives = resp.json()
    if archives.get("success") and archives["data"]["items"]:
        archive_id = archives["data"]["items"][0]["id"]
        print(f"找到档案ID: {archive_id}")

        resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
            "query": f"为档案ID {archive_id} 生成中医调理方案",
            "context": {"archive_id": archive_id}
        })
        r3 = resp.json()
        if r3.get("success"):
            plan3 = r3["data"]
            print(f"✓ 计划生成成功: {plan3['intent']}")

            resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
                "plan": plan3,
                "dry_run": False
            })
            result3 = resp.json()["data"]
            if result3['status'] == 'success':
                print(f"✓ 执行成功: {result3['created_entities']}")
            else:
                print(f"✗ 执行失败: {result3['summary']}")
        else:
            print(f"✗ 计划失败")

if __name__ == "__main__":
    test_simple()
