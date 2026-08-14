"""Shared constants for CashPilot labels and container naming."""

LABEL_SERVICE = "cashpilot.service"
LABEL_MANAGED = "cashpilot.managed"
LABEL_VERSION = "cashpilot.version"
LABEL_CATEGORY = "cashpilot.category"
LABEL_DEPLOYED_BY = "cashpilot.deployed-by"
CONTAINER_PREFIX = "cashpilot-"

# Catalog statuses that must never be deployed or exported: the service is
# gone, broken, or dropped, and producing a runnable artifact for it points
# users at something that cannot earn. One definition, shared by the deploy
# routes and the compose exporter, so the rule cannot half-change.
UNDEPLOYABLE_STATUSES = frozenset({"broken", "dead", "dropped"})
