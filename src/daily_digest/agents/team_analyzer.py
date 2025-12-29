"""Team Analyzer Agent - unified agent that extracts all team insights in one call."""

from dataclasses import dataclass, field
from typing import Optional

from .base import BaseAgent
from ..models.events import (
    EventType,
    StructuredEvent,
    Decision,
    Blocker,
    StatusUpdate,
    ActionItem,
)


@dataclass
class TeamAnalysis:
    """Complete analysis of a team's messages."""
    
    team_name: str
    channel_id: str
    message_count: int
    
    # Summary
    summary: str = ""
    themes: list[str] = field(default_factory=list)
    tone: str = "routine"  # productive, collaborative, challenging, routine, focused
    
    # Extracted items
    updates: list[dict] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    
    def to_events(self) -> list[StructuredEvent]:
        """Convert analysis to structured events for V2 pipeline."""
        events = []
        
        # Convert updates to StatusUpdate events
        for u in self.updates:
            events.append(StatusUpdate(
                event_type=EventType.STATUS_UPDATE,
                summary=u.get("update", ""),
                confidence=0.9,
                source_channel=self.channel_id,
                source_message_ts="",
                teams_involved=[self.team_name],
                owners=[u.get("author", "")] if u.get("author") else [],
                urgency="medium",
                topics=[u.get("category", "progress")],
                what_happened=u.get("update", ""),
                who=u.get("author", ""),
                category=u.get("category", "progress"),
            ))
        
        # Convert blockers to Blocker events
        for b in self.blockers:
            events.append(Blocker(
                event_type=EventType.BLOCKER,
                summary=b.get("issue", ""),
                confidence=0.9,
                source_channel=self.channel_id,
                source_message_ts="",
                teams_involved=[self.team_name],
                owners=[b.get("owner", "")] if b.get("owner") else [],
                urgency="high" if b.get("severity") == "high" else "medium",
                topics=[],
                issue=b.get("issue", ""),
                owner=b.get("owner", ""),
                severity=b.get("severity", "medium"),
                status=b.get("status", "active"),
                blocked_by=b.get("blocked_by"),
            ))
        
        # Convert decisions to Decision events
        for d in self.decisions:
            events.append(Decision(
                event_type=EventType.DECISION,
                summary=d.get("decision", ""),
                confidence=0.9,
                source_channel=self.channel_id,
                source_message_ts="",
                teams_involved=[self.team_name],
                owners=[d.get("made_by", "")] if d.get("made_by") else [],
                urgency="medium",
                topics=[],
                what_decided=d.get("decision", ""),
                decided_by=d.get("made_by", ""),
                context=d.get("context", ""),
                impact=d.get("impact", ""),
            ))
        
        return events
    
    def to_action_items(self) -> list[ActionItem]:
        """Convert extracted action items to ActionItem objects."""
        items = []
        for a in self.action_items:
            items.append(ActionItem(
                description=a.get("description", ""),
                owner=a.get("owner", "unassigned"),
                source_event_type=EventType.STATUS_UPDATE,
                source_link="",
                priority=a.get("priority", "medium"),
            ))
        return items


