import importlib.util
import os
import sys

from conftest import MODULE_PATH


def _fresh_import():
    spec = importlib.util.spec_from_file_location("KryptikClicks_data_dir_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_from_source_user_data_lives_next_to_the_script():
    module = _fresh_import()

    assert os.path.dirname(module.CONFIG_PATH) == module.SCRIPT_DIR
    assert os.path.dirname(module.TEMPLATE_PATH) == module.SCRIPT_DIR
    assert os.path.dirname(module.TARGET_PATH) == module.SCRIPT_DIR


def test_the_onefile_exe_keeps_user_data_somewhere_that_survives_exit(tmp_path, monkeypatch):
    # A --onefile exe runs from a temp _MEI folder (where __file__ points) that's
    # deleted on exit - saving captures/settings next to __file__ lost them every run.
    meipass = tmp_path / "_MEI12345"
    appdata = tmp_path / "AppData" / "Roaming"
    meipass.mkdir()
    appdata.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))

    module = _fresh_import()

    data_dir = str(appdata / "KryptikClicks")
    assert os.path.isdir(data_dir)
    for path in (module.CONFIG_PATH, module.TEMPLATE_PATH, module.TARGET_PATH):
        assert os.path.dirname(path) == data_dir
    # Bundled assets still come from the unpacked bundle.
    assert module.resource_path("assets", "icon.ico").startswith(str(meipass))
