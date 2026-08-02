"""Lateral containment, and owning the attribution risk (CashPilot-q0o).

The documented danger of running proxyware is not container escape. It is that
someone else's traffic exits YOUR address and is attributed to you — the FBI/IC3
has issued a public notice about residential proxy networks, and researchers
have shown operators cannot see what traffic leaves their own exit node. The
second realistic risk is a hostile image scanning the home LAN it was handed:
Home Assistant, NAS shares, a media server, a password manager.

The first risk cannot be engineered away here. Selling that egress IS the
product, so any control that blocked it would block the thing the user installed
CashPilot to do. What can be reduced is LATERAL reach: a bandwidth container has
no business talking to a NAS.

Two decisions shape this module.

**It states the attribution risk plainly, at deploy time.** Not in an FAQ, not
in a tooltip. A self-hosting audience is persuaded by a project that owns the
downside; burying it is what makes people distrust the whole category.

**It does not silently reconfigure the host's network.** Creating bridges and
firewall rules on someone's machine is a change with real blast radius, and
several services would break in ways that cost money: Storj needs an inbound
port and its own dashboard reachable for the collector, and Mysterium runs on
the host network where no bridge applies at all. So this computes what CAN be
isolated, names every exception and why, and leaves the act to the operator.
"""

from __future__ import annotations

from typing import Any

from app import disclosure

# Verdicts for whether a service can be confined to an isolated bridge.
ISOLATABLE = "isolatable"
NEEDS_EXCEPTIONS = "needs_exceptions"
NOT_ISOLATABLE = "not_isolatable"

# Private ranges a managed container has no business reaching. Not a firewall
# implementation — the list a user needs in order to write one.
RFC1918 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
# Link-local carries cloud metadata endpoints; a container reaching those on a
# VPS can often mint credentials for the whole account.
LINK_LOCAL = ("169.254.0.0/16",)

DEFAULT_NETWORK_NAME = "cashpilot-isolated"


def _docker(service: dict[str, Any] | None) -> dict[str, Any]:
    return (service or {}).get("docker") or {}


def uses_host_network(service: dict[str, Any] | None) -> bool:
    """Host networking means there is no bridge to isolate it onto."""
    return str(_docker(service).get("network_mode") or "").strip().lower() == "host"


def published_ports(service: dict[str, Any] | None) -> list[str]:
    """Ports the service must accept connections on."""
    ports = _docker(service).get("ports") or []
    return [str(p) for p in ports if str(p).strip()]


def exceptions_for(service: dict[str, Any] | None) -> list[dict[str, str]]:
    """Everything that must stay reachable, and why.

    An isolation rule written without these silently breaks the thing it was
    meant to protect — and for a storage node, breaking inbound reachability
    costs held payout balance, not just uptime.
    """
    found: list[dict[str, str]] = []
    if uses_host_network(service):
        found.append(
            {
                "kind": "host_network",
                "detail": "This service runs on the host network, so a container bridge does not apply to it at all.",
            }
        )
    for port in published_ports(service):
        found.append(
            {
                "kind": "inbound_port",
                "detail": f"Port {port} must accept inbound connections, or the node cannot do its job.",
            }
        )
    if (service or {}).get("collector") or (service or {}).get("slug") == "storj":
        api_url_env = [
            e.get("key")
            for e in (_docker(service).get("env") or [])
            if isinstance(e, dict) and "URL" in str(e.get("key", ""))
        ]
        if api_url_env:
            found.append(
                {
                    "kind": "collector_reachability",
                    "detail": (
                        "CashPilot reads this service's earnings from its own local dashboard, so that "
                        f"address ({', '.join(str(k) for k in api_url_env)}) must stay reachable from the UI."
                    ),
                }
            )
    return found


