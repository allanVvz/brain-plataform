from scripts.classify_deploy_impact import classify


def test_documentation_does_not_touch_production():
    result = classify(["docs/roadmaps/deploy.md"])
    assert result["class"] == "documentation"
    assert result["touch_vps"] is False


def test_dashboard_only_routes_to_vercel_without_vps():
    result = classify(["dashboard/app/page.tsx"])
    assert result["class"] == "dashboard"
    assert result["touch_vps"] is False


def test_administrative_api_route_does_not_pause_workers():
    result = classify(["api/routes/users.py"])
    assert result["class"] == "api"
    assert result["pause_claims"] is False


def test_non_conversation_worker_uses_drain_without_api_publish():
    result = classify(["api/workers/kb_sync_worker.py"])
    assert result["class"] == "worker"
    assert result["publish_api"] is False
    assert result["pause_claims"] is True


def test_conversation_runtime_requires_semantic_path():
    result = classify(["api/services/graph_agent_runtime_v3.py"])
    assert result["class"] == "conversational"
    assert result["wa_validator"] is True


def test_migration_requires_backup_and_complete_path():
    result = classify(["supabase/migrations/131_example.sql"])
    assert result["class"] == "migration"
    assert result["backup"] is True
    assert result["publish_migrate"] is True


def test_release_infrastructure_uses_controlled_path_without_migration():
    result = classify([".github/workflows/deploy-production.yml", "api/Dockerfile"])
    assert result["class"] == "conversational"
    assert result["pause_claims"] is True
    assert result["wa_validator"] is True
    assert result["backup"] is False
    assert result["publish_migrate"] is False


def test_graph_bundle_has_separate_publication_path():
    result = classify(["data/graph_bundles/example/bundle.json"])
    assert result["class"] == "graph"
    assert result["touch_vps"] is False


def test_graph_publication_script_stays_out_of_code_deploy():
    result = classify(["api/scripts/publish_aurora_graph.py", "docs/graph.md"])
    assert result["class"] == "graph"
    assert result["touch_vps"] is False


def test_mixed_api_and_worker_fails_into_conversation_control():
    result = classify(["api/routes/users.py", "api/workers/kb_sync_worker.py"])
    assert result["class"] == "conversational"
    assert result["publish_api"] is True
    assert result["publish_worker"] is True
