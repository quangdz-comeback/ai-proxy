"""Tests for auth middleware and API key CRUD operations."""
import json


class TestAuthMiddleware:
    """Test the before_request auth middleware."""

    def test_no_api_key_returns_401(self, client):
        """Request without Authorization header should return 401."""
        r = client.get("/v1/status")
        assert r.status_code == 401
        data = r.get_json()
        assert "error" in data

    def test_invalid_api_key_returns_401(self, client):
        """Request with a key not in the DB should return 401."""
        r = client.get(
            "/v1/status",
            headers={"Authorization": "Bearer sk-nonexistent-key"},
        )
        assert r.status_code == 401

    def test_malformed_auth_header_returns_401(self, client):
        """Request with malformed Authorization header returns 401."""
        r = client.get(
            "/v1/status",
            headers={"Authorization": "NotBearer sk-test-admin"},
        )
        assert r.status_code == 401

    def test_valid_key_passes_auth(self, client, user_key):
        """Request with a valid key should pass auth."""
        r = client.get(
            "/v1/status",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert r.status_code == 200

    def test_exhausted_key_returns_429(self, client):
        """Key with uses=0 should return 429 Too Many Requests."""
        from auth.api_keys import create_key

        key = create_key(uses=0, admin=0)
        r = client.get(
            "/v1/status",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert r.status_code == 429


class TestAdminCRUD:
    """Test admin API key CRUD endpoints."""

    def _admin_headers(self):
        return {"Authorization": "Bearer sk-test-admin"}

    def test_create_key(self, client):
        """Admin can create a new API key."""
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"uses": 50, "admin": 0},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "key" in data
        assert data["key"].startswith("sk-test-")

    def test_list_keys(self, client, user_key):
        """Admin can list all API keys."""
        r = client.get(
            "/v1/admin/api/list",
            headers=self._admin_headers(),
        )
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # Each key entry should have expected fields
        key_entry = next(k for k in data if k["key"] == user_key)
        assert key_entry["uses"] == 100
        assert key_entry["admin"] == 0

    def test_edit_key(self, client, user_key):
        """Admin can edit an API key's properties."""
        r = client.post(
            "/v1/admin/api/edit",
            headers=self._admin_headers(),
            json={"key": user_key, "uses": 200},
        )
        assert r.status_code == 200

        # Verify the edit took effect
        from auth.api_keys import get_key

        row = get_key(user_key)
        assert row["uses"] == 200

    def test_delete_key(self, client, user_key):
        """Admin can delete an API key."""
        r = client.post(
            "/v1/admin/api/delete",
            headers=self._admin_headers(),
            json={"key": user_key},
        )
        assert r.status_code == 200

        # Verify the key is gone
        from auth.api_keys import get_key

        row = get_key(user_key)
        assert row is None

    def test_create_key_default_values(self, client):
        """Creating a key with no body uses defaults."""
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "key" in data
        assert data["key"].startswith("sk-test-")

    def test_admin_routes_reject_non_admin(self, client, user_key):
        """Non-admin keys should be rejected from admin routes with 403."""
        headers = {"Authorization": f"Bearer {user_key}"}

        # Create
        r = client.post(
            "/v1/admin/api/create",
            headers=headers,
            json={"uses": 10},
        )
        assert r.status_code == 403

        # List
        r = client.get("/v1/admin/api/list", headers=headers)
        assert r.status_code == 403

        # Edit
        r = client.post(
            "/v1/admin/api/edit",
            headers=headers,
            json={"key": user_key, "uses": 999},
        )
        assert r.status_code == 403

        # Delete
        r = client.post(
            "/v1/admin/api/delete",
            headers=headers,
            json={"key": user_key},
        )
        assert r.status_code == 403


class TestStatusEndpoint:
    """Test /v1/status endpoint for checking own key info."""

    def test_status_returns_own_key_info(self, client, user_key):
        """User can check their own key info via /v1/status."""
        r = client.get(
            "/v1/status",
            headers={"Authorization": f"Bearer {user_key}"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["key"] == user_key
        assert data["uses"] == 100
        assert data["admin"] == 0

    def test_status_returns_admin_flag(self, client, admin_key):
        """Admin key shows admin flag in status."""
        r = client.get(
            "/v1/status",
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["admin"] == 1
