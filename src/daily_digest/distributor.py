"""Digest distributor - posts to Slack channels and users."""

from datetime import datetime
from typing import Optional

from .slack_client import SlackClient
from .config import DigestConfig
from .orchestrator import DigestOutput
from .agents.team_analyzer import TeamAnalysis
from .formatter import DigestFormatter, DigestItemMessage
from .observability import logger

# Optional feedback store import - graceful degradation if not configured
try:
    from .feedback import FeedbackStore
    from .feedback.feedback_store import DigestItem
    FEEDBACK_AVAILABLE = True
except ImportError:
    FEEDBACK_AVAILABLE = False

# Optional personalization import - graceful degradation if not configured
try:
    from .personalization import DigestRanker, PersonaManager
    PERSONALIZATION_AVAILABLE = True
except ImportError:
    PERSONALIZATION_AVAILABLE = False


class DigestDistributor:
    """
    Distributes the digest to Slack with privacy-aware routing.
    
    Distribution targets:
    1. Main digest channel - Header + individual item messages (for feedback)
    2. Team-specific channels - Detailed breakdown for each team
    3. Leadership DMs - Executive summary with blockers and decisions
    
    Each digest item is posted as a separate message for clean feedback mapping:
    message_ts -> digest_item_id
    """
    
    def __init__(
        self,
        slack_client: SlackClient,
        config: DigestConfig,
        formatter: Optional[DigestFormatter] = None,
        feedback_store: Optional["FeedbackStore"] = None,
    ):
        self.client = slack_client
        self.config = config
        self.formatter = formatter or DigestFormatter()
        self.feedback_store = feedback_store
        
        # Initialize personalization components if available
        if PERSONALIZATION_AVAILABLE and feedback_store:
            self.persona_manager = PersonaManager()  # PersonaManager doesn't need feedback_store
            self.ranker = DigestRanker(feedback_store, self.persona_manager)
        else:
            self.persona_manager = None
            self.ranker = None
    
    async def distribute(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
        run_id: Optional[str] = None,
        item_confidences: Optional[dict[str, float]] = None,
    ) -> dict:
        """
        Distribute the digest to all targets.
        
        Each digest item is posted as a separate message for feedback tracking.
        
        Args:
            output: DigestOutput from orchestrator
            team_analyses: Dict of team_name -> TeamAnalysis
            run_id: Unique identifier for this digest run
            item_confidences: Optional confidence overrides from feedback processor
        
        Returns:
            Dictionary with distribution results including message_ts mappings
        """
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        results = {
            "run_id": run_id,
            "main_post": None,
            "item_posts": [],  # Individual item message results
            "team_posts": {},
            "dms": [],
            "errors": [],
            "items_stored": 0,
        }
        
        # 1. Post header + individual items to main digest channel
        try:
            main_results = await self._post_main_digest_with_items(
                output, team_analyses, run_id, item_confidences
            )
            results["main_post"] = main_results.get("header")
            results["item_posts"] = main_results.get("items", [])
            results["items_stored"] = main_results.get("items_stored", 0)
            logger.info(
                f"Posted main digest to {self.config.digest_channel} "
                f"({len(results['item_posts'])} items)"
            )
        except Exception as e:
            error = f"Failed to post main digest: {e}"
            results["errors"].append(error)
            logger.error(error)
        
        # 2. Post DETAILED breakdown to each team's channel
        for team_name, team_analysis in team_analyses.items():
            try:
                team_result = await self._post_team_details(team_analysis)
                results["team_posts"][team_name] = team_result
                logger.info(f"Posted details to {team_name} channel")
            except Exception as e:
                error = f"Failed to post to {team_name}: {e}"
                results["errors"].append(error)
                logger.error(error)
        
        # 3. DM leadership with executive summary
        for user_id in self.config.leadership_users:
            try:
                dm_result = await self._send_leadership_dm(output, team_analyses, user_id)
                results["dms"].append({"user": user_id, "result": dm_result})
                logger.info(f"Sent DM to {user_id}")
            except Exception as e:
                error = f"Failed to DM {user_id}: {e}"
                results["errors"].append(error)
                logger.error(error)
        
        return results
    
    async def _post_main_digest_with_items(
        self,
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
        run_id: str,
        item_confidences: Optional[dict[str, float]] = None,
    ) -> dict:
        """
        Post header + individual item messages to main digest channel.
        
        Returns dict with header result and list of item results with message_ts.
        """
        channel = self.config.digest_channel
        results = {"header": None, "items": [], "items_stored": 0}
        
        # 1. Post header message first
        header_text, header_blocks = self.formatter.format_header_message(output, team_analyses)
        header_result = await self.client.post_message(
            channel=channel,
            text=header_text,
            blocks=header_blocks,
        )
        results["header"] = header_result
        
        # 2. Get formatted items grouped by confidence
        high_conf, low_conf, excluded = self.formatter.format_digest_items(
            team_analyses, run_id, item_confidences
        )
        
        logger.info(
            f"Posting {len(high_conf)} high-confidence, {len(low_conf)} low-confidence items "
            f"({len(excluded)} excluded)"
        )
        
        # 3. Post high confidence items
        for item_msg in high_conf:
            try:
                result = await self.client.post_message(
                    channel=channel,
                    text=item_msg.text,
                    blocks=item_msg.blocks,
                )
                
                # Store item with message_ts for feedback tracking
                if self.feedback_store and result.get("ok"):
                    self._store_digest_item(item_msg, result.get("ts", ""), channel, run_id)
                    results["items_stored"] += 1
                
                results["items"].append({
                    "digest_item_id": item_msg.digest_item_id,
                    "message_ts": result.get("ts"),
                    "ok": result.get("ok"),
                    "confidence": item_msg.confidence,
                    "section": "main",
                })
            except Exception as e:
                logger.warning(f"Failed to post item {item_msg.digest_item_id}: {e}")
        
        # 4. Post low confidence section header if there are items
        if low_conf:
            await self.client.post_message(
                channel=channel,
                text="📋 Lower Confidence / FYI",
                blocks=[{
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*📋 Lower Confidence / FYI*\n_These items may need verification:_"}
                }]
            )
            
            # Post low confidence items
            for item_msg in low_conf:
                try:
                    result = await self.client.post_message(
                        channel=channel,
                        text=item_msg.text,
                        blocks=item_msg.blocks,
                    )
                    
                    if self.feedback_store and result.get("ok"):
                        self._store_digest_item(item_msg, result.get("ts", ""), channel, run_id)
                        results["items_stored"] += 1
                    
                    results["items"].append({
                        "digest_item_id": item_msg.digest_item_id,
                        "message_ts": result.get("ts"),
                        "ok": result.get("ok"),
                        "confidence": item_msg.confidence,
                        "section": "fyi",
                    })
                except Exception as e:
                    logger.warning(f"Failed to post FYI item {item_msg.digest_item_id}: {e}")
        
        return results
    
    def _store_digest_item(
        self,
        item_msg: DigestItemMessage,
        message_ts: str,
        channel_id: str,
        run_id: str,
    ):
        """Store digest item in feedback store for feedback tracking."""
        if not self.feedback_store or not FEEDBACK_AVAILABLE:
            return
        
        digest_item = DigestItem(
            digest_item_id=item_msg.digest_item_id,
            run_id=run_id,
            date=datetime.now().strftime("%Y-%m-%d"),
            team=item_msg.team,
            item_type=item_msg.item_type,
            title=item_msg.title,
            summary=item_msg.text,
            confidence=item_msg.confidence,
            slack_message_ts=message_ts,
            slack_channel_id=channel_id,
        )
        self.feedback_store.store_digest_item(digest_item)
    
    async def _post_team_details(self, team_analysis: TeamAnalysis) -> dict:
        """Post detailed breakdown to the team's own channel."""
        channel_id = self.config.channels.get(team_analysis.team_name)
        if not channel_id:
            logger.warning(f"No channel configured for team: {team_analysis.team_name}")
            return {"ok": False, "error": "no_channel_configured"}
        
        details = self.formatter.format_team_details(team_analysis)
        
        return await self.client.post_message(
            channel=channel_id,
            text=details,
        )
    
    async def _send_leadership_dm(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
        user_id: str,
    ) -> dict:
        """
        Send personalized executive summary to leadership.
        
        Uses DigestRanker to rank items based on user's persona (role, team).
        Falls back to standard formatting if personalization is not available.
        """
        # Try personalized ranking if available
        if self.ranker and self.feedback_store and FEEDBACK_AVAILABLE:
            personalized_content = self._create_personalized_dm(
                output, team_analyses, user_id
            )
            if personalized_content:
                return await self.client.send_dm(
                    user_id=user_id,
                    text=personalized_content,
                )
        
        # Fall back to standard format
        summary = self.formatter.format_leadership_dm(output, team_analyses)
        
        return await self.client.send_dm(
            user_id=user_id,
            text=summary,
        )
    
    def _create_personalized_dm(
        self,
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
        user_id: str,
    ) -> Optional[str]:
        """
        Create a personalized DM using the ranker.
        
        Converts team analyses to DigestItems, ranks them by persona,
        and formats the top items for the user.
        """
        if not self.ranker or not FEEDBACK_AVAILABLE:
            return None
        
        # Get user persona
        user_persona = None
        if self.feedback_store:
            user_config = self.feedback_store.get_user_persona(user_id)
            if user_config:
                user_role = user_config.get("role", "lead")
                user_team = user_config.get("team", "general")
            else:
                # Default leadership to "lead" role
                user_role = "lead"
                user_team = "general"
        else:
            user_role = "lead"
            user_team = "general"
        
        # Extract items from team analyses
        digest_items = []
        for team_name, ta in team_analyses.items():
            # Blockers
            for i, blocker in enumerate(ta.blockers):
                item = DigestItem(
                    digest_item_id=f"blocker_{team_name}_{i}",
                    run_id="live",
                    date=output.global_digest.date,
                    team=team_name,
                    item_type="blocker",
                    title=blocker.get("issue", "Unknown blocker"),
                    summary=blocker.get("issue", ""),
                    severity=blocker.get("severity", "medium"),
                    confidence=0.9,
                    owners=[blocker.get("owner")] if blocker.get("owner") else [],
                )
                digest_items.append(item)
            
            # Decisions
            for i, decision in enumerate(ta.decisions):
                item = DigestItem(
                    digest_item_id=f"decision_{team_name}_{i}",
                    run_id="live",
                    date=output.global_digest.date,
                    team=team_name,
                    item_type="decision",
                    title=decision.get("decision", "Unknown decision"),
                    summary=decision.get("decision", ""),
                    confidence=0.85,
                )
                digest_items.append(item)
            
            # Action items
            for i, action in enumerate(ta.action_items):
                item = DigestItem(
                    digest_item_id=f"action_{team_name}_{i}",
                    run_id="live",
                    date=output.global_digest.date,
                    team=team_name,
                    item_type="action_item",
                    title=action.get("action", "Unknown action"),
                    summary=action.get("action", ""),
                    confidence=0.8,
                    owners=[action.get("owner")] if action.get("owner") else [],
                )
                digest_items.append(item)
        
        if not digest_items:
            return None
        
        # Rank items for this user
        ranked_items = self.ranker.rank_items(
            digest_items,
            user_id=user_id,
            team=user_team,
            role=user_role,
        )
        
        # Partition by confidence
        high_items, low_items, _ = self.ranker.partition_by_confidence(ranked_items)
        
        # Format personalized digest
        lines = [
            f"*📰 Personalized Digest - {output.global_digest.date}*",
            f"_Ranked for your role ({user_role}) and focus areas_",
            "",
        ]
        
        # Top priority items (cross-team first)
        cross_team = [r for r in high_items if r.is_cross_team]
        if cross_team:
            lines.append("*🔗 Cross-Team (Priority):*")
            for r in cross_team[:3]:
                icon = {"blocker": "🚨", "decision": "✅", "action_item": "⚡"}.get(
                    r.item.item_type, "📝"
                )
                lines.append(f"{icon} *[{r.item.team.upper()}]* {r.item.title}")
            lines.append("")
        
        # Key blockers
        blockers = [r for r in high_items if r.item.item_type == "blocker"][:4]
        if blockers:
            lines.append("*🚨 Key Blockers:*")
            for r in blockers:
                cross = " 🔗" if r.is_cross_team else ""
                lines.append(f"• *[{r.item.team.upper()}]*{cross} {r.item.title}")
            lines.append("")
        
        # Key decisions
        decisions = [r for r in high_items if r.item.item_type == "decision"][:3]
        if decisions:
            lines.append("*✅ Decisions:*")
            for r in decisions:
                lines.append(f"• *[{r.item.team.upper()}]* {r.item.title}")
            lines.append("")
        
        # Action items
        actions = [r for r in high_items if r.item.item_type == "action_item"][:3]
        if actions:
            lines.append("*⚡ Action Items:*")
            for r in actions:
                owner = r.item.owners[0] if r.item.owners else "TBD"
                lines.append(f"• *[{r.item.team.upper()}]* {r.item.title} → {owner}")
            lines.append("")
        
        # Add "Why you got this" rationale for top 3 items (A2)
        top_3 = ranked_items[:3]
        if top_3:
            lines.append("*💡 Why These Are Your Top 3:*")
            for i, r in enumerate(top_3, 1):
                rationale = self._explain_ranking(r, user_role, user_team)
                lines.append(f"{i}. _{rationale}_")
            lines.append("")
        
        # Summary stats
        lines.append(f"_📊 {len(high_items)} high-priority | {len(low_items)} lower-priority items_")
        
        return "\n".join(lines)
    
    def _explain_ranking(self, ranked_item, user_role: str, user_team: str) -> str:
        """Generate a short rationale for why this item was ranked highly."""
        reasons = []
        
        if ranked_item.is_cross_team:
            reasons.append("cross-team")
        
        item_type = ranked_item.item.item_type
        if item_type == "blocker":
            reasons.append("blocker")
        elif item_type == "decision":
            reasons.append("decision")
        elif item_type == "action_item":
            reasons.append("action needed")
        
        if ranked_item.item.team.lower() == user_team.lower():
            reasons.append(f"your team ({user_team})")
        
        if user_role == "lead" and item_type in ["blocker", "decision"]:
            reasons.append("lead focus")
        elif user_role == "ic" and item_type == "action_item":
            reasons.append("IC focus")
        
        if ranked_item.item.severity == "high":
            reasons.append("high severity")
        
        if not reasons:
            reasons.append("relevance score")
        
        return f"Boosted: {' + '.join(reasons[:3])}"
    
    async def preview(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
        run_id: Optional[str] = None,
        item_confidences: Optional[dict[str, float]] = None,
    ) -> dict:
        """
        Generate preview of what would be posted (for testing).
        
        Returns formatted content without actually posting.
        """
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get header
        header_text, header_blocks = self.formatter.format_header_message(output, team_analyses)
        
        # Get items grouped by confidence
        high_conf, low_conf, excluded = self.formatter.format_digest_items(
            team_analyses, run_id, item_confidences
        )
        
        # Legacy format for backward compatibility
        text, blocks = self.formatter.format_main_digest(output, team_analyses)
        
        team_details = {}
        for team_name, ta in team_analyses.items():
            team_details[team_name] = self.formatter.format_team_details(ta)
        
        leadership_dm = self.formatter.format_leadership_dm(output, team_analyses)
        
        return {
            "run_id": run_id,
            "main_post": {
                "text": text,
                "blocks": blocks,
            },
            "header": {
                "text": header_text,
                "blocks": header_blocks,
            },
            "high_confidence_items": [
                {"id": m.digest_item_id, "text": m.text, "confidence": m.confidence}
                for m in high_conf
            ],
            "low_confidence_items": [
                {"id": m.digest_item_id, "text": m.text, "confidence": m.confidence}
                for m in low_conf
            ],
            "excluded_items": excluded,
            "team_details": team_details,
            "leadership_dm": leadership_dm,
        }

