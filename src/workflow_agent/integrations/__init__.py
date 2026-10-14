"""External systems behind small interfaces: a file-backed simulation and an HTTP client each.

Tools depend only on the interfaces (``OrderService``, ``CarrierService``), so switching from
the simulated data to real systems is configuration (``ORDERS_API_URL``, ``CARRIER_API_URL``),
not a code or workflow change.
"""
from .services import CarrierService, OrderService, build_services  # noqa: F401
