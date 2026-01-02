"""Unit tests for the personalization module (personas and ranker)."""

import pytest
from datetime import datetime

from src.daily_digest.personalization.personas import (
    Persona,
    PersonaType,
    PersonaManager,
    RolePersona,
    TeamPersona,
)
from src.daily_digest.personalization.ranker import (
    DigestRanker,
    RankedItem,
    CROSS_TEAM_PATTERNS,
)
from src.daily_digest.feedback.feedback_store import FeedbackStore, DigestItem


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_feedback.db"
    return str(db_path)


@pytest.fixture
def feedback_store(temp_db):
    """Create a FeedbackStore with temporary database."""
    return FeedbackStore(temp_db)


@pytest.fixture
def ranker(feedback_store):
    """Create a DigestRanker with the test store."""
    return DigestRanker(feedback_store)


# =============================================================================
# Persona Tests
# =============================================================================

class TestPersona:
    """Tests for the Persona dataclass."""
    
    def test_persona_creation(self):
        """Test basic persona creation."""
        persona = Persona(
            persona_type=PersonaType.ROLE,
            name="test",
            item_boosts={"blocker": 1.5},
            cross_team_weight=0.8,
            topics_of_interest=["test", "example"],
        )
        
        assert persona.name == "test"
        assert persona.cross_team_weight == 0.8
        assert persona.get_item_boost("blocker") == 1.5
        assert persona.get_item_boost("unknown") == 1.0  # Default
    
    def test_matches_topic(self):
        """Test topic matching."""
        persona = Persona(
            persona_type=PersonaType.TEAM,
            name="electrical",
            topics_of_interest=["PCB", "power", "thermal"],
        )
        
        assert persona.matches_topic("Running PCB layout review")
        assert persona.matches_topic("Power supply issue")
        assert persona.matches_topic("THERMAL simulation complete")  # Case insensitive
        assert not persona.matches_topic("CNC machine status")


class TestRolePersona:
    """Tests for role personas."""
    
    def test_lead_persona(self):
        """Test lead persona properties."""
        lead = RolePersona.LEAD
        
        assert lead.name == "lead"
        assert lead.cross_team_weight == 0.9
        assert lead.get_item_boost("blocker") == 1.5
        assert lead.min_severity_for_main == "low"
    
    def test_ic_persona(self):
        """Test IC persona properties."""
        ic = RolePersona.IC
        
        assert ic.name == "ic"
        assert ic.cross_team_weight == 0.5
        assert ic.get_item_boost("action_item") == 1.4
        assert ic.min_severity_for_main == "medium"
    
    def test_get_role_by_name(self):
        """Test getting role by name."""
        assert RolePersona.get("lead") == RolePersona.LEAD
        assert RolePersona.get("manager") == RolePersona.LEAD
        assert RolePersona.get("ic") == RolePersona.IC
        assert RolePersona.get("engineer") == RolePersona.IC
        assert RolePersona.get("unknown") == RolePersona.IC  # Default


class TestTeamPersona:
    """Tests for team personas."""
    
    def test_mechanical_persona(self):
        """Test mechanical team persona."""
        mech = TeamPersona.MECHANICAL
        
        assert mech.name == "mechanical"
        assert "FEA" in mech.topics_of_interest
        assert "CNC" in mech.topics_of_interest
        assert "bracket" in mech.topics_of_interest
    
    def test_electrical_persona(self):
        """Test electrical team persona."""
        ee = TeamPersona.ELECTRICAL
        
        assert ee.name == "electrical"
        assert "PCB" in ee.topics_of_interest
        assert "power" in ee.topics_of_interest
        assert ee.cross_team_weight > TeamPersona.SOFTWARE.cross_team_weight
    
    def test_get_team_by_name(self):
        """Test getting team by name."""
        assert TeamPersona.get("mechanical") == TeamPersona.MECHANICAL
        assert TeamPersona.get("mech") == TeamPersona.MECHANICAL
        assert TeamPersona.get("electrical") == TeamPersona.ELECTRICAL
        assert TeamPersona.get("ee") == TeamPersona.ELECTRICAL
        assert TeamPersona.get("unknown") == TeamPersona.GENERAL


class TestPersonaManager:
    """Tests for PersonaManager."""
    
    def test_set_and_get_user_persona(self):
        """Test setting and getting user personas."""
        manager = PersonaManager()
        
        manager.set_user_persona("U_TEST", role="lead", team="mechanical")
        config = manager.get_user_config("U_TEST")
        
        assert config.user_id == "U_TEST"
        assert config.role == "lead"
        assert config.team == "mechanical"
    
    def test_get_combined_persona(self):
        """Test combined persona generation."""
        manager = PersonaManager()
        manager.set_user_persona("U_MARIA", role="lead", team="mechanical")
        
        combined = manager.get_combined_persona("U_MARIA")
        
        # Should have lead's cross-team weight
        assert combined.cross_team_weight == 0.9
        
        # Should have mechanical's topics
        assert "FEA" in combined.topics_of_interest
        assert "CNC" in combined.topics_of_interest
    
    def test_combined_persona_with_custom_topics(self):
        """Test combined persona with custom topics."""
        manager = PersonaManager()
        manager.set_user_persona(
            "U_CUSTOM",
            role="ic",
            team="electrical",
            custom_topics=["custom_topic", "special"],
        )
        
        combined = manager.get_combined_persona("U_CUSTOM")
        
        # Should have both team topics and custom topics
        assert "PCB" in combined.topics_of_interest
        assert "custom_topic" in combined.topics_of_interest


# =============================================================================
# Ranker Tests
# =============================================================================

