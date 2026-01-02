"""Digest Evaluator - LLM-based quality assessment of digest items."""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

from ..personalization.personas import Persona
from ..feedback.feedback_store import DigestItem


@dataclass
class DigestEvaluation:
    """
    Evaluation result for a single digest item.
    
    Scores are 0-1 where higher is better.
    """
    
    digest_item_id: str
    item_type: str
    team: str
    
    # Quality scores (0-1)
    completeness_score: float  # Does it capture full context?
    relevance_score: float     # Is it relevant to the recipient?
    actionability_score: float # Can recipient act on it?
    cross_team_surfacing: float # Was cross-team impact highlighted?
    
    # Overall quality
    overall_score: float
    
    # Simulated feedback (what a user would likely react with)
    simulated_feedback_type: str  # "accurate", "wrong", "irrelevant", "missing_context"
    feedback_reason: str
    
    # Metadata
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    persona_name: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


# Evaluation rubric for the LLM
EVALUATION_RUBRIC = """
## Digest Item Evaluation Rubric

Evaluate each digest item on the following criteria (score 0-1):

### COMPLETENESS (0-1)
- 0.9-1.0: Full context provided - who, what, when, why, impact all clear
- 0.7-0.89: Most context present, minor details missing
- 0.5-0.69: Some context missing that would help understanding
- 0.3-0.49: Significant context gaps
- 0.0-0.29: Major information missing, hard to understand

### RELEVANCE (0-1)
Consider the recipient's role and team:
- 1.0: Directly affects recipient's work, must-know
- 0.7-0.9: Important for situational awareness
- 0.4-0.69: Tangentially related, nice-to-know
- 0.0-0.39: Not relevant to this recipient

### ACTIONABILITY (0-1)
- 1.0: Clear action required with owner/deadline
- 0.7-0.9: Implies action needed, mostly clear
- 0.4-0.69: May need action but unclear what/when
- 0.0-0.39: No action needed or possible

### CROSS-TEAM SURFACING (0-1)
- 1.0: Cross-team dependency explicitly called out with both teams named
- 0.7-0.9: Cross-team nature mentioned but could be clearer
- 0.4-0.69: Implicit cross-team impact not highlighted
- 0.0-0.39: Cross-team aspect missed or not applicable

## Feedback Type Rules

Based on scores, determine what feedback a user would give:

- ACCURATE: overall >= 0.75 and relevance >= 0.6
- WRONG: completeness < 0.4 OR (relevance < 0.3 AND actionability < 0.3)
- IRRELEVANT: relevance < 0.4 AND overall >= 0.4
- MISSING_CONTEXT: completeness < 0.5 OR cross_team_surfacing < 0.4 (for cross-team items)
"""


