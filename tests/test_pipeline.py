"""Tests for the complete digest pipeline."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from daily_digest.config import DigestConfig
from daily_digest.slack_client import SlackClient, MockSlackClient
from daily_digest.message_aggregator import MessageAggregator, ChannelMessages
from daily_digest.orchestrator import DigestOrchestrator, DigestOutput, GlobalDigest
from daily_digest.agents.team_analyzer import TeamAnalyzerAgent, TeamAnalysis
from daily_digest.formatter import DigestFormatter
from daily_digest.distributor import DigestDistributor
from daily_digest.state import DigestState
from daily_digest.observability import MetricsLogger


class TestSlackClient:
    """Tests for SlackClient."""
    
    def test_mock_client_initialization(self, mock_fixture_path):
        """Test mock client loads fixtures."""
        client = SlackClient(mock_data_path=mock_fixture_path)
        
        assert client.is_mock
        assert isinstance(client._client, MockSlackClient)
    
    @pytest.mark.asyncio
    async def test_mock_get_channel_history(self, mock_fixture_path):
        """Test mock client returns channel history."""
        client = SlackClient(mock_data_path=mock_fixture_path)
        
        messages = await client.get_channel_history("C_MECHANICAL")
        
        assert len(messages) > 0
        assert all("text" in m for m in messages)
    
    @pytest.mark.asyncio
    async def test_mock_post_message(self, mock_fixture_path):
        """Test mock client records posted messages."""
        client = SlackClient(mock_data_path=mock_fixture_path)
        
        result = await client.post_message("C_TEST", "Test message")
        
        assert result["ok"]
        assert len(client.posted_messages) == 1
        assert client.posted_messages[0]["text"] == "Test message"
    
    def test_mock_get_user_name(self, mock_fixture_path):
        """Test mock client resolves user names."""
        client = SlackClient(mock_data_path=mock_fixture_path)
        
        name = client.get_user_name("U_ALEX")
        
        assert name == "Alex Thompson"


class TestTeamAnalyzerAgent:
    """Tests for the unified TeamAnalyzerAgent."""
    
    @pytest.fixture
    def agent(self):
        return TeamAnalyzerAgent(mock_mode=True)
    
    def test_analyze_team_mock(self, agent):
        """Test team analysis in mock mode."""
        messages = "Sample messages from the team"
        
        analysis = agent.analyze_team(
            messages_text=messages,
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=10,
        )
        
        assert isinstance(analysis, TeamAnalysis)
        assert analysis.team_name == "software"
        assert analysis.message_count == 10
        assert len(analysis.summary) > 0
        assert len(analysis.updates) > 0
        assert len(analysis.blockers) > 0
        assert len(analysis.decisions) > 0
    
    def test_to_events_conversion(self, agent):
        """Test conversion of TeamAnalysis to StructuredEvents."""
        analysis = agent.analyze_team(
            messages_text="test",
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=5,
        )
        
        events = analysis.to_events()
        
        assert len(events) > 0
        # Should have events from updates, blockers, decisions
        event_types = set(e.event_type.value for e in events)
        assert "status_update" in event_types or "blocker" in event_types or "decision" in event_types


class TestDigestFormatter:
    """Tests for DigestFormatter with V2 models."""
    
    @pytest.fixture
    def formatter(self):
        return DigestFormatter()
    
    @pytest.fixture
    def sample_team_analysis(self):
        return TeamAnalysis(
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=10,
            summary="The team worked on API improvements.",
            themes=["API development", "Bug fixes"],
            tone="productive",
            updates=[{"update": "Fixed memory leak", "author": "Ryan", "category": "completion"}],
            blockers=[{"issue": "OAuth bug", "owner": "Kevin", "severity": "high", "status": "active"}],
            decisions=[{"decision": "Hotfix tonight at 2am", "made_by": "Kevin", "context": "Memory issues", "impact": "Fix memory"}],
            action_items=[{"description": "Deploy hotfix", "owner": "Kevin", "priority": "high"}],
        )
    
    @pytest.fixture
    def sample_output(self, sample_team_analysis):
        return DigestOutput(
            global_digest=GlobalDigest(
                date="2024-12-24",
                cross_team_highlights=["2 decisions made today"],
                org_wide_risks=[],
                notable_decisions=[],
                total_events=5,
            ),
            personalized_digests=[],
            memory_writes={},
            team_analyses={"software": sample_team_analysis},
        )
    
    def test_format_main_digest(self, formatter, sample_output):
        """Test main digest formatting."""
        text, blocks = formatter.format_main_digest(
            sample_output, 
            sample_output.team_analyses
        )
        
        assert isinstance(text, str)
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        
        # Check header exists
        assert any(b.get("type") == "header" for b in blocks)
    
    def test_format_team_details(self, formatter, sample_team_analysis):
        """Test team details formatting."""
        details = formatter.format_team_details(sample_team_analysis)
        
        assert isinstance(details, str)
        assert "software" in details.lower()
        assert "Updates" in details
        assert "Blockers" in details
    
    def test_format_leadership_dm(self, formatter, sample_output):
        """Test leadership DM formatting."""
        dm = formatter.format_leadership_dm(
            sample_output,
            sample_output.team_analyses
        )
        
        assert isinstance(dm, str)
        assert "Executive Digest" in dm
        assert "software" in dm.lower()


class TestDigestDistributor:
    """Tests for DigestDistributor with V2 models."""
    
    @pytest.fixture
    def config(self):
        return DigestConfig(
            channels={"software": "C_SOFTWARE"},
            digest_channel="C_DIGEST",
            leadership_users=["U_LEAD1"],
        )
    
    @pytest.fixture
    def mock_client(self, mock_fixture_path):
        return SlackClient(mock_data_path=mock_fixture_path)
    
    @pytest.fixture
    def distributor(self, mock_client, config):
        return DigestDistributor(mock_client, config)
    
    @pytest.fixture
    def sample_team_analysis(self):
        return TeamAnalysis(
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=5,
            summary="Test summary",
            themes=[],
            tone="productive",
            updates=[],
            blockers=[],
            decisions=[],
            action_items=[],
        )
    
    @pytest.fixture
    def sample_output(self, sample_team_analysis):
        return DigestOutput(
            global_digest=GlobalDigest(
                date="2024-12-24",
                cross_team_highlights=[],
                org_wide_risks=[],
                notable_decisions=[],
                total_events=0,
            ),
            personalized_digests=[],
            memory_writes={},
            team_analyses={"software": sample_team_analysis},
        )
    
    @pytest.mark.asyncio
    async def test_preview(self, distributor, sample_output):
        """Test preview mode doesn't post."""
        result = await distributor.preview(
            sample_output,
            sample_output.team_analyses
        )
        
        assert "main_post" in result
        assert "team_details" in result
        assert "leadership_dm" in result
        
        # Verify nothing was actually posted
        assert len(distributor.client.posted_messages) == 0
    
    @pytest.mark.asyncio
    async def test_distribute(self, distributor, sample_output):
        """Test distribution posts messages (main + team channels)."""
        result = await distributor.distribute(
            sample_output,
            sample_output.team_analyses
        )
        
        assert result["main_post"]["ok"]
        # 2 posts: main digest + team-specific details
        assert len(distributor.client.posted_messages) == 2
        assert len(distributor.client.sent_dms) == 1


