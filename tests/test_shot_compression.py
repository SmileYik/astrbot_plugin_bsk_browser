import pytest
from pathlib import Path
from PIL import Image
from bsk.shots import compress_and_optimize_image

def test_compress_normal_png(tmp_path: Path):
    raw_png = tmp_path / "raw.png"
    img = Image.new("RGBA", (1920, 1080), (255, 0, 0, 255))
    img.save(raw_png, format="PNG")
    
    opt_path = compress_and_optimize_image(raw_png, max_size_bytes=1_500_000)
    assert opt_path.exists()
    assert opt_path.suffix.lower() in (".jpg", ".jpeg")
    assert opt_path.stat().st_size <= 1_500_000
    with Image.open(opt_path) as opt_img:
        assert opt_img.format == "JPEG"
        assert opt_img.size == (1920, 1080)

def test_compress_super_tall_long_screenshot(tmp_path: Path):
    raw_png = tmp_path / "super_tall.png"
    img = Image.new("RGB", (3840, 12000), (200, 200, 200))
    img.save(raw_png, format="PNG")
    
    opt_path = compress_and_optimize_image(raw_png, max_size_bytes=1_500_000, max_width=1920)
    assert opt_path.exists()
    assert opt_path.stat().st_size <= 1_500_000
    with Image.open(opt_path) as opt_img:
        assert opt_img.width <= 1920
        # 3840 -> 1920, height 12000 -> 6000
        assert opt_img.height == 6000

def test_compress_rgba_white_background(tmp_path: Path):
    # 透明背景的 RGBA 图片转 JPEG 时必须填充白色底色，不能抛出 OSError
    raw_png = tmp_path / "transparent.png"
    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    img.save(raw_png, format="PNG")
    
    opt_path = compress_and_optimize_image(raw_png)
    assert opt_path.exists()
    with Image.open(opt_path) as opt_img:
        assert opt_img.mode == "RGB"
        # 采样左上角像素，应为白色底 (255, 255, 255)
        assert opt_img.getpixel((0, 0)) == (255, 255, 255)
