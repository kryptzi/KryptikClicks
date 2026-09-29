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


def test_analyze_color_trigger_ignores_dark_pixels_with_deceptively_high_saturation_ratio(kc):
    # Real bug: a near-black background pixel like (20, 22, 34) has a HIGH
    # saturation *ratio* ((max-min)/max) purely because it's dark, even though
    # it's visually indistinguishable from black/background to a human - not
    # a real "distinctive foreground color" the way bright purple text is.
    # Saturation alone can't tell them apart; a minimum brightness floor can.
    # This previously caused a captured trigger to resolve to near-black and
    # then match almost the entire (dark-themed) window as "the trigger".
    img = Image.new("RGB", (6, 6), (20, 22, 34))
    for x, y in [(2, 2), (3, 2), (2, 3), (3, 3)]:
        img.putpixel((x, y), (127, 60, 179))

    target_color, pixel_count = kc.analyze_color_trigger(img)

    assert target_color == (127, 60, 179)
    assert pixel_count == 4


class _FakeSct:
    """Stands in for an mss instance: grab() returns a BGRA frame of one flat color."""

    def __init__(self, bgra=(0, 0, 0, 255)):
        self.bgra = bgra

    def grab(self, region):
        frame = np.empty((region["height"], region["width"], 4), dtype=np.uint8)
        frame[:] = self.bgra
        return frame


def test_color_mode_never_matches_a_frame_with_zero_target_pixels(kc):
    # load_config falls back to min_color_pixels=0 when the saved value is missing or
    # corrupt, and a frame with no target-colored pixels scores 0 - "0 >= 0" used to
    # count as a match, so an all-black screen triggered nonstop clicking.
    cfg = kc.load_config()
    cfg.update(detection_method="color", target_color=[102, 46, 143], min_color_pixels=0)
    d = kc.Detector(cfg, log=lambda m: None)

    region = {"left": 0, "top": 0, "width": 50, "height": 40}

    assert d._find_match_in(_FakeSct(bgra=(0, 0, 0, 255)), region) is None
    # ...while a frame that really is the target color still matches.
    assert d._find_match_in(_FakeSct(bgra=(143, 46, 102, 255)), region) is not None
