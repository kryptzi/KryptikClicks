import importlib.util
import os
import sys

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PROJECT_DIR, "KryptikClicks.py")


@pytest.fixture
def kc(tmp_path, monkeypatch):
    """Fresh import of KryptikClicks.py per test, with its data files redirected
    into a throwaway tmp_path so tests never touch the real capture/config files."""
    spec = importlib.util.spec_from_file_location("KryptikClicks_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "SCRIPT_DIR", str(tmp_path))
    monkeypatch.setattr(module, "TEMPLATE_PATH", str(tmp_path / "trigger_template.png"))
    monkeypatch.setattr(module, "TARGET_PATH", str(tmp_path / "click_target.txt"))
    monkeypatch.setattr(module, "CONFIG_PATH", str(tmp_path / "kryptikclicks_config.json"))
    return module
