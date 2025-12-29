"""State management for digest runs."""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class DigestRun:
    """Record of a single digest run."""
    run_id: str
    timestamp: str
    channels_processed: list[str]
    message_counts: dict[str, int]
    success: bool
    error: Optional[str] = None


class DigestState:
    """
    Tracks last run and stores history for incremental fetches.
    
    Persists state to a JSON file for continuity between runs.
    """
    
    DEFAULT_STATE_PATH = "data/digest_state.json"
    
    def __init__(self, state_path: Optional[str] = None):
        self.state_path = Path(state_path or self.DEFAULT_STATE_PATH)
        self._state: dict = {}
        self._load()
    
    def _load(self):
        """Load state from file."""
        if self.state_path.exists():
            with open(self.state_path, "r") as f:
                self._state = json.load(f)
        else:
            self._state = {
                "last_run": None,
                "history": [],
            }
    
    def _save(self):
        """Save state to file."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)
    
    def get_last_run(self) -> Optional[datetime]:
        """
        Get the timestamp of the last successful run.
        
        Returns None if no previous run exists.
        """
        last_run = self._state.get("last_run")
        if last_run:
            return datetime.fromisoformat(last_run)
        return None
    
    def save_run(self, run: DigestRun):
        """
        Record a digest run.
        
        Updates last_run timestamp if successful.
        """
        if run.success:
            self._state["last_run"] = run.timestamp
        
        # Keep last 30 runs in history
        history = self._state.get("history", [])
        history.append(asdict(run))
        self._state["history"] = history[-30:]
        
        self._save()
    
    def get_history(self, limit: int = 10) -> list[DigestRun]:
        """Get recent run history."""
        history = self._state.get("history", [])[-limit:]
        return [DigestRun(**h) for h in history]
    
    def clear(self):
        """Clear all state (for testing)."""
        self._state = {"last_run": None, "history": []}
        if self.state_path.exists():
            self.state_path.unlink()
