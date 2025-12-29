"""Main entry point for the Daily Digest pipeline."""

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from .config import get_config, DigestConfig
from .slack_client import SlackClient
from .orchestrator import DigestOrchestrator
from .formatter import DigestFormatter
from .distributor import DigestDistributor
from .state import DigestState, DigestRun
from .observability import logger


async def run_digest(
    mock: bool = False,
    preview_only: bool = False,
    config: DigestConfig = None,
) -> dict:
    """
    Main entry point for digest generation.
    
    Args:
        mock: Use mock Slack client with fixtures
        preview_only: Generate digest but don't post
        config: Optional config override
        
    Returns:
        Dictionary with pipeline results
    """
    # Initialize config
    if mock and config is None:
        config = DigestConfig(
            channels={
                "mechanical": "C_MECHANICAL",
                "electrical": "C_ELECTRICAL",
                "software": "C_SOFTWARE",
            },
            digest_channel="C_DIGEST",
            leadership_users=["U_LEAD_1"],
        )
        logger.info("Using mock configuration with fixture channel IDs")
    else:
        config = config or get_config()
    
    # Determine fixture path
    fixture_path = None
    if mock:
        fixture_path = str(Path(__file__).parent.parent.parent / "fixtures" / "slack_mock.json")
        logger.info(f"Using mock client with fixtures: {fixture_path}")
    
    slack_client = SlackClient(mock_data_path=fixture_path)
    
    # Initialize state tracking (skip in mock mode)
    state = None if mock else DigestState()
    
    # Determine since timestamp
    if mock:
        since = datetime(2023, 12, 1)
        logger.info(f"Mock mode: Fetching messages since {since}")
    elif state:
        since = state.get_last_run()
        if since:
            logger.info(f"Stateful mode: Fetching messages since last run at {since.isoformat()}")
        else:
            logger.info("No previous run found, fetching all messages within lookback window")
    else:
        since = None
    
    # Track run info for state
    run_timestamp = datetime.now()
    run_id = run_timestamp.strftime("%Y%m%d_%H%M%S")
    
    try:
        # Create orchestrator
        orchestrator = DigestOrchestrator(config=config, mock_mode=mock)
        
        # Run the pipeline
        logger.info("Running digest pipeline...")
        output = await orchestrator.run(slack_client, since)
        
        logger.info(f"Generated digest with {len(output.team_analyses)} team analyses")
        
        # Format and distribute
        formatter = DigestFormatter()
        distributor = DigestDistributor(slack_client, config, formatter)
        
        if preview_only:
            logger.info("Preview mode - not posting to Slack")
            result = await distributor.preview(output, output.team_analyses)
            _print_preview(result)
        else:
            logger.info("Distributing digest...")
            result = await distributor.distribute(output, output.team_analyses)
            
            if result.get("errors"):
                logger.warning(f"Distribution completed with {len(result['errors'])} errors")
            else:
                logger.info("Distribution completed successfully")
                
                # Save successful run to state (advance timestamp)
                if state:
                    channels_processed = list(output.team_analyses.keys())
                    message_counts = {
                        name: analysis.message_count 
                        for name, analysis in output.team_analyses.items()
                    }
                    run = DigestRun(
                        run_id=run_id,
                        timestamp=run_timestamp.isoformat(),
                        channels_processed=channels_processed,
                        message_counts=message_counts,
                        success=True,
                    )
                    state.save_run(run)
                    logger.info(f"State saved: next run will fetch messages after {run_timestamp.isoformat()}")
        
        return {
            "success": True,
            "output": output,
            "distribution": result if not preview_only else None,
        }
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def _print_preview(result: dict):
    """Print preview output to console."""
    print("\n" + "=" * 60)
    print("DIGEST PREVIEW")
    print("=" * 60)
    
    print("\n--- MAIN POST ---")
    print(f"Text: {result['main_post']['text']}")
    print(f"Blocks: {len(result['main_post']['blocks'])} blocks")
    
    for i, block in enumerate(result['main_post']['blocks'][:10]):
        block_type = block.get('type', 'unknown')
        if block_type == 'section':
            text = block.get('text', {}).get('text', '')[:100]
            print(f"  [{i}] section: {text}...")
        elif block_type == 'header':
            text = block.get('text', {}).get('text', '')
            print(f"  [{i}] header: {text}")
        else:
            print(f"  [{i}] {block_type}")
    
    print("\n--- TEAM DETAILS ---")
    for team_name, details in result.get('team_details', {}).items():
        print(f"\n[{team_name}]")
        print(details[:500] + "..." if len(details) > 500 else details)
    
    print("\n--- LEADERSHIP DM ---")
    print(result['leadership_dm'][:1000] + "..." if len(result['leadership_dm']) > 1000 else result['leadership_dm'])
    print("=" * 60)


def cli():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate and distribute daily team digest from Slack"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock Slack client with fixture data"
    )
    parser.add_argument(
        "--preview",
        action="store_true", 
        help="Generate digest but don't post to Slack"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        import logging
        logging.getLogger("daily_digest").setLevel(logging.DEBUG)
    
    result = asyncio.run(run_digest(
        mock=args.mock,
        preview_only=args.preview,
    ))
    
    if result["success"]:
        print("\n✅ Digest generated successfully!")
    else:
        print(f"\n❌ Digest generation failed: {result.get('error')}")
        exit(1)


if __name__ == "__main__":
    cli()
