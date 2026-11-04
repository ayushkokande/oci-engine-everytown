import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "python_api"
sys.path.insert(0, str(API))
os.environ.setdefault("OCI_LLM_MODE", "mock")
os.environ.setdefault("OCI_SEED_ON_STARTUP", "false")


@pytest.fixture
def in_scope():
    return ["PL", "FR", "FM", "ML"]


@pytest.fixture
def tmp_store(tmp_path):
    from app.store import LocalSubmissionStore
    return LocalSubmissionStore(tmp_path / "store")


@pytest.fixture
def client_factory(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.llm import MockClaude
    from app.main import create_app
    from app.store import LocalSubmissionStore

    def make(llm=None, store=None, in_scope=None, seed=False):
        settings = Settings(in_scope_domains=in_scope or ["PL", "FR", "FM", "ML"], llm_mode="mock",
                            local_store_dir=tmp_path / "store", seed_on_startup=seed,
                            frontend_dist=tmp_path / "no-dist")
        store = store or LocalSubmissionStore(tmp_path / "store")
        llm = llm or MockClaude()
        return TestClient(create_app(settings, store=store, llm=llm)), store, llm
    return make