class TestDigestState:
    """Tests for DigestState."""
    
    @pytest.fixture
    def temp_state_path(self, tmp_path):
        return str(tmp_path / "test_state.json")
    
    @pytest.fixture
    def state(self, temp_state_path):
        return DigestState(state_path=temp_state_path)
    
    def test_initial_state_has_no_last_run(self, state):
        """Test new state has no last run."""
        assert state.get_last_run() is None
    
    def test_save_and_get_last_run(self, state):
        """Test saving and retrieving last run."""
        from datetime import datetime
        from daily_digest.state import DigestRun
        
        run = DigestRun(
            run_id="test123",
            timestamp=datetime.now().isoformat(),
            channels_processed=["software"],
            message_counts={"software": 10},
            success=True,
        )
        
        state.save_run(run)
        
        last_run = state.get_last_run()
        assert last_run is not None
    
    def test_get_history(self, state):
        """Test getting run history."""
        from datetime import datetime
        from daily_digest.state import DigestRun
        
        for i in range(3):
            run = DigestRun(
                run_id=f"test{i}",
                timestamp=datetime.now().isoformat(),
                channels_processed=["software"],
                message_counts={"software": i},
                success=True,
            )
            state.save_run(run)
        
        history = state.get_history(limit=2)
        assert len(history) == 2


class TestMetricsLogger:
    """Tests for MetricsLogger."""
    
    def test_start_and_finish(self):
        """Test metrics timing."""
        metrics = MetricsLogger()
        
        metrics.start()
        metrics.finish()
        
        assert metrics.metrics.total_duration_ms >= 0
    
    def test_record_channel(self):
        """Test recording channel metrics."""
        metrics = MetricsLogger()
        
        metrics.record_channel("software", 15, tokens_used=500)
        
        assert metrics.metrics.channels_processed == 1
        assert metrics.metrics.messages_per_channel["software"] == 15
        assert metrics.metrics.token_usage["software"] == 500
    
    def test_record_failure(self):
        """Test recording failures."""
        metrics = MetricsLogger()
        
        metrics.record_failure("Test error")
        
        assert len(metrics.metrics.failures) == 1
        assert "Test error" in metrics.metrics.failures[0]
