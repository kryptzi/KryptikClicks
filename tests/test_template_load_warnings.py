def test_warns_when_template_file_is_corrupted_and_unreadable(kc):
    # A 0-byte / non-image file at TEMPLATE_PATH makes cv2.imread return None.
    # Detector.load() should log a warning about it, same as it already does
    # for a corrupted click_target.txt, instead of failing silently.
    with open(kc.TEMPLATE_PATH, "wb") as f:
        f.write(b"not a real png")

    logs = []
    kc.Detector(kc.load_config(), log=logs.append)

    assert any("trigger_template.png" in m and "corrupted" in m.lower() for m in logs), logs
