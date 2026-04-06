"""
tests/test_web.py — API endpoint tests for the optional web backend.
======================================================================
Uses FastAPI's built-in TestClient (which wraps httpx).

Isolation rule
--------------
``pytest.importorskip("fastapi")`` at the top of this module guarantees that
if the test suite is executed in an environment where the ``[web]`` extra has
NOT been installed, the entire module is silently skipped — the core CI/CD
pipeline (which only installs ``.[dev]``) continues to pass without changes.
"""

import pytest

pytest.importorskip("fastapi")   # skip entire module if [web] extra not installed

from pathlib import Path
from fastapi.testclient import TestClient

from web.server import app

client = TestClient(app, raise_server_exceptions=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROFILES_DIR = Path(__file__).parent.parent / "profiles"


# ===========================================================================
# GET /api/profiles
# ===========================================================================

class TestGetProfiles:
    def test_returns_200(self):
        """Endpoint must respond with HTTP 200."""
        resp = client.get("/api/profiles")
        assert resp.status_code == 200

    def test_response_has_profiles_key(self):
        """Response JSON must contain a top-level 'profiles' list."""
        data = client.get("/api/profiles").json()
        assert "profiles" in data
        assert isinstance(data["profiles"], list)

    def test_builtin_profiles_present(self):
        """All three built-in profiles (mvs, arcade, dvd) must be listed."""
        data = client.get("/api/profiles").json()
        names = {p["name"] for p in data["profiles"]}
        assert {"mvs", "arcade", "dvd"}.issubset(names)

    def test_profile_entries_have_required_fields(self):
        """Each profile entry must expose name, template_w, template_h."""
        data = client.get("/api/profiles").json()
        for p in data["profiles"]:
            assert "name"       in p
            assert "template_w" in p
            assert "template_h" in p
            assert isinstance(p["template_w"], int)
            assert isinstance(p["template_h"], int)

    def test_dimensions_within_oom_limit(self):
        """No profile may advertise a dimension > 8192px (Lei de Ferro)."""
        data = client.get("/api/profiles").json()
        for p in data["profiles"]:
            assert p["template_w"] <= 8192
            assert p["template_h"] <= 8192


# ===========================================================================
# POST /api/validate-path
# ===========================================================================

class TestValidatePath:
    def test_existing_directory_returns_valid_true(self, tmp_path):
        """A path that exists and is a directory must return valid=True."""
        resp = client.post("/api/validate-path", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["path"]  == str(tmp_path)

    def test_nonexistent_path_returns_valid_false(self):
        """A path that does not exist must return valid=False."""
        resp = client.post(
            "/api/validate-path",
            json={"path": "/this/path/does/not/exist/at/all"},
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_file_path_returns_valid_false(self, tmp_path):
        """A path to a file (not a directory) must return valid=False."""
        f = tmp_path / "file.txt"
        f.write_text("x")
        resp = client.post("/api/validate-path", json={"path": str(f)})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_empty_string_returns_valid_false(self):
        """An empty path string must return valid=False without raising."""
        resp = client.post("/api/validate-path", json={"path": ""})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_invalid_payload_returns_422(self):
        """Omitting the required 'path' field must return HTTP 422."""
        resp = client.post("/api/validate-path", json={})
        assert resp.status_code == 422


# ===========================================================================
# POST /api/render — input validation only (no actual rendering in unit tests)
# ===========================================================================

class TestRenderEndpoint:
    def test_unknown_profile_returns_400(self, tmp_path):
        """Requesting a non-existent profile must return HTTP 400."""
        resp = client.post("/api/render", json={
            "profile":     "nonexistent_profile_xyz",
            "covers_dir":  str(tmp_path),
            "output_dir":  str(tmp_path / "out"),
        })
        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_missing_covers_dir_returns_400(self, tmp_path):
        """A covers_dir that does not exist must return HTTP 400."""
        resp = client.post("/api/render", json={
            "profile":    "mvs",
            "covers_dir": str(tmp_path / "does_not_exist"),
            "output_dir": str(tmp_path / "out"),
        })
        assert resp.status_code == 400
        assert resp.json()["status"] == "error"

    def test_valid_request_returns_started(self, tmp_path):
        """A valid request with an existing covers_dir must return status=started."""
        covers = tmp_path / "covers"
        covers.mkdir()
        resp = client.post("/api/render", json={
            "profile":    "mvs",
            "covers_dir": str(covers),
            "output_dir": str(tmp_path / "out"),
            "workers":    1,
            "dry_run":    True,   # prevent actual I/O in this unit test
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_invalid_payload_returns_422(self):
        """Omitting required fields must return HTTP 422 (Pydantic validation)."""
        resp = client.post("/api/render", json={})
        assert resp.status_code == 422
