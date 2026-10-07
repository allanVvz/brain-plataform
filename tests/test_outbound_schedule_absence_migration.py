from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "supabase/migrations"


def test_absent_send_window_is_immediate_and_published_window_stays_validated():
    sql = (ROOT / "162_allow_immediate_send_without_business_window.sql").read_text()
    absent = sql.index("IF v_checksum IS NULL THEN")
    return_immediate = sql.index("NEW.available_at := coalesce(NEW.available_at, now());")
    configured = sql.index("v_available_at := nullif(NEW.payload->>'available_at','')::timestamptz;")
    incomplete_gate = sql.index("IF v_available_at IS NULL THEN")

    assert absent < return_immediate < configured < incomplete_gate
    assert "CREATE TABLE" not in sql.upper()
    assert "DROP TABLE" not in sql.upper()
