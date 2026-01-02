"""Feedback Simulator - multi-day simulation of feedback loop learning."""

import json
import random
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .evaluator import DigestEvaluator, DigestEvaluation
from ..personalization.personas import Persona, PersonaManager, RolePersona, TeamPersona
from ..personalization.ranker import DigestRanker, RankedItem
from ..feedback.feedback_store import FeedbackStore, DigestItem, FeedbackEvent
from ..feedback.feedback_processor import FeedbackProcessor
from ..feedback.prompt_enhancer import PromptEnhancer
from ..feedback.feedback_metrics import FeedbackMetrics


@dataclass
class SimulatedDay:
    """Results from a single simulated day."""
    
    date: str
    day_number: int
    
    # Items and evaluations
    digest_items: list[dict] = field(default_factory=list)
    ranked_items: list[dict] = field(default_factory=list)
    evaluations: list[dict] = field(default_factory=list)
    
    # Feedback generated
    feedback_events: list[dict] = field(default_factory=list)
    
    # Metrics
    metrics: dict = field(default_factory=dict)
    
    # Improvements applied
    new_directives: list[str] = field(default_factory=list)
    confidence_changes: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LearningPoint:
    """A data point in the learning curve."""
    
    day: int
    date: str
    
    # Quality metrics
    wrong_ratio: float
    irrelevant_ratio: float
    accuracy_ratio: float
    
    # Cross-team metrics
    cross_team_surfacing_avg: float
    cross_team_items_boosted: int
    
    # Ranker state
    active_directives: int
    items_processed: int


