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

from app import arch, catalog, egress, gpu
from app.i18n import t

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
    worker: dict[str, Any] | None = None,
    fleet_workers: list[dict[str, Any]] | None = None,
    also_deploying_to: set[Any] | None = None,
    replacing: bool = False,
) -> dict[str, Any]:
    """Answer "what will this realistically do for me?" before the deploy runs.

    ``replacing`` says the deploy replaces the copies of this service already
    running on this worker rather than adding one (a redeploy, the Fleet move,
    an imported draft): those are not a second device, so they are not counted.

    ``already_deployed_slugs`` is what is already running on the SAME worker,
    which is what makes a per-IP limit checkable at all.

    ``also_deploying_to`` is the set of worker ids receiving this service in the
    SAME action. Without it the cross-machine check only sees what is already
    running, so ticking two boxes behind one connection in the wizard produced
    no warning at all: neither worker had the service yet, so neither counted
    against the other. The warning then appeared the NEXT time, after the
    account was already at risk (CashPilot-3tr).

    ``worker`` and ``fleet_workers`` add the cross-machine half (CashPilot-5qc):
    providers cap per IP, so a sibling worker behind the same public address
    counts against the same limit. Omit them and the assessment degrades to the
    single-machine checks and keeps saying that the egress IP was not examined.
    """
    already_deployed = already_deployed_slugs or set()
    # Derived from the worker when not passed explicitly. Reading this from a
    # separate kwarg while the fleet half read worker["system_info"] meant the
    # SAME worker produced different verdicts depending on whether the caller
    # remembered a redundant argument.
    info = system_info if system_info is not None else ((worker or {}).get("system_info") or {})
    if not isinstance(info, dict):
        info = {}
    reqs = service.get("requirements") or {}
    slug = service.get("slug", "")

    findings: list[dict[str, str]] = []
    verdicts: list[str] = []

    # Already running here. A second instance on one egress IP is the case
    # several providers forbid outright, and the penalty is a forfeited balance.
    if slug and slug in already_deployed and not replacing:
        devices_per_ip = reqs.get("devices_per_ip")
        if devices_per_ip == 1:
            findings.append(
                {
                    "verdict": EARNS_NOTHING,
                    "message": (t("preflight.already_running_machine_allows_only", name=service.get("name", slug))),
                }
            )
            verdicts.append(EARNS_NOTHING)
        elif catalog.mining_facts(service):
            findings.append(
                {
                    "verdict": REDUCED,
                    "message": (
                        t("preflight.already_running_gpu", name=service.get("name", slug))
                        if reqs.get("gpu") is True
                        else t("preflight.already_running_cpu", name=service.get("name", slug))
                    ),
                }
            )
            verdicts.append(REDUCED)
        else:
            findings.append(
                {
                    "verdict": REDUCED,
                    "message": (t("preflight.already_running_machine_second_instance", name=service.get("name", slug))),
                }
            )
            verdicts.append(REDUCED)

    # The provider forbids the very thing CashPilot does. This outranks every
    # other finding: the outcome is not "earns less", it is a terminated account
    # with the pending balance cancelled, and CashPilot deploying it as a
    # container is itself the violation. Saying nothing here would be the worst
    # possible silence, because the tool causes the breach on the user's behalf.
    if reqs.get("container_prohibited"):
        findings.append(
            {
                "verdict": EARNS_NOTHING,
                "message": (t("preflight.provider_forbids_running_software_docker")),
            }
        )
        verdicts.append(EARNS_NOTHING)

    # Hardware the container cannot conjure.
    gpu_findings = _gpu_findings(service, info, already_deployed - {slug} if worker is not None else set())
    for finding in gpu_findings:
        findings.append(finding)
        verdicts.append(finding["verdict"])

    min_storage = reqs.get("min_storage")
    if min_storage:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (t("preflight.needs_least_disk_you_can", min_storage=min_storage)),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    # IP type. Since CashPilot-5qc a worker can sometimes identify itself as a
    # hosted machine, which turns a precondition into a real finding. When it
    # cannot, this stays an explicitly unverified precondition rather than being
    # dressed up as a check.
    if reqs.get("residential_ip") and catalog.vps_allowed(reqs) is False:
        if egress.normalise_network_type(info.get("egress_network_type")) == egress.HOSTING:
            findings.append(
                {
                    "verdict": EARNS_NOTHING,
                    "message": (t("preflight.machine_identifies_itself_hosted_vps")),
                }
            )
            verdicts.append(EARNS_NOTHING)
        else:
            findings.append(
                {
                    "verdict": CHECK_YOURSELF,
                    "message": (t("preflight.needs_residential_ip_vps_datacentre")),
                }
            )
            verdicts.append(CHECK_YOURSELF)

    hosting_note = reqs.get("hosting_note")
    if hosting_note and egress.normalise_network_type(info.get("egress_network_type")) == egress.HOSTING:
        findings.append({"verdict": CHECK_YOURSELF, "message": hosting_note, "kind": "hosting_note"})
        verdicts.append(CHECK_YOURSELF)

    min_bandwidth = reqs.get("min_bandwidth")
    if min_bandwidth:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (t("preflight.wants_least_below_still_runs", min_bandwidth=min_bandwidth)),
            }
        )
        verdicts.append(CHECK_YOURSELF)

    # A note the catalog author left specifically for this situation.
    note = reqs.get("note")
    if note:
        findings.append({"verdict": CHECK_YOURSELF, "message": str(note)})
        verdicts.append(CHECK_YOURSELF)

    # Does the provider publish a build for this CPU at all? The catalog's
    # platforms field used to be a badge nobody read; a Raspberry Pi user could
    # deploy an amd64-only image and get a container that died with "exec
    # format error" and a red row that explained nothing. The worker reports
    # platform.machine() in its heartbeat, so this is checkable, and a wrong
    # answer here is not "earns less" but "never starts", so it gets the top
    # verdict. Emulation (Docker Desktop with Rosetta, binfmt/qemu) makes such
    # an image run anyway; the worker cannot see the host's binfmt from inside
    # its container, so that is stated as unchecked rather than guessed.
    docker_conf = service.get("docker") or {}
    machine = info.get("arch")
    fam = arch.family(machine)
    verdict_for_cpu = arch.supports(docker_conf, machine) if docker_conf.get("image") else None
    arch_checked = verdict_for_cpu is not None
    if verdict_for_cpu is False:
        have = arch.describe_builds(docker_conf)
        findings.append(
            {
                "verdict": EARNS_NOTHING,
                "message": (
                    t(
                        "preflight.machine_publishes_no_build_only",
                        fam=arch.label(fam),
                        machine=machine,
                        name=service.get("name", slug),
                        have=have,
                    )
                ),
            }
        )
        verdicts.append(EARNS_NOTHING)

    # The cross-machine half: what the REST of the fleet implies about this.
    for finding in _fleet_findings(
        service,
        worker=worker,
        fleet_workers=fleet_workers,
        also_deploying_to=also_deploying_to,
        replacing=replacing,
    ):
        findings.append(finding)
        verdicts.append(finding["verdict"])

    verdict = _worst(verdicts)
    not_checked = ["connection speed", "available disk"]
    # Gated on the connection TYPE, not on the address. Knowing the IP says
    # nothing about whether it is residential, and dropping the label because we
    # learned the address produced a response that claimed the type was checked
    # while a finding in the same payload said it could not be.
    # Read from `info`, the same source the residential finding uses. Gating this
    # on the worker while that finding reads the kwarg is exactly the two-source
    # divergence this function was just fixed to remove, mirrored.
    if egress.normalise_network_type(info.get("egress_network_type")) == egress.UNKNOWN:
        not_checked.insert(0, "egress IP type")
    if docker_conf.get("image") and not arch_checked:
        # An old worker sends no arch, an unusual CPU folds to nothing, or the
        # entry declares no platforms. Say so instead of implying a pass.
        not_checked.append("whether the image has a build for this CPU")
    summary = _summary(verdict, service)
    if any(finding["verdict"] == EARNS_NOTHING for finding in gpu_findings):
        summary = "The worker will refuse this deploy because it cannot provide the required GPU."
    return {
        "slug": slug,
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        # Say what was NOT checked, so a clean result is not mistaken for a
        # guarantee about things we never looked at.
        "not_checked": not_checked,
        "worker_arch": info.get("arch"),
        "blocking": False,  # informed consent, never a block
    }


