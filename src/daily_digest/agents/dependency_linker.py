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
        """Generate mock dependencies for testing."""
        return {
            "dependencies": [
                {
                    "type": "waiting_on",
                    "from_team": "software",
                    "to_team": "electrical",
                    "what_changed": "New PCB firmware interface needed",
                    "why_it_matters": "Software team blocked on API definition",
                    "recommended_action": "Schedule 30-min sync to align on interface",
                    "suggested_owner": "electrical lead",
                    "urgency": "medium",
                    "confidence": 0.85
                }
            ],
            "cross_team_highlights": [
                "Electrical and Software teams need to sync on firmware API"
            ]
        }
    
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
