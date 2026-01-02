"""Digest Ranker - re-ranks items based on personas and feedback history."""

import re
from dataclasses import dataclass
from typing import Optional

from .personas import Persona, PersonaManager, RolePersona, TeamPersona
from ..feedback.feedback_store import FeedbackStore, DigestItem
from ..feedback.feedback_processor import FeedbackProcessor, ProcessorAdjustments


@dataclass
class RankedItem:
    """A digest item with its computed score and ranking metadata."""
    
    item: DigestItem
    final_score: float
    
    # Score breakdown
    base_score: float
    cross_team_boost: float
    actionability_boost: float
    role_boost: float
    topic_boost: float
    feedback_adjustment: float
    
    # Metadata
    is_cross_team: bool
    matched_topics: list[str]
    
    def __lt__(self, other: "RankedItem") -> bool:
        """Sort by final_score descending."""
        return self.final_score > other.final_score


# Cross-team detection patterns
CROSS_TEAM_PATTERNS = [
    r"<@U_\w+>",  # User mentions
    r"@\w+",       # At-mentions
    r"waiting on (mechanical|electrical|software|firmware|mech|ee|sw)",
    r"blocked by (mechanical|electrical|software|firmware|mech|ee|sw)",
    r"blocked on (mechanical|electrical|software|firmware|mech|ee|sw)",
    r"need.* from (mechanical|electrical|software|firmware|mech|ee|sw)",
    r"(mechanical|electrical|software|firmware) team",
    r"cross[- ]team",
]

# Teams and their aliases for detection
TEAM_ALIASES = {
    "mechanical": ["mechanical", "mech", "me"],
    "electrical": ["electrical", "ee", "hardware", "hw"],
    "software": ["software", "sw", "firmware", "fw"],
}


