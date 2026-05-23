"""Storage layer tests — JSON file fallback and PostgreSQL path.

The JSON file fallback is the default in all other tests (DATABASE_URL=None).
This file specifically validates both paths, including the Postgres mock.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestJsonFileFallback:
    def test_register_user_creates_json_file(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        err = web_app.register_user("new@x.com", "password123")
        assert err is None
        data = json.loads((tmp_path / "users.json").read_text())
        assert "new@x.com" in data

    def test_password_stored_as_hash_not_plaintext(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        web_app.register_user("secure@x.com", "MyPlainPass")
        data = json.loads((tmp_path / "users.json").read_text())
        user = data["secure@x.com"]
        assert "MyPlainPass" not in json.dumps(user)
        assert len(user["hash"]) >= 32

    def test_password_hash_uses_per_user_salt(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        web_app.register_user("u1@x.com", "SamePassword1!")
        web_app.register_user("u2@x.com", "SamePassword1!")
        data = json.loads((tmp_path / "users.json").read_text())
        assert data["u1@x.com"]["salt"] != data["u2@x.com"]["salt"]
        assert data["u1@x.com"]["hash"] != data["u2@x.com"]["hash"]

    def test_authenticate_correct_password_returns_none(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        web_app.register_user("auth@x.com", "CorrectHorse99!")
        err = web_app.authenticate_user("auth@x.com", "CorrectHorse99!")
        assert err is None

    def test_authenticate_wrong_password_returns_error(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        web_app.register_user("auth2@x.com", "CorrectHorse99!")
        err = web_app.authenticate_user("auth2@x.com", "WRONGPASSWORD")
        assert err is not None
        assert "Incorrect" in err

    def test_authenticate_unknown_email_returns_error(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        err = web_app.authenticate_user("ghost@x.com", "AnyPass1!")
        assert err is not None
        assert "No account" in err

    def test_duplicate_email_returns_error_string(self, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        web_app.register_user("dup@x.com", "SomePass1!")
        err = web_app.register_user("dup@x.com", "SomePass1!")
        assert err is not None
        assert "already exists" in err.lower()

    def test_missing_users_file_initialises_empty_store(self, tmp_path, monkeypatch):
        import web_app
        users_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", users_file)
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        assert not users_file.exists()
        err = web_app.register_user("first@x.com", "FirstPass1!")
        assert err is None
        assert users_file.exists()


class TestPostgresPath:
    def _make_mock_conn(self, cursor_mock=None):
        mock_cursor = cursor_mock or MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cursor

    def test_register_user_inserts_to_postgres(self, monkeypatch):
        import web_app
        mock_conn, mock_cursor = self._make_mock_conn()
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(web_app, "_get_conn", lambda: mock_conn)
        err = web_app.register_user("pg@x.com", "StrongPass1!")
        assert err is None
        assert mock_cursor.execute.called

    def test_duplicate_email_postgres_returns_error_string(self, monkeypatch):
        import web_app, psycopg2
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = psycopg2.errors.UniqueViolation()
        mock_conn, _ = self._make_mock_conn(mock_cursor)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(web_app, "_get_conn", lambda: mock_conn)
        err = web_app.register_user("dup@x.com", "StrongPass1!")
        assert err is not None
        assert "already exists" in err.lower()

    def test_authenticate_user_queries_postgres(self, monkeypatch):
        import web_app
        import hashlib, secrets
        salt = "testsalt"
        pw = "CorrectPass1!"
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 260_000)
        stored_hash = dk.hex()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (salt, stored_hash)
        mock_conn, _ = self._make_mock_conn(mock_cursor)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(web_app, "_get_conn", lambda: mock_conn)
        err = web_app.authenticate_user("pg@x.com", pw)
        assert err is None

    def test_authenticate_unknown_email_postgres_returns_error(self, monkeypatch):
        import web_app
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn, _ = self._make_mock_conn(mock_cursor)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(web_app, "_get_conn", lambda: mock_conn)
        err = web_app.authenticate_user("ghost@x.com", "AnyPass1!")
        assert err is not None
        assert "No account" in err
