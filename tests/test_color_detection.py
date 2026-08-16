import numpy as np
import pytest
from PIL import Image


def test_count_color_pixels_matches_within_tolerance(kc):
    arr = np.array([
        [[100, 100, 100], [118, 52, 171]],
        [[120, 50, 170], [200, 200, 200]],
    ], dtype=np.uint8)
    mask = kc.count_color_pixels(arr, (118, 52, 171), tolerance=5)
    assert mask.tolist() == [[False, True], [True, False]]


def test_count_color_pixels_zero_tolerance_requires_exact_match(kc):
    arr = np.array([[[118, 52, 171], [119, 52, 171]]], dtype=np.uint8)
    mask = kc.count_color_pixels(arr, (118, 52, 171), tolerance=0)
    assert mask.tolist() == [[True, False]]


def test_analyze_color_trigger_picks_the_saturated_color_over_gray_background(kc):
    # Mostly gray/background pixels, with a small purple cluster - like a
    # tight drag-select around trigger text that includes a bit of background.
    img = Image.new("RGB", (4, 4), (110, 96, 98))
    for x, y in [(1, 1), (2, 1), (1, 2), (2, 2)]:
        img.putpixel((x, y), (118, 52, 171))

    target_color, pixel_count = kc.analyze_color_trigger(img)

    assert pixel_count == 4
    # median of the 4 identical purple pixels is exactly that color
    assert target_color == (118, 52, 171)


def test_analyze_color_trigger_falls_back_to_whole_image_when_nothing_saturated(kc):
    # An all-gray capture (no saturated pixels) shouldn't crash - falls back
    # to using every pixel rather than an empty selection.
    img = Image.new("RGB", (3, 3), (128, 128, 128))
    target_color, pixel_count = kc.analyze_color_trigger(img)
    assert target_color == (128, 128, 128)
    assert pixel_count == 9
