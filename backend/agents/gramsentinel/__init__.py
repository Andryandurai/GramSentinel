"""GramSentinel — the community layer's eight agents.

Six signal agents (one per source type), a village trend agent, and a cluster
detection agent. Each signal agent sees only its own source and compares it
against that source's own baseline. They do not see each other's conclusions
before forming their own — that independence is what makes corroboration mean
something.
"""

from .signal_agents import (
    CHWSignalAgent,
    LabEvidenceAgent,
    PHCSignalAgent,
    PharmacySignalAgent,
    SchoolSignalAgent,
    WeatherSignalAgent,
    SIGNAL_AGENTS,
)
from .village_trend import VillageTrendAgent
from .cluster import ClusterDetectionAgent

__all__ = [
    "CHWSignalAgent",
    "PHCSignalAgent",
    "PharmacySignalAgent",
    "SchoolSignalAgent",
    "WeatherSignalAgent",
    "LabEvidenceAgent",
    "VillageTrendAgent",
    "ClusterDetectionAgent",
    "SIGNAL_AGENTS",
]
