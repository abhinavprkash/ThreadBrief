"""Memory Store - persists decisions, actions, and summaries."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models.events import Decision, Blocker, ActionItem, StructuredEvent


@dataclass
class StoredDecision:
    """A decision stored in memory."""
    decision_id: str
    summary: str
    what_decided: str
    decided_by: str
    team: str
    timestamp: str
    source_link: str = ""


@dataclass
class StoredBlocker:
    """A blocker stored in memory."""
    blocker_id: str
    issue: str
    owner: str
    team: str
    severity: str
    status: str
    created_at: str
    resolved_at: Optional[str] = None
    age_days: int = 0


class MemoryStore:
    """
    Persistent memory for decisions, blockers, and action items.
    
    Stores:
    - Decision log: all decisions with context
    - Open blockers: tracked with age
    - Action items: tasks with ownership
    - Team summaries: daily summaries for reference
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(__file__).parent.parent.parent.parent / "data" / "memory"
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._decisions_file = self.data_dir / "decisions.json"
        self._blockers_file = self.data_dir / "blockers.json"
        self._actions_file = self.data_dir / "actions.json"
        
        self._load_state()
    
    def _load_state(self):
        """Load state from files."""
        self.decisions = self._load_json(self._decisions_file, [])
        self.blockers = self._load_json(self._blockers_file, [])
        self.actions = self._load_json(self._actions_file, [])
    
    def _load_json(self, path: Path, default) -> list:
        """Load JSON file or return default."""
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return default
    
    def _save_json(self, path: Path, data: list):
        """Save data to JSON file."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    
    # Decision logging
    
    def log_decision(self, decision: Decision) -> str:
        """Log a decision and return its ID."""
        decision_id = f"dec_{len(self.decisions)}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        stored = {
            "decision_id": decision_id,
            "summary": decision.summary,
            "what_decided": decision.what_decided,
            "decided_by": decision.decided_by,
            "team": decision.teams_involved[0] if decision.teams_involved else "",
            "context": decision.context,
            "impact": decision.impact,
            "timestamp": datetime.now().isoformat(),
            "source_channel": decision.source_channel,
        }
        
        self.decisions.append(stored)
        self._save_json(self._decisions_file, self.decisions)
        
        return decision_id
    
    def get_recent_decisions(self, days: int = 7, team: Optional[str] = None) -> list[dict]:
        """Get decisions from the last N days."""
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        
        results = []
        for dec in self.decisions:
            try:
                ts = datetime.fromisoformat(dec.get("timestamp", "")).timestamp()
                if ts >= cutoff:
                    if team is None or dec.get("team") == team:
                        results.append(dec)
            except (ValueError, TypeError):
                continue
        
        return results
    
    # Blocker tracking
    
    def log_blocker(self, blocker: Blocker) -> str:
        """Log a blocker and return its ID."""
        blocker_id = f"blk_{len(self.blockers)}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        stored = {
            "blocker_id": blocker_id,
            "issue": blocker.issue,
            "owner": blocker.owner,
            "team": blocker.teams_involved[0] if blocker.teams_involved else "",
            "severity": blocker.severity,
            "status": blocker.status,
            "blocked_by": blocker.blocked_by,
            "created_at": datetime.now().isoformat(),
            "resolved_at": None,
        }
        
        self.blockers.append(stored)
        self._save_json(self._blockers_file, self.blockers)
        
        return blocker_id
    
    def get_open_blockers(self, team: Optional[str] = None) -> list[dict]:
        """Get all unresolved blockers."""
        results = []
        now = datetime.now()
        
        for blk in self.blockers:
            if blk.get("status") not in ["resolved", "mitigated"]:
                if team is None or blk.get("team") == team:
                    # Calculate age
                    try:
                        created = datetime.fromisoformat(blk.get("created_at", ""))
                        age_days = (now - created).days
                        blk["age_days"] = age_days
                    except (ValueError, TypeError):
                        blk["age_days"] = 0
                    
                    results.append(blk)
        
        return results
    
    def resolve_blocker(self, blocker_id: str, status: str = "resolved") -> bool:
        """Mark a blocker as resolved."""
        for blk in self.blockers:
            if blk.get("blocker_id") == blocker_id:
                blk["status"] = status
                blk["resolved_at"] = datetime.now().isoformat()
                self._save_json(self._blockers_file, self.blockers)
                return True
        return False
    
    # Action items
    
    def log_action(self, action: ActionItem) -> str:
        """Log an action item and return its ID."""
        action_id = f"act_{len(self.actions)}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        stored = {
            "action_id": action_id,
            "description": action.description,
            "owner": action.owner,
            "priority": action.priority,
            "due_date": action.due_date,
            "source_link": action.source_link,
            "created_at": datetime.now().isoformat(),
            "completed": False,
        }
        
        self.actions.append(stored)
        self._save_json(self._actions_file, self.actions)
        
        return action_id
    
    def get_open_actions(self, owner: Optional[str] = None) -> list[dict]:
        """Get all incomplete action items."""
        results = []
        
        for act in self.actions:
            if not act.get("completed", False):
                if owner is None or act.get("owner") == owner:
                    results.append(act)
        
        return results
    
    def complete_action(self, action_id: str) -> bool:
        """Mark an action as complete."""
        for act in self.actions:
            if act.get("action_id") == action_id:
                act["completed"] = True
                act["completed_at"] = datetime.now().isoformat()
                self._save_json(self._actions_file, self.actions)
                return True
        return False
    
    # Bulk operations
    
    def process_events(self, events: list[StructuredEvent]) -> dict:
        """Process multiple events and log them appropriately."""
        results = {
            "decisions_logged": 0,
            "blockers_logged": 0,
            "actions_logged": 0,
        }
        
        for event in events:
            if isinstance(event, Decision):
                self.log_decision(event)
                results["decisions_logged"] += 1
            elif isinstance(event, Blocker):
                self.log_blocker(event)
                results["blockers_logged"] += 1
        
        return results
