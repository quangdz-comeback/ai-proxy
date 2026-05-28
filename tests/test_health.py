def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"


def test_health_v1(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"


def test_health_no_auth_required(client):
    """Health endpoint should work without any Authorization header."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"
