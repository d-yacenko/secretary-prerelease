from sqlalchemy import text

from app.db.engine import engine


def test_database_connection() -> None:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
    assert result == 1