#: The key of the finding for a GPU that CashPilot cannot see.
_GPU_CHECK_YOURSELF = "preflight.gpu_check_yourself"


def _gpu_check_yourself() -> str:
    return t(_GPU_CHECK_YOURSELF)  # i18n-keys: preflight.gpu_check_yourself


def _gpu_findings(service: dict[str, Any], info: dict[str, Any], deployed: set[str]) -> list[dict[str, str]]:
    """What the worker's GPU report says about a service that needs a GPU.

    An entry CashPilot only tracks (``requirements.gpu`` without ``docker.gpu``)
    keeps the plain "check yourself": CashPilot passes it no GPU. For a GPU
    grant (app/gpu.py) the worker's sysfs read decides: a conclusive read
    without the vendor earns nothing (the worker refuses the deploy too).
    """
    reqs = service.get("requirements") or {}
    grant = gpu.spec_of(service)
    if not grant:
        if reqs.get("gpu"):
            return [{"verdict": CHECK_YOURSELF, "message": _gpu_check_yourself()}]
        return []
    name = service.get("name") or service.get("slug") or "This service"
    vendor = grant["vendor"]
    report = info.get("gpu") if isinstance(info.get("gpu"), dict) else {}
    host = gpu.host_from_report(report)
    vendors = host["vendors"]
    findings: list[dict[str, str]] = []
    if problem := gpu.missing(grant, host):
        findings.append({"verdict": EARNS_NOTHING, "message": t("preflight.worker_refuses_deploy", problem=problem)})
    elif vendors is None or vendor not in vendors:
        findings.append({"verdict": CHECK_YOURSELF, "message": _gpu_check_yourself()})
    elif vendor == "nvidia" and report.get("nvidia_toolkit") is not True:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": t("preflight.machine_has_nvidia_gpu_reaches", name=name, toolkit_url=gpu.TOOLKIT_URL),
            }
        )
    sharing = sorted(
        (other.get("name") or s)
        for s in deployed
        if (other := catalog.get_service(s)) and (other_grant := gpu.spec_of(other)) and other_grant["vendor"] == vendor
    )
    if sharing:
        findings.append(
            {
                "verdict": REDUCED,
                "message": t("preflight.shares_gpu_already_running_machine", name=name, sharing=", ".join(sharing)),
            }
        )
    return findings