class DigestEvaluator:
    """
    LLM-based evaluator for digest quality.
    
    Evaluates digest items against a rubric considering:
    - Completeness: Does it capture the full context?
    - Relevance: Is it important for the recipient?
    - Actionability: Can they act on it?
    - Cross-team surfacing: Are dependencies highlighted?
    """
    
    def __init__(self, use_mock: bool = False):
        """
        Initialize evaluator.
        
        Args:
            use_mock: If True, use mock evaluations instead of LLM
        """
        self.use_mock = use_mock
        self._llm = None
    
    @property
    def llm(self) -> ChatOpenAI:
        """Lazy-load LLM."""
        if self._llm is None:
            model = os.getenv("CHAT_MODEL", "gpt-4")
            self._llm = ChatOpenAI(model=model, temperature=0.3)
        return self._llm
    
    def evaluate_items(
        self,
        items: list[DigestItem],
        recipient_persona: Persona,
        original_messages: Optional[list[dict]] = None,
    ) -> list[DigestEvaluation]:
        """
        Evaluate a batch of digest items.
        
        Args:
            items: Digest items to evaluate
            recipient_persona: Who is receiving this digest
            original_messages: Optional source messages for context
            
        Returns:
            List of evaluations
        """
        if self.use_mock:
            return self._mock_evaluate(items, recipient_persona)
        
        return self._llm_evaluate(items, recipient_persona, original_messages)
    
    def _mock_evaluate(
        self,
        items: list[DigestItem],
        persona: Persona,
    ) -> list[DigestEvaluation]:
        """Generate mock evaluations for testing."""
        evaluations = []
        
        for item in items:
            # Heuristic-based scoring
            completeness = self._mock_completeness(item)
            relevance = self._mock_relevance(item, persona)
            actionability = self._mock_actionability(item)
            cross_team = self._mock_cross_team(item)
            
            overall = (completeness + relevance + actionability + cross_team) / 4
            
            # Determine feedback type
            feedback_type, reason = self._determine_feedback(
                completeness, relevance, actionability, cross_team, overall
            )
            
            evaluations.append(DigestEvaluation(
                digest_item_id=item.digest_item_id,
                item_type=item.item_type,
                team=item.team,
                completeness_score=completeness,
                relevance_score=relevance,
                actionability_score=actionability,
                cross_team_surfacing=cross_team,
                overall_score=overall,
                simulated_feedback_type=feedback_type,
                feedback_reason=reason,
                persona_name=persona.name,
            ))
        
        return evaluations
    
    def _mock_completeness(self, item: DigestItem) -> float:
        """Heuristic for completeness based on text length and structure."""
        text = f"{item.title} {item.summary}"
        
        # Longer summaries tend to be more complete
        length_score = min(len(text) / 200, 1.0) * 0.5
        
        # Check for key information
        has_owner = bool(item.owners) or "owner" in text.lower()
        has_context = len(item.summary) > 50
        
        structure_score = (0.25 if has_owner else 0) + (0.25 if has_context else 0)
        
        base = 0.5 + length_score * 0.3 + structure_score
        return min(base + (item.confidence - 0.5) * 0.2, 1.0)
    
    def _mock_relevance(self, item: DigestItem, persona: Persona) -> float:
        """Heuristic for relevance based on persona matching."""
        text = f"{item.title} {item.summary}".lower()
        
        # Check topic matches
        topic_matches = sum(1 for t in persona.topics_of_interest if t.lower() in text)
        topic_score = min(topic_matches / 3, 1.0) * 0.4 if persona.topics_of_interest else 0.5
        
        # Check team match
        team_match = item.team.lower() in persona.name.lower() if item.team else False
        team_score = 0.3 if team_match else 0.1
        
        # Item type relevance from persona boosts
        type_boost = persona.get_item_boost(item.item_type)
        type_score = min((type_boost - 0.5) * 0.5, 0.3)
        
        return min(0.4 + topic_score + team_score + type_score, 1.0)
    
    def _mock_actionability(self, item: DigestItem) -> float:
        """Heuristic for actionability based on item type and content."""
        text = f"{item.title} {item.summary}".lower()
        
        # Item type base scores
        type_scores = {
            "blocker": 0.8,
            "action_item": 0.9,
            "decision": 0.5,
            "update": 0.3,
        }
        base = type_scores.get(item.item_type, 0.5)
        
        # Check for action words
        action_words = ["need", "should", "must", "please", "required", "asap", "urgent"]
        has_action = any(word in text for word in action_words)
        
        # Check for owner
        has_owner = bool(item.owners) or "@" in text
        
        return min(base + (0.1 if has_action else 0) + (0.1 if has_owner else 0), 1.0)
    
    def _mock_cross_team(self, item: DigestItem) -> float:
        """Heuristic for cross-team surfacing."""
        text = f"{item.title} {item.summary}".lower()
        
        # Check for cross-team indicators
        teams = ["mechanical", "electrical", "software", "firmware", "mech", "ee", "sw"]
        mentioned_teams = [t for t in teams if t in text]
        
        # Check for explicit cross-team language
        cross_team_phrases = [
            "cross-team", "waiting on", "blocked by", "need from",
            "sync with", "coordinate with", "depends on"
        ]
        has_cross_phrase = any(phrase in text for phrase in cross_team_phrases)
        
        if len(mentioned_teams) >= 2:
            return 0.9 if has_cross_phrase else 0.7
        elif len(mentioned_teams) == 1 and has_cross_phrase:
            return 0.6
        elif has_cross_phrase:
            return 0.5
        else:
            return 0.3  # No cross-team aspect detected
    
    def _determine_feedback(
        self,
        completeness: float,
        relevance: float,
        actionability: float,
        cross_team: float,
        overall: float,
    ) -> tuple[str, str]:
        """Determine simulated feedback type and reason."""
        
        if overall >= 0.75 and relevance >= 0.6:
            return "accurate", "High quality, relevant item"
        
        if completeness < 0.4:
            return "wrong", f"Incomplete information (completeness: {completeness:.2f})"
        
        if relevance < 0.4 and overall >= 0.4:
            return "irrelevant", f"Not relevant to recipient (relevance: {relevance:.2f})"
        
        if completeness < 0.5 or cross_team < 0.4:
            return "missing_context", f"Needs more context (completeness: {completeness:.2f}, cross_team: {cross_team:.2f})"
        
        if relevance < 0.3 and actionability < 0.3:
            return "wrong", f"Low value item (relevance: {relevance:.2f}, actionability: {actionability:.2f})"
        
        return "accurate", "Acceptable quality"
    
    def _llm_evaluate(
        self,
        items: list[DigestItem],
        persona: Persona,
        original_messages: Optional[list[dict]] = None,
    ) -> list[DigestEvaluation]:
        """Use LLM for evaluation."""
        
        # Format items for evaluation
        items_text = ""
        for i, item in enumerate(items):
            items_text += f"""
--- Item {i+1} ---
ID: {item.digest_item_id}
Type: {item.item_type}
Team: {item.team}
Title: {item.title}
Summary: {item.summary}
Severity: {item.severity}
Owners: {', '.join(item.owners) if item.owners else 'None'}
"""
        
        # Format persona context
        persona_context = f"""
Recipient Persona:
- Type: {persona.persona_type.value}
- Name: {persona.name}
- Cross-team interest: {persona.cross_team_weight}
- Topics of interest: {', '.join(persona.topics_of_interest[:10])}
"""
        
        prompt = f"""{EVALUATION_RUBRIC}

{persona_context}

## Items to Evaluate

{items_text}

## Instructions

For each item, provide a JSON evaluation with these fields:
- digest_item_id
- completeness_score (0-1)
- relevance_score (0-1)
- actionability_score (0-1)
- cross_team_surfacing (0-1)
- overall_score (average of above)
- simulated_feedback_type ("accurate", "wrong", "irrelevant", "missing_context")
- feedback_reason (brief explanation)

Return a JSON array with one evaluation per item.
"""
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="You are a digest quality evaluator. Respond only with valid JSON."),
                HumanMessage(content=prompt),
            ])
            
            # Parse JSON response
            content = response.content
            start = content.find("[")
            end = content.rfind("]") + 1
            
            if start != -1 and end > start:
                evals_data = json.loads(content[start:end])
                
                evaluations = []
                for eval_dict in evals_data:
                    evaluations.append(DigestEvaluation(
                        digest_item_id=eval_dict.get("digest_item_id", ""),
                        item_type=next((i.item_type for i in items if i.digest_item_id == eval_dict.get("digest_item_id")), ""),
                        team=next((i.team for i in items if i.digest_item_id == eval_dict.get("digest_item_id")), ""),
                        completeness_score=float(eval_dict.get("completeness_score", 0.5)),
                        relevance_score=float(eval_dict.get("relevance_score", 0.5)),
                        actionability_score=float(eval_dict.get("actionability_score", 0.5)),
                        cross_team_surfacing=float(eval_dict.get("cross_team_surfacing", 0.5)),
                        overall_score=float(eval_dict.get("overall_score", 0.5)),
                        simulated_feedback_type=eval_dict.get("simulated_feedback_type", "accurate"),
                        feedback_reason=eval_dict.get("feedback_reason", ""),
                        persona_name=persona.name,
                    ))
                return evaluations
                
        except Exception as e:
            print(f"LLM evaluation failed: {e}, falling back to mock")
        
        # Fallback to mock
        return self._mock_evaluate(items, persona)
