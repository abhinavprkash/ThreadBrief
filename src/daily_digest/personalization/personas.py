"""Personas - role-level and team-level personalization preferences."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PersonaType(str, Enum):
    """Types of personas."""
    ROLE = "role"
    TEAM = "team"


@dataclass
class Persona:
    """
    Base persona defining preferences for digest personalization.
    
    Attributes:
        persona_type: Whether this is a role or team persona
        name: Identifier (e.g., "lead", "mechanical")
        item_boosts: Multipliers for different item types
        cross_team_weight: 0-1, how much to boost cross-team items
        topics_of_interest: Keywords that increase relevance for this persona
        min_severity_for_main: Minimum severity to include in main digest
    """
    
    persona_type: PersonaType
    name: str
    
    # Item type boosting (item_type -> multiplier, 1.0 = no change)
    item_boosts: dict[str, float] = field(default_factory=dict)
    
    # Cross-team sensitivity (0-1, higher = more interested in cross-team items)
    cross_team_weight: float = 0.5
    
    # Topics that increase relevance for this persona
    topics_of_interest: list[str] = field(default_factory=list)
    
    # Minimum severity to include in main digest ("low", "medium", "high")
    min_severity_for_main: str = "medium"
    
    def get_item_boost(self, item_type: str) -> float:
        """Get boost multiplier for an item type."""
        return self.item_boosts.get(item_type, 1.0)
    
    def matches_topic(self, text: str) -> bool:
        """Check if text matches any topic of interest."""
        text_lower = text.lower()
        return any(topic.lower() in text_lower for topic in self.topics_of_interest)


# =============================================================================
# Role Personas - Based on job function
# =============================================================================

class RolePersona:
    """Pre-defined role personas."""
    
    LEAD = Persona(
        persona_type=PersonaType.ROLE,
        name="lead",
        item_boosts={
            "blocker": 1.5,      # Leads care a lot about blockers
            "decision": 1.4,    # Decisions need visibility
            "action_item": 1.2,
            "update": 0.9,      # General updates less critical
        },
        cross_team_weight=0.9,  # Very interested in cross-team coordination
        topics_of_interest=[
            "risk", "timeline", "deadline", "blocked", "decision",
            "escalate", "priority", "sprint", "release", "demo"
        ],
        min_severity_for_main="low",  # Leads see everything
    )
    
    IC = Persona(
        persona_type=PersonaType.ROLE,
        name="ic",
        item_boosts={
            "blocker": 1.3,
            "decision": 1.1,
            "action_item": 1.4,  # ICs care about their tasks
            "update": 1.0,
        },
        cross_team_weight=0.5,  # Moderate cross-team interest
        topics_of_interest=[],  # Filled by team persona
        min_severity_for_main="medium",
    )
    
    @classmethod
    def get(cls, role: str) -> Persona:
        """Get role persona by name."""
        role_map = {
            "lead": cls.LEAD,
            "manager": cls.LEAD,
            "ic": cls.IC,
            "engineer": cls.IC,
            "developer": cls.IC,
        }
        return role_map.get(role.lower(), cls.IC)


# =============================================================================
# Team Personas - Based on team/domain
# =============================================================================

class TeamPersona:
    """Pre-defined team personas."""
    
    MECHANICAL = Persona(
        persona_type=PersonaType.TEAM,
        name="mechanical",
        item_boosts={
            "blocker": 1.2,
            "decision": 1.1,
            "action_item": 1.1,
            "update": 1.0,
        },
        cross_team_weight=0.6,  # Often needs to sync with electrical
        topics_of_interest=[
            # Design/Engineering
            "FEA", "CAD", "STEP", "DXF", "simulation", "stress", "tolerances",
            "GD&T", "surface finish", "Ra", "fillet", "rib", "wall thickness",
            # Manufacturing
            "CNC", "machining", "toolpath", "fixture", "setup", "first article",
            "pilot run", "DFM", "prototype",
            # Materials
            "6061", "7075", "aluminum", "stock", "plate", "inventory",
            # Components
            "bracket", "housing", "mount", "chassis", "hinge", "actuator",
            # Suppliers
            "vendor", "supplier", "lead time", "expedite",
        ],
        min_severity_for_main="medium",
    )
    
    ELECTRICAL = Persona(
        persona_type=PersonaType.TEAM,
        name="electrical",
        item_boosts={
            "blocker": 1.3,  # EE blockers often affect others
            "decision": 1.1,
            "action_item": 1.1,
            "update": 1.0,
        },
        cross_team_weight=0.7,  # Interfaces with mech (physical) and SW (firmware)
        topics_of_interest=[
            # PCB Design
            "PCB", "schematic", "layout", "DRC", "rev", "Rev C", "Rev B",
            "copper pour", "via", "trace", "component", "BOM",
            # Power
            "power", "voltage", "24V", "12V", "3.3V", "current", "thermal",
            "FET", "heatsink", "junction", "overcurrent", "transient",
            # Testing
            "stress test", "burn-in", "brown-out", "power-good", "sequencing",
            # Integration
            "firmware", "interface", "connector", "board outline", "keepout",
        ],
        min_severity_for_main="medium",
    )
    
    SOFTWARE = Persona(
        persona_type=PersonaType.TEAM,
        name="software",
        item_boosts={
            "blocker": 1.2,
            "decision": 1.2,  # Architecture decisions important
            "action_item": 1.1,
            "update": 0.9,
        },
        cross_team_weight=0.5,  # Usually more encapsulated
        topics_of_interest=[
            # Development
            "PR", "code review", "merge", "branch", "deploy", "release",
            "staging", "production", "API", "endpoint", "cache",
            # Infrastructure
            "latency", "P99", "memory", "CPU", "monitoring", "metrics",
            # Integration  
            "firmware", "algorithm", "integration", "interface",
        ],
        min_severity_for_main="medium",
    )
    
    GENERAL = Persona(
        persona_type=PersonaType.TEAM,
        name="general",
        item_boosts={},
        cross_team_weight=0.5,
        topics_of_interest=[],
        min_severity_for_main="medium",
    )
    
    @classmethod
    def get(cls, team: str) -> Persona:
        """Get team persona by name."""
        team_map = {
            "mechanical": cls.MECHANICAL,
            "mech": cls.MECHANICAL,
            "electrical": cls.ELECTRICAL,
            "ee": cls.ELECTRICAL,
            "hardware": cls.ELECTRICAL,
            "software": cls.SOFTWARE,
            "sw": cls.SOFTWARE,
            "firmware": cls.SOFTWARE,
        }
        return team_map.get(team.lower(), cls.GENERAL)


# =============================================================================
# Persona Manager
# =============================================================================

@dataclass
class UserPersonaConfig:
    """User's persona configuration."""
    user_id: str
    role: str = "ic"
    team: str = "general"
    custom_topics: list[str] = field(default_factory=list)
    custom_boosts: dict[str, float] = field(default_factory=dict)


