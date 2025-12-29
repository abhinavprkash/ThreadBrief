"""Tests for LangChain agents."""

import os
import pytest

# Set dummy API key and enable mock mode for testing
os.environ["OPENAI_API_KEY"] = "sk-test-dummy-key-for-testing"
os.environ["MOCK_LLM"] = "true"

from daily_digest.agents import TeamAnalyzerAgent, TeamAnalysis


class TestTeamAnalyzerAgent:
    """Tests for the unified TeamAnalyzerAgent."""
    
    @pytest.fixture
    def agent(self):
        return TeamAnalyzerAgent(mock_mode=True)
    
    def test_prompt_template_exists(self, agent):
        """Test that prompt template is defined."""
        assert agent.prompt_template
        assert "{messages}" in agent.prompt_template
        assert "{team_name}" in agent.prompt_template
    
    def test_agent_name(self, agent):
        """Test agent name."""
        assert agent.agent_name == "TeamAnalyzer"
    
    def test_empty_result(self, agent):
        """Test empty result structure."""
        result = agent._empty_result()
        assert "summary" in result
        assert "themes" in result
        assert "tone" in result
        assert "updates" in result
        assert "blockers" in result
        assert "decisions" in result
        assert "action_items" in result
    
    def test_process_with_empty_input(self, agent):
        """Test process returns empty result for empty input."""
        result = agent.process("", "software")
        assert "summary" in result
        assert result["updates"] == []
    
    def test_mock_result(self, agent):
        """Test mock result generation."""
        result = agent.process("Test message", "software")
        assert "summary" in result
        assert "updates" in result
        assert "blockers" in result
        assert "decisions" in result
        assert "action_items" in result
        assert len(result["updates"]) > 0
        assert len(result["blockers"]) > 0
        assert len(result["decisions"]) > 0
    
    def test_analyze_team(self, agent):
        """Test analyze_team returns TeamAnalysis object."""
        analysis = agent.analyze_team(
            messages_text="Test messages from the team",
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=10,
        )
        
        assert isinstance(analysis, TeamAnalysis)
        assert analysis.team_name == "software"
        assert analysis.channel_id == "C_SOFTWARE"
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
        assert len(event_types) > 0
    
    def test_to_action_items(self, agent):
        """Test conversion to ActionItem objects."""
        analysis = agent.analyze_team(
            messages_text="test",
            team_name="software",
            channel_id="C_SOFTWARE",
            message_count=5,
        )
        
        actions = analysis.to_action_items()
        
        assert len(actions) > 0
        for action in actions:
            assert hasattr(action, "description")
            assert hasattr(action, "owner")
            assert hasattr(action, "priority")


class TestAgentTokenEstimation:
    """Test token estimation across agents."""
    
    def test_estimate_tokens(self):
        """Test token estimation."""
        agent = TeamAnalyzerAgent(mock_mode=True)
        
        short_text = "Hello world"
        long_text = "a" * 1000
        
        short_tokens = agent.estimate_tokens(short_text)
        long_tokens = agent.estimate_tokens(long_text)
        
        assert short_tokens < long_tokens
        assert long_tokens == 250  # 1000 / 4
