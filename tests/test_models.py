"""Tests for /v1/models endpoint."""


EXPECTED_MODELS = {
    "mimo-v2.5-pro",
    "mimo-v2.5",
    "mimo-v2-pro",
    "mimo-v2-flash",
    "mimo-v2-omni",
}


def test_models_list_format(client):
    """GET /v1/models returns OpenAI-style list."""
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.get_json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)


def test_models_contains_all_mimo_models(client):
    """All 5 mimo models are present."""
    r = client.get("/v1/models")
    assert r.status_code == 200
    data = r.get_json()
    ids = {m["id"] for m in data["data"]}
    assert EXPECTED_MODELS.issubset(ids), f"Missing models: {EXPECTED_MODELS - ids}"


def test_models_entry_fields(client):
    """Each model entry has required OpenAI fields."""
    r = client.get("/v1/models")
    data = r.get_json()
    for model in data["data"]:
        assert "id" in model
        assert "object" in model
        assert model["object"] == "model"
        # OpenAI standard also includes created and owned_by
        assert "created" in model
        assert "owned_by" in model


def test_models_no_auth_required(client):
    """/v1/models works without authentication."""
    r = client.get("/v1/models")
    assert r.status_code == 200


def test_models_registry_resolve():
    """resolve_model accepts valid names and rejects invalid ones."""
    from models.registry import resolve_model, MODELS, MODEL_SET

    # All hardcoded names should be resolvable
    for name in MODELS:
        assert resolve_model(name) == name

    # Unknown model name should raise
    import pytest

    with pytest.raises(ValueError):
        resolve_model("gpt-4")

    with pytest.raises(ValueError):
        resolve_model("")


def test_models_registry_set_matches_list():
    """MODEL_SET should contain exactly the MODELS list."""
    from models.registry import MODELS, MODEL_SET

    assert MODEL_SET == set(MODELS)
    assert EXPECTED_MODELS.issubset(MODEL_SET)
