import json
from pathlib import Path

from adapters.base import CLIAdapter

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "agents.json"


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_adapters(cfg):
    return {n: CLIAdapter(n, a) for n, a in cfg["agents"].items()}
