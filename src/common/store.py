"""
Persistence layer. ArtifactStore: immutable content addressed by content_ref
(plain files under artifacts/{session_id}/). SessionStore: single JSON state
document with append-only checkpoint copies under state/{session_id}/checkpoints/.
Never overwrite a checkpoint. Sessions are resumable by loading latest state.
"""
from __future__ import annotations
import json
from pathlib import Path
from src.common.models import SessionState, ResultMessage, _now
ARTIFACTS_ROOT = Path("/app/artifacts")
STATE_ROOT = Path("/app/state")


class ArtifactStore:
    def __init__(self, root: Path = ARTIFACTS_ROOT):
        self.root = root

    def write_content(self, session_id: str, rel_path: str, text: str) -> str:
        """Returns the canonical content_ref ('artifacts/{sid}/{rel}')."""
        target = self.root / session_id / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return f"artifacts/{session_id}/{rel_path}"

    def read_content(self, content_ref: str) -> str:
        # Strip leading 'artifacts/' prefix and resolve inside the root, guarding
        # against traversal outside the store.
        parts = Path(content_ref).parts[1:]
        resolved = (self.root.joinpath(*parts)).resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise ValueError(f"content_ref escapes artifact store: {content_ref}")
        return resolved.read_text(encoding="utf-8")


class SessionStore:
    def __init__(self, root: Path = STATE_ROOT):
        self.root = root

    def save(self, state: SessionState, node_name: str) -> None:
        """Persist current state as live document AND append an immutable
        checkpoint copy named {seq}_{node_name}.json."""
        sid = state.intake.session_id
        d = self.root / sid
        ck = d / "checkpoints"
        ck.mkdir(parents=True, exist_ok=True)
        state.checkpoint_seq += 1
        state.updated_at = _now()
        payload = state.model_dump(mode="json")
        (d / "state.json").write_text(json.dumps(payload, indent=2))
        (ck / f"{state.checkpoint_seq:04d}_{node_name}.json").write_text(
            json.dumps(payload, indent=2)
        )

    # In src/common/store.py, inside class SessionStore
    def save_tree(self, session_id: str, tree_dict: dict) -> str:
        """Persist a hypothesis-tree version as JSON under the session dir.
        Returns the path written. Versioned by the caller's file naming."""
        d = self.root / session_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"hypothesis_tree_v{tree_dict['version']}.json"
        p.write_text(json.dumps(tree_dict, indent=2))
        return str(p)


    def load(self, session_id: str) -> SessionState:
        p = self.root / session_id / "state.json"
        return SessionState(**json.loads(p.read_text()))

    def ingest_result(self, state: SessionState, result: ResultMessage) -> None:
        """Idempotent result ingestion: update ledger, source index, task status."""
        if state.tasks_dispatched.get(result.task_id) == "complete":
            return
        state.tasks_dispatched[result.task_id] = result.status
        state.ledger["tokens_used"] += result.tokens_used
        state.ledger["cost_usd"] += result.cost_usd
        for s in result.sources:
            state.source_counter += 1
            state.source_index[s.source_id] = {
                "url": s.url,
                "source_class": s.source_class,
                "credibility_tier": s.credibility_tier,
                "content_ref": s.content_ref,
                "retrieved_at": s.retrieved_at,
                "from_task": result.task_id,
            }
