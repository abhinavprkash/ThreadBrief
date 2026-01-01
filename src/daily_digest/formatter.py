"""Digest formatter - creates Slack-ready output from V2 DigestOutput."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid

from .orchestrator import DigestOutput, GlobalDigest
from .agents.team_analyzer import TeamAnalysis
from .models.events import StructuredEvent, Decision, Blocker, StatusUpdate


@dataclass
class DigestItemMessage:
    """Individual digest item formatted for Slack posting."""
    digest_item_id: str
    team: str
    item_type: str  # blocker/decision/update/action_item
    title: str
    confidence: float
    text: str
    blocks: list[dict] = field(default_factory=list)


class DigestFormatter:
    """
    Formats the digest into Slack-ready output.
    
    Creates:
    - Individual digest item messages (for feedback tracking)
    - Main header post
    - Team-specific detailed breakdowns  
    - Executive summary for leadership DMs
    
    Confidence-aware formatting:
    - confidence >= 0.7: main digest sections
    - confidence < 0.7: "Lower Confidence / FYI" section
    - confidence < 0.4: excluded from digest
    """
    
    # Confidence thresholds
    HIGH_CONFIDENCE_THRESHOLD = 0.7
    LOW_CONFIDENCE_THRESHOLD = 0.4
    
    # Feedback emoji guide
    FEEDBACK_GUIDE = "✅ accurate | ❌ wrong | 🧩 missing context | 🔕 not relevant"
    
    EMOJI_MAP = {
        "mechanical": "⚙️",
        "electrical": "⚡",
        "software": "💻",
    }
    
    TONE_EMOJI = {
        "productive": "🚀",
        "collaborative": "🤝",
        "challenging": "⚠️",
        "routine": "📋",
        "focused": "🎯",
        "quiet": "🔇",
    }
    
    def format_digest_items(
        self,
        team_analyses: dict[str, TeamAnalysis],
        run_id: str,
        item_confidences: dict[str, float] = None,
    ) -> tuple[list[DigestItemMessage], list[DigestItemMessage], list[str]]:
        """
        Format digest items as individual messages for separate Slack posts.
        
        Each item becomes its own message for clean feedback mapping.
        
        Args:
            team_analyses: Dict of team_name -> TeamAnalysis
            run_id: Current digest run ID
            item_confidences: Optional dict of item_id -> confidence override
            
        Returns:
            Tuple of (high_confidence_items, low_confidence_items, excluded_item_ids)
        """
        high_confidence = []
        low_confidence = []
        excluded = []
        
        item_confidences = item_confidences or {}
        item_idx = 0
        
        for team_name, ta in team_analyses.items():
            emoji = self.EMOJI_MAP.get(team_name, "📁")
            
            # Process blockers
            for i, b in enumerate(ta.blockers):
                item_idx += 1
                item_id = f"{run_id}_{team_name}_blocker_{i}"
                confidence = item_confidences.get(item_id, 0.9)  # Default high
                
                if confidence < self.LOW_CONFIDENCE_THRESHOLD:
                    excluded.append(item_id)
                    continue
                
                severity = b.get("severity", "medium")
                icon = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🟢"
                owner = b.get("owner", "TBD")
                
                msg = DigestItemMessage(
                    digest_item_id=item_id,
                    team=team_name,
                    item_type="blocker",
                    title=b.get("issue", ""),
                    confidence=confidence,
                    text=f"{icon} *[{team_name}] Blocker:* {b.get('issue', '')}",
                    blocks=[
                        {"type": "section", "text": {"type": "mrkdwn", 
                            "text": f"{icon} *[{team_name}] Blocker:* {b.get('issue', '')}\n_Owner: {owner}_ | _Severity: {severity}_"}},
                        {"type": "context", "elements": [
                            {"type": "mrkdwn", "text": f"_{self.FEEDBACK_GUIDE}_"}
                        ]}
                    ]
                )
                
                if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                    high_confidence.append(msg)
                else:
                    low_confidence.append(msg)
            
            # Process decisions
            for i, d in enumerate(ta.decisions):
                item_idx += 1
                item_id = f"{run_id}_{team_name}_decision_{i}"
                confidence = item_confidences.get(item_id, 0.9)
                
                if confidence < self.LOW_CONFIDENCE_THRESHOLD:
                    excluded.append(item_id)
                    continue
                
                made_by = d.get("made_by", "")
                
                msg = DigestItemMessage(
                    digest_item_id=item_id,
                    team=team_name,
                    item_type="decision",
                    title=d.get("decision", ""),
                    confidence=confidence,
                    text=f"✅ *[{team_name}] Decision:* {d.get('decision', '')}",
                    blocks=[
                        {"type": "section", "text": {"type": "mrkdwn",
                            "text": f"✅ *[{team_name}] Decision:* {d.get('decision', '')}\n_Made by: {made_by}_"}},
                        {"type": "context", "elements": [
                            {"type": "mrkdwn", "text": f"_{self.FEEDBACK_GUIDE}_"}
                        ]}
                    ]
                )
                
                if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                    high_confidence.append(msg)
                else:
                    low_confidence.append(msg)
            
            # Process updates (top 3 only for main digest)
            for i, u in enumerate(ta.updates[:3]):
                item_idx += 1
                item_id = f"{run_id}_{team_name}_update_{i}"
                confidence = item_confidences.get(item_id, 0.8)
                
                if confidence < self.LOW_CONFIDENCE_THRESHOLD:
                    excluded.append(item_id)
                    continue
                
                category = u.get("category", "info")
                author = u.get("author", "")
                
                msg = DigestItemMessage(
                    digest_item_id=item_id,
                    team=team_name,
                    item_type="update",
                    title=u.get("update", ""),
                    confidence=confidence,
                    text=f"📊 *[{team_name}] Update:* {u.get('update', '')}",
                    blocks=[
                        {"type": "section", "text": {"type": "mrkdwn",
                            "text": f"📊 *[{team_name}] {category.title()}:* {u.get('update', '')}\n_From: {author}_"}},
                        {"type": "context", "elements": [
                            {"type": "mrkdwn", "text": f"_{self.FEEDBACK_GUIDE}_"}
                        ]}
                    ]
                )
                
                if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                    high_confidence.append(msg)
                else:
                    low_confidence.append(msg)
            
            # Process action items
            for i, a in enumerate(ta.action_items):
                item_idx += 1
                item_id = f"{run_id}_{team_name}_action_{i}"
                confidence = item_confidences.get(item_id, 0.85)
                
                if confidence < self.LOW_CONFIDENCE_THRESHOLD:
                    excluded.append(item_id)
                    continue
                
                priority = a.get("priority", "medium")
                icon = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
                owner = a.get("owner", "TBD")
                
                msg = DigestItemMessage(
                    digest_item_id=item_id,
                    team=team_name,
                    item_type="action_item",
                    title=a.get("description", ""),
                    confidence=confidence,
                    text=f"📌 *[{team_name}] Action:* {a.get('description', '')}",
                    blocks=[
                        {"type": "section", "text": {"type": "mrkdwn",
                            "text": f"{icon} *[{team_name}] Action:* {a.get('description', '')}\n_Owner: {owner}_ | _Priority: {priority}_"}},
                        {"type": "context", "elements": [
                            {"type": "mrkdwn", "text": f"_{self.FEEDBACK_GUIDE}_"}
                        ]}
                    ]
                )
                
                if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
                    high_confidence.append(msg)
                else:
                    low_confidence.append(msg)
        
        return high_confidence, low_confidence, excluded
    
    def format_header_message(
        self,
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> tuple[str, list[dict]]:
        """
        Format the header message summarizing the digest.
        Posted first, before individual items.
        """
        date = output.global_digest.date
        
        total_blockers = sum(
            len([b for b in ta.blockers if b.get("status") != "resolved"]) 
            for ta in team_analyses.values()
        )
        total_decisions = sum(len(ta.decisions) for ta in team_analyses.values())
        total_messages = sum(ta.message_count for ta in team_analyses.values())
        
        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": f"📰 Daily Digest - {date}", "emoji": True}
        }, {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                f"*{len(team_analyses)} teams* • "
                f"*{total_messages} messages* • "
                f"*{total_blockers} active blockers* • "
                f"*{total_decisions} decisions*"
            )}
        }, {
            "type": "divider"
        }, {
            "type": "context",
            "elements": [{"type": "mrkdwn", 
                "text": f"💡 _React to items below:_ {self.FEEDBACK_GUIDE}"}]
        }]
        
        text = f"Daily Digest - {date}: {total_messages} messages"
        return text, blocks
    
    def format_main_digest(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> tuple[str, list[dict]]:
        """
        Format the main digest post for #daily-digest channel.
        
        Args:
            output: DigestOutput from orchestrator
            team_analyses: Dict of team_name -> TeamAnalysis
        
        Returns (text, blocks) for Slack posting.
        """
        blocks = []
        date = output.global_digest.date
        
        # Header
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📰 Daily Digest - {date}",
                "emoji": True,
            }
        })
        
        # Summary stats
        total_blockers = sum(
            len([b for b in ta.blockers if b.get("status") != "resolved"]) 
            for ta in team_analyses.values()
        )
        total_decisions = sum(len(ta.decisions) for ta in team_analyses.values())
        total_messages = sum(ta.message_count for ta in team_analyses.values())
        
        stats_text = (
            f"*{len(team_analyses)} teams* • "
            f"*{total_messages} messages* • "
            f"*{total_blockers} active blockers* • "
            f"*{total_decisions} decisions*"
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": stats_text}
        })
        
        blocks.append({"type": "divider"})
        
        # Team summaries with brief overview
        for team_name, ta in team_analyses.items():
            emoji = self.EMOJI_MAP.get(team_name, "📁")
            tone_emoji = self.TONE_EMOJI.get(ta.tone, "")
            
            # Team header
            header = f"{emoji} *{team_name.title()}* {tone_emoji}"
            
            # Brief summary (first 150 chars)
            summary = ta.summary[:150] + "..." if len(ta.summary) > 150 else ta.summary
            
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{header}\n_{summary}_"}
            })
        
        blocks.append({"type": "divider"})
        
        # Cross-team blockers with impact
        cross_team_blockers = []
        for team_name, ta in team_analyses.items():
            for b in ta.blockers:
                if b.get("status") != "resolved":
                    issue = b.get("issue", "")
                    if any(team in issue.lower() for team in ["mechanical", "electrical", "software", "firmware"]):
                        cross_team_blockers.append((team_name, b, "cross-team"))
                    elif b.get("severity") == "high":
                        cross_team_blockers.append((team_name, b, "high"))
        
        if cross_team_blockers:
            blocker_lines = ["*🚨 Key Blockers Affecting Teams:*"]
            for team, b, reason in cross_team_blockers[:4]:
                icon = "🔴" if b.get("severity") == "high" else "🟡"
                blocker_lines.append(f"{icon} *[{team}]* {b.get('issue', '')[:100]}")
            
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(blocker_lines)}
            })
        
        # Key decisions summary
        key_decisions = []
        for team_name, ta in team_analyses.items():
            for d in ta.decisions[:2]:  # Top 2 per team
                key_decisions.append((team_name, d.get("decision", "")))
        
        if key_decisions:
            decision_lines = [f"*✅ Key Decisions ({len(key_decisions)}):*"]
            for team, decision in key_decisions[:5]:
                decision_lines.append(f"• *[{team}]* {decision[:80]}")
            
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(decision_lines)}
            })
        
        blocks.append({"type": "divider"})
        
        # Cross-team highlights from global digest
        if output.global_digest.cross_team_highlights:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🔗 Cross-Team Coordination:*\n" + "\n".join(
                        f"• {h}" for h in output.global_digest.cross_team_highlights[:3]
                    )
                }
            })
        
        # Note about detailed breakdowns
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "📋 _Full details posted to each team's channel_"
            }]
        })
        
        text = f"Daily Digest - {date}: {total_messages} messages"
        return text, blocks
    
    def format_team_details(self, team_analysis: TeamAnalysis) -> str:
        """
        Format FULL detailed breakdown for a team's own channel.
        
        This is team-private content, includes everything.
        """
        team_name = team_analysis.team_name
        emoji = self.EMOJI_MAP.get(team_name, "📁")
        tone_emoji = self.TONE_EMOJI.get(team_analysis.tone, "")
        
        lines = [
            f"{emoji} *{team_name.title()} Daily Digest* {tone_emoji}",
            "",
        ]
        
        # Summary
        if team_analysis.summary:
            lines.append(f"_{team_analysis.summary}_")
            lines.append("")
        
        # Themes
        if team_analysis.themes:
            lines.append(f"*Themes:* {', '.join(team_analysis.themes)}")
            lines.append("")
        
        # All updates with details
        if team_analysis.updates:
            lines.append("*📊 Updates:*")
            for u in team_analysis.updates:
                category = u.get("category", "info")
                author = u.get("author", "")
                update = u.get("update", "")
                lines.append(f"• [{category}] {update}")
                if author:
                    lines.append(f"  _→ {author}_")
            lines.append("")
        
        # All blockers with full details
        if team_analysis.blockers:
            lines.append("*⚠️ Blockers:*")
            for b in team_analysis.blockers:
                severity = b.get("severity", "medium")
                status = b.get("status", "active")
                owner = b.get("owner", "TBD")
                icon = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🟢"
                lines.append(f"{icon} {b.get('issue', '')} [{status}]")
                lines.append(f"  _Owner: {owner}_")
            lines.append("")
        
        # All decisions with context
        if team_analysis.decisions:
            lines.append("*✅ Decisions:*")
            for d in team_analysis.decisions:
                decision = d.get("decision", "")
                made_by = d.get("made_by", "")
                context = d.get("context", "")
                lines.append(f"✓ {decision}")
                if made_by:
                    lines.append(f"  _→ {made_by}_")
                if context:
                    lines.append(f"  _Context: {context}_")
            lines.append("")
        
        # Action items
        if team_analysis.action_items:
            lines.append("*📌 Action Items:*")
            for a in team_analysis.action_items:
                priority = a.get("priority", "medium")
                icon = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
                lines.append(f"{icon} {a.get('description', '')} - _{a.get('owner', 'TBD')}_")
            lines.append("")
        
        return "\n".join(lines)
    
    def format_leadership_dm(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> str:
        """
        Format executive summary for leadership DMs.
        
        Includes:
        - Overall status per team
        - ALL critical blockers (not just 3)
        - ALL decisions made
        - Cross-team dependencies
        """
        date = output.global_digest.date
        total_messages = sum(ta.message_count for ta in team_analyses.values())
        
        lines = [
            f"*📰 Executive Digest - {date}*",
            "",
            f"_{total_messages} messages • {len(team_analyses)} teams_",
            "",
        ]
        
        # Team status summary
        lines.append("*📊 Team Status:*")
        for team_name, ta in team_analyses.items():
            emoji = self.EMOJI_MAP.get(team_name, "📁")
            tone_emoji = self.TONE_EMOJI.get(ta.tone, "")
            blocker_count = len([b for b in ta.blockers if b.get("status") != "resolved"])
            decision_count = len(ta.decisions)
            lines.append(
                f"{emoji} *{team_name.title()}*: {tone_emoji} {ta.tone} | "
                f"{blocker_count} blockers | {decision_count} decisions"
            )
        lines.append("")
        
        # ALL critical blockers from all teams
        critical_blockers = []
        for team_name, ta in team_analyses.items():
            for b in ta.blockers:
                if b.get("status") != "resolved":
                    critical_blockers.append((team_name, b))
        
        if critical_blockers:
            lines.append(f"*🚨 Active Blockers ({len(critical_blockers)}):*")
            for team, blocker in critical_blockers:
                severity = blocker.get("severity", "medium")
                icon = "🔴" if severity == "high" else "🟡"
                owner = blocker.get("owner", "TBD")
                lines.append(f"{icon} [{team}] {blocker.get('issue', '')}")
                lines.append(f"   _Owner: {owner}_")
            lines.append("")
        
        # ALL decisions from all teams
        all_decisions = []
        for team_name, ta in team_analyses.items():
            for d in ta.decisions:
                all_decisions.append((team_name, d))
        
        if all_decisions:
            lines.append(f"*✅ Decisions Made ({len(all_decisions)}):*")
            for team, decision in all_decisions:
                made_by = decision.get("made_by", "")
                lines.append(f"• [{team}] {decision.get('decision', '')}")
                if made_by:
                    lines.append(f"   _→ {made_by}_")
            lines.append("")
        
        # Cross-team highlights
        if output.global_digest.cross_team_highlights:
            lines.append("*🔗 Cross-Team Dependencies:*")
            for h in output.global_digest.cross_team_highlights:
                lines.append(f"• {h}")
            lines.append("")
        
        # High priority action items
        high_priority_actions = []
        for team_name, ta in team_analyses.items():
            for a in ta.action_items:
                if a.get("priority") == "high":
                    high_priority_actions.append((team_name, a))
        
        if high_priority_actions:
            lines.append(f"*⚡ High Priority Actions ({len(high_priority_actions)}):*")
            for team, action in high_priority_actions[:5]:
                lines.append(f"• [{team}] {action.get('description', '')}")
            lines.append("")
        
        lines.append("_Full details in team channels._")
        
        return "\n".join(lines)
