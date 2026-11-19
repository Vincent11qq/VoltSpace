"""Service layer for VoltSpace.

Services combine the pure calculators with reference data (tariff plans, appliance
catalogue) and produce the payloads the FastAPI layer returns to the mobile app.
"""

from .recommendations import catalog_summary, generate_recommendations
from .simulation import SimulationError, simulate, what_if_reduction

__all__ = [
    "SimulationError",
    "catalog_summary",
    "generate_recommendations",
    "simulate",
    "what_if_reduction",
]
