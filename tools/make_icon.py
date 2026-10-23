"""生成应用图标（.ico + PNG）。

设计：
  深色圆角底 (#1D1D1F) + 白色 "PK" 字母，跟 UI 的克制风格一致。
  不用微信赞赏码（那是收款码，不适合当应用图标）。

产出：assets/app.ico（多尺寸）、assets/app.png（256 预览）
"""
import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(r"E:\code\单词pk\assets")
OUT.mkdir(parents=True, exist_ok=True)

SIZES = [16, 24, 32, 48, 64, 128, 256]


def find_font(size: int):
    """找一个能渲染的粗体字。"""
    cands = [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
    ]
    for p in cands:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def make(size: int) -> Image.Image:
    """按目标尺寸渲染，保证小图也清晰（不是缩放大图）。"""
    s = size * 4          # 超采样，缩小后边缘更干净
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底：深色 #1D1D1F
    pad = int(s * 0.06)
    radius = int(s * 0.22)
    d.rounded_rectangle(
        [pad, pad, s - pad, s - pad],
        radius=radius,
        fill=(29, 29, 31, 255),
    )

    # "PK" 白字，居中
    txt = "PK"
    # 字号按边长比例，再按实际包围盒微调居中
    fs = int(s * 0.46)
    font = find_font(fs)
    bbox = d.textbbox((0, 0), txt, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (s - tw) / 2 - bbox[0]
    y = (s - th) / 2 - bbox[1]
    d.text((x, y), txt, font=font, fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    imgs = [make(z) for z in SIZES]
    ico = OUT / "app.ico"
    # PIL 保存多尺寸 ico：第一个当主图，其余进 frames
    imgs[-1].save(ico, format="ICO", sizes=[(z, z) for z in SIZES])
    print(f"已生成 {ico}  ({ico.stat().st_size // 1024} KB)")

    png = OUT / "app.png"
    imgs[-1].save(png, format="PNG")
    print(f"已生成 {png}  ({png.stat().st_size // 1024} KB)")

    # 顺手导一个 32x32 的供界面用
    imgs[3].save(OUT / "app-32.png", format="PNG")
    print(f"已生成 {OUT / 'app-32.png'}")


if __name__ == "__main__":
    main()
