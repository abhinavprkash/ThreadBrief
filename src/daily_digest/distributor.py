"""Digest distributor - posts to Slack channels and users."""

from typing import Optional

from .slack_client import SlackClient
from .config import DigestConfig
from .orchestrator import DigestOutput
from .agents.team_analyzer import TeamAnalysis
from .formatter import DigestFormatter
from .observability import logger


class DigestDistributor:
    """
    Distributes the digest to Slack with privacy-aware routing.
    
    Distribution targets:
    1. Main digest channel - Short summary (no cross-team sensitive info)
    2. Team-specific channels - Detailed breakdown for each team
    3. Leadership DMs - Executive summary with blockers and decisions
    """
    
    def __init__(
        self,
        slack_client: SlackClient,
        config: DigestConfig,
        formatter: Optional[DigestFormatter] = None
    ):
        self.client = slack_client
        self.config = config
        self.formatter = formatter or DigestFormatter()
    
    async def distribute(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> dict:
        """
        Distribute the digest to all targets.
        
        Args:
            output: DigestOutput from orchestrator
            team_analyses: Dict of team_name -> TeamAnalysis
        
        Returns:
            Dictionary with distribution results
        """
        results = {
            "main_post": None,
            "team_posts": {},
            "dms": [],
            "errors": [],
        }
        
        # 1. Post SHORT summary to main digest channel
        try:
            main_result = await self._post_main_digest(output, team_analyses)
            results["main_post"] = main_result
            logger.info(f"Posted main digest to {self.config.digest_channel}")
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
    
    async def _post_main_digest(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> dict:
        """Post SHORT summary to the main digest channel (no sensitive cross-team info)."""
        text, blocks = self.formatter.format_main_digest(output, team_analyses)
        
        return await self.client.post_message(
            channel=self.config.digest_channel,
            text=text,
            blocks=blocks,
        )
    
    async def _post_team_details(self, team_analysis: TeamAnalysis) -> dict:
        """Post detailed breakdown to the team's own channel."""
        # Get team's channel ID
        channel_id = self.config.channels.get(team_analysis.team_name)
        if not channel_id:
            logger.warning(f"No channel configured for team: {team_analysis.team_name}")
            return {"ok": False, "error": "no_channel_configured"}
        
        # Format detailed team content
        details = self.formatter.format_team_details(team_analysis)
        
        # Post as plain text (not blocks) to avoid Slack's 3000 char block limit
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
        """Send executive summary with blockers and decisions to leadership."""
        summary = self.formatter.format_leadership_dm(output, team_analyses)
        
        return await self.client.send_dm(
            user_id=user_id,
            text=summary,
        )
    
    async def preview(
        self, 
        output: DigestOutput,
        team_analyses: dict[str, TeamAnalysis],
    ) -> dict:
        """
        Generate preview of what would be posted (for testing).
        
        Returns formatted content without actually posting.
        """
        text, blocks = self.formatter.format_main_digest(output, team_analyses)
        
        team_details = {}
        for team_name, ta in team_analyses.items():
            team_details[team_name] = self.formatter.format_team_details(ta)
        
        leadership_dm = self.formatter.format_leadership_dm(output, team_analyses)
        
        return {
            "main_post": {
                "text": text,
                "blocks": blocks,
            },
            "team_details": team_details,
            "leadership_dm": leadership_dm,
        }
