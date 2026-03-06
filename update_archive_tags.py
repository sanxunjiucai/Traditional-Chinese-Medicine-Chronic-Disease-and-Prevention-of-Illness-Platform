"""给档案添加标签"""
import asyncio
from app.database import AsyncSessionLocal
from app.models.archive import PatientArchive
from sqlalchemy import select

async def update_tags():
    async with AsyncSessionLocal() as sess:
        stmt = select(PatientArchive).where(PatientArchive.is_deleted == False).limit(25)
        archives = (await sess.execute(stmt)).scalars().all()

        # 标签分配规则
        tag_rules = [
            ([1, 15, 18], "高血压+高风险+规律随访"),
            ([2, 16, 18], "糖尿病+中风险+规律随访"),
            ([1, 2, 15, 18], "高血压+糖尿病+高风险+规律随访"),
            ([3, 15, 19], "冠心病+高风险+偶尔随访"),
            ([7, 17, 18], "气虚质+低风险+规律随访"),
            ([8, 16, 18], "阳虚质+中风险+规律随访"),
            ([10, 16, 19], "痰湿质+中风险+偶尔随访"),
            ([6, 17, 18], "平和质+低风险+规律随访"),
        ]

        for i, archive in enumerate(archives):
            tags = tag_rules[i % len(tag_rules)][0]
            archive.tags = tags
            print(f"✓ {archive.name}: {tag_rules[i % len(tag_rules)][1]}")

        await sess.commit()
        print(f"\n已更新 {len(archives)} 个档案的标签")

if __name__ == "__main__":
    asyncio.run(update_tags())
