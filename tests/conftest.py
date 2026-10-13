"""Every test runs with no OpenAI key and no way to reach the real OpenAI.

explain.py imports ENV_PATH by name, so a test that patches lta_static.ENV_PATH does not stop it reading the real .env.
A test that needs a key or a model reply sets it itself (explain.read_openai_api_key, explain._openai_complete).
With no key explain falls back to the fixed clause before any network call, in Demo Mode too.
"""

import pytest

import config
import explain


@pytest.fixture(autouse=True)
def _no_real_openai(monkeypatch, tmp_path):
    monkeypatch.setattr(explain, "ENV_PATH", tmp_path / "no-openai.env")  # a file that does not exist
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_EXPLANATION_ENABLED", raising=False)  # the model path is off unless a test turns it on


@pytest.fixture(autouse=True, scope="module")
def _no_bus_traffic_factor(request):
    """The bus traffic factor (config.BUS_PEAK_FACTOR) depends on the time a bus leg starts, and many fixtures here are
    stamped with the machine clock. So that no older test depends on the time of day, they run with the factor at 1.0
    (the behaviour they were written for). It is module scoped on purpose: a module-scoped browser fixture builds its
    page before any function-scoped fixture runs, and would otherwise see the real factor in the weekday peak hours. A
    module that tests the factor sets USES_BUS_TRAFFIC = True and pins its own clock."""
    if getattr(request.module, "USES_BUS_TRAFFIC", False):
        yield
        return
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "BUS_PEAK_FACTOR", 1.0)
        yield
