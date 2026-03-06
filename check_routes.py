import re, os

with open('app/gui/admin_pages.py', 'r', encoding='utf-8') as f:
    content = f.read()

blocks = re.split(r'\n(?=@router\.get)', content)

missing = []
for block in blocks:
    route_m = re.search(r"@router\.get\(['\"]([^'\"]+)['\"]", block)
    tpl_m = re.search(r"TemplateResponse\(['\"]([^'\"]+)['\"]", block)
    if route_m and tpl_m:
        route = route_m.group(1)
        tpl = tpl_m.group(1)
        tpl = tpl.replace('\\', '/')
        tpl_path = os.path.join('app/templates', tpl)
        if not os.path.exists(tpl_path):
            missing.append((route, tpl))

print(f'路由模板文件缺失: {len(missing)} 个')
for route, tpl in missing:
    print(f'  {route:55s} -> {tpl}')
