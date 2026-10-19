#!/usr/bin/env python3
"""从 R11 单色标志（assets/brand/on-hold-mono-256.png 的透明度）生成 favicon 全套。

纸白底 = style.css --bg #ffffff，墨黑 = --ink #171c1f；不改标志造型。
16/32 让标志尽量撑满，并对打结处的白色分隔线做形态学膨胀（加粗），保证小尺寸可辨认。
用法：python3 scripts/build-favicons.py（需要 Pillow）
"""
import base64, io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "site" / "assets" / "brand"
PAPER, INK = (0xFF, 0xFF, 0xFF), (0x17, 0x1C, 0x1F)
SS = 8  # 超采样倍数

src = Image.open(BRAND / "on-hold-mono-256.png").convert("RGBA").split()[3]
MARK = src.crop(src.getbbox())

# size: (边距占比, 圆角占比, 线条加粗半径[输出像素]；负值=加粗白色分隔线)；radius None = 满底方块
SPEC = {16: (0.02, 0.22, -0.35), 32: (0.04, 0.22, -0.25), 48: (0.07, 0.22, -0.12)}

def render(size, margin, radius, dilate, full=False):
    S = size * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full:
        d.rectangle([0, 0, S, S], fill=PAPER + (255,))
    else:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * radius), fill=PAPER + (255,))
    box = S * (1 - 2 * margin)
    k = box / max(MARK.size)
    m = MARK.resize((round(MARK.width * k), round(MARK.height * k)), Image.LANCZOS)
    r = round(dilate * SS)
    if r > 0:  # 膨胀墨色：加粗线条
        m = m.filter(ImageFilter.MaxFilter(2 * r + 1))
    elif r < 0:  # 膨胀透明缝：加粗打结处的白色分隔线和声孔，小尺寸不糊成一团
        m = m.filter(ImageFilter.MinFilter(-2 * r + 1))
    ink = Image.new("RGBA", m.size, INK + (255,))
    img.paste(ink, ((S - m.width) // 2, (S - m.height) // 2), m)
    return img.resize((size, size), Image.LANCZOS)

def small(size):
    m, rad, dil = SPEC[size]
    return render(size, m, rad, dil)

def main():
    small(32).save(BRAND / "favicon-32.png", optimize=True)
    small(16).save(BRAND / "favicon-16.png", optimize=True)
    ico = [small(s) for s in (16, 32, 48)]
    ico[2].save(ROOT / "site" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=ico[:2])
    # apple-touch-icon / manifest：满底方块，系统自己裁圆角
    render(180, 0.14, 0, 0, full=True).convert("RGB").save(BRAND / "favicon-180.png", optimize=True)
    for s in (192, 512):
        render(s, 0.16, 0, 0, full=True).convert("RGB").save(BRAND / f"icon-{s}.png", optimize=True)
    # favicon.svg / logo.svg：圆角纸白底 + 墨黑标志（位图内嵌）
    layer = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
    S = 360; box = S * 0.8; k = box / max(MARK.size)
    mm = MARK.resize((round(MARK.width * k), round(MARK.height * k)), Image.LANCZOS)
    layer.paste(Image.new("RGBA", mm.size, INK + (255,)), ((S - mm.width) // 2, (S - mm.height) // 2), mm)
    buf = io.BytesIO(); layer.save(buf, "PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180" width="180" height="180" role="img" aria-label="DeepSuck logo">
<title>DeepSuck</title>
<!-- R11 品牌单色标志（打结听筒，有声孔），纸白圆角底 + 墨黑标志；由 scripts/build-favicons.py 生成。保留本文件供 voice 服务 /static/logo.svg 与 README 使用 -->
<rect width="180" height="180" rx="40" fill="#ffffff"/>
<image width="180" height="180" href="data:image/png;base64,{b64}"/>
</svg>
'''
    for p in (ROOT / "site" / "favicon.svg", ROOT / "site" / "assets" / "logo.svg"):
        p.write_text(svg)

if __name__ == "__main__":
    main()
