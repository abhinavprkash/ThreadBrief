"""Feedback Metrics - tracks success metrics and guardrails for the feedback loop."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from .feedback_store import FeedbackStore


@dataclass
class FeedbackMetricsSnapshot:
    """Snapshot of feedback metrics for a time period."""
    
    period_start: str
    period_end: str
    team: Optional[str] = None
    
    # Core metrics
    total_digest_items: int = 0
    total_feedback_events: int = 0
    feedback_rate: float = 0.0  # events per item
    
    # Breakdown by type
    accurate_count: int = 0
    wrong_count: int = 0
    missing_context_count: int = 0
    irrelevant_count: int = 0
    
    # Ratios
    accuracy_ratio: float = 0.0
    wrong_ratio: float = 0.0
    irrelevant_ratio: float = 0.0
    missing_context_ratio: float = 0.0
    
    # Patch metrics
    active_directives: int = 0
    directives_expired: int = 0
    
    def to_dict(self) -> dict:
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "team": self.team,
            "total_digest_items": self.total_digest_items,
            "total_feedback_events": self.total_feedback_events,
            "feedback_rate": round(self.feedback_rate, 3),
            "accurate_count": self.accurate_count,
            "wrong_count": self.wrong_count,
            "missing_context_count": self.missing_context_count,
            "irrelevant_count": self.irrelevant_count,
            "accuracy_ratio": round(self.accuracy_ratio, 3),
            "wrong_ratio": round(self.wrong_ratio, 3),
            "irrelevant_ratio": round(self.irrelevant_ratio, 3),
            "missing_context_ratio": round(self.missing_context_ratio, 3),
            "active_directives": self.active_directives,
        }


class FeedbackMetrics:
    """
    Tracks and logs feedback loop metrics.
    
    Metrics tracked:
    - Feedback rate (events per digest run/item)
    - Accuracy ratio (accurate / total)
    - Wrong ratio, irrelevant ratio, missing context ratio
    - Fix speed (time for wrong ratio to decrease after a patch)
    - Patch effectiveness
    """
    
    # Rate limiting thresholds
    MAX_FEEDBACK_PER_USER_PER_DAY = 10
    
    def __init__(self, store: FeedbackStore):
        self.store = store
    
    def compute_snapshot(self, days: int = 7, team: Optional[str] = None) -> FeedbackMetricsSnapshot:
        """
        Compute metrics snapshot for the specified period.
        
        Args:
            days: Number of days to look back
            team: Optional team filter
            
        Returns:
            FeedbackMetricsSnapshot with computed metrics
        """
        period_end = datetime.now()
        period_start = period_end - timedelta(days=days)
        
        snapshot = FeedbackMetricsSnapshot(
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            team=team,
        )
        
        # Get data
        items = self.store.get_recent_items(days=days, team=team)
        feedback_counts = self.store.get_feedback_counts_by_type(days=days, team=team)
        
        snapshot.total_digest_items = len(items)
        
        # Calculate feedback counts
        snapshot.accurate_count = feedback_counts.get("accurate", 0)
        snapshot.wrong_count = feedback_counts.get("wrong", 0)
        snapshot.missing_context_count = feedback_counts.get("missing_context", 0)
        snapshot.irrelevant_count = feedback_counts.get("irrelevant", 0)
        
        snapshot.total_feedback_events = sum(feedback_counts.values())
        
        # Calculate ratios
        if snapshot.total_feedback_events > 0:
            snapshot.accuracy_ratio = snapshot.accurate_count / snapshot.total_feedback_events
            snapshot.wrong_ratio = snapshot.wrong_count / snapshot.total_feedback_events
            snapshot.irrelevant_ratio = snapshot.irrelevant_count / snapshot.total_feedback_events
            snapshot.missing_context_ratio = snapshot.missing_context_count / snapshot.total_feedback_events
        
        # Feedback rate
        if snapshot.total_digest_items > 0:
            snapshot.feedback_rate = snapshot.total_feedback_events / snapshot.total_digest_items
        
        # Directive metrics
        if team:
            snapshot.active_directives = len(
                self.store.get_active_directives(team, max_count=100, expiry_days=14)
            )
        
        return snapshot
    
    def check_rate_limit(self, user_id: str) -> tuple[bool, int]:
        """
        Check if a user has exceeded the daily feedback rate limit.
        
        Returns:
            (is_allowed, remaining_count)
        """
        count = self.store.get_user_feedback_count_today(user_id)
        remaining = max(0, self.MAX_FEEDBACK_PER_USER_PER_DAY - count)
        return count < self.MAX_FEEDBACK_PER_USER_PER_DAY, remaining
    
    def log_metrics(self, snapshot: FeedbackMetricsSnapshot):
        """Log metrics to observability system."""
        # Import here to avoid circular dependency
        from ..observability import logger
        
        logger.info(
            f"Feedback metrics ({snapshot.team or 'all teams'}): "
            f"rate={snapshot.feedback_rate:.2f}, "
            f"accuracy={snapshot.accuracy_ratio:.1%}, "
            f"wrong={snapshot.wrong_ratio:.1%}, "
            f"irrelevant={snapshot.irrelevant_ratio:.1%}"
        )
    
    def get_improvement_trend(self, team: str, weeks: int = 4) -> list[dict]:
        """
        Get weekly trend of wrong ratio to measure improvement.
        
        Returns list of weekly snapshots.
        """
        trends = []
        
        for week in range(weeks):
            end_days = week * 7
            start_days = (week + 1) * 7
            
            # Compute snapshot for that week
            period_end = datetime.now() - timedelta(days=end_days)
            period_start = datetime.now() - timedelta(days=start_days)
            
            # Get feedback for that specific week
            snapshot = self.compute_snapshot(days=7, team=team)
            
            trends.append({
                "week": week,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "wrong_ratio": snapshot.wrong_ratio,
                "accuracy_ratio": snapshot.accuracy_ratio,
            })
        
        return trends
    
    def is_user_spamming(self, user_id: str, digest_item_id: str) -> bool:
        """Check if user has already provided feedback on this item."""
        return self.store.has_user_feedback_for_item(user_id, digest_item_id)
