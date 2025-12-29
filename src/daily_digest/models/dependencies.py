"""Dependency models for cross-team linking."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DependencyType(str, Enum):
    """Types of cross-team dependencies."""
    WAITING_ON = "waiting_on"  # Team A waiting on Team B
    INTERFACE_CHANGE = "interface_change"  # API/spec change affecting downstream
    TIMELINE_IMPACT = "timeline_impact"  # Schedule change affecting others
    SHARED_RESOURCE = "shared_resource"  # Competing for same resource
    BLOCKING = "blocking"  # Hard blocker
    INFORMATIONAL = "informational"  # FYI that impacts another team


@dataclass
class Dependency:
    """A cross-team dependency linking two teams."""
    
    dependency_type: DependencyType
    
    # Teams involved
    from_team: str
    to_team: str
    
    # Description
    what_changed: str
    why_it_matters: str
    
    # Action
    recommended_action: str
    suggested_owner: str
    
    # Urgency
    urgency: str = "medium"  # low, medium, high
    
    # Source evidence
    source_events: list[str] = field(default_factory=list)  # Event IDs
    source_links: list[str] = field(default_factory=list)  # Permalinks
    
    # Metadata
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved: bool = False
    resolved_at: Optional[str] = None


@dataclass
class CrossTeamAlert:
    """An alert to surface cross-team dependencies."""
    
    title: str
    dependency: Dependency
    
    # For display
    impacted_users: list[str] = field(default_factory=list)
    priority: int = 0  # Higher = more important
    
    # Feedback tracking
    alert_id: str = ""
    shown_to: list[str] = field(default_factory=list)
    acknowledged_by: list[str] = field(default_factory=list)