class TeamAnalyzerAgent(BaseAgent):
    """
    Unified agent that analyzes team messages and extracts all insights in one call.
    
    Replaces the 4 V1 agents (UpdateExtractor, BlockerDetector, DecisionTracker, 
    DiscussionSummarizer) with a single LLM call per team.
    
    Returns structured JSON with:
    - summary: Overall team summary
    - themes: Key topics discussed
    - tone: Team energy/mood
    - updates[]: Key updates with author, category
    - blockers[]: Issues with severity, owner, status
    - decisions[]: Decisions with context, impact
    - action_items[]: Extracted action items
    """
    
    @property
    def agent_name(self) -> str:
        return "TeamAnalyzer"
    
    @property
    def prompt_template(self) -> str:
        return """Analyze these Slack messages from the {team_name} team and extract a complete analysis.

Messages:
{messages}

Return a JSON object with this exact structure:
{{
    "summary": "2-3 sentence summary of the team's activity today. Be specific about what was worked on.",
    "themes": ["theme1", "theme2", "theme3"],
    "tone": "productive|collaborative|challenging|routine|focused",
    "updates": [
        {{
            "update": "Brief description of the update",
            "author": "Person who made the update",
            "category": "completion|progress|announcement|milestone"
        }}
    ],
    "blockers": [
        {{
            "issue": "Description of the blocker or issue",
            "owner": "Person responsible or affected",
            "severity": "high|medium|low",
            "status": "active|resolved|mitigated",
            "blocked_by": "Person or team causing block (optional)"
        }}
    ],
    "decisions": [
        {{
            "decision": "Clear statement of what was decided",
            "made_by": "Person who made or confirmed the decision",
            "context": "Brief context on why this decision was made",
            "impact": "What this decision affects"
        }}
    ],
    "action_items": [
        {{
            "description": "What needs to be done",
            "owner": "Person responsible",
            "priority": "high|medium|low"
        }}
    ]
}}

Guidelines:
- Summary: Be concise but informative (2-3 sentences max)
- Themes: 2-4 words each, limit to 3-4 themes
- Updates: Only include significant updates, limit to top 5-7
- Blockers: Include actual issues, not hypotheticals. High severity = blocks critical path
- Decisions: Only include actual decisions made, not discussions or proposals
- Action items: Extract implicit action items (e.g., "I'll fix this by EOD")"""
    
    def _empty_result(self) -> dict:
        return {
            "summary": "No significant activity to summarize.",
            "themes": [],
            "tone": "routine",
            "updates": [],
            "blockers": [],
            "decisions": [],
            "action_items": [],
        }
    
    def _mock_result(self, messages_text: str, team_name: str) -> dict:
        """Generate mock analysis for testing."""
        return {
            "summary": f"[Mock] The {team_name} team had an active day with multiple discussions and progress on key deliverables.",
            "themes": ["Project progress", "Team coordination", "Technical discussions"],
            "tone": "productive",
            "updates": [
                {
                    "update": f"[Mock] Progress made on {team_name} deliverables",
                    "author": "Team Member",
                    "category": "progress"
                },
                {
                    "update": f"[Mock] Completed key task for {team_name}",
                    "author": "Team Lead",
                    "category": "completion"
                }
            ],
            "blockers": [
                {
                    "issue": f"[Mock] Waiting on external dependency for {team_name}",
                    "owner": "Team Lead",
                    "severity": "medium",
                    "status": "active"
                }
            ],
            "decisions": [
                {
                    "decision": f"[Mock] Approved approach for {team_name} deliverable",
                    "made_by": "Team Lead",
                    "context": "After team discussion",
                    "impact": "Unblocks next sprint work"
                }
            ],
            "action_items": [
                {
                    "description": f"[Mock] Follow up on {team_name} blockers",
                    "owner": "Team Lead",
                    "priority": "medium"
                }
            ]
        }
    
    def analyze_team(
        self,
        messages_text: str,
        team_name: str,
        channel_id: str = "",
        message_count: int = 0,
    ) -> TeamAnalysis:
        """
        Analyze team messages and return complete TeamAnalysis.
        
        Args:
            messages_text: Formatted messages text
            team_name: Name of the team
            channel_id: Slack channel ID
            message_count: Number of messages analyzed
            
        Returns:
            TeamAnalysis with all extracted insights
        """
        result = self.process(messages_text, team_name)
        
        return TeamAnalysis(
            team_name=team_name,
            channel_id=channel_id,
            message_count=message_count,
            summary=result.get("summary", ""),
            themes=result.get("themes", []),
            tone=result.get("tone", "routine"),
            updates=result.get("updates", []),
            blockers=result.get("blockers", []),
            decisions=result.get("decisions", []),
            action_items=result.get("action_items", []),
        )
