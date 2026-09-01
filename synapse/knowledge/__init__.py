"""Knowledge system — team designer, convergence detection, and knowledge orchestrator."""

from .artifacts import Artifact, ArtifactStore, compute_python
from .convergence import ConvergenceDetector
from .orchestrator import KnowledgeOrchestrator
from .team_designer import TeamDesigner

__all__ = [
    "Artifact",
    "ArtifactStore",
    "compute_python",
    "ConvergenceDetector",
    "KnowledgeOrchestrator",
    "TeamDesigner",
]