class DigestRanker:
    """
    Re-ranks digest items based on personas and feedback history.
    
    Ranking priority (highest to lowest):
    1. Cross-team impact (items affecting multiple teams)
    2. Actionability (blockers > action_items > decisions > updates)
    3. Role persona preferences (leads see different priority than ICs)
    4. Team persona topic matching
    5. Historical feedback adjustments
    
    The ranker produces a final score in [0, 1] range for each item.
    """
    
    # Boost amounts
    CROSS_TEAM_BOOST = 0.3
    ACTIONABILITY_BOOSTS = {
        "blocker": 0.20,
        "action_item": 0.15,
        "decision": 0.10,
        "update": 0.0,
    }
    TOPIC_MATCH_BOOST = 0.1
    
    def __init__(
        self,
        feedback_store: Optional[FeedbackStore] = None,
        persona_manager: Optional[PersonaManager] = None,
    ):
        self.feedback_store = feedback_store or FeedbackStore()
        self.persona_manager = persona_manager or PersonaManager()
        self.feedback_processor = FeedbackProcessor(self.feedback_store)
        self._cached_adjustments: Optional[ProcessorAdjustments] = None
    
    def rank_items(
        self,
        items: list[DigestItem],
        user_id: Optional[str] = None,
        team: str = "general",
        role: str = "ic",
        source_team: Optional[str] = None,
    ) -> list[RankedItem]:
        """
        Rank items for a specific user based on their persona.
        
        Args:
            items: List of DigestItem to rank
            user_id: Optional user ID for personalized ranking
            team: Team name for team persona
            role: Role name for role persona
            source_team: The team that generated these items (for cross-team detection)
            
        Returns:
            List of RankedItem sorted by final_score descending
        """
        # Get combined persona
        if user_id:
            persona = self.persona_manager.get_combined_persona(user_id, role, team)
        else:
            # Create temporary combined persona
            role_persona = RolePersona.get(role)
            team_persona = TeamPersona.get(team)
            persona = Persona(
                persona_type=role_persona.persona_type,
                name=f"{role}_{team}",
                item_boosts=role_persona.item_boosts,
                cross_team_weight=role_persona.cross_team_weight,
                topics_of_interest=team_persona.topics_of_interest,
                min_severity_for_main=role_persona.min_severity_for_main,
            )
        
        # Get feedback adjustments (cached for efficiency)
        if self._cached_adjustments is None:
            self._cached_adjustments = self.feedback_processor.get_adjustments(days=7)
        
        # Rank each item
        ranked = []
        for item in items:
            ranked_item = self._score_item(item, persona, source_team)
            ranked.append(ranked_item)
        
        # Sort by final score descending
        ranked.sort()
        
        return ranked
    
    def _score_item(
        self,
        item: DigestItem,
        persona: Persona,
        source_team: Optional[str] = None,
    ) -> RankedItem:
        """Compute score for a single item."""
        
        # Base score from item confidence
        base_score = item.confidence
        
        # 1. Cross-team boost (highest priority)
        is_cross_team, cross_team_boost = self._compute_cross_team_boost(
            item, persona, source_team
        )
        
        # 2. Actionability boost
        actionability_boost = self.ACTIONABILITY_BOOSTS.get(item.item_type, 0.0)
        
        # 3. Role persona boost
        role_boost = persona.get_item_boost(item.item_type) - 1.0  # Convert multiplier to additive
        
        # 4. Topic matching boost
        matched_topics, topic_boost = self._compute_topic_boost(item, persona)
        
        # 5. Feedback adjustment
        feedback_adjustment = self._get_feedback_adjustment(item)
        
        # Compute final score
        final_score = (
            base_score
            + cross_team_boost
            + actionability_boost
            + role_boost * 0.1  # Scale down role boost
            + topic_boost
            + feedback_adjustment
        )
        
        # Clamp to [0, 1]
        final_score = max(0.0, min(1.0, final_score))
        
        return RankedItem(
            item=item,
            final_score=final_score,
            base_score=base_score,
            cross_team_boost=cross_team_boost,
            actionability_boost=actionability_boost,
            role_boost=role_boost,
            topic_boost=topic_boost,
            feedback_adjustment=feedback_adjustment,
            is_cross_team=is_cross_team,
            matched_topics=matched_topics,
        )
    
    def _compute_cross_team_boost(
        self,
        item: DigestItem,
        persona: Persona,
        source_team: Optional[str] = None,
    ) -> tuple[bool, float]:
        """
        Detect cross-team items and compute boost.
        
        Returns (is_cross_team, boost_amount).
        """
        text = f"{item.title} {item.summary}".lower()
        item_team = item.team.lower() if item.team else ""
        
        # Check for cross-team patterns
        is_cross_team = False
        
        # Pattern matching
        for pattern in CROSS_TEAM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                is_cross_team = True
                break
        
        # Check if item mentions teams other than its own
        if not is_cross_team and item_team:
            for team_name, aliases in TEAM_ALIASES.items():
                if team_name != item_team:
                    for alias in aliases:
                        if alias in text:
                            is_cross_team = True
                            break
                if is_cross_team:
                    break
        
        # Check if item affects source team differently
        if not is_cross_team and source_team:
            source_lower = source_team.lower()
            if item_team and item_team != source_lower:
                # Item is from a different team than we're generating for
                is_cross_team = True
        
        if is_cross_team:
            # Apply persona's cross-team weight
            boost = self.CROSS_TEAM_BOOST * persona.cross_team_weight
            return True, boost
        
        return False, 0.0
    
    def _compute_topic_boost(
        self,
        item: DigestItem,
        persona: Persona,
    ) -> tuple[list[str], float]:
        """
        Check topic matching and compute boost.
        
        Returns (matched_topics, boost_amount).
        """
        text = f"{item.title} {item.summary}".lower()
        matched = []
        
        for topic in persona.topics_of_interest:
            if topic.lower() in text:
                matched.append(topic)
        
        if matched:
            # Boost increases with more matches, but cap at 2x base boost
            boost = min(self.TOPIC_MATCH_BOOST * len(matched), self.TOPIC_MATCH_BOOST * 2)
            return matched, boost
        
        return [], 0.0
    
    def _get_feedback_adjustment(self, item: DigestItem) -> float:
        """Get feedback-based adjustment for item type."""
        if self._cached_adjustments is None:
            return 0.0
        
        return self._cached_adjustments.confidence_adjustments.get(item.item_type, 0.0)
    
    def invalidate_cache(self):
        """Invalidate cached adjustments (call after feedback is processed)."""
        self._cached_adjustments = None
    
    def get_cross_team_items(
        self,
        ranked_items: list[RankedItem],
    ) -> list[RankedItem]:
        """Filter to only cross-team items."""
        return [r for r in ranked_items if r.is_cross_team]
    
    def partition_by_confidence(
        self,
        ranked_items: list[RankedItem],
        high_threshold: float = 0.7,
        low_threshold: float = 0.4,
    ) -> tuple[list[RankedItem], list[RankedItem], list[RankedItem]]:
        """
        Partition ranked items by confidence thresholds.
        
        Returns (high_confidence, low_confidence, excluded).
        """
        high = []
        low = []
        excluded = []
        
        for item in ranked_items:
            if item.final_score >= high_threshold:
                high.append(item)
            elif item.final_score >= low_threshold:
                low.append(item)
            else:
                excluded.append(item)
        
        return high, low, excluded
    
    def explain_ranking(self, ranked_item: RankedItem) -> str:
        """Generate human-readable explanation of ranking."""
        parts = [f"Score: {ranked_item.final_score:.2f}"]
        
        if ranked_item.is_cross_team:
            parts.append(f"Cross-team: +{ranked_item.cross_team_boost:.2f}")
        
        if ranked_item.actionability_boost > 0:
            parts.append(f"Actionability ({ranked_item.item.item_type}): +{ranked_item.actionability_boost:.2f}")
        
        if ranked_item.role_boost != 0:
            sign = "+" if ranked_item.role_boost > 0 else ""
            parts.append(f"Role: {sign}{ranked_item.role_boost:.2f}")
        
        if ranked_item.matched_topics:
            parts.append(f"Topics: {', '.join(ranked_item.matched_topics[:3])}")
        
        if ranked_item.feedback_adjustment != 0:
            sign = "+" if ranked_item.feedback_adjustment > 0 else ""
            parts.append(f"Feedback: {sign}{ranked_item.feedback_adjustment:.2f}")
        
        return " | ".join(parts)
