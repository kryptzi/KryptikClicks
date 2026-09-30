import fnmatch
import os

from conftest import PROJECT_DIR


def test_every_per_user_file_the_app_writes_is_gitignored():
    # Run from source, captures/settings live in the git checkout. The config (and so
    # its backups) holds the target window title - e.g. a game account name - and the
    # repo is public, so none of these may be picked up by `git add -A`.
    with open(os.path.join(PROJECT_DIR, ".gitignore"), encoding="utf-8") as f:
        patterns = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    user_files = [
        "trigger_template.png",
        "click_target.txt",
        "kryptikclicks_config.json",
        "kryptikclicks_config.json.tmp",
        "kryptikclicks_config.json.unreadable-20260929-120000",
    ]

    not_ignored = [name for name in user_files if not any(fnmatch.fnmatch(name, p) for p in patterns)]

    assert not_ignored == []
