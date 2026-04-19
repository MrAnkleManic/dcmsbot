"""Test isolation fixtures.

Two modules (`answers_store`, `usage_store`) persist side-effects from
`/query` to the filesystem under `data/cache/...`. Without redirecting
those paths, any test that drives the `query()` handler through its
full flow — e.g. `test_app_regressions.test_query_llm_path_*` — will
happily pollute the real `data/cache/` directory during CI or local
runs. An autouse fixture moves both stores into a per-test tmp_path
so tests are hermetic by default.

Tests that want to inspect store contents can still do so by reading
their own `tmp_path` — no change needed since tmp_path is a builtin
pytest fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _redirect_side_effect_stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect archive + usage stores into the per-test tmp_path.

    Patches the module-level DEFAULT_STORE_DIR *and* the `app` module's
    local bindings for the store functions so callers that closed over
    the original defaults (via default-argument binding) also land in
    the isolated location.
    """
    import backend.core.answers_store as answers_store_module
    import backend.core.usage_store as usage_store_module
    from backend import app as app_module

    answers_dir = tmp_path / "answers"
    usage_dir = tmp_path / "api_usage"
    monkeypatch.setattr(answers_store_module, "DEFAULT_STORE_DIR", answers_dir)
    monkeypatch.setattr(usage_store_module, "DEFAULT_STORE_DIR", usage_dir)

    # Wrap the app.py call sites so they always pass store_dir=<tmp>,
    # defeating Python's late-binding default-argument gotcha.
    def _append_answer(*, request_id, query_text, answer, citations,
                       evidence_pack, api_usage=None, timestamp=None):
        return answers_store_module.append_answer_record(
            request_id=request_id, query_text=query_text, answer=answer,
            citations=citations, evidence_pack=evidence_pack,
            api_usage=api_usage, timestamp=timestamp, store_dir=answers_dir,
        )

    def _list_answers(*, since=None, until=None, q=None, limit=50):
        return answers_store_module.list_answers(
            since=since, until=until, q=q, limit=limit, store_dir=answers_dir,
        )

    def _load_answer(request_id):
        return answers_store_module.load_answer_record(
            request_id, store_dir=answers_dir,
        )

    def _append_usage(*, request_id, query_text, summary, timestamp=None):
        return usage_store_module.append_usage_record(
            request_id=request_id, query_text=query_text, summary=summary,
            timestamp=timestamp, store_dir=usage_dir,
        )

    monkeypatch.setattr(app_module, "append_answer_record", _append_answer)
    monkeypatch.setattr(app_module, "list_answers", _list_answers)
    monkeypatch.setattr(app_module, "load_answer_record", _load_answer)
    monkeypatch.setattr(app_module, "append_usage_record", _append_usage)
