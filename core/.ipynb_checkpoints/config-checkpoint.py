"""
Config loading helpers for the stock enrichment notebook.
"""

import json
import os


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config.json",
)


def load_app_config(config_path=None):
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    required = ["tenant_id", "api_url", "update_url", "elastic_url", "elastic_scroll_api"]
    missing = [key for key in required if not str(config.get(key, "")).strip()]
    if missing:
        raise ValueError(f"Missing required config keys in {path}: {missing}")

    return config
