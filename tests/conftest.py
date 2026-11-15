from pathlib import Path

def pytest_configure(config):
    (Path(__file__).resolve().parents[1] / 'tmp').mkdir(exist_ok=True)
