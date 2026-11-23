"""The seeded configuration validates and the averaging fixtures match their expected values."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


def test_config_validates():
    res = run("tools/validate_config.py")
    assert res.returncode == 0, res.stdout + res.stderr


def test_averaging_fixtures_reproduce():
    res = run("tests/fixtures/averaging/build_fixtures.py", "--check")
    assert res.returncode == 0, res.stdout + res.stderr
