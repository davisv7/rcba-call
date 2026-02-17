import subprocess
import tempfile
import os


def test_migrations_on_fresh_db():
    """alembic upgrade succeeds on an empty SQLite DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite:///{db_path}"
        env["SECRET_KEY"] = "test"
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Migration failed:\n{result.stderr}"
