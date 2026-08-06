import pytest

import mousewatch.icon_factory as icon_factory


def test_battery_color_threshold_logic():
    assert icon_factory._battery_color(50, 20) == "#4CAF50"
    assert icon_factory._battery_color(20, 20) == "#F44336"


def test_render_battery_icon_resizes_to_target_size():
    img = icon_factory._render_battery_icon(
        42,
        20,
        size=128,
        ring_box=[10, 10, 117, 117],
        ring_width=4,
        font_names=["missing-font.ttf"],
        font_size_lt100=30,
        font_size_100=24,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
        target_size=64,
    )

    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_create_battery_icon_returns_64_square_image():
    img = icon_factory.create_battery_icon(88, 20)
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_create_unknown_battery_icon_returns_64_square_image():
    img = icon_factory.create_unknown_battery_icon()
    assert img.size == (64, 64)
    assert img.mode == "RGBA"


def test_create_windows_battery_icons_return_64_square_images():
    img_known = icon_factory.create_windows_battery_icon(33, 15)
    img_unknown = icon_factory.create_windows_unknown_battery_icon()

    assert img_known.size == (64, 64)
    assert img_unknown.size == (64, 64)


def test_qt_icon_builders_raise_on_windows(monkeypatch):
    monkeypatch.setattr(icon_factory, "IS_WINDOWS", True)

    with pytest.raises(RuntimeError, match="Qt icon generation is not supported on Windows"):
        icon_factory.create_qt_battery_icon(40, 20)

    with pytest.raises(RuntimeError, match="Qt icon generation is not supported on Windows"):
        icon_factory.create_qt_unknown_battery_icon()
