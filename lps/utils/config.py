import importlib.resources
from pathlib import Path

import yaml

_CONFIG = None

def config_path() -> Path:
    return importlib.resources.files("lps").parent / "conf"

def load_configuration(flavor: str):
    global _CONFIG
    assert _CONFIG is None, "must be run once"

    conf_path = config_path()
    conf_file = conf_path / f"{flavor}.yaml"

    assert conf_file.is_file(), "config file not found"

    _CONFIG = yaml.safe_load(conf_file.read_text())

def logging_config():
    assert _CONFIG is not None, "config must be loaded"
    assert 'logging' in _CONFIG, "incorrect configuration"

    return _CONFIG['logging']

def get_config():
    return _CONFIG
