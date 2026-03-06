"""
数据迁移：修复 guidance_records 表的旧枚举值。

背景：
  GuidanceType 枚举值曾从 LIFESTYLE/MEDICATION/DIET/EXERCISE 改为
  GUIDANCE/EDUCATION/INTERVENTION，status 从 COMPLETED/IN_PROGRESS 改为
  PUBLISHED/DRAFT。存量 demo.db 数据可能仍保留旧值。

执行方式：
  python -m scripts.migrate_guidance_enums
"""
import asyncio

from sqlalchemy import text

from app.database import AsyncSessionLocal


# 旧值 → 新值 映射
GUIDANCE_TYPE_MAP = {
    "LIFESTYLE":    "GUIDANCE",
    "MEDICATION":   "GUIDANCE",
    "DIET":         "GUIDANCE",
    "EXERCISE":     "GUIDANCE",
}

GUIDANCE_STATUS_MAP = {
    "COMPLETED":   "PUBLISHED",
    "IN_PROGRESS": "DRAFT",
    "PENDING":     "DRAFT",
}


async def run_migration() -> None:
    async with AsyncSessionLocal() as db:
        # 修复 guidance_records.guidance_type
        for old, new in GUIDANCE_TYPE_MAP.items():
            result = await db.execute(
                text(
                    "UPDATE guidance_records SET guidance_type = :new "
                    "WHERE guidance_type = :old"
                ),
                {"old": old, "new": new},
            )
            if result.rowcount:
                print(f"  guidance_type: {old} → {new}（{result.rowcount} 条）")

        # 修复 guidance_records.status
        for old, new in GUIDANCE_STATUS_MAP.items():
            result = await db.execute(
                text(
                    "UPDATE guidance_records SET status = :new "
                    "WHERE status = :old"
                ),
                {"old": old, "new": new},
            )
            if result.rowcount:
                print(f"  status: {old} → {new}（{result.rowcount} 条）")

        # 修复 guidance_templates 同字段（如存在）
        for old, new in GUIDANCE_TYPE_MAP.items():
            try:
                result = await db.execute(
                    text(
                        "UPDATE guidance_templates SET guidance_type = :new "
                        "WHERE guidance_type = :old"
                    ),
                    {"old": old, "new": new},
                )
                if result.rowcount:
                    print(f"  templates.guidance_type: {old} → {new}（{result.rowcount} 条）")
            except Exception:
                pass  # guidance_templates 可能不含该字段

        await db.commit()
        print("迁移完成。")


if __name__ == "__main__":
    asyncio.run(run_migration())
