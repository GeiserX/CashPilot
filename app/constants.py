"""Shared constants for CashPilot labels and container naming."""

import os

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


#: deployed-by values only CashPilot itself writes: "worker" by deploy_raw, and
#: "direct" by the deploy path before workers (removed in #85), whose containers
#: still run on old installs. "compose" is an exported file the user runs by hand.
CASHPILOT_DEPLOYED = frozenset({"worker", "direct"})


def drift_warnings_enabled() -> bool:
    """CASHPILOT_DRIFT_WARNINGS: off stops the worker reporting container settings
    and the UI judging them (app/drift.py). On unless set to 0, off, false or no."""
    return os.getenv("CASHPILOT_DRIFT_WARNINGS", "").strip().lower() not in {"0", "off", "false", "no"}