@dataclass
class SimulationReport:
    """Complete report from a multi-day simulation."""
    
    simulation_id: str
    start_date: str
    end_date: str
    num_days: int
    
    # Results by day
    days: list[SimulatedDay] = field(default_factory=list)
    
    # Learning curve
    learning_curve: list[LearningPoint] = field(default_factory=list)
    
    # Summary statistics
    initial_wrong_ratio: float = 0.0
    final_wrong_ratio: float = 0.0
    wrong_ratio_improvement: float = 0.0
    
    initial_cross_team_score: float = 0.0
    final_cross_team_score: float = 0.0
    cross_team_improvement: float = 0.0
    
    total_feedback_events: int = 0
    total_items_processed: int = 0
    total_directives_generated: int = 0
    
    def to_dict(self) -> dict:
        return {
            "simulation_id": self.simulation_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "num_days": self.num_days,
            "summary": {
                "initial_wrong_ratio": round(self.initial_wrong_ratio, 3),
                "final_wrong_ratio": round(self.final_wrong_ratio, 3),
                "wrong_ratio_improvement": round(self.wrong_ratio_improvement, 3),
                "initial_cross_team_score": round(self.initial_cross_team_score, 3),
                "final_cross_team_score": round(self.final_cross_team_score, 3),
                "cross_team_improvement": round(self.cross_team_improvement, 3),
                "total_feedback_events": self.total_feedback_events,
                "total_items_processed": self.total_items_processed,
                "total_directives_generated": self.total_directives_generated,
            },
            "learning_curve": [asdict(lp) for lp in self.learning_curve],
            "days": [d.to_dict() for d in self.days],
        }
    
    def save(self, path: str):
        """Save report to JSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    def format_day_digest(self, day: SimulatedDay, day_idx: int) -> str:
        """
        Format a single day's digest as human-readable markdown.
        
        Structure:
        1. Global Digest (Top 5 headlines + risks)
        2. Blockers Requiring Action (owner, next step, ETA)
        3. Decisions Made (what changed, impact)
        4. Cross-Team Dependencies (who needs what from whom, by when)
        5. Team Updates (deltas only)
        6. Leadership Summary
        7. Tomorrow's Priorities
        """
        lines = []
        lines.append(f"## 📅 Day {day.day_number}: {day.date}")
        lines.append("")
        
        # Get learning point for this day
        lp = self.learning_curve[day_idx] if day_idx < len(self.learning_curve) else None
        if lp:
            lines.append(f"> **Quality Score:** {lp.accuracy_ratio:.0%} accuracy | **Cross-Team Coverage:** {lp.cross_team_surfacing_avg:.0%}")
            lines.append("")
        
        # Categorize items
        blockers = []
        decisions = []
        action_items = []
        updates = []
        cross_team_items = []
        
        for ranked in day.ranked_items:
            item_id = ranked.get("item_id", "")
            full_item = next((it for it in day.digest_items if it.get("digest_item_id") == item_id), {})
            
            item_data = {
                "title": full_item.get("title", "Unknown"),
                "team": full_item.get("team", "unknown"),
                "type": full_item.get("item_type", "unknown"),
                "severity": full_item.get("severity", "medium"),
                "owners": full_item.get("owners", []),
                "is_cross_team": ranked.get("is_cross_team", False),
                "score": ranked.get("final_score", 0),
            }
            
            if item_data["type"] == "blocker":
                blockers.append(item_data)
            elif item_data["type"] == "decision":
                decisions.append(item_data)
            elif item_data["type"] == "action_item":
                action_items.append(item_data)
            else:
                updates.append(item_data)
            
            if item_data["is_cross_team"]:
                cross_team_items.append(item_data)
        
        # ===== 1. GLOBAL DIGEST: TOP 5 HEADLINES =====
        lines.append("### 🎯 Today's Top 5")
        lines.append("")
        
        # Combine and sort all items by score
        all_items = blockers + decisions + action_items
        all_items.sort(key=lambda x: x["score"], reverse=True)
        
        for i, item in enumerate(all_items[:5], 1):
            icon = {"blocker": "🚨", "decision": "✅", "action_item": "⚡"}.get(item["type"], "📝")
            cross = " 🔗" if item["is_cross_team"] else ""
            high = " **HIGH**" if item["severity"] == "high" else ""
            lines.append(f"{i}. {icon}{cross} **[{item['team'].upper()}]** {item['title']}{high}")
        
        if not all_items:
            lines.append("_No significant items today._")
        lines.append("")
        
        # ===== 2. BLOCKERS REQUIRING ACTION =====
        lines.append("### 🚨 Blockers Requiring Action")
        lines.append("")
        
        if blockers:
            lines.append("| Team | Issue | Owner | Next Step | ETA |")
            lines.append("|------|-------|-------|-----------|-----|")
            
            for b in blockers[:5]:
                team = b["team"].upper()
                issue = b["title"][:40] + "..." if len(b["title"]) > 40 else b["title"]
                owner = b["owners"][0] if b["owners"] else "TBD"
                # Generate mock next step and ETA based on severity
                if b["severity"] == "high":
                    next_step = "Escalate to leads"
                    eta = "Today"
                else:
                    next_step = "Follow up required"
                    eta = "EOD Tomorrow"
                lines.append(f"| {team} | {issue} | {owner} | {next_step} | {eta} |")
            
            if len(blockers) > 5:
                lines.append(f"| ... | +{len(blockers) - 5} more blockers | | | |")
        else:
            lines.append("✅ _No active blockers today._")
        lines.append("")
        
        # ===== 3. DECISIONS MADE =====
        lines.append("### ✅ Decisions Made")
        lines.append("")
        
        if decisions:
            for d in decisions[:4]:
                cross = " 🔗" if d["is_cross_team"] else ""
                lines.append(f"- **[{d['team'].upper()}]**{cross} {d['title']}")
                # Add mock impact
                if d["is_cross_team"]:
                    lines.append(f"  - _Impact: Affects multiple teams. Notify stakeholders._")
                else:
                    lines.append(f"  - _Impact: Team-internal change._")
            if len(decisions) > 4:
                lines.append(f"- _+{len(decisions) - 4} more decisions_")
        else:
            lines.append("_No decisions recorded today._")
        lines.append("")
        
        # ===== 4. CROSS-TEAM DEPENDENCIES =====
        lines.append("### 🔗 Cross-Team Dependencies")
        lines.append("")
        
        if cross_team_items:
            lines.append("| From | Needs | To | Item | By When |")
            lines.append("|------|-------|----|------|---------|")
            
            for ct in cross_team_items[:5]:
                from_team = ct["team"].upper()
                # Parse "other team" from title
                to_team = "OTHER"
                for team_name in ["mechanical", "electrical", "software"]:
                    if team_name in ct["title"].lower() and team_name != ct["team"].lower():
                        to_team = team_name.upper()
                        break
                
                need = "Interface specs" if "spec" in ct["title"].lower() else "Coordination"
                by_when = "Fri" if ct["severity"] == "high" else "Next week"
                
                lines.append(f"| {from_team} | {need} | {to_team} | {ct['title'][:30]}... | {by_when} |")
            
            if len(cross_team_items) > 5:
                lines.append(f"| ... | +{len(cross_team_items) - 5} more | | | |")
        else:
            lines.append("✅ _No cross-team dependencies flagged today._")
        lines.append("")
        
        # ===== 5. TEAM UPDATES (Grouped) =====
        lines.append("### 📊 Team Updates")
        lines.append("")
        
        teams = {}
        for item in day.digest_items:
            team = item.get("team", "unknown")
            teams.setdefault(team, []).append(item)
        
        for team_name, team_items in sorted(teams.items()):
            team_blockers = [i for i in team_items if i.get("item_type") == "blocker"]
            team_decisions = [i for i in team_items if i.get("item_type") == "decision"]
            team_actions = [i for i in team_items if i.get("item_type") == "action_item"]
            
            emoji = {"mechanical": "⚙️", "electrical": "⚡", "software": "💻"}.get(team_name, "📁")
            lines.append(f"**{emoji} {team_name.title()}**: {len(team_blockers)} blockers | {len(team_decisions)} decisions | {len(team_actions)} action items")
            
            # Show top 2 items per team
            top_team_items = [i for i in all_items if i["team"] == team_name][:2]
            for item in top_team_items:
                icon = {"blocker": "🚨", "decision": "✅", "action_item": "⚡"}.get(item["type"], "📝")
                lines.append(f"  - {icon} {item['title'][:50]}")
            lines.append("")
        
        # ===== 6. LEADERSHIP SUMMARY =====
        lines.append("### 👔 Leadership Summary")
        lines.append("")
        
        total_blockers = len(blockers)
        high_sev = len([b for b in blockers if b["severity"] == "high"])
        cross_team_count = len(cross_team_items)
        
        lines.append(f"- **Risk Level:** {'🔴 HIGH' if high_sev > 0 else '🟡 MEDIUM' if total_blockers > 2 else '🟢 LOW'}")
        lines.append(f"- **Active Blockers:** {total_blockers} ({high_sev} high severity)")
        lines.append(f"- **Cross-Team Items:** {cross_team_count} requiring coordination")
        lines.append(f"- **Decisions Today:** {len(decisions)}")
        lines.append("")
        
        if high_sev > 0:
            lines.append("**⚠️ Executive Attention Needed:**")
            for b in [x for x in blockers if x["severity"] == "high"][:2]:
                lines.append(f"- {b['title']}")
            lines.append("")
        
        # ===== 7. TOMORROW'S PRIORITIES =====
        lines.append("### 🎯 Tomorrow's Priorities (Org-Wide)")
        lines.append("")
        
        # Generate priorities based on blockers and cross-team items
        priorities = []
        if high_sev > 0:
            priorities.append("1. **Resolve high-severity blockers** - Escalate as needed")
        if cross_team_count > 2:
            priorities.append(f"2. **Clear {cross_team_count} cross-team dependencies** - Schedule sync meetings")
        if action_items:
            priorities.append("3. **Complete pending action items** - Update progress by EOD")
        
        if priorities:
            for p in priorities[:3]:
                lines.append(p)
        else:
            lines.append("1. Continue planned work")
            lines.append("2. Monitor for emerging blockers")
            lines.append("3. Prepare for sprint review")
        lines.append("")
        
        # ===== FEEDBACK & LEARNING =====
        if day.feedback_events:
            lines.append("### 📣 Feedback Received")
            lines.append("")
            
            fb_by_type = {}
            for fb in day.feedback_events:
                fb_type = fb.get("feedback_type", "unknown")
                fb_by_type.setdefault(fb_type, []).append(fb)
            
            fb_summary = []
            for fb_type, events in fb_by_type.items():
                emoji = {"accurate": "✓", "wrong": "✗", "irrelevant": "−", "missing_context": "?"}.get(fb_type, "•")
                fb_summary.append(f"{emoji} {fb_type}: {len(events)}")
            lines.append(" | ".join(fb_summary))
            lines.append("")
        
        if day.new_directives:
            unique_directives = list(set(d.strip() for d in day.new_directives if d.strip()))
            if unique_directives:
                lines.append("### 🧠 System Learning")
                lines.append("")
                lines.append("_New patterns learned from feedback:_")
                for directive in unique_directives[:3]:
                    lines.append(f"- {directive}")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        return "\n".join(lines)
    
    def save_digests_markdown(self, path: str):
        """
        Save human-readable markdown digests showing improvement over time.
        
        This output allows humans to verify:
        1. Cross-team items are surfaced first
        2. Quality improves over days
        3. Learned directives make sense
        """
        lines = []
        
        # Header
        lines.append("# AI Digest Improvement Over Time")
        lines.append("")
        lines.append(f"**Simulation ID:** {self.simulation_id}")
        lines.append(f"**Period:** {self.start_date} to {self.end_date} ({self.num_days} days)")
        lines.append("")
        
        # Summary
        lines.append("## 📊 Summary")
        lines.append("")
        lines.append("| Metric | Start | End | Change |")
        lines.append("|--------|-------|-----|--------|")
        lines.append(f"| Wrong Ratio | {self.initial_wrong_ratio:.1%} | {self.final_wrong_ratio:.1%} | {self.wrong_ratio_improvement:+.1%} |")
        lines.append(f"| Cross-Team Score | {self.initial_cross_team_score:.2f} | {self.final_cross_team_score:.2f} | {self.cross_team_improvement:+.2f} |")
        lines.append(f"| Total Feedback | - | {self.total_feedback_events} | - |")
        lines.append(f"| Directives Learned | - | {self.total_directives_generated} | - |")
        lines.append("")
        
        # Learning curve visualization (text-based)
        lines.append("## 📈 Learning Curve")
        lines.append("")
        lines.append("```")
        lines.append("Cross-Team Score by Day:")
        lines.append("")
        
        max_score = max((lp.cross_team_surfacing_avg for lp in self.learning_curve), default=1.0)
        for lp in self.learning_curve:
            bar_len = int((lp.cross_team_surfacing_avg / max(max_score, 0.01)) * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            lines.append(f"Day {lp.day:2d} |{bar}| {lp.cross_team_surfacing_avg:.2f}")
        
        lines.append("```")
        lines.append("")
        
        # Key observations
        lines.append("## 🔍 Key Observations")
        lines.append("")
        
        if self.cross_team_improvement > 0:
            lines.append(f"✅ **Cross-team surfacing improved by {self.cross_team_improvement:.2f}** - The system learned to prioritize cross-team dependencies.")
        elif self.cross_team_improvement < 0:
            lines.append(f"⚠️ **Cross-team surfacing decreased by {-self.cross_team_improvement:.2f}** - May need tuning.")
        else:
            lines.append("➡️ **Cross-team surfacing unchanged** - Baseline maintained.")
        
        if self.wrong_ratio_improvement > 0:
            lines.append(f"✅ **Wrong ratio decreased by {self.wrong_ratio_improvement:.1%}** - Fewer incorrect items.")
        
        if self.total_directives_generated > 0:
            lines.append(f"✅ **{self.total_directives_generated} directives generated** - System learned from feedback patterns.")
        
        lines.append("")
        
        # Daily digests
        lines.append("---")
        lines.append("")
        lines.append("# Daily Digests")
        lines.append("")
        lines.append("Below are the AI-generated digests for each day, showing ranked items and how the system improved.")
        lines.append("")
        
        for i, day in enumerate(self.days):
            lines.append(self.format_day_digest(day, i))
        
        # Write to file
        with open(path, 'w') as f:
            f.write("\n".join(lines))
    
    def save_daily_digests(self, output_dir: str):
        """
        Save each day's digest as a separate markdown file.
        
        Creates a directory structure:
          output_dir/
            day_01_2026-01-01.md
            day_02_2026-01-02.md
            ...
        """
        from pathlib import Path
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        
        for i, day in enumerate(self.days):
            # Format filename
            filename = f"day_{day.day_number:02d}_{day.date}.md"
            file_path = output_path / filename
            
            # Create day header
            content_lines = []
            content_lines.append(f"# ThreadBrief Daily Digest")
            content_lines.append("")
            content_lines.append(f"**Simulation:** {self.simulation_id}")
            content_lines.append(f"**Date:** {day.date}")
            content_lines.append(f"**Day:** {day.day_number} of {self.num_days}")
            content_lines.append("")
            
            # Add the formatted digest
            content_lines.append(self.format_day_digest(day, i))
            
            # Add comparison with previous day if applicable
            if i > 0:
                prev_lp = self.learning_curve[i - 1]
                curr_lp = self.learning_curve[i]
                
                content_lines.append("## 📊 Comparison vs Yesterday")
                content_lines.append("")
                content_lines.append("| Metric | Yesterday | Today | Change |")
                content_lines.append("|--------|-----------|-------|--------|")
                
                acc_change = curr_lp.accuracy_ratio - prev_lp.accuracy_ratio
                content_lines.append(f"| Accuracy | {prev_lp.accuracy_ratio:.0%} | {curr_lp.accuracy_ratio:.0%} | {acc_change:+.0%} |")
                
                ct_change = curr_lp.cross_team_surfacing_avg - prev_lp.cross_team_surfacing_avg
                content_lines.append(f"| Cross-Team | {prev_lp.cross_team_surfacing_avg:.2f} | {curr_lp.cross_team_surfacing_avg:.2f} | {ct_change:+.2f} |")
                content_lines.append("")
                
                if ct_change > 0.05:
                    content_lines.append(f"✅ **Cross-team surfacing improved** (+{ct_change:.2f})")
                elif ct_change < -0.05:
                    content_lines.append(f"⚠️ **Cross-team surfacing declined** ({ct_change:.2f})")
                content_lines.append("")
            
            # Write file
            with open(file_path, 'w') as f:
                f.write("\n".join(content_lines))
            
            saved_files.append(str(file_path))
        
        # Create index file
        index_path = output_path / "index.md"
        index_lines = []
        index_lines.append(f"# Daily Digest Index")
        index_lines.append("")
        index_lines.append(f"**Simulation:** {self.simulation_id}")
        index_lines.append(f"**Period:** {self.start_date} to {self.end_date}")
        index_lines.append("")
        index_lines.append("## Learning Curve")
        index_lines.append("")
        index_lines.append("| Day | Date | Accuracy | Cross-Team | File |")
        index_lines.append("|-----|------|----------|------------|------|")
        
        for i, day in enumerate(self.days):
            lp = self.learning_curve[i] if i < len(self.learning_curve) else None
            acc = f"{lp.accuracy_ratio:.0%}" if lp else "-"
            ct = f"{lp.cross_team_surfacing_avg:.2f}" if lp else "-"
            filename = f"day_{day.day_number:02d}_{day.date}.md"
            index_lines.append(f"| {day.day_number} | {day.date} | {acc} | {ct} | [{filename}]({filename}) |")
        
        index_lines.append("")
        index_lines.append("## Summary")
        index_lines.append("")
        index_lines.append(f"- **Initial Cross-Team:** {self.initial_cross_team_score:.2f}")
        index_lines.append(f"- **Final Cross-Team:** {self.final_cross_team_score:.2f}")
        index_lines.append(f"- **Improvement:** {self.cross_team_improvement:+.2f}")
        
        with open(index_path, 'w') as f:
            f.write("\n".join(index_lines))
        
        saved_files.append(str(index_path))
        
        return saved_files



# Simulated user configurations
SIMULATED_USERS = [
    {"user_id": "U_MARIA", "role": "lead", "team": "mechanical"},
    {"user_id": "U_ALEX", "role": "ic", "team": "mechanical"},
    {"user_id": "U_KEVIN", "role": "lead", "team": "electrical"},
    {"user_id": "U_LISA", "role": "ic", "team": "electrical"},
    {"user_id": "U_RYAN", "role": "lead", "team": "software"},
]


class FeedbackSimulator:
    """
    Multi-day simulation of the feedback loop learning process.
    
    Simulates:
    1. Digest generation with current ranker state
    2. Quality evaluation of items
    3. User feedback based on evaluations
    4. Learning updates (confidence, directives)
    5. Metrics tracking over time
    
    The simulation demonstrates how the system improves as it receives
    more feedback, with particular focus on:
    - Cross-team dependency surfacing
    - Reduction in wrong/irrelevant items
    - Personalization learning
    """
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        use_mock_evaluation: bool = True,
    ):
        """
        Initialize simulator.
        
        Args:
            db_path: Path to feedback database (creates temp if None)
            use_mock_evaluation: Use heuristic evaluation instead of LLM
        """
        # Create isolated database for simulation
        if db_path:
            self.db_path = db_path
        else:
            data_dir = Path(__file__).parent.parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            self.db_path = str(data_dir / "simulation_feedback.db")
        
        self.feedback_store = FeedbackStore(self.db_path)
        self.feedback_processor = FeedbackProcessor(self.feedback_store)
        self.prompt_enhancer = PromptEnhancer(self.feedback_store)
        self.feedback_metrics = FeedbackMetrics(self.feedback_store)
        
        self.persona_manager = PersonaManager()
        self.ranker = DigestRanker(self.feedback_store, self.persona_manager)
        self.evaluator = DigestEvaluator(use_mock=use_mock_evaluation)
        
        # Initialize simulated users
        for user in SIMULATED_USERS:
            self.persona_manager.set_user_persona(
                user["user_id"],
                role=user["role"],
                team=user["team"],
            )
    
    def generate_synthetic_items(
        self,
        date: str,
        num_items: int = 15,
    ) -> list[DigestItem]:
        """
        Generate synthetic digest items for simulation.
        
        Creates a mix of:
        - Team-specific items
        - Cross-team blockers
        - Action items
        - Decisions
        - Updates (some low-value)
        """
        items = []
        run_id = f"sim_{date.replace('-', '')}_{uuid.uuid4().hex[:8]}"
        
        teams = ["mechanical", "electrical", "software"]
        item_types = ["blocker", "decision", "action_item", "update"]
        
        # Templates for different item types
        templates = {
            "blocker": [
                ("Waiting on {other_team} for interface specs", True, 0.9),
                ("CNC machine down for maintenance", False, 0.85),
                ("Blocked on firmware update from {other_team}", True, 0.95),
                ("Missing test fixtures", False, 0.7),
            ],
            "decision": [
                ("Approved: Use Rev C for pilot run", False, 0.9),
                ("Decision: Split first article between vendors", False, 0.85),
                ("Agreed: 24V ±20% input specification", False, 0.8),
            ],
            "action_item": [
                ("Update BOM with new part numbers", False, 0.85),
                ("Sync with {other_team} on connector placement", True, 0.9),
                ("Run stress test on new design", False, 0.8),
            ],
            "update": [
                ("FEA simulation complete, results nominal", False, 0.75),
                ("Coffee run anyone?", False, 0.3),  # Noise
                ("Sprint planning complete", False, 0.6),
                ("Lunch break - back at 1pm", False, 0.2),  # Noise
            ],
        }
        
        for i in range(num_items):
            team = random.choice(teams)
            item_type = random.choice(item_types)
            
            # Pick a template
            type_templates = templates.get(item_type, templates["update"])
            title_template, is_cross_team, base_confidence = random.choice(type_templates)
            
            # Generate cross-team reference if applicable
            other_teams = [t for t in teams if t != team]
            other_team = random.choice(other_teams)
            title = title_template.format(other_team=other_team)
            
            # Add some randomness to confidence
            confidence = base_confidence + random.uniform(-0.1, 0.1)
            confidence = max(0.3, min(1.0, confidence))
            
            item = DigestItem(
                digest_item_id=f"{run_id}_{team}_{item_type}_{i}",
                run_id=run_id,
                date=date,
                team=team,
                item_type=item_type,
                title=title,
                summary=f"{title}. Additional context about the {item_type}.",
                severity="high" if "block" in title.lower() else "medium",
                confidence=confidence,
                owners=[f"U_{team.upper()[:3]}"] if item_type in ["action_item", "blocker"] else [],
            )
            items.append(item)
        
        return items
    
    def simulate_day(
        self,
        date: str,
        day_number: int,
        items_per_team: int = 5,
        feedback_rate: float = 0.4,
    ) -> SimulatedDay:
        """
        Simulate one day of the feedback loop.
        
        Steps:
        1. Generate digest items
        2. Store items (for feedback tracking)
        3. Rank items for each simulated user
        4. Evaluate item quality
        5. Generate feedback based on evaluation
        6. Process feedback to update system
        7. Record metrics
        """
        day_result = SimulatedDay(date=date, day_number=day_number)
        
        # 1. Generate items
        items = self.generate_synthetic_items(date, num_items=items_per_team * 3)
        day_result.digest_items = [item.to_dict() for item in items]
        
        # 2. Store items
        for item in items:
            self.feedback_store.store_digest_item(item)
        
        # 3-6. For each simulated user
        all_evaluations = []
        all_feedback = []
        
        for user_config in SIMULATED_USERS:
            user_id = user_config["user_id"]
            role = user_config["role"]
            team = user_config["team"]
            
            # Get persona
            persona = self.persona_manager.get_combined_persona(user_id, role, team)
            
            # Rank items (filter to user's team + cross-team)
            team_items = [i for i in items if i.team == team or self._is_cross_team(i, team)]
            ranked = self.ranker.rank_items(team_items, user_id, team, role)
            
            # Store ranked items (first user only to avoid duplicates)
            if user_id == SIMULATED_USERS[0]["user_id"]:
                day_result.ranked_items = [
                    {
                        "item_id": r.item.digest_item_id,
                        "final_score": r.final_score,
                        "is_cross_team": r.is_cross_team,
                        "explanation": self.ranker.explain_ranking(r),
                    }
                    for r in ranked[:10]
                ]
            
            # Evaluate items
            evaluations = self.evaluator.evaluate_items(
                [r.item for r in ranked[:10]],  # Top 10 items
                persona,
            )
            all_evaluations.extend(evaluations)
            
            # Generate feedback (based on feedback_rate)
            for evaluation in evaluations:
                if random.random() < feedback_rate:
                    feedback = FeedbackEvent(
                        digest_item_id=evaluation.digest_item_id,
                        user_id=user_id,
                        team=team,
                        feedback_type=evaluation.simulated_feedback_type,
                        comment=evaluation.feedback_reason,
                    )
                    self.feedback_store.store_feedback(feedback)
                    all_feedback.append(feedback)
        
        # Store evaluations
        day_result.evaluations = [e.to_dict() for e in all_evaluations]
        day_result.feedback_events = [
            {
                "user_id": f.user_id,
                "digest_item_id": f.digest_item_id,
                "feedback_type": f.feedback_type,
                "comment": f.comment,
            }
            for f in all_feedback
        ]
        
        # 6. Process feedback to update system
        for feedback in all_feedback:
            self.feedback_processor.apply_item_specific_feedback(feedback.digest_item_id)
        
        # Generate new directives based on patterns
        for team in ["mechanical", "electrical", "software"]:
            new_directives = self.prompt_enhancer.generate_directives(team)
            if new_directives:
                day_result.new_directives.extend(new_directives.split("\n"))
        
        # Invalidate ranker cache to pick up changes
        self.ranker.invalidate_cache()
        
        # 7. Compute metrics
        snapshot = self.feedback_metrics.compute_snapshot(days=1)
        day_result.metrics = snapshot.to_dict()
        
        return day_result
    
    def _is_cross_team(self, item: DigestItem, team: str) -> bool:
        """Check if item is cross-team relevant."""
        text = f"{item.title} {item.summary}".lower()
        return team.lower() in text or "cross-team" in text or "waiting on" in text
    
    def run_simulation(
        self,
        num_days: int = 14,
        items_per_team: int = 5,
        feedback_rate: float = 0.4,
        start_date: Optional[str] = None,
    ) -> SimulationReport:
        """
        Run a multi-day feedback simulation.
        
        Args:
            num_days: Number of days to simulate
            items_per_team: Items to generate per team per day
            feedback_rate: Probability of feedback per item (0-1)
            start_date: Starting date (ISO format), defaults to today
            
        Returns:
            SimulationReport with complete results
        """
        if start_date:
            current_date = datetime.fromisoformat(start_date)
        else:
            current_date = datetime.now()
        
        report = SimulationReport(
            simulation_id=f"sim_{uuid.uuid4().hex[:8]}",
            start_date=current_date.isoformat()[:10],
            end_date=(current_date + timedelta(days=num_days - 1)).isoformat()[:10],
            num_days=num_days,
        )
        
        print(f"🚀 Starting {num_days}-day feedback simulation...")
        print(f"   Feedback rate: {feedback_rate:.0%}")
        print(f"   Items per team per day: {items_per_team}")
        print()
        
        # Run each day
        for day_num in range(num_days):
            date_str = (current_date + timedelta(days=day_num)).isoformat()[:10]
            print(f"📅 Day {day_num + 1}/{num_days} ({date_str})...", end=" ")
            
            day_result = self.simulate_day(
                date=date_str,
                day_number=day_num + 1,
                items_per_team=items_per_team,
                feedback_rate=feedback_rate,
            )
            report.days.append(day_result)
            
            # Compute learning point
            evaluations = day_result.evaluations
            if evaluations:
                cross_team_scores = [e["cross_team_surfacing"] for e in evaluations]
                cross_team_avg = sum(cross_team_scores) / len(cross_team_scores)
            else:
                cross_team_avg = 0.0
            
            feedback_counts = {"wrong": 0, "irrelevant": 0, "accurate": 0, "missing_context": 0}
            for fb in day_result.feedback_events:
                feedback_counts[fb["feedback_type"]] = feedback_counts.get(fb["feedback_type"], 0) + 1
            
            total_fb = sum(feedback_counts.values()) or 1
            
            learning_point = LearningPoint(
                day=day_num + 1,
                date=date_str,
                wrong_ratio=feedback_counts["wrong"] / total_fb,
                irrelevant_ratio=feedback_counts["irrelevant"] / total_fb,
                accuracy_ratio=feedback_counts["accurate"] / total_fb,
                cross_team_surfacing_avg=cross_team_avg,
                cross_team_items_boosted=len([r for r in day_result.ranked_items if r.get("is_cross_team")]),
                active_directives=len(day_result.new_directives),
                items_processed=len(day_result.digest_items),
            )
            report.learning_curve.append(learning_point)
            
            # Running totals
            report.total_feedback_events += len(day_result.feedback_events)
            report.total_items_processed += len(day_result.digest_items)
            report.total_directives_generated += len(day_result.new_directives)
            
            print(f"✓ {len(day_result.feedback_events)} feedback events")
        
        # Compute summary statistics
        if report.learning_curve:
            report.initial_wrong_ratio = report.learning_curve[0].wrong_ratio
            report.final_wrong_ratio = report.learning_curve[-1].wrong_ratio
            report.wrong_ratio_improvement = report.initial_wrong_ratio - report.final_wrong_ratio
            
            report.initial_cross_team_score = report.learning_curve[0].cross_team_surfacing_avg
            report.final_cross_team_score = report.learning_curve[-1].cross_team_surfacing_avg
            report.cross_team_improvement = report.final_cross_team_score - report.initial_cross_team_score
        
        print()
        print("=" * 50)
        print("📊 Simulation Complete!")
        print(f"   Days simulated: {num_days}")
        print(f"   Total items: {report.total_items_processed}")
        print(f"   Total feedback: {report.total_feedback_events}")
        print(f"   Directives generated: {report.total_directives_generated}")
        print()
        print("📈 Learning Results:")
        print(f"   Wrong ratio: {report.initial_wrong_ratio:.1%} → {report.final_wrong_ratio:.1%} ({report.wrong_ratio_improvement:+.1%})")
        print(f"   Cross-team score: {report.initial_cross_team_score:.2f} → {report.final_cross_team_score:.2f} ({report.cross_team_improvement:+.2f})")
        print("=" * 50)
        
        return report
