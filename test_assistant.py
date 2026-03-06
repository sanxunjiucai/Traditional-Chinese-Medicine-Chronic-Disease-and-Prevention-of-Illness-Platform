"""测试 Assistant API"""
import requests
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8010"

def test_plan():
    """测试生成计划"""
    session = requests.Session()

    # 登录
    resp = session.post(f"{BASE_URL}/tools/auth/login", json={
        "phone": "admin@tcm",
        "password": "Demo@123456"
    })
    print(f"登录成功: {resp.json()['data']['name']}")

    # 测试生成计划
    print("\n=== 测试 1: 新建儿童档案 ===")
    resp = session.post(f"{BASE_URL}/tools/assistant/plan", json={
        "query": "为张小明创建儿童档案，2020年1月1日出生，男孩",
        "context": {}
    })
    print(f"状态码: {resp.status_code}")
    result = resp.json()
    print(f"响应: {json.dumps(result, ensure_ascii=False, indent=2)}")

    if result.get("success") and result.get("data"):
        # 测试执行计划 (dry_run)
        print("\n=== 测试 2: 执行计划 (dry_run) ===")
        resp = session.post(f"{BASE_URL}/tools/assistant/execute", json={
            "plan": result["data"],
            "dry_run": True
        })
        print(f"状态码: {resp.status_code}")
        print(f"响应: {json.dumps(resp.json(), ensure_ascii=False, indent=2)}")

if __name__ == "__main__":
    test_plan()
