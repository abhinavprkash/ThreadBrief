"""Prompt Enhancer - generates bounded, expiring prompt directives from feedback patterns."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from .feedback_store import FeedbackStore, FeedbackEvent


@dataclass
class DirectiveCandidate:
    """A candidate directive with scoring."""
    directive: str
    score: float  # Higher = more important
    feedback_count: int
    last_seen: str


class PromptEnhancer:
    """
    Generates prompt directives from feedback patterns.
    
    Features:
    - Max 10-15 bullets per team
    - Weekly rotation
    - 14-day expiry unless reconfirmed
    - Prioritization by confirmation count
    """
    
    MAX_DIRECTIVES = 12  # 10-15 bullets max
    EXPIRY_DAYS = 14     # Expire unless reconfirmed
    ROTATION_DAYS = 7    # Weekly rotation for new analysis
    
    # Heuristic templates for common failure patterns
    DIRECTIVE_TEMPLATES = {
        "wrong_decision": "Do not label as a decision unless explicit approval language exists (e.g., 'approved', 'decided', 'agreed').",
        "wrong_blocker": "Only classify as blocker if there's clear blocking language (e.g., 'blocked by', 'waiting on', 'can't proceed').",
        "wrong_owner": "Prefer naming owners only when an @mention or clear assignment exists.",
        "missing_context_decision": "Include context for decisions: who made it, when, and what alternatives were considered.",
        "missing_context_blocker": "Include blocked-by entity and estimated impact when classifying blockers.",
        "irrelevant_update": "Skip routine status updates that don't indicate meaningful progress or changes.",
        "irrelevant_fyi": "Exclude FYI messages that are purely informational with no action required.",
        "wrong_severity": "Reserve 'high' severity for items that block critical path or have deadline implications.",
    }
    
    def __init__(self, store: Optional[FeedbackStore] = None, use_llm: bool = False):
        if store is None:
            store = FeedbackStore()
        self.store = store
        self.use_llm = use_llm
    
    def generate_directives(self, team: str) -> str:
        """
        Generate prompt directives for a team based on recent feedback.
        
        Returns formatted directive bullets ready for prompt injection.
        """
        # First, expire old directives
        self.store.expire_old_directives(self.EXPIRY_DAYS)
        
        # Get existing active directives
        existing = self.store.get_active_directives(team, self.MAX_DIRECTIVES, self.EXPIRY_DAYS)
        
        # Analyze recent feedback for new patterns
        new_directives = self._analyze_feedback_patterns(team)
        
        # Merge and dedupe
        all_directives = self._merge_directives(existing, new_directives)
        
        # Store new ones for persistence
        for directive in new_directives:
            if directive not in existing:
                self.store.add_directive(team, directive)
        
        # Format as bullets
        if all_directives:
            return "\n".join(f"- {d}" for d in all_directives[:self.MAX_DIRECTIVES])
        return ""
    
    def _analyze_feedback_patterns(self, team: str) -> list[str]:
        """
        Analyze feedback to generate new directive candidates.
        
        Uses heuristics for PoC; can be extended with LLM for production.
        """
        candidates = []
        
        # Get recent feedback with associated items
        recent_feedback = self.store.get_recent_feedback(days=self.ROTATION_DAYS, team=team)
        
        # Group feedback by type and analyze patterns
        wrong_items: list[tuple[FeedbackEvent, str]] = []
        missing_context_items: list[tuple[FeedbackEvent, str]] = []
        irrelevant_items: list[tuple[FeedbackEvent, str]] = []
        
        for fb in recent_feedback:
            # Get the associated item to understand what was marked wrong
            items = self.store.get_items_by_run("")  # We need item details
            item = next((i for i in self.store.get_recent_items(days=30) 
                        if i.digest_item_id == fb.digest_item_id), None)
            
            if not item:
                continue
            
            if fb.feedback_type == "wrong":
                wrong_items.append((fb, item.item_type))
            elif fb.feedback_type == "missing_context":
                missing_context_items.append((fb, item.item_type))
            elif fb.feedback_type == "irrelevant":
                irrelevant_items.append((fb, item.item_type))
        
        # Generate directives based on patterns
        wrong_by_type = defaultdict(int)
        for fb, item_type in wrong_items:
            wrong_by_type[item_type] += 1
        
        missing_by_type = defaultdict(int)
        for fb, item_type in missing_context_items:
            missing_by_type[item_type] += 1
        
        irrelevant_by_type = defaultdict(int)
        for fb, item_type in irrelevant_items:
            irrelevant_by_type[item_type] += 1
        
        # Apply heuristic templates
        if wrong_by_type.get("decision", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["wrong_decision"])
        
        if wrong_by_type.get("blocker", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["wrong_blocker"])
        
        if wrong_by_type.get("update", 0) >= 3:
            candidates.append(self.DIRECTIVE_TEMPLATES["wrong_owner"])
        
        if missing_by_type.get("decision", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["missing_context_decision"])
        
        if missing_by_type.get("blocker", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["missing_context_blocker"])
        
        if irrelevant_by_type.get("update", 0) >= 3:
            candidates.append(self.DIRECTIVE_TEMPLATES["irrelevant_update"])
        
        if irrelevant_by_type.get("fyi", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["irrelevant_fyi"])
        
        # Check for severity issues
        if wrong_by_type.get("blocker", 0) >= 2 or wrong_by_type.get("risk", 0) >= 2:
            candidates.append(self.DIRECTIVE_TEMPLATES["wrong_severity"])
        
        return candidates
    
    def _merge_directives(self, existing: list[str], new: list[str]) -> list[str]:
        """Merge existing and new directives, removing duplicates."""
        seen = set()
        merged = []
        
        # Existing directives first (already prioritized by confirmation count)
        for d in existing:
            normalized = d.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                merged.append(d)
        
        # Then new ones
        for d in new:
            normalized = d.lower().strip()
            if normalized not in seen:
                seen.add(normalized)
                merged.append(d)
        
        return merged[:self.MAX_DIRECTIVES]
    
    def get_active_patches(self, team: str) -> str:
        """
        Get current active patches for a team, ready for prompt injection.
        
        This is the main interface used by TeamAnalyzerAgent.
        """
        directives = self.store.get_active_directives(
            team, 
            max_count=self.MAX_DIRECTIVES,
            expiry_days=self.EXPIRY_DAYS
        )
        
        if directives:
            return "\n".join(f"- {d}" for d in directives)
        return ""
    
    def confirm_directive(self, team: str, directive: str):
        """
        Confirm a directive based on new matching feedback.
        
        This extends the directive's lifespan.
        """
        self.store.add_directive(team, directive)
    
    def force_expire(self, team: str, directive: str):
        """Manually expire a specific directive."""
        self.store.deactivate_directive(team, directive)
    
    def get_prompt_instructions(self, team: str = "", item_type: str = "") -> str:
        """
        Get formatted prompt instructions for a team, ready for injection.
        
        This is the interface used by BaseAgent._get_feedback_instructions().
        
        Args:
            team: Team name to get directives for
            item_type: Optional filter for specific item types (blocker, decision, etc.)
            
        Returns:
            Formatted instructions string for prompt injection
        """
        if not team:
            return ""
        
        directives = self.store.get_active_directives(
            team,
            max_count=self.MAX_DIRECTIVES,
            expiry_days=self.EXPIRY_DAYS
        )
        
        if not directives:
            return ""
        
        # Filter by item type if specified
        if item_type:
            type_keywords = {
                "blocker": ["blocker", "blocking", "blocked"],
                "decision": ["decision", "decided", "approval"],
                "update": ["update", "status", "progress"],
                "action_item": ["action", "task", "owner"],
            }
            keywords = type_keywords.get(item_type, [])
            if keywords:
                directives = [
                    d for d in directives 
                    if any(kw in d.lower() for kw in keywords)
                ]
        
        if directives:
            formatted = "\n".join(f"- {d}" for d in directives)
            return f"\n\n## Quality rules from user feedback (apply these):\n{formatted}"
        return ""

