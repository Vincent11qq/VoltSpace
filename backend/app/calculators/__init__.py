"""Pure calculation modules for VoltSpace.

Every module in this package is free of web framework and database dependencies so
that the formulas can be unit tested directly and reused by other services.
"""

from .consumption import (
    ApplianceInput,
    MonthlyConsumption,
    calculate_consumption,
    calculate_total_consumption,
    daily_energy_kwh,
    monthly_energy_kwh,
    validate_appliance,
)

__all__ = [
    "ApplianceInput",
    "MonthlyConsumption",
    "calculate_consumption",
    "calculate_total_consumption",
    "daily_energy_kwh",
    "monthly_energy_kwh",
    "validate_appliance",
]
