"""Read and verify the active publication before applying a generator overlay."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
for path in (ROOT / "packages/brain-contracts", ROOT / "packages/brain-shared", ROOT / "apps/control-plane/api"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from services import graph_editor

def load_active_bundle(persona_slug: str) -> dict:
    publication = graph_editor.active_publication(persona_slug)
    checked = graph_editor.verify_round_trip(publication)
    if not checked["editable"]:
        raise graph_editor.GraphEditorError("generator_active_base_round_trip_failed")
    return graph_editor.bundle_from_publication(publication, purpose="Generator overlay over the active publication")