def create_test_item(
    item_id: str,
    team: str = "mechanical",
    item_type: str = "update",
    title: str = "Test item",
    summary: str = "Test summary",
    confidence: float = 0.8,
) -> DigestItem:
    """Helper to create test items."""
    return DigestItem(
        digest_item_id=item_id,
        run_id="test_run",
        date=datetime.now().isoformat()[:10],
        team=team,
        item_type=item_type,
        title=title,
        summary=summary,
        confidence=confidence,
    )


class TestDigestRanker:
    """Tests for DigestRanker."""
    
    def test_cross_team_detection(self, ranker):
        """Test cross-team item detection."""
        # Cross-team item
        cross_team_item = create_test_item(
            "item_1",
            team="mechanical",
            item_type="blocker",
            title="Waiting on electrical for specs",
            summary="Blocked on electrical team for PCB dimensions",
        )
        
        # Regular item
        regular_item = create_test_item(
            "item_2",
            team="mechanical",
            item_type="update",
            title="FEA complete",
            summary="Stress analysis finished",
        )
        
        ranked = ranker.rank_items(
            [cross_team_item, regular_item],
            team="mechanical",
            role="lead",
        )
        
        # Cross-team item should rank higher
        assert ranked[0].item.digest_item_id == "item_1"
        assert ranked[0].is_cross_team
        assert not ranked[1].is_cross_team
    
    def test_actionability_boost(self, ranker):
        """Test that blockers rank higher than updates."""
        blocker = create_test_item(
            "blocker_1",
            item_type="blocker",
            title="Blocked on test fixtures",
            confidence=0.7,
        )
        
        update = create_test_item(
            "update_1",
            item_type="update",
            title="Regular status update",
            confidence=0.8,
        )
        
        ranked = ranker.rank_items([blocker, update], role="ic")
        
        # Blocker should rank higher despite lower confidence
        assert ranked[0].item.item_type == "blocker"
        assert ranked[0].actionability_boost > ranked[1].actionability_boost
    
    def test_role_persona_boost(self, ranker):
        """Test role-based persona boosts."""
        decision = create_test_item(
            "decision_1",
            item_type="decision",
            title="Approved Rev C design",
            confidence=0.8,
        )
        
        # Leads care more about decisions
        lead_ranked = ranker.rank_items([decision], role="lead")
        ic_ranked = ranker.rank_items([decision], role="ic")
        
        assert lead_ranked[0].role_boost > ic_ranked[0].role_boost
    
    def test_topic_matching(self, ranker):
        """Test team topic matching."""
        pcb_item = create_test_item(
            "pcb_1",
            team="electrical",
            title="PCB layout review",
            summary="Review PCB Rev C layout",
        )
        
        generic_item = create_test_item(
            "generic_1",
            team="electrical",
            title="Meeting notes",
            summary="General team sync",
        )
        
        ranked = ranker.rank_items([pcb_item, generic_item], team="electrical")
        
        # PCB item should get topic boost
        assert ranked[0].item.digest_item_id == "pcb_1"
        assert len(ranked[0].matched_topics) > 0
    
    def test_partition_by_confidence(self, ranker):
        """Test confidence-based partitioning."""
        high_item = create_test_item("high", confidence=0.9)
        medium_item = create_test_item("medium", confidence=0.5)
        low_item = create_test_item("low", confidence=0.3)
        
        ranked = ranker.rank_items([high_item, medium_item, low_item])
        
        high, low, excluded = ranker.partition_by_confidence(ranked)
        
        # Check partitioning
        assert len(high) == 1
        assert len(low) == 1
        assert len(excluded) == 1
    
    def test_explain_ranking(self, ranker):
        """Test ranking explanation generation."""
        cross_team_blocker = create_test_item(
            "blocker_x",
            item_type="blocker",
            title="Waiting on software for API",
            summary="Blocked by software team on API changes",
        )
        
        ranked = ranker.rank_items([cross_team_blocker], role="lead")
        explanation = ranker.explain_ranking(ranked[0])
        
        assert "Score:" in explanation
        assert "Cross-team:" in explanation
        assert "Actionability" in explanation


class TestCrossTeamPatterns:
    """Tests for cross-team pattern detection."""
    
    def test_at_mention_patterns(self):
        """Test @mention detection."""
        import re
        
        text_with_mention = "Need help from <@U_KEVIN> on this"
        for pattern in CROSS_TEAM_PATTERNS:
            if "<@" in pattern or "@" in pattern:
                if re.search(pattern, text_with_mention, re.IGNORECASE):
                    assert True
                    return
        # At least one pattern should match
        assert False, "No pattern matched @mention"
    
    def test_waiting_on_team_patterns(self):
        """Test 'waiting on team' detection."""
        import re
        
        text = "waiting on electrical for specs"
        matched = False
        for pattern in CROSS_TEAM_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matched = True
                break
        assert matched


# =============================================================================
# Integration Tests
# =============================================================================

class TestRankerIntegration:
    """Integration tests for ranker with feedback store."""
    
    def test_ranker_with_stored_items(self, feedback_store, ranker):
        """Test that ranker works with items from the store."""
        # Store some items
        for i in range(5):
            item = create_test_item(f"stored_{i}", confidence=0.7 + i * 0.05)
            feedback_store.store_digest_item(item)
        
        # Retrieve and rank
        items = feedback_store.get_recent_items(days=1)
        ranked = ranker.rank_items(items)
        
        assert len(ranked) == 5
        # Items should be sorted by score
        for i in range(len(ranked) - 1):
            assert ranked[i].final_score >= ranked[i + 1].final_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
