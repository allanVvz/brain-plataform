from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "ops" / "vps" / "rollout-microservices.sh").read_text(encoding="utf-8")


def test_finish_recreates_active_slot_workers_from_manifest_before_unpausing():
    finish = SCRIPT.split("  finish)", 1)[1].split("\n  *)", 1)[0]

    assert 'paused || {' in finish
    assert 'configure_manifest_environment' in finish
    assert '"${COMPOSE[@]}" up -d --no-deps --force-recreate "${active_workers[@]}"' in finish
    assert 'worker digest mismatch after recreate' in finish
    assert 'docker start "$name"' not in finish
    assert finish.index('--force-recreate "${active_workers[@]}"') < finish.index('rm -f "$PAUSE_MARKER"')


def test_finish_recreates_all_active_worker_groups_and_keeps_retired_slots_stopped():
    finish = SCRIPT.split("  finish)", 1)[1].split("\n  *)", 1)[0]

    assert 'for service in control-plane conversation-runtime transport; do' in finish
    assert 'brain-ai-${worker}-${slot}-1' in finish
    assert 'retired slot still on the queue' in finish
