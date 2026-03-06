"""
批量修复 admin 模板的 UI 样式不一致问题。
运行：python scripts/fix_ui_styles.py
"""
import os
import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent.parent / "app" / "templates" / "admin"

# ── 简单字符串替换 ─────────────────────────────────────────────────────
REPLACEMENTS = [
    # 表格行分隔线统一为 gray-100
    ("divide-y divide-gray-50",  "divide-y divide-gray-100"),
    ("divide-y divide-gray-200", "divide-y divide-gray-100"),
    # 筛选栏 flex gap 方式统一（CSS space-x 不支持 flex-wrap）
    (" space-x-3 ", " gap-3 "),
    (" space-x-4 ", " gap-4 "),
    ('"space-x-3"', '"gap-3"'),
    ('"space-x-4"', '"gap-4"'),
    # Badge 背景浓度：bg-X-50 + text-X-600 → bg-X-100 + text-X-700
    ("bg-purple-50 text-purple-600", "bg-purple-100 text-purple-700"),
    ("bg-indigo-50 text-indigo-600", "bg-indigo-100 text-indigo-700"),
    ("bg-blue-50 text-blue-600",     "bg-blue-100 text-blue-700"),
    ("bg-teal-50 text-teal-600",     "bg-teal-100 text-teal-700"),
    ("bg-green-50 text-green-600",   "bg-green-100 text-green-700"),
    ("bg-red-50 text-red-600",       "bg-red-100 text-red-700"),
    ("bg-amber-50 text-amber-600",   "bg-amber-100 text-amber-700"),
    ("bg-orange-50 text-orange-600", "bg-orange-100 text-orange-700"),
    ("bg-gray-50 text-gray-600",     "bg-gray-100 text-gray-600"),   # gray 无需加深
    # Focus ring 异常值修复
    ("focus:ring-indigo-200", "focus:ring-indigo-300"),
    # 添加 font-medium 给缺少它的主按钮（text-white 的小按钮）
    # —— 此项通过正则处理，见下方 ——
]

# ── 正则替换：badge text-600 → text-700 ────────────────────────────
# 在 JS 常量对象中，统一将 text-X-600（X≠gray）改为 text-X-700
# 覆盖 text-blue-600, text-green-600, text-red-600, text-amber-600 等
BADGE_TEXT_RE = re.compile(
    r"(bg-(?:blue|green|red|amber|orange|purple|indigo|teal|rose|emerald|pink)-100\s+"
    r"text-(?:blue|green|red|amber|orange|purple|indigo|teal|rose|emerald|pink))-600"
)

# ── badge rounded 圆角：在明确 badge 上下文中统一 ─────────────────────
# 将 JS 常量里 "px-2 py-0.5 rounded text-xs" → "px-2 py-0.5 rounded-full text-xs"
# 注意：仅当位于 JS 字符串 '' 内时才替换
BADGE_ROUNDED_RE = re.compile(
    r"(px-2(?:\.5)? py-0\.5 )rounded( text-xs font-medium)"
)


def fix_file(path: Path) -> int:
    """修复单个文件，返回替换次数"""
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  SKIP {path.name}: {e}")
        return 0

    content = original

    # 简单字符串替换
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)

    # 正则：badge text-600 → text-700
    content = BADGE_TEXT_RE.sub(r"\g<1>-700", content)

    # 正则：badge rounded → rounded-full（仅在 JS badge 常量字符串中）
    # 通过判断：紧邻的字符是引号
    def replace_rounded(m):
        return m.group(1) + "rounded-full" + m.group(2)
    content = BADGE_ROUNDED_RE.sub(replace_rounded, content)

    if content == original:
        return 0

    path.write_text(content, encoding="utf-8")
    count = sum(content.count(new) - original.count(new) for _, new in REPLACEMENTS if new != old)
    return 1


def main():
    html_files = sorted(TEMPLATE_DIR.glob("*.html"))
    print(f"Processing {len(html_files)} template files in {TEMPLATE_DIR}")

    changed = 0
    for f in html_files:
        result = fix_file(f)
        if result:
            changed += 1
            print(f"  OK {f.name}")

    print(f"\nDone. {changed}/{len(html_files)} files modified.")


if __name__ == "__main__":
    main()
