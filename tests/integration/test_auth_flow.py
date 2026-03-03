"""
认证流程端到端测试（via /tools/auth/*）。
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(async_client: AsyncClient):
    resp = await async_client.post("/tools/auth/register", json={
        "phone": "13900000010",
        "password": "Test@123456",
        "name": "新用户",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert "user_id" in body["data"]


@pytest.mark.asyncio
async def test_register_duplicate_phone(async_client: AsyncClient):
    phone = "13900000011"
    await async_client.post("/tools/auth/register", json={
        "phone": phone, "password": "Test@123456", "name": "用户A"
    })
    resp = await async_client.post("/tools/auth/register", json={
        "phone": phone, "password": "Test@123456", "name": "用户B"
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_login_success(async_client: AsyncClient):
    phone = "13900000012"
    await async_client.post("/tools/auth/register", json={
        "phone": phone, "password": "Test@123456", "name": "登录测试"
    })
    resp = await async_client.post("/tools/auth/login", json={
        "phone": phone, "password": "Test@123456"
    })
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "PATIENT"
    assert "access_token" in resp.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(async_client: AsyncClient):
    phone = "13900000013"
    await async_client.post("/tools/auth/register", json={
        "phone": phone, "password": "Test@123456", "name": "用户"
    })
    resp = await async_client.post("/tools/auth/login", json={
        "phone": phone, "password": "wrongpassword"
    })
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_protected_without_token(async_client: AsyncClient):
    resp = await async_client.get("/tools/indicators?indicator_type=BLOOD_PRESSURE")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "PERMISSION_ERROR"


@pytest.mark.asyncio
async def test_logout(async_client: AsyncClient):
    phone = "13900000014"
    await async_client.post("/tools/auth/register", json={
        "phone": phone, "password": "Test@123456", "name": "退出测试"
    })
    await async_client.post("/tools/auth/login", json={"phone": phone, "password": "Test@123456"})
    resp = await async_client.post("/tools/auth/logout")
    assert resp.status_code == 200
    # cookie 应被清除
    assert "access_token" not in resp.cookies or resp.cookies.get("access_token") == ""
