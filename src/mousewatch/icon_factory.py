from io import BytesIO

try:
    from .mw_platform import IS_WINDOWS
except ImportError:
    from mw_platform import IS_WINDOWS


FONT_ARIAL = "arial.ttf"
FONT_DEJAVU_BOLD = "DejaVuSans-Bold.ttf"


def _battery_color(level: int, threshold: int) -> str:
    """Return hex color based on the configured battery threshold."""
    if level > threshold:
        return "#4CAF50"
    return "#F44336"


def _render_battery_icon(
    level: int,
    threshold: int,
    *,
    size: int,
    ring_box: list[int],
    ring_width: int,
    font_names: list[str],
    font_size_lt100: int,
    font_size_100: int,
    stroke_width: int,
    stroke_fill: tuple[int, int, int, int],
    text_override: str | None = None,
    force_red: bool = False,
    target_size: int | None = None,
):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = "#F44336" if force_red else _battery_color(level, threshold)
    draw.ellipse(ring_box, outline=color, width=ring_width)

    text = text_override if text_override is not None else str(level)
    if text_override is not None:
        font_size = font_size_lt100
    else:
        font_size = font_size_lt100 if level < 100 else font_size_100
    font = None
    for font_name in font_names:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text(
        (tx, ty),
        text,
        fill=(255, 255, 255, 255),
        font=font,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )

    if target_size and target_size != size:
        return img.resize((target_size, target_size), Image.Resampling.LANCZOS)
    return img


def create_battery_icon(level: int, threshold: int):
    """Generate a 64x64 PIL Image showing battery percentage in a colored ring."""
    size = 256
    return _render_battery_icon(
        level,
        threshold,
        size=size,
        ring_box=[32, 32, size - 33, size - 33],
        ring_width=4,
        font_names=[FONT_DEJAVU_BOLD, FONT_ARIAL],
        font_size_lt100=116,
        font_size_100=92,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 220),
        target_size=64,
    )


def create_unknown_battery_icon():
    """Generate a 64x64 disconnected-state icon with a red ring and '?' label."""
    size = 256
    return _render_battery_icon(
        0,
        100,
        size=size,
        ring_box=[32, 32, size - 33, size - 33],
        ring_width=4,
        font_names=[FONT_DEJAVU_BOLD, FONT_ARIAL],
        font_size_lt100=116,
        font_size_100=92,
        stroke_width=3,
        stroke_fill=(0, 0, 0, 220),
        text_override="?",
        force_red=True,
        target_size=64,
    )


def create_qt_battery_icon(level: int, threshold: int):
    """Convert the generated PIL badge into a Qt icon."""
    if IS_WINDOWS:
        raise RuntimeError("Qt icon generation is not supported on Windows")

    from PIL import Image as PILImage
    try:
        from .mw_platform import QApplication, QIcon, QImage, QPixmap
    except ImportError:
        from mw_platform import QApplication, QIcon, QImage, QPixmap

    app = QApplication.instance() or QApplication([])
    _ = app

    icon = QIcon()
    base_image = create_battery_icon(level, threshold)
    for size in (16, 22, 24, 32, 48, 64):
        image = base_image.resize((size, size), PILImage.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        qimage = QImage.fromData(buffer.getvalue(), "PNG")
        icon.addPixmap(QPixmap.fromImage(qimage))
    return icon


def create_qt_unknown_battery_icon():
    """Convert the disconnected-state PIL badge into a Qt icon."""
    if IS_WINDOWS:
        raise RuntimeError("Qt icon generation is not supported on Windows")

    from PIL import Image as PILImage
    try:
        from .mw_platform import QApplication, QIcon, QImage, QPixmap
    except ImportError:
        from mw_platform import QApplication, QIcon, QImage, QPixmap

    app = QApplication.instance() or QApplication([])
    _ = app

    icon = QIcon()
    base_image = create_unknown_battery_icon()
    for size in (16, 22, 24, 32, 48, 64):
        image = base_image.resize((size, size), PILImage.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        qimage = QImage.fromData(buffer.getvalue(), "PNG")
        icon.addPixmap(QPixmap.fromImage(qimage))
    return icon


def create_windows_battery_icon(level: int, threshold: int):
    """Generate a Windows tray icon matching the Linux thin-circle style."""
    size = 64
    return _render_battery_icon(
        level,
        threshold,
        size=size,
        ring_box=[1, 1, size - 2, size - 2],
        ring_width=3,
        font_names=[FONT_ARIAL],
        font_size_lt100=45,
        font_size_100=36,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 200),
    )


def create_windows_unknown_battery_icon():
    """Generate a Windows tray icon for disconnected standby state."""
    size = 64
    return _render_battery_icon(
        0,
        100,
        size=size,
        ring_box=[1, 1, size - 2, size - 2],
        ring_width=3,
        font_names=[FONT_ARIAL],
        font_size_lt100=45,
        font_size_100=36,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 200),
        text_override="?",
        force_red=True,
    )
