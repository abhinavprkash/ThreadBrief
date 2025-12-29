"""Orchestrator - main pipeline for digest generation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import DigestConfig, get_config
from .slack_client import SlackClient
from .message_aggregator import MessageAggregator, ChannelMessages

# Agents
from .agents import TeamAnalyzerAgent, TeamAnalysis, DependencyLinker

# Models
from .models.events import StructuredEvent, Decision, Blocker, ActionItem
from .models.dependencies import Dependency, CrossTeamAlert
# Storage
from .memory import MemoryStore, DependencyGraph

# Observability
from .observability import MetricsLogger, logger


@dataclass
class GlobalDigest:
    """Org-wide digest content."""
    date: str
    cross_team_highlights: list[str] = field(default_factory=list)
    org_wide_risks: list[StructuredEvent] = field(default_factory=list)
    notable_decisions: list[Decision] = field(default_factory=list)
    total_events: int = 0


@dataclass
class DigestOutput:
    """Complete digest output with global and personalized content."""
    global_digest: GlobalDigest
    personalized_digests: list  # PersonalizedDigest
    memory_writes: dict
    team_analyses: dict[str, TeamAnalysis] = field(default_factory=dict)
    
    def to_json(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "global_digest": {
                "date": self.global_digest.date,
                "cross_team_highlights": self.global_digest.cross_team_highlights,
                "org_wide_risks": [e.summary for e in self.global_digest.org_wide_risks],
                "notable_decisions": [d.summary for d in self.global_digest.notable_decisions],
                "total_events": self.global_digest.total_events,
            },
            "personalized_digests": [
                {
                    "user_id": pd.user_id,
                    "delivery": {"type": pd.delivery_type, "target": pd.delivery_target},
                    "sections": {
                        "top_updates": [e.summary for e in pd.top_updates],
                        "blockers": [e.summary for e in pd.blockers],
                        "decisions": [e.summary for e in pd.decisions],
                        "action_items": [a.description for a in pd.action_items],
                    }
                }
                for pd in self.personalized_digests
            ],
            "memory_writes": self.memory_writes,
            "team_analyses": {
                name: {
                    "summary": ta.summary,
                    "themes": ta.themes,
                    "tone": ta.tone,
                    "updates": ta.updates,
                    "blockers": ta.blockers,
                    "decisions": ta.decisions,
                    "action_items": ta.action_items,
                }
                for name, ta in self.team_analyses.items()
            },
        }


class DigestOrchestrator:
    """
    Main pipeline orchestrator.
    
    Implements the 4-step process:
    1. Analyze teams → TeamAnalysis (via TeamAnalyzerAgent)
    2. Build dependency map (via DependencyLinker)
    3. Generate action items
    4. Learning hooks (via MemoryStore)
    """
    
    def __init__(
        self,
        config: Optional[DigestConfig] = None,
        mock_mode: bool = False,
    ):
        self.config = config or get_config()
        self.mock_mode = mock_mode
        
        # Initialize components
        self.metrics = MetricsLogger()
        
        # Agents
        self.team_analyzer = TeamAnalyzerAgent(mock_mode=mock_mode)
        self.dependency_linker = DependencyLinker(mock_mode=mock_mode)
        
        # Storage
        self.memory = MemoryStore()
        self.dep_graph = DependencyGraph()
    
    async def run(
        self,
        slack_client: SlackClient,
        since: Optional[datetime] = None,
    ) -> DigestOutput:
        """
        Run the complete digest pipeline.
        
        Args:
            slack_client: Slack client for message fetching
            since: Only process messages after this time
            
        Returns:
            Complete DigestOutput with global and personalized content
        """
        self.metrics.start()
        
        try:
            # Step 0: Aggregate messages
            logger.info("Step 0: Aggregating messages...")
            aggregator = MessageAggregator(slack_client, self.config)
            channel_messages = await aggregator.fetch_all_channels(since)
            
            total_msgs = sum(cm.message_count for cm in channel_messages)
            logger.info(f"Fetched {total_msgs} messages from {len(channel_messages)} channels")
            
            # Step 1: Analyze teams (unified agent call)
            logger.info("Step 1: Analyzing teams...")
            team_analyses, events_by_team = await self._step1_analyze_teams(channel_messages, aggregator)
            
            all_events = []
            for events in events_by_team.values():
                all_events.extend(events)
            logger.info(f"Extracted {len(all_events)} events from {len(team_analyses)} teams")
            
            # Step 2: Detect dependencies
            logger.info("Step 2: Detecting cross-team dependencies...")
            dependencies, highlights = await self._step2_detect_dependencies(events_by_team)
            logger.info(f"Found {len(dependencies)} dependencies")
            
            # Step 3: Extract action items
            logger.info("Step 3: Extracting action items...")
            actions = self._step3_extract_actions(all_events, team_analyses)
            logger.info(f"Extracted {len(actions)} action items")
            
            # Step 4: Write to memory
            logger.info("Step 4: Writing to memory...")
            memory_writes = self._step4_memory_writes(all_events, dependencies)
            
            # Create global digest
            global_digest = self._create_global_digest(all_events, dependencies, highlights)
            
            self.metrics.finish()
            self.metrics.log_summary()
            
            return DigestOutput(
                global_digest=global_digest,
                personalized_digests=[],
                memory_writes=memory_writes,
                team_analyses=team_analyses,
            )
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            self.metrics.record_failure(str(e))
            self.metrics.finish()
            raise
    
    async def _step1_analyze_teams(
        self,
        channel_messages: list[ChannelMessages],
        aggregator: MessageAggregator,
    ) -> tuple[dict[str, TeamAnalysis], dict[str, list[StructuredEvent]]]:
        """Step 1: Analyze teams using unified TeamAnalyzerAgent."""
        team_analyses = {}
        events_by_team = {}
        
        for cm in channel_messages:
            if cm.message_count == 0:
                # Create empty analysis for teams with no messages
                team_analyses[cm.team_name] = TeamAnalysis(
                    team_name=cm.team_name,
                    channel_id=cm.channel_id,
                    message_count=0,
                    summary="No activity in this channel today.",
                    tone="quiet",
                )
                events_by_team[cm.team_name] = []
                continue
            
            # Format messages for LLM
            messages_text = aggregator.format_messages_for_llm(cm.messages)
            
            # Analyze team with unified agent
            with self.metrics.track_agent(f"team_analyzer_{cm.team_name}"):
                analysis = self.team_analyzer.analyze_team(
                    messages_text,
                    cm.team_name,
                    cm.channel_id,
                    cm.message_count,
                )
            
            team_analyses[cm.team_name] = analysis
            events_by_team[cm.team_name] = analysis.to_events()
            self.metrics.record_channel(cm.team_name, len(events_by_team[cm.team_name]))
        
        return team_analyses, events_by_team
    
    async def _step2_detect_dependencies(
        self,
        events_by_team: dict[str, list[StructuredEvent]],
    ) -> tuple[list[Dependency], list[str]]:
        """Step 2: Build dependency map across teams."""
        if len(events_by_team) < 2:
            return [], []
        
        with self.metrics.track_agent("dependency_linker"):
            dependencies, highlights = self.dependency_linker.detect_dependencies(
                events_by_team
            )
        
        # Store in graph
        self.dep_graph.add_dependencies_bulk(dependencies)
        
        return dependencies, highlights
    
    def _step3_extract_actions(
        self,
        events: list[StructuredEvent],
        team_analyses: dict[str, TeamAnalysis],
    ) -> list[ActionItem]:
        """Step 3: Generate action items from events and team analyses."""
        actions = []
        
        # Extract from events
        for event in events:
            # Blockers become action items
            if isinstance(event, Blocker) and event.status != "resolved":
                actions.append(ActionItem(
                    description=f"Resolve: {event.issue}",
                    owner=event.owner or "unassigned",
                    source_event_type=event.event_type,
                    source_link=event.source_permalink or "",
                    priority="high" if event.severity == "high" else "medium",
                ))
            
            # Decisions may have follow-ups
            if isinstance(event, Decision) and event.impact:
                actions.append(ActionItem(
                    description=f"Follow up: {event.what_decided}",
                    owner=event.decided_by or "unassigned",
                    source_event_type=event.event_type,
                    source_link=event.source_permalink or "",
                    priority="medium",
                ))
        
        # Add action items from team analyses
        for ta in team_analyses.values():
            actions.extend(ta.to_action_items())
        
        return actions
    
    def _step4_memory_writes(
        self,
        events: list[StructuredEvent],
        dependencies: list[Dependency],
    ) -> dict:
        """Step 5: Write to memory for learning."""
        results = self.memory.process_events(events)
        
        return {
            "decisions": results.get("decisions_logged", 0),
            "blockers": results.get("blockers_logged", 0),
            "dependencies": len(dependencies),
        }
    
    def _create_global_digest(
        self,
        events: list[StructuredEvent],
        dependencies: list[Dependency],
        highlights: list[str],
    ) -> GlobalDigest:
        """Create the global org-wide digest."""
        # Get org-wide risks (high urgency blockers)
        risks = [e for e in events if isinstance(e, Blocker) and e.urgency == "high"]
        
        # Get notable decisions
        decisions = [e for e in events if isinstance(e, Decision)]
        
        # Combine highlights with graph highlights
        all_highlights = highlights + self.dep_graph.get_cross_team_highlights()
        
        return GlobalDigest(
            date=datetime.now().strftime("%Y-%m-%d"),
            cross_team_highlights=list(set(all_highlights))[:5],
            org_wide_risks=risks[:5],
            notable_decisions=decisions[:5],
            total_events=len(events),
        )