def assess(service: dict[str, Any] | None) -> dict[str, Any]:
    """Can this service be confined to a LAN-isolated bridge?"""
    if not service:
        return {"slug": None, "verdict": NOT_ISOLATABLE, "exceptions": [], "summary": "Unknown service."}

    name = service.get("name") or service.get("slug") or "This service"
    exceptions = exceptions_for(service)

    if uses_host_network(service):
        verdict = NOT_ISOLATABLE
        summary = (
            f"{name} runs on the host network, so it shares the host's interfaces directly and a "
            "container bridge cannot contain it. Isolating it means a VLAN or a separate machine."
        )
    elif exceptions:
        verdict = NEEDS_EXCEPTIONS
        summary = (
            f"{name} can run on an isolated bridge, but {len(exceptions)} exception(s) must be allowed "
            "through or it will stop working."
        )
    else:
        verdict = ISOLATABLE
        summary = f"{name} needs no inbound access and can be confined to an isolated bridge as-is."

    return {
        "slug": service.get("slug"),
        "verdict": verdict,
        "exceptions": exceptions,
        "blocked_destinations": list(RFC1918 + LINK_LOCAL),
        "network_name": DEFAULT_NETWORK_NAME,
        "summary": summary,
    }


def attribution_notice(service: dict[str, Any] | None) -> dict[str, Any] | None:
    """The honest warning shown before deploying, or None when it does not apply.

    Driven by the service's own disclosure block, so it fires exactly where
    strangers really do route through the user's address — and stays silent for
    a storage node, where it would be false and would train people to click past
    it.

    Three outcomes, because "no warning" and "nothing known" are different and
    a user cannot tell them apart from silence:

    * documented as reselling the IP -> the full notice;
    * documented as NOT reselling (a storage node) -> None, correctly silent,
      since a false warning here trains people to click past the real ones;
    * undocumented -> a notice saying exactly that. Most of the catalog is
      undocumented, and letting that render as "no risk" would be the worst
      reading of it.
    """
    routes = disclosure.routes_third_party_traffic(service)
    name = (service or {}).get("name") or (service or {}).get("slug") or "This service"

    if routes is False:
        return None
    if routes is None:
        return {
            "slug": (service or {}).get("slug"),
            "documented": False,
            "headline": f"Nobody has documented what {name} does with your connection.",
            "body": (
                "That is not the same as it being safe. Most services in this category resell access "
                "to your internet connection, which means other people's traffic leaves under your IP "
                "and is attributed to you. Until somebody writes down what this one does, assume it "
                "might and check the provider's terms — and your ISP's — yourself."
            ),
            "lateral_note": ("Consider putting these containers on a network that cannot reach the rest of your LAN."),
            "source": "No disclosure entry exists for this service in the catalog.",
        }

    return {
        "slug": (service or {}).get("slug"),
        "documented": True,
        "headline": f"{name} sells access to your internet connection.",
        "body": (
            "Other people's traffic will leave your connection under your IP address, and anything "
            "they do with it looks like you to the outside world — to your ISP, to sites that block "
            "the address, and to law enforcement. You cannot see or filter what they send. "
            "Check your ISP's terms before running this: many consumer contracts prohibit resharing "
            "the connection, and the account that gets suspended is yours."
        ),
        "lateral_note": (
            "Consider putting these containers on a network that cannot reach the rest of your LAN. "
            "A hostile image's realistic prize is your NAS, your Home Assistant, or your password "
            "manager — not the bandwidth."
        ),
        "source": "This service's own disclosure entry in the catalog.",
    }


def compose_snippet(network_name: str = DEFAULT_NETWORK_NAME) -> str:
    """A Docker network definition the operator can actually paste.

    Deliberately returned as text rather than applied. Creating networks and
    firewall rules on someone's host is their decision, and the rules that
    matter here are enforced by the host firewall, which Docker cannot express.
    """
    blocked = "\n".join(f"#   {cidr}" for cidr in RFC1918 + LINK_LOCAL)
    return (
        f"networks:\n"
        f"  {network_name}:\n"
        f"    driver: bridge\n"
        f"    driver_opts:\n"
        f'      com.docker.network.bridge.name: "{network_name}"\n'
        f"\n"
        f"# Docker alone does NOT stop a container reaching your LAN. Add host firewall\n"
        f"# rules on the {network_name} bridge denying these destinations:\n"
        f"{blocked}\n"
        f"# ...while still allowing the exceptions listed for each service, or the\n"
        f"# services that need inbound ports will silently stop earning.\n"
    )
