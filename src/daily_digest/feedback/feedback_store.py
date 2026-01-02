"""Feedback Store - SQLite persistence for digest items, feedback events, and prompt patches."""

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from contextlib import contextmanager


@dataclass
class DigestItem:
    """A structured digest item stored for feedback tracking."""
    
    digest_item_id: str
    run_id: str
    date: str
    team: str
    item_type: str  # blocker/decision/update/action_item/risk
    title: str
    summary: str
    severity: str = "medium"
    owners: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    source_links: list[str] = field(default_factory=list)
    confidence: float = 1.0
    slack_message_ts: str = ""
    slack_channel_id: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FeedbackEvent:
    """A feedback reaction from a user."""
    
    id: Optional[int] = None
    digest_item_id: str = ""
    user_id: str = ""
    team: str = ""
    feedback_type: str = ""  # accurate/wrong/missing/irrelevant
    comment: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PromptPatch:
    """A prompt directive patch for a team."""
    
    id: Optional[int] = None
    team: str = ""
    directive: str = ""  # Single directive bullet
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_confirmed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    confirmation_count: int = 1
    active: bool = True


class FeedbackStore:
    """
    SQLite-based persistent storage for feedback loop.
    
    Tables:
    - digest_items: Structured digest atoms for each run
    - feedback_events: User reactions on items
    - prompt_patches: Team-specific directive rules
    """
    
    # Emoji to feedback type mapping
    EMOJI_MAP = {
        "white_check_mark": "accurate",
        "+1": "accurate",
        "heavy_check_mark": "accurate",
        "x": "wrong",
        "no_entry": "wrong",
        "jigsaw": "missing_context",
        "puzzle_piece": "missing_context",
        "no_bell": "irrelevant",
        "mute": "irrelevant",
    }
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = Path(__file__).parent.parent.parent.parent / "data" / "feedback.db"
        
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    @contextmanager
    def _get_conn(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Digest items table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS digest_items (
                    digest_item_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    team TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    severity TEXT DEFAULT 'medium',
                    owners TEXT DEFAULT '[]',
                    mentions TEXT DEFAULT '[]',
                    projects TEXT DEFAULT '[]',
                    source_links TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 1.0,
                    slack_message_ts TEXT,
                    slack_channel_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Feedback events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    digest_item_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    team TEXT,
                    feedback_type TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (digest_item_id) REFERENCES digest_items(digest_item_id)
                )
            """)
            
            # Prompt patches table - individual directives with expiry tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prompt_patches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team TEXT NOT NULL,
                    directive TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_confirmed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    confirmation_count INTEGER DEFAULT 1,
                    active BOOLEAN DEFAULT 1,
                    UNIQUE(team, directive)
                )
            """)
            
            # User personas table - stores role and team preferences
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_personas (
                    user_id TEXT PRIMARY KEY,
                    role TEXT DEFAULT 'ic',
                    team TEXT DEFAULT 'general',
                    custom_topics TEXT DEFAULT '[]',
                    custom_boosts TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create indexes for common queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_team ON digest_items(team)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_ts ON digest_items(slack_message_ts)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_run ON digest_items(run_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_item ON feedback_events(digest_item_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback_events(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_patches_team ON prompt_patches(team, active)")
    
    # ==================== Digest Items ====================
    
    def store_digest_item(self, item: DigestItem) -> str:
        """Store a digest item. Returns the item ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO digest_items (
                    digest_item_id, run_id, date, team, item_type, title, summary,
                    severity, owners, mentions, projects, source_links,
                    confidence, slack_message_ts, slack_channel_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item.digest_item_id,
                item.run_id,
                item.date,
                item.team,
                item.item_type,
                item.title,
                item.summary,
                item.severity,
                json.dumps(item.owners),
                json.dumps(item.mentions),
                json.dumps(item.projects),
                json.dumps(item.source_links),
                item.confidence,
                item.slack_message_ts,
                item.slack_channel_id,
            ))
        return item.digest_item_id
    
    def get_item_by_message_ts(self, message_ts: str, channel_id: str) -> Optional[DigestItem]:
        """Look up a digest item by its Slack message timestamp."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM digest_items 
                WHERE slack_message_ts = ? AND slack_channel_id = ?
            """, (message_ts, channel_id))
            row = cursor.fetchone()
            if row:
                return self._row_to_digest_item(row)
        return None
    
    def get_items_by_run(self, run_id: str) -> list[DigestItem]:
        """Get all digest items from a run."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM digest_items WHERE run_id = ?", (run_id,))
            return [self._row_to_digest_item(row) for row in cursor.fetchall()]
    
    def get_recent_items(self, days: int = 7, team: Optional[str] = None) -> list[DigestItem]:
        """Get recent digest items."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if team:
                cursor.execute("""
                    SELECT * FROM digest_items 
                    WHERE date >= ? AND team = ?
                    ORDER BY date DESC
                """, (cutoff, team))
            else:
                cursor.execute("""
                    SELECT * FROM digest_items WHERE date >= ?
                    ORDER BY date DESC
                """, (cutoff,))
            return [self._row_to_digest_item(row) for row in cursor.fetchall()]
    
    def update_item_confidence(self, digest_item_id: str, new_confidence: float):
        """Update confidence score for an item (used by FeedbackProcessor)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE digest_items SET confidence = ? WHERE digest_item_id = ?
            """, (max(0.0, min(1.0, new_confidence)), digest_item_id))
    
    def _row_to_digest_item(self, row: sqlite3.Row) -> DigestItem:
        """Convert database row to DigestItem."""
        return DigestItem(
            digest_item_id=row["digest_item_id"],
            run_id=row["run_id"],
            date=row["date"],
            team=row["team"],
            item_type=row["item_type"],
            title=row["title"],
            summary=row["summary"] or "",
            severity=row["severity"] or "medium",
            owners=json.loads(row["owners"] or "[]"),
            mentions=json.loads(row["mentions"] or "[]"),
            projects=json.loads(row["projects"] or "[]"),
            source_links=json.loads(row["source_links"] or "[]"),
            confidence=row["confidence"] or 1.0,
            slack_message_ts=row["slack_message_ts"] or "",
            slack_channel_id=row["slack_channel_id"] or "",
        )
    
    # ==================== Feedback Events ====================
    
    def store_feedback(self, event: FeedbackEvent) -> int:
        """Store a feedback event. Returns the event ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO feedback_events (
                    digest_item_id, user_id, team, feedback_type, comment, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.digest_item_id,
                event.user_id,
                event.team,
                event.feedback_type,
                event.comment,
                event.created_at,
            ))
            return cursor.lastrowid
    
    def get_feedback_for_item(self, digest_item_id: str) -> list[FeedbackEvent]:
        """Get all feedback for a specific item."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM feedback_events WHERE digest_item_id = ?
                ORDER BY created_at DESC
            """, (digest_item_id,))
            return [self._row_to_feedback_event(row) for row in cursor.fetchall()]
    
    def get_recent_feedback(self, days: int = 7, team: Optional[str] = None) -> list[FeedbackEvent]:
        """Get recent feedback events."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if team:
                cursor.execute("""
                    SELECT * FROM feedback_events 
                    WHERE created_at >= ? AND team = ?
                    ORDER BY created_at DESC
                """, (cutoff, team))
            else:
                cursor.execute("""
                    SELECT * FROM feedback_events WHERE created_at >= ?
                    ORDER BY created_at DESC
                """, (cutoff,))
            return [self._row_to_feedback_event(row) for row in cursor.fetchall()]
    
    def get_feedback_counts_by_type(self, days: int = 7, team: Optional[str] = None) -> dict[str, int]:
        """Get aggregated feedback counts by type."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if team:
                cursor.execute("""
                    SELECT feedback_type, COUNT(*) as count 
                    FROM feedback_events 
                    WHERE created_at >= ? AND team = ?
                    GROUP BY feedback_type
                """, (cutoff, team))
            else:
                cursor.execute("""
                    SELECT feedback_type, COUNT(*) as count 
                    FROM feedback_events 
                    WHERE created_at >= ?
                    GROUP BY feedback_type
                """, (cutoff,))
            return {row["feedback_type"]: row["count"] for row in cursor.fetchall()}
    
    def get_user_feedback_count_today(self, user_id: str) -> int:
        """Get feedback count for a user today (for rate limiting)."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM feedback_events 
                WHERE user_id = ? AND created_at LIKE ?
            """, (user_id, f"{today}%"))
            row = cursor.fetchone()
            return row["count"] if row else 0
    
    def has_user_feedback_for_item(self, user_id: str, digest_item_id: str) -> bool:
        """Check if user already gave feedback on an item."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM feedback_events WHERE user_id = ? AND digest_item_id = ?
            """, (user_id, digest_item_id))
            return cursor.fetchone() is not None
    
    def _row_to_feedback_event(self, row: sqlite3.Row) -> FeedbackEvent:
        """Convert database row to FeedbackEvent."""
        return FeedbackEvent(
            id=row["id"],
            digest_item_id=row["digest_item_id"],
            user_id=row["user_id"],
            team=row["team"] or "",
            feedback_type=row["feedback_type"],
            comment=row["comment"],
            created_at=row["created_at"],
        )
    
    # ==================== Prompt Patches ====================
    
    def add_directive(self, team: str, directive: str) -> int:
        """Add or update a prompt directive for a team."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Try to update existing directive
            cursor.execute("""
                UPDATE prompt_patches 
                SET last_confirmed_at = ?, confirmation_count = confirmation_count + 1, active = 1
                WHERE team = ? AND directive = ?
            """, (now, team, directive))
            
            if cursor.rowcount == 0:
                # Insert new directive
                cursor.execute("""
                    INSERT INTO prompt_patches (team, directive, created_at, last_confirmed_at, active)
                    VALUES (?, ?, ?, ?, 1)
                """, (team, directive, now, now))
                return cursor.lastrowid
            return 0
    
    def get_active_directives(self, team: str, max_count: int = 12, expiry_days: int = 14) -> list[str]:
        """
        Get active, non-expired directives for a team.
        Returns at most max_count directives, prioritized by confirmation count.
        """
        cutoff = (datetime.now() - timedelta(days=expiry_days)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT directive FROM prompt_patches 
                WHERE team = ? AND active = 1 AND last_confirmed_at >= ?
                ORDER BY confirmation_count DESC, last_confirmed_at DESC
                LIMIT ?
            """, (team, cutoff, max_count))
            return [row["directive"] for row in cursor.fetchall()]
    
    def expire_old_directives(self, expiry_days: int = 14):
        """Mark old directives as inactive."""
        cutoff = (datetime.now() - timedelta(days=expiry_days)).isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE prompt_patches SET active = 0 
                WHERE last_confirmed_at < ? AND active = 1
            """, (cutoff,))
            return cursor.rowcount
    
    def deactivate_directive(self, team: str, directive: str):
        """Manually deactivate a specific directive."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE prompt_patches SET active = 0 WHERE team = ? AND directive = ?
            """, (team, directive))
    
    # ==================== User Personas ====================
    
    def set_user_persona(
        self,
        user_id: str,
        role: str = "ic",
        team: str = "general",
        custom_topics: list[str] = None,
        custom_boosts: dict[str, float] = None,
    ):
        """Set or update a user's persona preferences."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_personas (user_id, role, team, custom_topics, custom_boosts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role = excluded.role,
                    team = excluded.team,
                    custom_topics = excluded.custom_topics,
                    custom_boosts = excluded.custom_boosts,
                    updated_at = excluded.updated_at
            """, (
                user_id,
                role,
                team,
                json.dumps(custom_topics or []),
                json.dumps(custom_boosts or {}),
                now,
            ))
    
    def get_user_persona(self, user_id: str) -> Optional[dict]:
        """Get a user's persona preferences."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM user_personas WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "user_id": row["user_id"],
                    "role": row["role"],
                    "team": row["team"],
                    "custom_topics": json.loads(row["custom_topics"] or "[]"),
                    "custom_boosts": json.loads(row["custom_boosts"] or "{}"),
                }
        return None
    
    def get_all_user_personas(self) -> list[dict]:
        """Get all stored user personas."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_personas")
            return [
                {
                    "user_id": row["user_id"],
                    "role": row["role"],
                    "team": row["team"],
                    "custom_topics": json.loads(row["custom_topics"] or "[]"),
                    "custom_boosts": json.loads(row["custom_boosts"] or "{}"),
                }
                for row in cursor.fetchall()
            ]
    
    # ==================== Utility ====================
    
    def generate_item_id(self, run_id: str, team: str, item_type: str, index: int) -> str:
        """Generate a stable digest item ID."""
        return f"{run_id}_{team}_{item_type}_{index}"
    
    def emoji_to_feedback_type(self, emoji: str) -> Optional[str]:
        """Map Slack emoji name to feedback type."""
        return self.EMOJI_MAP.get(emoji.lower().strip(":"))

