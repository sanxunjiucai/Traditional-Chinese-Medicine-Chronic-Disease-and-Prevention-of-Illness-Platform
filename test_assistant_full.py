"""测试 Assistant API - 完整用例"""
import requests
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8010"

def test_all_cases():
    session = requests.Session()

    # 登录
    session.post(f"{BASE_URL}/tools/auth/login", json={
        "phone": "admin@tcm",
        "password": "Demo@123456"
    })
    print("登录成功\n")

    # 用例1: 新建儿童档案
    print("=== 用例1: 新建儿童档案 ===")
    resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
        "query": "为李小花创建儿童档案，2021年3月15日出生，女孩，电话13800138001",
        "context": {}
    })
    r1 = resp.json()
    if not r1.get("success"):
        print(f"计划失败: {r1.get('error', {}).get('message')}\n")
        return

    plan1 = r1["data"]
    print(f"计划: {plan1['intent']}, 步骤数: {len(plan1['steps'])}")

    resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
        "plan": plan1,
        "dry_run": False
    })
    result1 = resp.json()["data"]
    print(f"执行结果: {result1['status']}")
    if result1['status'] == 'success':
        print(f"创建的实体: {result1['created_entities']}\n")
    else:
        print(f"失败: {result1['summary']}\n")
        print(f"详情: {result1['executed_steps']}\n")

    # 用例2: 创建随访任务
    print("=== 用例2: 创建随访任务 ===")
    resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
        "query": "为张伟创建高血压随访任务，每7天一次",
        "context": {}
    })
    r2 = resp.json()
    if not r2.get("success"):
        print(f"计划失败: {r2.get('error', {}).get('message')}\n")
        return

    plan2 = r2["data"]
    print(f"计划: {plan2['intent']}, 步骤数: {len(plan2['steps'])}")

    resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
        "plan": plan2,
        "dry_run": False
    })
    result2 = resp.json()["data"]
    print(f"执行结果: {result2['status']}")
    if result2['status'] == 'success':
        print(f"创建的实体: {result2['created_entities']}\n")
    else:
        print(f"失败原因: {result2['summary']}\n")

    # 用例3: 生成中医调理方案
    print("=== 用例3: 生成中医调理方案 ===")
    if result1['status'] == 'success' and 'archive_id' in result1['created_entities']:
        archive_id = result1['created_entities']['archive_id']
        resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
            "query": f"为档案ID {archive_id} 生成中医调理方案",
            "context": {"archive_id": archive_id}
        })
        plan3 = resp.json()["data"]
        print(f"计划: {plan3['intent']}, 步骤数: {len(plan3['steps'])}")

        resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
            "plan": plan3,
            "dry_run": False
        })
        result3 = resp.json()["data"]
        print(f"执行结果: {result3['status']}")
        print(f"创建的实体: {result3['created_entities']}")

if __name__ == "__main__":
    test_all_cases()
