"""Pre-deploy reality check (CashPilot-w58).

The catalog shows one generic earnings range per service. A user cannot tell,
before deploying, whether a service will work at all *in their situation* — and
several will not. They find out weeks later, when it has earned nothing.

This turns what we already know into a decision the user can actually make:
a verdict and one or two plain sentences, not a wall of warnings.

Two rules shape everything here:

* **Informed consent, not a nanny.** Where the answer is "this will earn nothing
  for you", say so plainly and let them deploy anyway. Nothing here blocks.
* **Never imply a check we did not run.** We cannot currently detect egress IP
  type or connection speed (that is CashPilot-5qc). Requirements that depend on
  those are reported as *unverified preconditions in the user's own words*,
  never as a pass. Claiming a green light we did not earn is worse than silence.
"""

from __future__ import annotations

from typing import Any

# Verdicts, worst first. The caller shows the worst one that applies.
EARNS_NOTHING = "will_earn_nothing"
REDUCED = "reduced_earnings"
CHECK_YOURSELF = "check_these"
LOOKS_FINE = "looks_fine"

_SEVERITY = {EARNS_NOTHING: 3, REDUCED: 2, CHECK_YOURSELF: 1, LOOKS_FINE: 0}


def _worst(verdicts: list[str]) -> str:
    return max(verdicts, key=lambda v: _SEVERITY[v], default=LOOKS_FINE)


def assess(
    service: dict[str, Any],
    *,
    already_deployed_slugs: set[str] | None = None,
    system_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer "what will this realistically do for me?" before the deploy runs.

    ``already_deployed_slugs`` is what is already running on the SAME worker,
    which is what makes a per-IP limit checkable at all.
    """
    already_deployed = already_deployed_slugs or set()
    info = system_info or {}
    reqs = service.get("requirements") or {}
    slug = service.get("slug", "")

    findings: list[dict[str, str]] = []
    verdicts: list[str] = []

    # Already running here. A second instance on one egress IP is the case
    # several providers forbid outright, and the penalty is a forfeited balance.
    if slug and slug in already_deployed:
        devices_per_ip = reqs.get("devices_per_ip")
        if devices_per_ip == 1:
            findings.append(
                {
                    "verdict": EARNS_NOTHING,
                    "message": (
                        f"{service.get('name', slug)} is already running on this machine, and it "
                        "allows only one device per IP. A second instance normally earns nothing, "
                        "and some providers forfeit the balance of accounts that do this."
                    ),
                }
            )
            verdicts.append(EARNS_NOTHING)
        else:
            findings.append(
                {
                    "verdict": REDUCED,
                    "message": (
                        f"{service.get('name', slug)} is already running on this machine. "
                        "A second instance shares the same connection, so expect the pair to earn "
                        "roughly what one already does."
                    ),
                }
            )
            verdicts.append(REDUCED)

    # Hardware the container cannot conjure.
    if reqs.get("gpu"):
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (
                    "This needs a supported GPU passed through to the container. Without one it "
                    "will start and then sit idle, earning nothing."
                ),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    min_storage = reqs.get("min_storage")
    if min_storage:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (
                    f"Needs at least {min_storage} of disk you can commit for months. Storage "
                    "payouts accrue slowly and part of the balance is held back and forfeited if "
                    "the node is abandoned early — running one for a month is worse than not "
                    "running it at all."
                ),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    # IP type. We cannot detect this yet, so it is stated as a precondition and
    # explicitly labelled unverified rather than dressed up as a check.
    if reqs.get("residential_ip") and reqs.get("vps_ip") is False:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (
                    "This needs a residential IP. On a VPS or datacentre connection it typically "
                    "earns far less, or the account is banned outright. CashPilot cannot check "
                    "your connection type, so this one is on you."
                ),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    min_bandwidth = reqs.get("min_bandwidth")
    if min_bandwidth:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (
                    f"Wants at least {min_bandwidth}. Below that it still runs, it just earns "
                    "proportionally less. CashPilot does not measure your connection."
                ),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    # A note the catalog author left specifically for this situation.
    note = reqs.get("note")
    if note:
        findings.append({"verdict": CHECK_YOURSELF, "message": str(note)})
        verdicts.append(CHECK_YOURSELF)

    verdict = _worst(verdicts)
    return {
        "slug": slug,
        "verdict": verdict,
        "summary": _summary(verdict, service),
        "findings": findings,
        # Say what was NOT checked, so a clean result is not mistaken for a
        # guarantee about things we never looked at.
        "not_checked": ["egress IP type", "connection speed", "available disk"],
        "worker_arch": info.get("arch"),
        "blocking": False,  # informed consent, never a block
    }


def _summary(verdict: str, service: dict[str, Any]) -> str:
    name = service.get("name") or service.get("slug") or "This service"
    if verdict == EARNS_NOTHING:
        return f"{name} will most likely earn nothing here. You can deploy it anyway."
    if verdict == REDUCED:
        return f"{name} will probably earn less here than the catalog range suggests."
    if verdict == CHECK_YOURSELF:
        return f"{name} should work, provided the points below are true of your setup."
    return f"Nothing stands out — {name} should work normally here."
