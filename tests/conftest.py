"""Every test runs with no OpenAI key and no way to reach the real OpenAI.

explain.py imports ENV_PATH by name, so a test that patches lta_static.ENV_PATH does not stop it reading the real .env.
A test that needs a key or a model reply sets it itself (explain.read_openai_api_key, explain._openai_complete).
With no key explain falls back to the fixed clause before any network call, in Demo Mode too.
"""

import pytest

import explain


@pytest.fixture(autouse=True)
def _no_real_openai(monkeypatch, tmp_path):
    monkeypatch.setattr(explain, "ENV_PATH", tmp_path / "no-openai.env")  # a file that does not exist
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    yield
