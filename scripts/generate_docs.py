#!/usr/bin/env python3
"""
generate_docs.py - Generate README service table and individual guide pages
from YAML service definitions.

Reads all YAML files from services/ (recursively, excluding _schema.yml),
then:
  1. Replaces the services table in README.md between markers
  2. Generates individual guide pages in docs/guides/{slug}.md
  3. Generates docs/guides/README.md as an index

Usage:
    python scripts/generate_docs.py
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install it with: pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICES_DIR = ROOT_DIR / "services"
README_PATH = ROOT_DIR / "README.md"
GUIDES_DIR = ROOT_DIR / "docs" / "guides"

TABLE_START_MARKER = "<!-- SERVICES_TABLE_START"
TABLE_END_MARKER = "<!-- SERVICES_TABLE_END -->"

CATEGORY_ORDER = ["bandwidth", "depin", "storage", "compute"]
CATEGORY_LABELS = {
    "bandwidth": "Bandwidth Sharing",
    "depin": "DePIN",
    "storage": "Storage Sharing",
    "compute": "GPU Compute",
}


# ---------------------------------------------------------------------------
# Load services
# ---------------------------------------------------------------------------


def load_services() -> list[dict]:
    """Recursively load all YAML service definitions from services/."""
    services = []
    for yml_path in sorted(SERVICES_DIR.rglob("*.yml")):
        if yml_path.name.startswith("_"):
            continue
        with open(yml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict) and "name" in data:
            data["_source"] = str(yml_path.relative_to(ROOT_DIR))
            services.append(data)
    for yaml_path in sorted(SERVICES_DIR.rglob("*.yaml")):
        if yaml_path.name.startswith("_"):
            continue
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict) and "name" in data:
            data["_source"] = str(yaml_path.relative_to(ROOT_DIR))
            services.append(data)
    # Deduplicate by slug
    seen = set()
    unique = []
    for s in services:
        slug = s.get("slug", s["name"].lower())
        if slug not in seen:
            seen.add(slug)
            unique.append(s)
    return unique


def group_by_category(services: list[dict]) -> dict[str, list[dict]]:
    """Group services by category, preserving CATEGORY_ORDER."""
    groups: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}
    for svc in services:
        cat = svc.get("category", "bandwidth")
        if cat not in groups:
            groups[cat] = []
        groups[cat].append(svc)
    # Sort each group alphabetically by name
    for cat in groups:
        groups[cat].sort(key=lambda s: s["name"].lower())
    return groups


# ---------------------------------------------------------------------------
# README table generation
# ---------------------------------------------------------------------------


_METHOD_LABELS = {
    "paypal": "PayPal",
    "crypto": "Crypto",
    "bank": "Bank Transfer",
    "amazon_giftcard": "Gift Cards",
    "giftcard": "Gift Cards",
}


def _earnings_range(svc: dict) -> str:
    earn = svc.get("earnings", {})
    low = earn.get("monthly_low", "?")
    high = earn.get("monthly_high", "?")
    currency = earn.get("currency", "USD")
    if currency == "USD":
        return f"${low} - ${high}"
    return f"{low} - {high} {currency}"


def _service_name_link(svc: dict) -> str:
    """Service name linked to referral signup URL, fallback to website."""
    name = svc["name"]
    ref = svc.get("referral", {})
    signup_url = ref.get("signup_url", "")
    if signup_url:
        return f"[{name}]({signup_url})"
    website = svc.get("website", "")
    if website:
        return f"[{name}]({website})"
    return name


def _ip_badge(value: bool) -> str:
    return "\u2705" if value else "\u274c"


def _get_vps_ip(svc: dict) -> bool:
    """Get VPS IP support. If explicitly set, use that. Otherwise derive from residential_ip."""
    req = svc.get("requirements", {})
    vps = req.get("vps_ip")
    if vps is not None:
        return bool(vps)
    return not req.get("residential_ip", False)


def _devices_str(value) -> str:
    if not value or value == 0:
        return "Unlimited"
    return str(value)


def _payout_str(svc: dict) -> str:
    """Generate payout column string from payment data."""
    payment = svc.get("payment", {})
    methods = payment.get("methods", [])
    currency = payment.get("currency", "USD")
    crypto_token = payment.get("crypto_token", "")

    parts = []
    for m in methods:
        label = _METHOD_LABELS.get(m, m.replace("_", " ").title())
        if m == "crypto":
            token = crypto_token or (currency if currency not in ("USD", "EUR") else "")
            if token:
                label = f"Crypto ({token})"
        parts.append(label)

    return ", ".join(parts) if parts else "N/A"


def generate_services_table(services: list[dict]) -> str:
    """Generate the full markdown table block, split by deployability."""
    docker_svcs = []
    browser_svcs = []
    gpu_svcs = []

    for svc in services:
        status = svc.get("status", "active")
        if status in ("dead", "broken", "dropped", "shady"):
            continue
        cat = svc.get("category", "bandwidth")
        docker_img = svc.get("docker", {}).get("image", "")
        if cat == "compute":
            gpu_svcs.append(svc)
        elif docker_img:
            docker_svcs.append(svc)
        else:
            browser_svcs.append(svc)

    docker_svcs.sort(key=lambda s: s["name"].lower())
    browser_svcs.sort(key=lambda s: s["name"].lower())
    gpu_svcs.sort(key=lambda s: s["name"].lower())

    lines: list[str] = []
    footnotes: list[str] = []

    # --- Docker-Deployable Services ---
    if docker_svcs:
        lines.append("### Docker-Deployable Services")
        lines.append("")
        lines.append("Services CashPilot can deploy and manage automatically via Docker.")
        lines.append("")
        lines.append("| Service | Residential IP | VPS IP | Devices / Acct | Devices / IP | Payout |")
        lines.append("|---------|:-:|:-:|:-:|:-:|--------|")

        for svc in docker_svcs:
            req = svc.get("requirements", {})
            vps = _get_vps_ip(svc)
            dev_acct = _devices_str(req.get("devices_per_account", 0))
            dev_ip = _devices_str(req.get("devices_per_ip", 1))
            payout = _payout_str(svc)

            vps_str = _ip_badge(vps)
            dev_ip_str = dev_ip

            note = req.get("note", "")
            if note:
                footnotes.append(note)
                mark = "\\*" * len(footnotes)
                col = req.get("note_column", "")
                if col == "vps_ip":
                    vps_str = f"{vps_str} {mark}"
                elif col == "devices_per_ip":
                    dev_ip_str = f"{dev_ip_str} {mark}"

            name_link = _service_name_link(svc)
            lines.append(f"| {name_link} | \u2705 | {vps_str} | {dev_acct} | {dev_ip_str} | {payout} |")

        lines.append("")
        if footnotes:
            for i, fn in enumerate(footnotes):
                mark = "\\*" * (i + 1)
                lines.append(f"> {mark} {fn}")
                lines.append(">")
            lines[-1] = ""

    # --- Browser Extension / Desktop Only ---
    if browser_svcs:
        lines.append("### Browser Extension / Desktop Only")
        lines.append("")
        lines.append(
            "These services have no Docker image. CashPilot lists them in the "
            "catalog with signup links and earning estimates, but cannot deploy "
            "or monitor them."
        )
        lines.append("")
        lines.append("| Service | Residential IP | VPS IP | Devices / Acct | Devices / IP | Payout | Status |")
        lines.append("|---------|:-:|:-:|:-:|:-:|--------|--------|")

        for svc in browser_svcs:
            req = svc.get("requirements", {})
            vps = _get_vps_ip(svc)
            dev_acct = _devices_str(req.get("devices_per_account", 0))
            dev_ip = _devices_str(req.get("devices_per_ip", 1))
            payout = _payout_str(svc)
            status = svc.get("status", "active").title()
            name_link = _service_name_link(svc)
            lines.append(f"| {name_link} | \u2705 | {_ip_badge(vps)} | {dev_acct} | {dev_ip} | {payout} | {status} |")

        lines.append("")

    # --- GPU Compute ---
    if gpu_svcs:
        lines.append("### GPU Compute")
        lines.append("")
        lines.append("GPU-intensive computing services. Requires compatible hardware.")
        lines.append("")
        lines.append("| Service | Residential IP | GPU | Min Storage | Payout | Status |")
        lines.append("|---------|:-:|:-:|:-:|--------|--------|")

        for svc in gpu_svcs:
            req = svc.get("requirements", {})
            gpu = _ip_badge(req.get("gpu", False))
            min_storage = req.get("min_storage", "") or "N/A"
            payout = _payout_str(svc)
            status = svc.get("status", "active").title()
            name_link = _service_name_link(svc)
            lines.append(f"| {name_link} | \u2705 | {gpu} | {min_storage} | {payout} | {status} |")

        lines.append("")

    return "\n".join(lines).rstrip()


def update_readme(table_content: str) -> None:
    """Replace the services table in README.md between markers."""
    if not README_PATH.exists():
        print(f"WARNING: {README_PATH} does not exist, skipping README update.")
        return

    readme = README_PATH.read_text(encoding="utf-8")

    start_idx = readme.find(TABLE_START_MARKER)
    end_idx = readme.find(TABLE_END_MARKER)

    if start_idx == -1 or end_idx == -1:
        print(
            f"WARNING: Could not find table markers in {README_PATH}. "
            "Ensure the README contains:\n"
            f"  {TABLE_START_MARKER}\n"
            f"  ...table content...\n"
            f"  {TABLE_END_MARKER}"
        )
        return

    # Advance past the full start marker line (may contain trailing comment)
    start_line_end = readme.index("\n", start_idx)
    new_readme = readme[:start_line_end] + "\n" + table_content + "\n" + readme[end_idx:]

    README_PATH.write_text(new_readme, encoding="utf-8")
    print(f"Updated {README_PATH.relative_to(ROOT_DIR)}")


# ---------------------------------------------------------------------------
# Individual guide generation
# ---------------------------------------------------------------------------


def _payment_methods_str(svc: dict) -> str:
    payment = svc.get("payment", {})
    methods = payment.get("methods", [])
    if not methods:
        return "Not specified"
    return ", ".join(m.replace("_", " ").title() for m in methods)


def _platforms_str(svc: dict) -> str:
    platforms = svc.get("platforms", [])
    if not platforms:
        return "Not specified"
    return ", ".join(p.replace("_", " ").title() for p in platforms)


def _env_table(svc: dict) -> str:
    docker = svc.get("docker", {})
    env_vars = docker.get("env", [])
    if not env_vars:
        return "No environment variables required."
    lines = [
        "| Variable | Label | Required | Secret | Description |",
        "|----------|-------|:--------:|:------:|-------------|",
    ]
    for var in env_vars:
        key = var.get("key", "")
        label = var.get("label", "")
        required = "Yes" if var.get("required") else "No"
        secret = "Yes" if var.get("secret") else "No"
        desc = var.get("description", "")
        default = var.get("default", "")
        if default:
            desc += f" (default: `{default}`)"
        lines.append(f"| `{key}` | {label} | {required} | {secret} | {desc} |")
    return "\n".join(lines)


def _docker_run_example(svc: dict) -> str:
    docker = svc.get("docker", {})
    image = docker.get("image", "")
    if not image:
        return ""

    slug = svc.get("slug", svc["name"].lower().replace(" ", "-"))
    parts = ["docker run -d \\", f"  --name cashpilot-{slug} \\"]

    network_mode = docker.get("network_mode", "")
    if network_mode:
        parts.append(f"  --network {network_mode} \\")

    for cap in docker.get("cap_add", []):
        parts.append(f"  --cap-add {cap} \\")

    for port in docker.get("ports", []):
        parts.append(f"  -p {port} \\")

    for vol in docker.get("volumes", []):
        parts.append(f"  -v {vol} \\")

    for var in docker.get("env", []):
        key = var.get("key", "")
        label = var.get("label", key)
        parts.append(f'  -e {key}="<{label}>" \\')

    command = docker.get("command", "")
    if command:
        parts.append(f"  {image} {command}")
    else:
        parts.append(f"  {image}")

    return "\n".join(parts)


def generate_guide(svc: dict) -> str:
    """Generate a full Markdown guide page for a single service."""
    name = svc["name"]
    slug = svc.get("slug", name.lower().replace(" ", "-"))
    category = svc.get("category", "unknown")
    cat_label = CATEGORY_LABELS.get(category, category.title())
    website = svc.get("website", "")
    description = svc.get("description", "").strip()
    status = svc.get("status", "active")

    ref = svc.get("referral", {})
    signup_url = ref.get("signup_url", website)
    ref_bonus_referrer = ref.get("bonus", {}).get("referrer", "N/A")
    ref_bonus_referee = ref.get("bonus", {}).get("referee", "N/A")

    earn = svc.get("earnings", {})
    earnings_range = _earnings_range(svc)
    earnings_per = earn.get("per", "device")
    earnings_notes = earn.get("notes", "")

    payment = svc.get("payment", {})
    min_payout = payment.get("minimum_payout", "N/A")
    payout_freq = payment.get("frequency", "N/A")

    req = svc.get("requirements", {})
    residential = "Yes" if req.get("residential_ip") else "No"
    min_bw = req.get("min_bandwidth", "") or "None"
    gpu = "Yes" if req.get("gpu") else "No"
    min_storage = req.get("min_storage", "") or "None"

    docker_image = svc.get("docker", {}).get("image", "N/A")
    docker_platforms = ", ".join(svc.get("docker", {}).get("platforms", []))

    sections = []

    # Header
    sections.append(f"# {name}")
    sections.append("")
    sections.append(f"> **Category:** {cat_label} | **Status:** {status.title()}")
    if website:
        sections.append(f"> **Website:** [{website}]({website})")
    sections.append("")

    # Description
    sections.append("## Description")
    sections.append("")
    sections.append(description if description else f"{name} is a passive income service.")
    sections.append("")

    # Earning Estimates
    sections.append("## Earning Estimates")
    sections.append("")
    sections.append("| Metric | Value |")
    sections.append("|--------|-------|")
    sections.append(f"| Monthly range | {earnings_range} |")
    sections.append(f"| Per | {earnings_per} |")
    sections.append(f"| Minimum payout | {min_payout} |")
    sections.append(f"| Payout frequency | {payout_freq} |")
    sections.append(f"| Payment methods | {_payment_methods_str(svc)} |")
    sections.append("")
    if earnings_notes:
        sections.append(f"> {earnings_notes}")
        sections.append("")

    # Requirements
    sections.append("## Requirements")
    sections.append("")
    sections.append("| Requirement | Value |")
    sections.append("|-------------|-------|")
    sections.append(f"| Residential IP | {residential} |")
    sections.append(f"| Minimum bandwidth | {min_bw} |")
    sections.append(f"| GPU required | {gpu} |")
    sections.append(f"| Minimum storage | {min_storage} |")
    sections.append(f"| Supported platforms | {_platforms_str(svc)} |")
    sections.append("")

    # Setup Instructions
    sections.append("## Setup Instructions")
    sections.append("")
    sections.append("### 1. Create an account")
    sections.append("")
    if signup_url:
        sections.append(f"Sign up at [{name}]({signup_url}).")
    else:
        sections.append(f"Sign up at the [{name} website]({website}).")
    sections.append("")

    sections.append("### 2. Get your credentials")
    sections.append("")
    sections.append(
        "After signing up, locate the credentials needed for Docker deployment. "
        "These are typically your email/password or an API token found in the dashboard."
    )
    sections.append("")

    sections.append("### 3. Deploy with CashPilot")
    sections.append("")
    sections.append(
        f"In the CashPilot web UI, find **{name}** in the service catalog and click "
        f"**Deploy**. Enter the required credentials and CashPilot will handle the rest."
    )
    sections.append("")

    # Docker Configuration
    sections.append("## Docker Configuration")
    sections.append("")
    sections.append(f"- **Image:** `{docker_image}`")
    if docker_platforms:
        sections.append(f"- **Platforms:** {docker_platforms}")
    sections.append("")

    sections.append("### Environment Variables")
    sections.append("")
    sections.append(_env_table(svc))
    sections.append("")

    docker_example = _docker_run_example(svc)
    if docker_example:
        sections.append("### Manual Docker Run")
        sections.append("")
        sections.append("If running outside CashPilot:")
        sections.append("")
        sections.append("```bash")
        sections.append(docker_example)
        sections.append("```")
        sections.append("")

    # Referral Program
    sections.append("## Referral Program")
    sections.append("")
    sections.append("| | Details |")
    sections.append("|---|---------|")
    sections.append(f"| Referrer bonus | {ref_bonus_referrer} |")
    sections.append(f"| New user bonus | {ref_bonus_referee} |")
    sections.append("")

    # Footer
    sections.append("---")
    sections.append("")
    sections.append(
        f"*This guide was auto-generated from "
        f"[`{svc.get('_source', slug + '.yml')}`]"
        f"(../../{svc.get('_source', 'services/' + slug + '.yml')}). "
        f"Edit the YAML source and run `python scripts/generate_docs.py` to update.*"
    )
    sections.append("")

    return "\n".join(sections)


def generate_guides_index(groups: dict[str, list[dict]]) -> str:
    """Generate docs/guides/README.md as an index of all guide pages."""
    lines = [
        "# CashPilot Service Guides",
        "",
        "Individual setup and configuration guides for every supported service.",
        "",
    ]

    total = sum(len(svcs) for svcs in groups.values())
    lines.append(f"**{total} services** across {len([g for g in groups.values() if g])} categories.")
    lines.append("")

    for cat in CATEGORY_ORDER:
        svcs = groups.get(cat, [])
        if not svcs:
            continue
        label = CATEGORY_LABELS.get(cat, cat.title())
        lines.append(f"## {label}")
        lines.append("")
        for svc in svcs:
            slug = svc.get("slug", svc["name"].lower().replace(" ", "-"))
            name = svc["name"]
            short = svc.get("short_description", "")
            link = f"[{name}]({slug}.md)"
            if short:
                lines.append(f"- {link} -- {short}")
            else:
                lines.append(f"- {link}")
        lines.append("")

    # Handle any extra categories
    for cat, svcs in groups.items():
        if cat in CATEGORY_ORDER or not svcs:
            continue
        label = cat.replace("_", " ").title()
        lines.append(f"## {label}")
        lines.append("")
        for svc in svcs:
            slug = svc.get("slug", svc["name"].lower().replace(" ", "-"))
            name = svc["name"]
            short = svc.get("short_description", "")
            link = f"[{name}]({slug}.md)"
            if short:
                lines.append(f"- {link} -- {short}")
            else:
                lines.append(f"- {link}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*Auto-generated by `scripts/generate_docs.py`. "
        "Edit service YAML files in `services/` and re-run the script to update.*"
    )
    lines.append("")
    return "\n".join(lines)


def write_guides(services: list[dict], groups: dict[str, list[dict]]) -> None:
    """Write individual guide files and the index."""
    GUIDES_DIR.mkdir(parents=True, exist_ok=True)

    for svc in services:
        slug = svc.get("slug", svc["name"].lower().replace(" ", "-"))
        guide_path = GUIDES_DIR / f"{slug}.md"
        guide_content = generate_guide(svc)
        guide_path.write_text(guide_content, encoding="utf-8")
        print(f"  Generated docs/guides/{slug}.md")

    index_path = GUIDES_DIR / "README.md"
    index_content = generate_guides_index(groups)
    index_path.write_text(index_content, encoding="utf-8")
    print("  Generated docs/guides/README.md")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading service definitions...")
    services = load_services()
    print(f"  Found {len(services)} service(s)")

    if not services:
        print("No service YAML files found in services/. Nothing to generate.")
        return

    groups = group_by_category(services)

    print("\nGenerating README services table...")
    table = generate_services_table(services)
    update_readme(table)

    print("\nGenerating individual guide pages...")
    write_guides(services, groups)

    print("\nDone.")


if __name__ == "__main__":
    main()
