"""Structured event models extracted from messages."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class EventType(str, Enum):
    """Types of events that can be extracted from messages."""
    DECISION = "decision"
    BLOCKER = "blocker"
    STATUS_UPDATE = "status_update"
    QUESTION = "question"
    RISK = "risk"
    FYI = "fyi"


@dataclass
class StructuredEvent:
    """Base class for all structured events."""
    
    event_type: EventType
    summary: str
    confidence: float  # 0.0 to 1.0
    
    # Source tracking
    source_channel: str
    source_message_ts: str
    source_permalink: Optional[str] = None
    
    # Classification
    teams_involved: list[str] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)
    urgency: str = "medium"  # low, medium, high
    topics: list[str] = field(default_factory=list)
    
    # Metadata
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())
    needs_verification: bool = False


@dataclass
class Decision(StructuredEvent):
    """A decision made by the team."""
    
    what_decided: str = ""
    decided_by: str = ""
    context: str = ""
    impact: str = ""
    
    def __post_init__(self):
        self.event_type = EventType.DECISION


@dataclass
class Blocker(StructuredEvent):
    """A blocker or issue preventing progress."""
    
    issue: str = ""
    owner: str = ""
    severity: str = "medium"  # low, medium, high
    status: str = "active"  # active, resolved, mitigated
    blocked_by: Optional[str] = None  # User or team blocking
    
    def __post_init__(self):
        self.event_type = EventType.BLOCKER


@dataclass
class StatusUpdate(StructuredEvent):
    """A status update or progress report."""
    
    what_happened: str = ""
    who: str = ""
    category: str = "progress"  # completion, progress, announcement, milestone
    
    def __post_init__(self):
        self.event_type = EventType.STATUS_UPDATE


@dataclass
class Question(StructuredEvent):
    """An open question needing an answer."""
    
    question: str = ""
    asked_by: str = ""
    target_audience: list[str] = field(default_factory=list)
    is_answered: bool = False
    answer: Optional[str] = None
    
    def __post_init__(self):
        self.event_type = EventType.QUESTION


@dataclass
class ActionItem:
    """A concrete task extracted from messages."""
    
    description: str
    owner: str  # user_id or "unassigned"
    source_event_type: EventType
    source_link: str
    
    due_date: Optional[str] = None
    priority: str = "medium"  # low, medium, high
    confidence: float = 1.0
    
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed: bool = False
