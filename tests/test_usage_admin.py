"""Tests for /v1/usage and enhanced /v1/admin/* endpoints."""


class TestUsageEndpoint:
    """Test /v1/usage documentation endpoint."""

    def test_usage_returns_markdown(self, client):
        """GET /v1/usage returns markdown documentation."""
        r = client.get("/v1/usage")
        assert r.status_code == 200
        assert "text/markdown" in r.content_type
        body = r.get_data(as_text=True)
        assert "OpenGateway" in body
        assert "mimo" in body.lower() or "model" in body.lower()

    def test_usage_no_auth_required(self, client):
        """Usage endpoint does not require authentication."""
        r = client.get("/v1/usage")
        assert r.status_code == 200


class TestAdminIndex:
    """Test GET /v1/admin index."""

    def test_admin_index_returns_endpoints(self, client):
        """Admin index lists available endpoints."""
        r = client.get(
            "/v1/admin",
            headers={"Authorization": "Bearer sk-test-admin"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "endpoints" in data
        endpoints = data["endpoints"]
        assert "/v1/admin/api/create" in endpoints
        assert "/v1/admin/api/list" in endpoints
        assert "/v1/admin/api/edit" in endpoints
        assert "/v1/admin/api/delete" in endpoints
        assert "/v1/admin/logs" in endpoints


class TestAdminCreateKey:
    """Test enhanced key creation with name."""

    def _admin_headers(self):
        return {"Authorization": "Bearer sk-test-admin"}

    def test_create_key_with_name(self, client):
        """Create key with custom name."""
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "test-key-1", "uses": 50, "admin": False},
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "test-key-1"
        assert data["uses"] == 50
        assert data["admin"] is False
        assert data["key"].startswith("sk-test-")
        assert "created_at" in data

    def test_create_key_duplicate_name_fails(self, client):
        """Creating key with same name should fail."""
        client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "dup-name"},
        )
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "dup-name"},
        )
        assert r.status_code == 409

    def test_create_key_unlimited_uses(self, client):
        """Create key with no uses = unlimited (NULL)."""
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "unlimited-key"},
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["uses"] is None

    def test_create_key_negative_uses_is_unlimited(self, client):
        """Create key with uses=-1 = unlimited (NULL)."""
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "neg-uses", "uses": -1},
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["uses"] is None

    def test_create_key_via_query_params(self, client):
        """Create key using query params instead of JSON body."""
        r = client.post(
            "/v1/admin/api/create?name=query-key&uses=25",
            headers=self._admin_headers(),
        )
        assert r.status_code == 201
        data = r.get_json()
        assert data["name"] == "query-key"
        assert data["uses"] == 25


class TestAdminEditKey:
    """Test enhanced key editing."""

    def _admin_headers(self):
        return {"Authorization": "Bearer sk-test-admin"}

    def test_edit_key_name(self, client, user_key):
        """Edit key's display name."""
        r = client.post(
            "/v1/admin/api/edit",
            headers=self._admin_headers(),
            json={"key": user_key, "name": "renamed-key"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "renamed-key"

    def test_edit_nonexistent_key_fails(self, client):
        """Editing non-existent key returns 404."""
        r = client.post(
            "/v1/admin/api/edit",
            headers=self._admin_headers(),
            json={"key": "sk-nonexistent", "name": "foo"},
        )
        assert r.status_code == 404

    def test_edit_nothing_fails(self, client, user_key):
        """Edit with no updateable fields returns error."""
        r = client.post(
            "/v1/admin/api/edit",
            headers=self._admin_headers(),
            json={"key": user_key},
        )
        assert r.status_code == 400

    def test_edit_key_via_patch(self, client, user_key):
        """Edit works with PATCH method too."""
        r = client.patch(
            "/v1/admin/api/edit",
            headers=self._admin_headers(),
            json={"key": user_key, "uses": 999},
        )
        assert r.status_code == 200


class TestAdminDeleteKey:
    """Test key deletion by name or key."""

    def _admin_headers(self):
        return {"Authorization": "Bearer sk-test-admin"}

    def test_delete_by_name(self, client):
        """Delete key by name."""
        # Create a key with known name
        r = client.post(
            "/v1/admin/api/create",
            headers=self._admin_headers(),
            json={"name": "deleteme"},
        )
        assert r.status_code == 201

        # Delete by name
        r = client.post(
            "/v1/admin/api/delete",
            headers=self._admin_headers(),
            json={"name": "deleteme"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert "deleted" in data
        assert data["deleted"]["name"] == "deleteme"

    def test_delete_nonexistent_fails(self, client):
        """Deleting non-existent key returns 404."""
        r = client.post(
            "/v1/admin/api/delete",
            headers=self._admin_headers(),
            json={"key": "sk-nonexistent"},
        )
        assert r.status_code == 404

    def test_delete_no_identifier_fails(self, client):
        """Delete without name or key returns 400."""
        r = client.post(
            "/v1/admin/api/delete",
            headers=self._admin_headers(),
            json={},
        )
        assert r.status_code == 400

    def test_delete_via_delete_method(self, client, user_key):
        """Delete works with HTTP DELETE method."""
        r = client.delete(
            "/v1/admin/api/delete",
            headers=self._admin_headers(),
            json={"key": user_key},
        )
        assert r.status_code == 200


class TestAdminLogs:
    """Test request logs endpoint."""

    def _admin_headers(self):
        return {"Authorization": "Bearer sk-test-admin"}

    def test_logs_returns_list(self, client):
        """Logs endpoint returns a list of log entries."""
        r = client.get("/v1/admin/logs", headers=self._admin_headers())
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_logs_with_limit(self, client):
        """Logs endpoint respects limit parameter."""
        r = client.get(
            "/v1/admin/logs?limit=5",
            headers=self._admin_headers(),
        )
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)

    def test_logs_with_key_filter(self, client):
        """Logs endpoint filters by key."""
        r = client.get(
            "/v1/admin/logs?key=sk-test-somekey",
            headers=self._admin_headers(),
        )
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
