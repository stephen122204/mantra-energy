"""
core/network/interfaces.py
Abstract interface for network wait energy estimation.

Every concrete estimator returns a 5-tuple:
    (energy_uj, method_id, confidence, measurement_type, coverage_fraction)

energy_uj is None when measurement is impossible (MIC-3: NULL not zero).
coverage_fraction indicates what fraction of requested windows had energy data.

PAC-1: ABCs defined here. Concrete imports only in factory.py (PAC-2).
"""

import abc
from typing import List, Optional, Tuple

# Return type alias — used by all strategy implementations
# (energy_uj, method_id, confidence, measurement_type, coverage_fraction)
NetworkEnergyResult = Tuple[Optional[int], str, float, str, float]


class NetworkEnergyEstimatorABC(abc.ABC):
    """
    Base class for all network wait energy estimators.

    Each platform provides a concrete subclass selected at runtime
    by NetworkEstimatorFactory based on NIC topology detection.

    Subclasses MUST NOT perform platform-conditional imports (PAC-2).
    All platform-conditional imports live in core/network/factory.py only.
    """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """
        Check if this estimator can operate on the current platform.

        Returns True if all required energy sources are accessible.
        Never raises — graceful degradation (PAC-4).
        """
        ...

    @abc.abstractmethod
    def get_method_id(self) -> str:
        """Return the provenance method_id for this strategy."""
        ...

    @abc.abstractmethod
    def estimate(
        self,
        run_id: int,
        windows: List[dict],
        db_conn: "sqlite3.Connection",
    ) -> NetworkEnergyResult:
        """
        Estimate energy consumed during network blocking windows.

        Each window dict has keys:
            request_start_ns: int   — start of LLM blocking period
            first_token_time_ns: int — end of blocking (first token received)
            non_local_ms: float     — duration in milliseconds

        Args:
            run_id:   The run to attribute energy for.
            windows:  List of blocking window dicts from llm_interactions.
            db_conn:  Open SQLite connection (EEI: estimator reads, does not open).

        Returns:
            NetworkEnergyResult 5-tuple. energy_uj is None if unmeasurable.
        """
        ...
