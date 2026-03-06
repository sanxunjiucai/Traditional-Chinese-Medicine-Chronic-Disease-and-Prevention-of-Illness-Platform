"""
生成插件图标（需要 Pillow 库，或使用纯 Python struct 生成最小 PNG）
运行此脚本以生成图标文件
"""
import struct
import zlib
import os

def make_png(size, bg_color=(22, 163, 74), fg_color=(255, 255, 255)):
    """生成简单的绿色圆形图标"""
    w, h = size, size
    # 创建像素数据
    pixels = []
    cx, cy = w / 2, h / 2
    r_outer = w / 2 - 1
    r_inner = w / 2 * 0.55  # 内圆（白色）

    for y in range(h):
        row = []
        for x in range(w):
            dx = x - cx + 0.5
            dy = y - cy + 0.5
            dist = (dx*dx + dy*dy) ** 0.5
            if dist <= r_outer:
                if dist <= r_inner:
                    row.extend([*fg_color, 255])  # RGBA 白色内圆
                else:
                    row.extend([*bg_color, 255])  # RGBA 绿色外环
            else:
                row.extend([0, 0, 0, 0])  # 透明
        pixels.append(bytes(row))

    # PNG 头
    def chunk(name, data):
        c = struct.pack('>I', len(data)) + name + data
        return c + struct.pack('>I', zlib.crc32(c[4:]) & 0xffffffff)

    signature = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    # 实际使用 RGBA（color type 6）
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))

    raw = b''.join(b'\x00' + row for row in pixels)
    idat = chunk(b'IDAT', zlib.compress(raw, 9))
    iend = chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for size in [16, 48, 128]:
        data = make_png(size)
        path = os.path.join(script_dir, f'icon{size}.png')
        with open(path, 'wb') as f:
            f.write(data)
        print(f'Generated icon{size}.png ({len(data)} bytes)')
    print('Done.')
