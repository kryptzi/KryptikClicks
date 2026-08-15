import os

from PIL import Image


def test_save_capture_writes_template_and_target(kc):
    img = Image.new("RGB", (200, 200), (10, 20, 30))
    w, h = kc.save_capture((10, 10, 60, 40), (150, 175), img)
    assert (w, h) == (50, 30)
    assert kc.Detector(kc.load_config(), log=lambda m: None).template is not None
    with open(kc.TARGET_PATH) as f:
        assert f.read().strip() == "150,175"


def test_save_capture_skips_target_file_when_no_click_point_given(kc):
    # Targeted+cursor mode doesn't need a captured click point - the capture
    # flow skips that step entirely, so target_point may legitimately be None.
    img = Image.new("RGB", (200, 200), (10, 20, 30))
    kc.save_capture((10, 10, 60, 40), None, img)
    assert not os.path.exists(kc.TARGET_PATH)
