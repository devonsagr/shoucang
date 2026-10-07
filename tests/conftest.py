"""Make the isolated pytest temp parent available in a fresh clone."""
from pathlib import Path

def pytest_configure(config):
    (Path(__file__).resolve().parents[1]/'tmp').mkdir(exist_ok=True)