class PersonaManager:
    """
    Manages user persona configurations and combines role + team personas.
    
    The combined persona merges:
    - Role persona's item_boosts and cross_team_weight
    - Team persona's topics_of_interest
    - User's custom overrides
    """
    
    def __init__(self):
        self._user_configs: dict[str, UserPersonaConfig] = {}
    
    def set_user_persona(
        self,
        user_id: str,
        role: str = "ic",
        team: str = "general",
        custom_topics: list[str] = None,
        custom_boosts: dict[str, float] = None,
    ):
        """Set or update a user's persona configuration."""
        self._user_configs[user_id] = UserPersonaConfig(
            user_id=user_id,
            role=role,
            team=team,
            custom_topics=custom_topics or [],
            custom_boosts=custom_boosts or {},
        )
    
    def get_user_config(self, user_id: str) -> UserPersonaConfig:
        """Get user's persona config, creating default if needed."""
        if user_id not in self._user_configs:
            self._user_configs[user_id] = UserPersonaConfig(user_id=user_id)
        return self._user_configs[user_id]
    
    def get_combined_persona(
        self,
        user_id: str,
        role_override: Optional[str] = None,
        team_override: Optional[str] = None,
    ) -> Persona:
        """
        Get a combined persona for a user, merging role + team + custom.
        
        Combination rules:
        - item_boosts: Role persona + custom (custom overrides)
        - cross_team_weight: Role persona (leads care more)
        - topics_of_interest: Team persona + custom topics
        - min_severity_for_main: Role persona
        """
        config = self.get_user_config(user_id)
        
        role = role_override or config.role
        team = team_override or config.team
        
        role_persona = RolePersona.get(role)
        team_persona = TeamPersona.get(team)
        
        # Combine item boosts (role is base, custom overrides)
        combined_boosts = dict(role_persona.item_boosts)
        combined_boosts.update(config.custom_boosts)
        
        # Combine topics (team + custom)
        combined_topics = list(team_persona.topics_of_interest) + config.custom_topics
        
        return Persona(
            persona_type=PersonaType.ROLE,  # Combined behaves as role-level
            name=f"{role}_{team}",
            item_boosts=combined_boosts,
            cross_team_weight=role_persona.cross_team_weight,
            topics_of_interest=combined_topics,
            min_severity_for_main=role_persona.min_severity_for_main,
        )
    
    def get_role_persona(self, role: str) -> Persona:
        """Get a role persona directly."""
        return RolePersona.get(role)
    
    def get_team_persona(self, team: str) -> Persona:
        """Get a team persona directly."""
        return TeamPersona.get(team)
