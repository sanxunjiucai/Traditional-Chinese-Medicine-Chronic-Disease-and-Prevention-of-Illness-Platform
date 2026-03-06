"""添加标签数据到数据库"""
import asyncio
from app.database import AsyncSessionLocal
from app.models.label import LabelCategory, Label

async def seed_labels():
    async with AsyncSessionLocal() as sess:
        # 1. 创建标签分类
        categories = [
            LabelCategory(id=1, name="慢病管理", color="#ef4444", sort_order=1),
            LabelCategory(id=2, name="中医体质", color="#10b981", sort_order=2),
            LabelCategory(id=3, name="风险分级", color="#f59e0b", sort_order=3),
            LabelCategory(id=4, name="随访状态", color="#3b82f6", sort_order=4),
            LabelCategory(id=5, name="特殊人群", color="#8b5cf6", sort_order=5),
        ]

        for cat in categories:
            existing = await sess.get(LabelCategory, cat.id)
            if not existing:
                sess.add(cat)

        await sess.commit()

        # 2. 创建标签
        labels = [
            # 慢病管理
            Label(id=1, name="高血压", category_id=1, scope="SYSTEM", color="#ef4444", description="原发性高血压患者"),
            Label(id=2, name="糖尿病", category_id=1, scope="SYSTEM", color="#f97316", description="2型糖尿病患者"),
            Label(id=3, name="冠心病", category_id=1, scope="SYSTEM", color="#dc2626", description="冠状动脉粥样硬化性心脏病"),
            Label(id=4, name="脑卒中", category_id=1, scope="SYSTEM", color="#b91c1c", description="脑血管意外患者"),
            Label(id=5, name="慢阻肺", category_id=1, scope="SYSTEM", color="#ea580c", description="慢性阻塞性肺疾病"),

            # 中医体质
            Label(id=6, name="平和质", category_id=2, scope="SYSTEM", color="#10b981", description="阴阳气血调和"),
            Label(id=7, name="气虚质", category_id=2, scope="SYSTEM", color="#6ee7b7", description="元气不足"),
            Label(id=8, name="阳虚质", category_id=2, scope="SYSTEM", color="#34d399", description="阳气不足"),
            Label(id=9, name="阴虚质", category_id=2, scope="SYSTEM", color="#059669", description="阴液亏少"),
            Label(id=10, name="痰湿质", category_id=2, scope="SYSTEM", color="#047857", description="痰湿凝聚"),
            Label(id=11, name="湿热质", category_id=2, scope="SYSTEM", color="#065f46", description="湿热内蕴"),
            Label(id=12, name="血瘀质", category_id=2, scope="SYSTEM", color="#7c3aed", description="血行不畅"),
            Label(id=13, name="气郁质", category_id=2, scope="SYSTEM", color="#6d28d9", description="气机郁滞"),
            Label(id=14, name="特禀质", category_id=2, scope="SYSTEM", color="#5b21b6", description="先天失常"),

            # 风险分级
            Label(id=15, name="高风险", category_id=3, scope="SYSTEM", color="#dc2626", description="需重点关注"),
            Label(id=16, name="中风险", category_id=3, scope="SYSTEM", color="#f59e0b", description="需定期随访"),
            Label(id=17, name="低风险", category_id=3, scope="SYSTEM", color="#10b981", description="健康状态良好"),

            # 随访状态
            Label(id=18, name="规律随访", category_id=4, scope="SYSTEM", color="#3b82f6", description="按计划规律随访"),
            Label(id=19, name="偶尔随访", category_id=4, scope="SYSTEM", color="#60a5fa", description="随访不规律"),
            Label(id=20, name="失访", category_id=4, scope="SYSTEM", color="#9ca3af", description="无法联系"),

            # 特殊人群
            Label(id=21, name="孕产妇", category_id=5, scope="SYSTEM", color="#ec4899", description="孕期或产后妇女"),
            Label(id=22, name="残疾人", category_id=5, scope="SYSTEM", color="#8b5cf6", description="持证残疾人"),
            Label(id=23, name="低保户", category_id=5, scope="SYSTEM", color="#6366f1", description="享受低保政策"),
            Label(id=24, name="独居老人", category_id=5, scope="SYSTEM", color="#a855f7", description="独自居住的老年人"),
        ]

        for label in labels:
            existing = await sess.get(Label, label.id)
            if not existing:
                sess.add(label)

        await sess.commit()
        print(f"✓ 已添加 {len(categories)} 个标签分类")
        print(f"✓ 已添加 {len(labels)} 个标签")

if __name__ == "__main__":
    asyncio.run(seed_labels())
