"""Audit-log schema repair: ensures audit_log has the columns write_audit_log
inserts (fixes the 'organization_id does not exist' drift)."""
import web_app


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, *args):
        self.executed.append(sql)


def test_ensure_audit_log_schema_creates_table_and_backfills_columns():
    cur = _FakeCursor()
    web_app._ensure_audit_log_schema(cur)
    joined = "\n".join(cur.executed)
    assert "CREATE TABLE IF NOT EXISTS audit_log" in joined
    # Every column write_audit_log() inserts must be backfilled idempotently.
    for col in ("organization_id", "user_email", "endpoint", "method", "status", "ip", "mrn"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in joined


def test_backfilled_columns_match_write_audit_log_insert():
    """The columns we ensure must be a superset of those the INSERT references."""
    cur = _FakeCursor()
    web_app._ensure_audit_log_schema(cur)
    joined = "\n".join(cur.executed)
    for col in ("organization_id", "user_email", "endpoint", "method", "status", "ip", "mrn"):
        assert col in joined
