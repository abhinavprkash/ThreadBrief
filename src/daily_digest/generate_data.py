#!/usr/bin/env python3
"""
CLI wrapper for synthetic data generation.
This ensures the script runs from the correct directory.
"""

import argparse
import sys
from pathlib import Path


def cli():
    """CLI entry point for data generation."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic Slack conversation data with multi-day story arcs"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="Number of days to generate (default: 5)"
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=5,
        help="Number of channels to use (default: 5, max: 5)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/synthetic_conversations.json",
        help="Output file path (default: data/synthetic_conversations.json)"
    )
    
    args = parser.parse_args()
    
    # Get the project root directory (where pyproject.toml is)
    project_root = Path(__file__).parent.parent.parent
    scripts_dir = project_root / "scripts"
    
    # Change to project root to ensure pyproject.toml is found
    import os
    original_dir = os.getcwd()
    os.chdir(project_root)
    
    # Add scripts directory to path
    sys.path.insert(0, str(scripts_dir))
    
    try:
        # Import and run the generator
        from generate_synthetic_data import main as generate_main, parse_args as generate_parse_args
        
        # Create args for the generator
        gen_args = generate_parse_args([
            "--days", str(args.days),
            "--channels", str(args.channels),
            "--output", args.output
        ])
        
        print(f"📂 Running from: {project_root}")
        print(f"📄 Output will be saved to: {project_root / args.output}\n")
        
        generate_main(gen_args)
        
        print(f"\n✅ Data generation complete!")
        print(f"   File: {project_root / args.output}")
        
    finally:
        # Restore original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    cli()
