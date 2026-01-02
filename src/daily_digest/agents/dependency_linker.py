"""Dependency Linker Agent - detects cross-team dependencies."""

from typing import Optional

from .base import BaseAgent
from ..models.events import StructuredEvent, EventType
from ..models.dependencies import Dependency, DependencyType, CrossTeamAlert


class DependencyLinker(BaseAgent):
    """
    Detects cross-team dependencies from extracted events.
    
    Identifies:
    - Team A waiting on Team B
    - Interface changes affecting downstream teams
    - Timeline shifts impacting dependencies
    - Shared resource conflicts
    - Blocking issues across teams
    """
    
    @property
    def agent_name(self) -> str:
        return "DependencyLinker"
    
    @property
    def prompt_template(self) -> str:
        return """Analyze these events from multiple teams and identify cross-team dependencies.

Events by team:
{messages}

Look for:
1. Team A waiting on Team B (explicit or implicit)
2. Interface/API changes that affect other teams
3. Timeline changes that impact dependent work
4. Shared resources being competed for
5. Blockers that cross team boundaries

Return a JSON object:
{{
    "dependencies": [
        {{
            "type": "waiting_on|interface_change|timeline_impact|shared_resource|blocking",
            "from_team": "team that is affected or waiting",
            "to_team": "team that is causing the dependency",
            "what_changed": "description of the change or situation",
            "why_it_matters": "impact on the from_team",
            "recommended_action": "what should be done",
            "suggested_owner": "who should own the resolution",
            "urgency": "low|medium|high",
            "confidence": 0.0-1.0
        }}
    ],
    "cross_team_highlights": [
        "Key insight about cross-team coordination"
    ]
}}

Guidelines:
- Only include real dependencies, not hypotheticals
- Be specific about who is impacted and why
- Suggest actionable next steps
- High urgency if it blocks critical path or multiple teams"""
    
    def _empty_result(self) -> dict:
        return {"dependencies": [], "cross_team_highlights": []}
    
    def _mock_result(self, messages_text: str, team_name: str) -> dict:
        """
        Generate dependencies using heuristic content analysis.
        
        Parses message content for cross-team patterns:
        - "waiting on [team]"
        - "blocked by [team]"
        - "need from [team]"
        - "@mentions of other team members"
        - Team name references in other team's context
        """
        import re
        
        dependencies = []
        highlights = set()
        
        # Team aliases for matching
        team_patterns = {
            "mechanical": ["mechanical", "mech", "hardware", "cnc", "fab"],
            "electrical": ["electrical", "ee", "pcb", "power", "firmware"],
            "software": ["software", "sw", "code", "api", "deploy"],
        }
        
        # Flatten to lookup
        team_lookup = {}
        for team, aliases in team_patterns.items():
            for alias in aliases:
                team_lookup[alias] = team
        
        # Cross-team detection patterns
        patterns = [
            # "waiting on X" / "waiting for X"
            (r"waiting (?:on|for) (\w+)", "waiting_on"),
            # "blocked by X" / "blocked on X"
            (r"blocked (?:by|on) (\w+)", "blocking"),
            # "need from X" / "needs from X"
            (r"needs? from (\w+)", "waiting_on"),
            # "depends on X"
            (r"depends? on (\w+)", "waiting_on"),
            # "coordinating with X"
            (r"coordinat(?:e|ing) with (\w+)", "informational"),
            # "sync with X"
            (r"sync(?:ing)? with (\w+)", "informational"),
            # "API" / "interface" mentions
            (r"(?:api|interface) (?:change|update)", "interface_change"),
            # "by Friday" / "by EOD" deadline patterns
            (r"(?:need|require|want).*by (?:friday|monday|eod|end of day|tomorrow)", "timeline_impact"),
        ]
        
        # Process patterns
        messages_lower = messages_text.lower()
        
        for pattern, dep_type in patterns:
            matches = re.findall(pattern, messages_lower, re.IGNORECASE)
            for match in matches:
                if isinstance(match, str):
                    # Check if the matched word is a team reference
                    matched_team = team_lookup.get(match.lower())
                    if matched_team:
                        # Only create dependency if it's a different team
                        source_team = self._detect_source_team(messages_text, team_patterns)
                        if source_team and source_team != matched_team:
                            dep = {
                                "type": dep_type,
                                "from_team": source_team,
                                "to_team": matched_team,
                                "what_changed": f"Cross-team dependency detected: {dep_type.replace('_', ' ')}",
                                "why_it_matters": f"{source_team.title()} team has dependency on {matched_team.title()} team",
                                "recommended_action": f"Schedule sync between {source_team} and {matched_team} teams",
                                "suggested_owner": f"{matched_team} lead",
                                "urgency": "high" if dep_type == "blocking" else "medium",
                                "confidence": 0.75,
                            }
                            # Avoid duplicates
                            if not any(d["from_team"] == dep["from_team"] and d["to_team"] == dep["to_team"] for d in dependencies):
                                dependencies.append(dep)
                                highlights.add(f"{source_team.title()} ↔ {matched_team.title()}: {dep_type.replace('_', ' ')}")
        
        # Check for @mentions (Slack user mentions)
        user_mentions = re.findall(r"<@([A-Z0-9_]+)>", messages_text)
        if user_mentions:
            source_team = self._detect_source_team(messages_text, team_patterns)
            if source_team:
                highlights.add(f"{source_team.title()} team has {len(user_mentions)} cross-reference mentions")
        
        # If no dependencies found, return empty (not fake hardcoded ones)
        if not dependencies:
            return {"dependencies": [], "cross_team_highlights": []}
        
        return {
            "dependencies": dependencies,
            "cross_team_highlights": list(highlights)[:5],
        }
    
    def _detect_source_team(self, text: str, team_patterns: dict) -> str | None:
        """Detect which team this message is about based on content."""
        text_lower = text.lower()
        
        # Count mentions of each team
        team_counts = {}
        for team, aliases in team_patterns.items():
            count = sum(text_lower.count(alias) for alias in aliases)
            if count > 0:
                team_counts[team] = count
        
        if not team_counts:
            return None
        
        # Return the most mentioned team
        return max(team_counts, key=team_counts.get)
    
    def detect_dependencies(
        self,
        events_by_team: dict[str, list[StructuredEvent]]
    ) -> tuple[list[Dependency], list[str]]:
        """
        Detect cross-team dependencies from events.
        
        Args:
            events_by_team: Dict mapping team name to list of events
            
        Returns:
            Tuple of (list of Dependencies, list of highlight strings)
        """
        # Format events for LLM
        messages_text = self._format_events_for_llm(events_by_team)
        
        result = self.process(messages_text, "cross-team")
        
        dependencies = []
        for dep_data in result.get("dependencies", []):
            dep = self._create_dependency(dep_data)
            if dep:
                dependencies.append(dep)
        
        highlights = result.get("cross_team_highlights", [])
        
        return dependencies, highlights
    
    def _format_events_for_llm(
        self, 
        events_by_team: dict[str, list[StructuredEvent]]
    ) -> str:
        """Format events by team for LLM processing."""
        lines = []
        
        for team_name, events in events_by_team.items():
            lines.append(f"\n## {team_name.upper()} TEAM")
            
            for event in events:
                event_type = event.event_type.value
                lines.append(f"- [{event_type.upper()}] {event.summary}")
                
                if hasattr(event, 'issue') and event.issue:
                    lines.append(f"  Issue: {event.issue}")
                if hasattr(event, 'owner') and event.owner:
                    lines.append(f"  Owner: {event.owner}")
                if event.urgency == "high":
                    lines.append(f"  ⚠️ HIGH URGENCY")
        
        return "\n".join(lines)
    
    def _create_dependency(self, data: dict) -> Optional[Dependency]:
        """Create Dependency from raw data."""
        type_map = {
            "waiting_on": DependencyType.WAITING_ON,
            "interface_change": DependencyType.INTERFACE_CHANGE,
            "timeline_impact": DependencyType.TIMELINE_IMPACT,
            "shared_resource": DependencyType.SHARED_RESOURCE,
            "blocking": DependencyType.BLOCKING,
            "informational": DependencyType.INFORMATIONAL,
        }
        
        dep_type = type_map.get(data.get("type", ""), DependencyType.INFORMATIONAL)
        
        return Dependency(
            dependency_type=dep_type,
            from_team=data.get("from_team", ""),
            to_team=data.get("to_team", ""),
            what_changed=data.get("what_changed", ""),
            why_it_matters=data.get("why_it_matters", ""),
            recommended_action=data.get("recommended_action", ""),
            suggested_owner=data.get("suggested_owner", ""),
            urgency=data.get("urgency", "medium"),
            confidence=data.get("confidence", 0.5),
        )
    
    def create_alerts(
        self, 
        dependencies: list[Dependency]
    ) -> list[CrossTeamAlert]:
        """Create alerts from dependencies for distribution."""
        alerts = []
        
        for i, dep in enumerate(dependencies):
            if dep.urgency == "high" or dep.dependency_type == DependencyType.BLOCKING:
                priority = 10
            elif dep.urgency == "medium":
                priority = 5
            else:
                priority = 1
            
            alert = CrossTeamAlert(
                title=f"{dep.from_team} ↔ {dep.to_team}: {dep.what_changed}",
                dependency=dep,
                priority=priority,
                alert_id=f"alert_{i}_{dep.from_team}_{dep.to_team}",
            )
            alerts.append(alert)
        
        # Sort by priority (highest first)
        alerts.sort(key=lambda a: a.priority, reverse=True)
        
        return alerts
