"""
pytest fixtures：
- async_client: httpx AsyncClient（in-process, 无需真实网络）
- test_db:       每个测试函数独立 session（使用 TEST_DATABASE_URL）
- admin_user / patient_user: 预建账号
- auth_headers:  返回带 cookie 的字典
"""
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import hash_password, create_access_token

# ── Test DB engine ──
TEST_ENGINE = create_async_engine(
    settings.test_database_url,
    echo=False,
    pool_pre_ping=True,
)
TestSession = async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """创建所有表（一次），测试结束后 drop。"""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """每个测试函数前清空数据并使用独立 session。"""
    async with TEST_ENGINE.begin() as conn:
        # SQLite 下禁用外键约束后按依赖逆序清表，避免跨用例数据污染
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
        await conn.execute(text("PRAGMA foreign_keys=ON"))

    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture()
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI 测试客户端，覆盖 get_db 使用 test session。"""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


# ── Helper: 创建用户 ──
async def create_user(
    db: AsyncSession,
    phone: str,
    name: str,
    password: str = "Test@123456",
    role: UserRole = UserRole.PATIENT,
) -> User:
    user = User(
        phone=phone,
        name=name,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture()
async def patient_user(db_session: AsyncSession) -> User:
    return await create_user(db_session, "13800000001", "测试患者", role=UserRole.PATIENT)


@pytest_asyncio.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    return await create_user(db_session, "13800000002", "管理员", role=UserRole.ADMIN)


@pytest_asyncio.fixture()
async def professional_user(db_session: AsyncSession) -> User:
    return await create_user(db_session, "13800000003", "医生", role=UserRole.PROFESSIONAL)


def make_auth_cookie(user: User) -> dict:
    """生成带 access_token cookie 的 headers dict。"""
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return {"cookies": {"access_token": token}}
