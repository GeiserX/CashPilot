"""Shared constants for CashPilot labels and container naming."""

LABEL_SERVICE = "cashpilot.service"
LABEL_MANAGED = "cashpilot.managed"
LABEL_VERSION = "cashpilot.version"
LABEL_CATEGORY = "cashpilot.category"
LABEL_DEPLOYED_BY = "cashpilot.deployed-by"
# Which copy of a service a container is, on a worker that runs more than one.
# Absent on the first, which keeps the name it always had (cashpilot-<slug>);
# copy N is cashpilot-<slug>-N and carries "N" here.
LABEL_INSTANCE = "cashpilot.instance"
# The most copies of one service a worker will run. A ceiling against a typo,
# not a recommendation: on one connection most providers pay for one.
MAX_INSTANCES = 10
CONTAINER_PREFIX = "cashpilot-"

# Catalog statuses that must never be deployed or exported: the service is
# gone, broken, or dropped, and producing a runnable artifact for it points
# users at something that cannot earn. One definition, shared by the deploy
# routes and the compose exporter, so the rule cannot half-change.
UNDEPLOYABLE_STATUSES = frozenset({"broken", "dead", "dropped"})
