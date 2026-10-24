"""VoltSpace backend calculation core (Member C).

This package is intentionally framework-light: the calculation modules under
``app.calculators`` and the services under ``app.services`` have no FastAPI or
database dependency, so they can be unit tested and reused.
"""

__version__ = "0.1.0"
