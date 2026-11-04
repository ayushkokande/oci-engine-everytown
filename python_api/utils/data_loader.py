"""Load and provide access to questions.json data."""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "questions.json")
_cache = None


def load_data():
    global _cache
    if _cache is None:
        with open(os.path.abspath(_DATA_PATH)) as f:
            _cache = json.load(f)
    return _cache


def get_domains():
    return load_data()["domains"]


def get_stage_weights():
    return load_data()["stage_weights"]


def get_stage_names():
    return load_data()["stage_names"]
