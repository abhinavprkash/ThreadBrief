"""Feedback Processor - applies deterministic improvements based on feedback."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from .feedback_store import FeedbackStore, DigestItem


@dataclass
class ConfidenceAdjustment:
    """Adjustment to apply to item confidence scores."""
    digest_item_id: str
    original_confidence: float
    new_confidence: float
    reason: str


@dataclass
class ChannelWeight:
    """Weight adjustment for a channel based on feedback."""
    channel_id: str
    team: str
    weight: float  # 0.0 to 1.0, lower = less contribution
    reason: str


@dataclass
class OwnerOverride:
    """Override for project-to-owner mapping."""
    project: str
    correct_owner: str
    created_at: str


@dataclass
class ProcessorAdjustments:
    """All adjustments to apply in the next run."""
    confidence_adjustments: dict[str, float] = field(default_factory=dict)  # item_type -> adjustment
    channel_weights: dict[str, float] = field(default_factory=dict)  # channel_id -> weight
    owner_overrides: dict[str, str] = field(default_factory=dict)  # project -> owner
    suppressed_patterns: list[str] = field(default_factory=list)  # title patterns to suppress
    recurring_items: dict[str, list[str]] = field(default_factory=dict)  # title -> list of item_ids


class FeedbackProcessor:
    """
    Applies deterministic improvements based on feedback without using LLM.
    
    Improvements:
    1. Confidence adjustments - wrong/irrelevant feedback lowers score
    2. Dedupe detection - detect recurring items by title similarity
    3. Channel noise filtering - reduce contribution from noisy channels
    4. Owner overrides - correct ownership based on feedback
    """
    
    # Thresholds for adjustments
    WRONG_THRESHOLD = 0.2  # >20% wrong feedback triggers adjustment
    IRRELEVANT_THRESHOLD = 0.2  # >20% irrelevant triggers adjustment
    
    WRONG_PENALTY = 0.3  # Reduce confidence by this amount
    IRRELEVANT_PENALTY = 0.2
    ACCURATE_BOOST = 0.1  # Boost for confirmed accurate items
    
    # Confidence thresholds for formatting
    HIGH_CONFIDENCE_THRESHOLD = 0.7  # Items >= this go in main sections
    LOW_CONFIDENCE_THRESHOLD = 0.4   # Items < this are excluded
    
    def __init__(self, store: FeedbackStore):
        self.store = store
    
    def get_adjustments(self, days: int = 7) -> ProcessorAdjustments:
        """
        Analyze recent feedback and compute adjustments for next run.
        
        Returns ProcessorAdjustments with all changes to apply.
        """
        adjustments = ProcessorAdjustments()
        
        # Get recent items and feedback
        recent_items = self.store.get_recent_items(days=days)
        
        # Group items by various dimensions for analysis
        items_by_type: dict[str, list[DigestItem]] = defaultdict(list)
        items_by_channel: dict[str, list[DigestItem]] = defaultdict(list)
        items_by_title: dict[str, list[DigestItem]] = defaultdict(list)
        
        for item in recent_items:
            items_by_type[item.item_type].append(item)
            items_by_channel[item.slack_channel_id].append(item)
            
            # Normalize title for dedup
            normalized_title = self._normalize_title(item.title)
            items_by_title[normalized_title].append(item)
        
        # 1. Analyze feedback by item type
        adjustments.confidence_adjustments = self._analyze_type_feedback(items_by_type)
        
        # 2. Analyze channel noise
        adjustments.channel_weights = self._analyze_channel_feedback(items_by_channel)
        
        # 3. Detect recurring items
        adjustments.recurring_items = self._detect_recurring(items_by_title)
        
        return adjustments
    
    def _analyze_type_feedback(self, items_by_type: dict[str, list[DigestItem]]) -> dict[str, float]:
        """Analyze feedback patterns by item type and return confidence adjustments."""
        adjustments = {}
        
        for item_type, items in items_by_type.items():
            total_feedback = 0
            wrong_count = 0
            irrelevant_count = 0
            accurate_count = 0
            
            for item in items:
                feedback = self.store.get_feedback_for_item(item.digest_item_id)
                for fb in feedback:
                    total_feedback += 1
                    if fb.feedback_type == "wrong":
                        wrong_count += 1
                    elif fb.feedback_type == "irrelevant":
                        irrelevant_count += 1
                    elif fb.feedback_type == "accurate":
                        accurate_count += 1
            
            if total_feedback == 0:
                continue
            
            wrong_ratio = wrong_count / total_feedback
            irrelevant_ratio = irrelevant_count / total_feedback
            accurate_ratio = accurate_count / total_feedback
            
            # Calculate adjustment
            adjustment = 0.0
            if wrong_ratio > self.WRONG_THRESHOLD:
                adjustment -= self.WRONG_PENALTY * (wrong_ratio / self.WRONG_THRESHOLD)
            if irrelevant_ratio > self.IRRELEVANT_THRESHOLD:
                adjustment -= self.IRRELEVANT_PENALTY * (irrelevant_ratio / self.IRRELEVANT_THRESHOLD)
            if accurate_ratio > 0.5:  # >50% accurate = boost
                adjustment += self.ACCURATE_BOOST
            
            if adjustment != 0.0:
                adjustments[item_type] = adjustment
        
        return adjustments
    
    def _analyze_channel_feedback(self, items_by_channel: dict[str, list[DigestItem]]) -> dict[str, float]:
        """Analyze feedback by channel and return weight adjustments."""
        weights = {}
        
        for channel_id, items in items_by_channel.items():
            total_feedback = 0
            irrelevant_count = 0
            
            for item in items:
                feedback = self.store.get_feedback_for_item(item.digest_item_id)
                for fb in feedback:
                    total_feedback += 1
                    if fb.feedback_type == "irrelevant":
                        irrelevant_count += 1
            
            if total_feedback < 5:  # Need minimum feedback to adjust
                continue
            
            irrelevant_ratio = irrelevant_count / total_feedback
            
            if irrelevant_ratio > 0.3:  # >30% irrelevant
                # Reduce channel weight proportionally
                weights[channel_id] = max(0.2, 1.0 - irrelevant_ratio)
        
        return weights
    
    def _detect_recurring(self, items_by_title: dict[str, list[DigestItem]]) -> dict[str, list[str]]:
        """Detect recurring items that should be collapsed."""
        recurring = {}
        
        for title, items in items_by_title.items():
            if len(items) > 2:  # Appeared more than twice
                recurring[title] = [item.digest_item_id for item in items]
        
        return recurring
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for dedup matching."""
        # Simple normalization: lowercase, remove punctuation, trim
        import re
        normalized = title.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized
    
    def apply_confidence_adjustment(self, item: DigestItem, adjustments: ProcessorAdjustments) -> float:
        """
        Apply confidence adjustment to an item based on feedback patterns.
        
        Returns the new confidence score.
        """
        new_confidence = item.confidence
        
        # Apply type-based adjustment
        if item.item_type in adjustments.confidence_adjustments:
            new_confidence += adjustments.confidence_adjustments[item.item_type]
        
        # Clamp to valid range
        new_confidence = max(0.0, min(1.0, new_confidence))
        
        return new_confidence
    
    def apply_item_specific_feedback(self, digest_item_id: str) -> float:
        """
        Apply feedback-based confidence adjustment for a specific item.
        
        Used when processing feedback in real-time.
        """
        feedback = self.store.get_feedback_for_item(digest_item_id)
        if not feedback:
            return 1.0
        
        total = len(feedback)
        wrong = sum(1 for f in feedback if f.feedback_type == "wrong")
        irrelevant = sum(1 for f in feedback if f.feedback_type == "irrelevant")
        accurate = sum(1 for f in feedback if f.feedback_type == "accurate")
        
        adjustment = 0.0
        if wrong / total > self.WRONG_THRESHOLD:
            adjustment -= self.WRONG_PENALTY
        if irrelevant / total > self.IRRELEVANT_THRESHOLD:
            adjustment -= self.IRRELEVANT_PENALTY
        if accurate / total > 0.5:
            adjustment += self.ACCURATE_BOOST
        
        return max(0.0, min(1.0, 1.0 + adjustment))
    
    def should_include_item(self, confidence: float) -> str:
        """
        Determine how to handle item based on confidence.
        
        Returns:
            "main" - include in main digest sections
            "fyi" - include in Lower Confidence / FYI section
            "exclude" - don't include at all
        """
        if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            return "main"
        elif confidence >= self.LOW_CONFIDENCE_THRESHOLD:
            return "fyi"
        else:
            return "exclude"
    
    def is_recurring(self, title: str, adjustments: ProcessorAdjustments) -> Optional[list[str]]:
        """Check if an item is recurring and return list of previous item IDs."""
        normalized = self._normalize_title(title)
        return adjustments.recurring_items.get(normalized)
    
    def get_channel_weight(self, channel_id: str, adjustments: ProcessorAdjustments) -> float:
        """Get weight for a channel (1.0 = normal, lower = reduced contribution)."""
        return adjustments.channel_weights.get(channel_id, 1.0)