def _summary(verdict: str, service: dict[str, Any]) -> str:
    name = service.get("name") or service.get("slug") or "This service"
    if (service.get("requirements") or {}).get("container_prohibited"):
        # "will earn nothing" is the right severity but the wrong words: the
        # outcome here is a closed account and a cancelled balance, not a
        # disappointing month.
        return t("preflight.forbids_being_run_way_risk", name=name)
    if verdict == EARNS_NOTHING:
        return t("preflight.will_most_likely_earn_nothing", name=name)
    if verdict == REDUCED:
        return t("preflight.will_probably_earn_less_here", name=name)
    if verdict == CHECK_YOURSELF:
        return t("preflight.should_work_provided_points_below", name=name)
    return t("preflight.nothing_stands_out_should_work", name=name)


def _fleet_findings(
    service: dict[str, Any],
    *,
    worker: dict[str, Any] | None,
    fleet_workers: list[dict[str, Any]] | None,
    also_deploying_to: set[Any] | None = None,
    replacing: bool = False,
) -> list[dict[str, str]]:
    """What the *rest of the fleet* implies about deploying this here.

    Returns findings in the preflight shape (``verdict``/``message``). Only the
    cross-machine facts live here; same-machine checks stay in ``preflight``.

    Verdicts are deliberately asymmetric. A documented one-device-per-IP service
    already running behind this exact address is a concrete, provider-documented
    loss, so it is stated as one. Everything resting on an undetected IP or an
    undocumented limit is a "check this" — a warning nobody can act on, fired at
    users who are fine, is how a safety feature gets ignored.

    The connection *type* is not handled here: ``preflight`` already reads it
    from the same ``system_info`` and owns that finding, so stating it twice
    would double-count one fact.
    """
    if not worker:
        return []

    name = service.get("name") or service.get("slug") or "This service"
    slug = str(service.get("slug") or "")
    limit = egress.devices_per_ip_limit(service)
    findings: list[dict[str, str]] = []

    peers = egress.peers_sharing_egress(worker, fleet_workers or [])
    if not peers:
        return findings

    # A peer counts if it is ALREADY running this service or is about to receive
    # it in the same action. Only the first half existed, so a single wizard
    # deploy to two machines behind one connection warned about nothing — each
    # was assessed as though the other were not getting it.
    planned = also_deploying_to or set()
    conflicting = [w for w in peers if slug in egress.running_slugs(w) or w.get("id") in planned]
    # Deduplicated for DISPLAY ONLY. Two different machines can share a display
    # name — WORKER_NAME defaults to the hostname, and duplicate hostnames in a
    # home fleet are ordinary — so counting the deduplicated names would merge
    # two real instances into one and under-warn, which is the failure this
    # whole module exists to remove. The arithmetic below uses `conflicting`.
    running_elsewhere = sorted(
        {w.get("name") or w.get("client_id") or f"machine {w.get('id') or '?'}" for w in conflicting}
    )
    if not running_elsewhere:
        return findings

    where = ", ".join(running_elsewhere)
    shared_ip = egress.egress_of(worker)

    if limit == 1:
        findings.append(
            {
                "verdict": EARNS_NOTHING,
                "message": (
                    t("preflight.already_running_which_leaves_internet", name=name, where=where, shared_ip=shared_ip)
                ),
            }
        )
    elif limit is None:
        findings.append(
            {
                "verdict": CHECK_YOURSELF,
                "message": (
                    t("preflight.already_running_behind_same_public", name=name, where=where, shared_ip=shared_ip)
                ),
            }
        )
    elif limit == 0:
        findings.append(
            {
                "verdict": REDUCED,
                "message": (
                    t("preflight.already_running_behind_same_public_2", name=name, where=where, shared_ip=shared_ip)
                ),
            }
        )
    else:
        # Peers + the one already running here + the prospective deploy. Omitting
        # the local one under-counts by exactly the case the feature is for.
        # A replacement is the prospective one itself, not one more.
        local = 1 if slug in egress.running_slugs(worker) and not replacing else 0
        instances = len(conflicting) + local + 1
        verdict = EARNS_NOTHING if instances > limit else REDUCED
        findings.append(
            {
                "verdict": verdict,
                "message": (
                    t(
                        "preflight.already_running_behind_same_public_3",
                        name=name,
                        where=where,
                        shared_ip=shared_ip,
                        limit=limit,
                        instances=instances,
                    )
                ),
            }
        )
    return findings
