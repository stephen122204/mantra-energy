"""
================================================================================
REPOSITORIES — Domain-specific database operation classes
================================================================================

Each repository owns one logical domain:
    RunsRepository        — runs table (80+ column insert, stats update)
    EventsRepository      — orchestration_events table
    SamplesRepository     — energy_samples, cpu_samples, interrupt_samples
    TaxRepository         — tax_summaries table
    ThermalRepository     — thermal_samples table
    MethodologyRepository — measurement_method_registry, method_references,
                            measurement_methodology (Chunk 9)

DatabaseManager is the only caller of these repositories.
Never import repositories directly outside of manager.py.
================================================================================
"""

from .events      import EventsRepository
from .methodology import MethodologyRepository
from .runs        import RunsRepository
from .samples     import SamplesRepository
from .tax         import TaxRepository
from .thermal     import ThermalRepository

__all__ = [
    "EventsRepository",
    "MethodologyRepository",
    "RunsRepository",
    "SamplesRepository",
    "TaxRepository",
    "ThermalRepository",
]
