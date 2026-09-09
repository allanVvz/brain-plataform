from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "supabase" / "migrations" / "136_business_hours_release_queue.sql"
).read_text(encoding="utf-8").lower()


def test_release_tables_are_additive_and_service_role_only():
    assert "create table if not exists public.release_batches" in MIGRATION
    assert "create table if not exists public.release_batch_items" in MIGRATION
    assert "alter table public.lead_buffer" not in MIGRATION
    assert "enable row level security" in MIGRATION
    assert "revoke all on table public.release_batches from public, anon, authenticated" in MIGRATION
    assert "revoke all on table public.release_batch_items from public, anon, authenticated" in MIGRATION
    assert "grant all on table public.release_batches to service_role" in MIGRATION
    assert "grant all on table public.release_batch_items to service_role" in MIGRATION


def test_release_batch_items_never_stores_its_own_delivery_status():
    items = MIGRATION.split(
        "create table if not exists public.release_batch_items", 1
    )[1].split("create index", 1)[0]
    # captured_status is a point-in-time snapshot for audit, not a live
    # delivery status column -- the table must never grow one of those,
    # since lead_buffer.status via lead_buffer_id is the only source of truth.
    assert "delivery_status" not in items
    assert "send_status" not in items
    assert "captured_status" in items


def test_safety_paused_scope_requires_binding_and_clears_the_pause_atomically():
    register = MIGRATION.split(
        "create or replace function public.register_release_batch_v1", 1
    )[1]
    assert "scope <> 'safety_paused_binding' or binding_id is not null" in MIGRATION
    assert "safety_paused_binding scope requires p_binding_id" in register
    assert "set connection_status = 'connected'" in register
    assert "'safety_paused', false" in register


def test_register_never_touches_status_for_non_waiting_human_rows():
    register = MIGRATION.split(
        "create or replace function public.register_release_batch_v1", 1
    )[1]
    assert "case when v_row.status = 'waiting_human' then 'retry' else status end" in register


def test_register_is_idempotent_on_its_own_unique_key():
    register = MIGRATION.split(
        "create or replace function public.register_release_batch_v1", 1
    )[1]
    assert "where idempotency_key = p_idempotency_key" in register
    assert "'deduplicated', true" in register


def test_pause_action_uses_a_sentinel_instead_of_a_new_worker_guard():
    override = MIGRATION.split(
        "create or replace function public.set_release_item_override_v1", 1
    )[1]
    assert "interval '10 years'" in override
    assert "paused = true" in override
    assert "paused = false" in override


def test_reschedule_requires_an_explicit_timestamp():
    override = MIGRATION.split(
        "create or replace function public.set_release_item_override_v1", 1
    )[1]
    assert "p_action = 'reschedule' and p_new_available_at is null" in override
    assert "reschedule requires p_new_available_at" in override


def test_business_hours_slot_validates_and_rolls_over_the_window():
    slot_fn = MIGRATION.split(
        "create or replace function public.next_business_hours_slot", 1
    )[1].split("create or replace function", 1)[0]
    assert "p_window_start >= p_window_end" in slot_fn
    assert "v_day_offset := v_total_seconds / v_window_seconds" in slot_fn
    assert "v_total_seconds := v_total_seconds % v_window_seconds" in slot_fn
    assert "at time zone p_tz" in slot_fn


def test_functions_are_granted_to_service_role_only():
    for fn in (
        "next_business_hours_slot(timestamptz, integer, integer, time, time, text)",
        "set_release_item_override_v1(uuid, text, text, text, timestamptz, uuid)",
    ):
        assert f"revoke all on function public.{fn}" in MIGRATION
        assert f"grant execute on function public.{fn}" in MIGRATION
    assert "revoke all on function public.register_release_batch_v1(" in MIGRATION
    assert "grant execute on function public.register_release_batch_v1(" in MIGRATION
