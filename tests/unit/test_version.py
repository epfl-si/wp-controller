import re

from version import SETUP_PY, read_version


def test_reads_the_version_passed_to_setup():
    with open(SETUP_PY) as f:
        expected = re.search(r'version="([^"]+)"', f.read()).group(1)

    assert read_version() == expected


def test_reads_it_without_executing_setup_py(tmp_path):
    setup_py = tmp_path / "setup.py"
    setup_py.write_text('raise SystemExit("must not run")\nsetup(name="x", version="9.8.7")\n')

    assert read_version(str(setup_py)) == "9.8.7"


def test_unknown_when_setup_py_is_missing_or_has_no_version(tmp_path):
    assert read_version(str(tmp_path / "nope.py")) == "unknown"

    no_version = tmp_path / "setup.py"
    no_version.write_text('setup(name="x")\n')
    assert read_version(str(no_version)) == "unknown"

    broken = tmp_path / "broken.py"
    broken.write_text("setup(name=\n")
    assert read_version(str(broken)) == "unknown"
