import json
from pathlib import Path

from adapters.base import CLIAdapter
from adapters.mock import MockAdapter

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "agents.json"


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_adapters(cfg, mock=False):
    cls = MockAdapter if mock else CLIAdapter
    return {n: cls(n, a) for n, a in cfg["agents"].items()}
