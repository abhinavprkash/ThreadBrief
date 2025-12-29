"""Dependency Graph - tracks cross-team dependencies."""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models.dependencies import Dependency, DependencyType


class DependencyGraph:
    """
    Graph structure for tracking cross-team dependencies.
    
    Provides:
    - Add/query dependencies between teams
    - Get all dependencies affecting a team
    - Track resolution status
    - Generate cross-team highlights
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(__file__).parent.parent.parent.parent / "data" / "memory"
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._graph_file = self.data_dir / "dependency_graph.json"
        
        self._load_graph()
    
    def _load_graph(self):
        """Load graph from file."""
        if self._graph_file.exists():
            with open(self._graph_file, "r") as f:
                data = json.load(f)
                self.edges = data.get("edges", [])
                self.nodes = set(data.get("nodes", []))
        else:
            self.edges = []
            self.nodes = set()
    
    def _save_graph(self):
        """Save graph to file."""
        with open(self._graph_file, "w") as f:
            json.dump({
                "edges": self.edges,
                "nodes": list(self.nodes),
            }, f, indent=2)
    
    def add_dependency(self, dependency: Dependency) -> str:
        """Add a dependency edge to the graph."""
        edge_id = f"dep_{len(self.edges)}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Add nodes
        self.nodes.add(dependency.from_team)
        self.nodes.add(dependency.to_team)
        
        # Create edge
        edge = {
            "edge_id": edge_id,
            "type": dependency.dependency_type.value,
            "from_team": dependency.from_team,
            "to_team": dependency.to_team,
            "what_changed": dependency.what_changed,
            "why_it_matters": dependency.why_it_matters,
            "recommended_action": dependency.recommended_action,
            "suggested_owner": dependency.suggested_owner,
            "urgency": dependency.urgency,
            "confidence": dependency.confidence,
            "created_at": datetime.now().isoformat(),
            "resolved": False,
        }
        
        self.edges.append(edge)
        self._save_graph()
        
        return edge_id
    
    def get_dependencies_for_team(
        self, 
        team: str, 
        direction: str = "both"
    ) -> list[dict]:
        """
        Get dependencies involving a team.
        
        Args:
            team: Team name to query
            direction: "from" (team depends on others), 
                      "to" (others depend on team),
                      "both" (all)
        """
        results = []
        
        for edge in self.edges:
            if edge.get("resolved"):
                continue
                
            if direction == "from" and edge.get("from_team") == team:
                results.append(edge)
            elif direction == "to" and edge.get("to_team") == team:
                results.append(edge)
            elif direction == "both" and (
                edge.get("from_team") == team or edge.get("to_team") == team
            ):
                results.append(edge)
        
        return results
    
    def get_active_dependencies(self) -> list[dict]:
        """Get all unresolved dependencies."""
        return [e for e in self.edges if not e.get("resolved")]
    
    def get_high_urgency_dependencies(self) -> list[dict]:
        """Get high urgency unresolved dependencies."""
        return [
            e for e in self.edges 
            if not e.get("resolved") and e.get("urgency") == "high"
        ]
    
    def resolve_dependency(self, edge_id: str) -> bool:
        """Mark a dependency as resolved."""
        for edge in self.edges:
            if edge.get("edge_id") == edge_id:
                edge["resolved"] = True
                edge["resolved_at"] = datetime.now().isoformat()
                self._save_graph()
                return True
        return False
    
    def get_cross_team_highlights(self, max_count: int = 5) -> list[str]:
        """
        Generate cross-team highlights for digest.
        
        Returns human-readable summaries of important dependencies.
        """
        highlights = []
        
        # High urgency dependencies first
        high_urgency = self.get_high_urgency_dependencies()
        for dep in high_urgency[:2]:
            highlights.append(
                f"🚨 {dep['from_team']} ↔ {dep['to_team']}: {dep['what_changed']}"
            )
        
        # Count by team pairs
        team_pairs = {}
        for edge in self.get_active_dependencies():
            pair = tuple(sorted([edge['from_team'], edge['to_team']]))
            team_pairs[pair] = team_pairs.get(pair, 0) + 1
        
        # Highlight frequent dependencies
        for pair, count in sorted(team_pairs.items(), key=lambda x: -x[1])[:3]:
            if count > 1:
                highlights.append(
                    f"📊 {pair[0]} & {pair[1]} have {count} active dependencies"
                )
        
        return highlights[:max_count]
    
    def get_team_dependency_count(self) -> dict[str, dict[str, int]]:
        """
        Get dependency counts per team.
        
        Returns dict like:
        {"team_a": {"blocking": 2, "waiting_on": 1}, ...}
        """
        counts = {}
        
        for edge in self.get_active_dependencies():
            team = edge.get("from_team")
            dep_type = edge.get("type")
            
            if team not in counts:
                counts[team] = {}
            
            counts[team][dep_type] = counts[team].get(dep_type, 0) + 1
        
        return counts
    
    def add_dependencies_bulk(self, dependencies: list[Dependency]) -> list[str]:
        """Add multiple dependencies at once."""
        edge_ids = []
        for dep in dependencies:
            edge_id = self.add_dependency(dep)
            edge_ids.append(edge_id)
        return edge_ids
