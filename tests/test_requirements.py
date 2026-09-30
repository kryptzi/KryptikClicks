import os
import re

from conftest import PROJECT_DIR


def test_every_requirement_is_pinned_to_an_exact_version():
    # Unpinned deps meant a fresh install could pull versions nobody tested (mss is
    # already deprecating the mss.mss() this app calls everywhere).
    with open(os.path.join(PROJECT_DIR, "requirements.txt"), encoding="utf-8") as f:
        lines = [line.split("#")[0].strip() for line in f]
    requirements = [line for line in lines if line]

    assert requirements
    unpinned = [r for r in requirements if not re.fullmatch(r"[A-Za-z0-9_.\-\[\]]+==[\w.]+", r)]
    assert unpinned == []
