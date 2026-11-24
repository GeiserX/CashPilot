"""Validate all YAML service definitions against the schema."""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "services"
CATEGORIES = {"bandwidth", "depin", "storage", "compute"}
VALID_STATUSES = {"active", "beta", "broken", "dead", "dropped"}

REQUIRED_FIELDS = {"name", "slug", "category", "status", "website", "description"}


def _discover_yamls():
    """Find all service YAML files across category subdirectories."""
    yamls = []
    for category_dir in SERVICES_DIR.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        for yml in category_dir.glob("*.yml"):
            if yml.name.startswith("_"):
                continue
            yamls.append(yml)
    return sorted(yamls, key=lambda p: p.name)


ALL_YAMLS = _discover_yamls()


@pytest.mark.parametrize("yml_path", ALL_YAMLS, ids=[y.stem for y in ALL_YAMLS])
class TestServiceYAML:
    def test_parses_without_error(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"{yml_path.name} did not parse to a dict"

    def test_required_fields_present(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        missing = REQUIRED_FIELDS - set(data.keys())
        assert not missing, f"{yml_path.name} missing fields: {missing}"

    def test_category_valid(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["category"] in CATEGORIES, f"Invalid category: {data['category']}"

    def test_status_valid(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["status"] in VALID_STATUSES, f"Invalid status: {data['status']}"

    def test_docker_has_image(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        if "docker" in data and data["docker"]:
            assert "image" in data["docker"], f"{yml_path.name}: docker section missing image"

    def test_docker_section_present(self, yml_path):
        """Runtime catalog loader expects a docker section on every service."""
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert "docker" in data, f"{yml_path.name}: missing docker section (required at runtime)"

    def test_volumes_are_strings(self, yml_path):
        """Deploy code splits volumes on ':'. Mappings break it."""
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        volumes = (data.get("docker") or {}).get("volumes") or []
        for v in volumes:
            assert isinstance(v, str), (
                f"{yml_path.name}: volume must be a colon-delimited string, got {type(v).__name__}: {v}"
            )

    def test_slug_matches_filename(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["slug"] == yml_path.stem, f"Slug '{data['slug']}' does not match filename '{yml_path.stem}'"


class _NoDuplicateKeysLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping with the same key twice."""


def _construct_unique_mapping(loader, node, deep=False):
    keys = [loader.construct_object(key, deep=deep) for key, _ in node.value]
    repeated = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if repeated:
        raise yaml.constructor.ConstructorError(None, None, f"duplicate key(s) {repeated}", node.start_mark)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_NoDuplicateKeysLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


@pytest.mark.parametrize("yml_path", ALL_YAMLS, ids=lambda p: p.stem)
def test_no_duplicate_keys(yml_path):
    """PyYAML keeps the last of two equal keys without a word, but the Desktop
    app's Go decoder rejects the whole file, so its catalog stops loading."""
    with open(yml_path) as f:
        yaml.load(f, Loader=_NoDuplicateKeysLoader)


def test_no_duplicate_slugs():
    slugs = []
    for yml_path in ALL_YAMLS:
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        slugs.append(data["slug"])
    duplicates = [s for s in slugs if slugs.count(s) > 1]
    assert not duplicates, f"Duplicate slugs found: {set(duplicates)}"


def test_repocket_container_env_keys():
    """Regression for #82: the repocket/repocket image reads RP_EMAIL + RP_API_KEY.

    A prior 'audit' (PR #46) renamed these to REPOCKET_EMAIL/REPOCKET_PASSWORD to
    match the earnings collector's auth model, which silently broke deployment —
    the container ignores unknown env vars and logs 'User credentials are missing!'.
    The container env contract is independent of the collector's Firebase login.
    """
    repocket = SERVICES_DIR / "bandwidth" / "repocket.yml"
    with open(repocket) as f:
        data = yaml.safe_load(f)
    env_keys = {e["key"] for e in data["docker"]["env"]}
    assert env_keys == {"RP_EMAIL", "RP_API_KEY"}, (
        f"Repocket container env must be exactly RP_EMAIL + RP_API_KEY, got {env_keys}"
    )
    by_key = {e["key"]: e for e in data["docker"]["env"]}
    assert by_key["RP_API_KEY"]["secret"] is True, "RP_API_KEY must be marked secret"
    assert by_key["RP_API_KEY"]["required"] is True, "RP_API_KEY must be required"
    assert by_key["RP_EMAIL"]["required"] is True, "RP_EMAIL must be required"


def test_proxybase_container_contract():
    """Regression for #103: ProxyBase migrated off Docker Hub to the GHCR peer-cli.

    The current client (ghcr.io/proxybaseorg/peer-cli) reads env vars ID + NAME
    (verified against the image's own --help: 'ProxyBase-Peer [<ID> [<NAME>]]',
    'set env var ID' / 'set env var NAME'). It does NOT read the old
    USER_ID/DEVICE_NAME, so a container built on those silently fails with
    'Missing ID and NAME'. Pin by digest — never fall back to the retired
    proxybase/proxybase image or a floating tag.
    """
    proxybase = SERVICES_DIR / "bandwidth" / "proxybase.yml"
    with open(proxybase) as f:
        data = yaml.safe_load(f)

    image = data["docker"]["image"]
    assert image.startswith("ghcr.io/proxybaseorg/peer-cli@sha256:"), (
        f"ProxyBase must use the digest-pinned GHCR peer-cli image, got {image}"
    )
    assert "linux/arm64" in data["docker"]["platforms"], (
        "ProxyBase must keep arm64 (the peer-cli image is multi-arch; Raspberry Pi support)"
    )

    env_keys = {e["key"] for e in data["docker"]["env"]}
    assert env_keys == {"ID", "NAME"}, (
        f"ProxyBase container env must be exactly ID + NAME (the peer-cli contract), got {env_keys}"
    )
    by_key = {e["key"]: e for e in data["docker"]["env"]}
    assert by_key["ID"]["required"] is True, "ID (Access Token) must be required"
    assert by_key["ID"]["secret"] is True, "ID (Access Token) must be marked secret (masked in the UI)"
    assert by_key["NAME"]["required"] is True, "NAME (Device Name) must be required"

    # Referral revenue guard: the signup URL must keep the referral code.
    assert data["referral"]["signup_url"] == "https://peer.proxybase.org?referral=nXzS3c6iTO", (
        f"ProxyBase signup_url must keep the referral code, got {data['referral']['signup_url']}"
    )

    # Datacenter/VPS IPs are accepted (per the ProxyBase team); drives the UI badge.
    assert data["requirements"]["residential_ip"] is False, "ProxyBase no longer requires a residential IP"
    assert data["requirements"]["vps_ip"] is True, "ProxyBase must mark VPS/datacenter IPs as supported"

    # Domain migrated proxybase.io -> proxybase.org across every user-facing URL.
    assert "proxybase.io" not in data["website"], "website must use proxybase.org"
    for e in data["docker"]["env"]:
        assert "proxybase.io" not in e.get("description", ""), f"env {e['key']} description still links proxybase.io"


def test_proxybase_markets_referral_and_image_contract():
    """Revenue + supply-chain guard for the ProxyBase Markets entry.

    This service was contributed by the vendor, so the two things a vendor has
    an incentive to change are pinned here:

    - The signup URL must keep OUR referral code. It is the same code as the
      sibling ProxyBase entry; a contributor swapping in their own code would
      silently redirect every CashPilot signup's commission.
    - The image must stay digest-pinned. A floating tag on a third-party image
      that proxies traffic would let the published content change under us.
    """
    with open(SERVICES_DIR / "bandwidth" / "proxybase-xyz.yml") as f:
        data = yaml.safe_load(f)

    assert data["referral"]["signup_url"] == "https://proxybase.xyz?referral=nXzS3c6iTO", (
        f"ProxyBase Markets signup_url must keep our referral code, got {data['referral']['signup_url']}"
    )

    image = data["docker"]["image"]
    assert image.startswith("ghcr.io/proxybasehq/proxybase-cli@sha256:"), (
        f"ProxyBase Markets must stay digest-pinned to the GHCR image, got {image}"
    )
    assert "linux/arm64" in data["docker"]["platforms"], (
        "ProxyBase Markets must keep arm64 (the image is multi-arch; Raspberry Pi support)"
    )

    # Every service must tell the user how to get paid (contribution rule).
    assert data["cashout"]["method"], "ProxyBase Markets must declare a cashout method"


# ---------------------------------------------------------------------------
# obligations: (services/_schema.yml, app/obligations.py)
# ---------------------------------------------------------------------------

# A dated rule this long past is dead: the money it protected is gone, so the
# rule only adds noise. Remove it.
OBLIGATION_DATE_GRACE_DAYS = 30


def _obligation_service(**rule_overrides):
    rule = {
        "id": "claim-thing",
        "action": "claim",
        "title": "Claim your thing",
        "loss": "The provider keeps it.",
        "url": "https://app.acme.io/claim",
        "when": {"date": "2027-01-22"},
        "source": "https://acme.io/terms",
        "checked": "2026-11-24",
    }
    rule.update(rule_overrides)
    return {
        "slug": "acme",
        "website": "https://www.acme.io",
        "cashout": {"dashboard_url": "https://dash.acme.io/pay"},
        "referral": {"signup_url": "https://join.acme.io/?ref=x"},
        "obligations": [rule],
    }


def _obligation_problems(**rule_overrides):
    from app.catalog import validate_obligations

    kept, problems = validate_obligations(_obligation_service(**rule_overrides))
    assert len(kept) + len(problems) == 1
    return problems


def _long_past(rule, today):
    from datetime import date, timedelta

    when = rule.get("when") or {}
    return "date" in when and today - date.fromisoformat(when["date"]) > timedelta(days=OBLIGATION_DATE_GRACE_DAYS)


@pytest.mark.parametrize("yml_path", ALL_YAMLS, ids=[y.stem for y in ALL_YAMLS])
def test_every_shipped_obligation_validates(yml_path):
    from app.catalog import validate_obligations

    data = yaml.safe_load(yml_path.read_text())
    if "obligations" not in data:
        return
    kept, problems = validate_obligations(data)
    assert not problems, f"{yml_path.name}: {problems}"
    assert kept, f"{yml_path.name}: an empty obligations: block"


def test_the_phase_one_rules_ship():
    """The seven rules from the design, so a bad edit cannot drop one quietly."""
    shipped = set()
    for path in ALL_YAMLS:
        data = yaml.safe_load(path.read_text())
        shipped |= {(data["slug"], rule["id"]) for rule in data.get("obligations") or []}
    assert shipped >= {
        ("grass", "claim-stage2-usdc"),
        ("mysterium", "claim-monthly-rewards-pool"),
        ("honeygain", "withdraw-before-24-month-write-off"),
        ("honeygain", "keep-active-6-months"),
        ("repocket", "avoid-12-month-dormancy"),
        ("bitping", "withdraw-before-12-month-forfeit"),
        ("salad", "earn-within-12-months"),
    }


@pytest.mark.parametrize("yml_path", ALL_YAMLS, ids=[y.stem for y in ALL_YAMLS])
def test_no_dated_obligation_is_long_past(yml_path):
    from datetime import date

    data = yaml.safe_load(yml_path.read_text())
    for rule in data.get("obligations") or []:
        assert not _long_past(rule, date.today()), (
            f"{yml_path.name}: {rule['id']} was due {rule['when']['date']}; the money is gone, remove the rule"
        )


def test_the_long_past_check_can_fail():
    """The check above, proved against the Grass rule a year after its date."""
    from datetime import date

    rule = {"when": {"date": "2027-01-22"}}
    assert not _long_past(rule, date(2027, 2, 21))
    assert _long_past(rule, date(2027, 2, 22))


def test_a_valid_rule_passes():
    assert _obligation_problems() == []


@pytest.mark.parametrize(
    "override",
    [
        {"action": "check"},
        {"id": "Claim_Thing"},
        {"title": "x" * 81},
        {"title": "Claim {amount}"},
        {"loss": "Lost <b>forever</b>"},
        {"how": "Use {{ link }}"},
        {"url": "https://acme-claim.io/drop"},
        {"url": "http://app.acme.io/claim"},
        {"source": "acme.io/terms"},
        {"checked": "24 Nov 2026"},
        {"when": {"date": "2027-02-30"}},
        {"when": {"date": "2027-01-22", "since": "last_payout", "days": 3}},
        {"when": {"since": "first_login", "days": 30}},
        {"when": {"since": "last_payout", "days": 0}},
        {"when": {"every": "month", "on": 31, "due_days": 30}},
        {"when": {"every": "week", "on": 1, "due_days": 3}},
        {"warn_days": [7, 30]},
        {"warn_days": [30, 30]},
        {"warn_days": [30, -1]},
        {"warn_days": []},
        {"confidence": "high"},
    ],
    ids=lambda o: f"{next(iter(o))}={next(iter(o.values()))!r}"[:40],
)
def test_a_bad_rule_is_refused(override):
    assert _obligation_problems(**override)


def test_a_link_on_the_services_own_domains_is_accepted():
    for url in ("https://acme.io/x", "https://dash.acme.io/pay", "https://join.acme.io/y"):
        assert _obligation_problems(url=url) == []


def test_ids_are_unique_in_a_file():
    from app.catalog import validate_obligations

    data = _obligation_service()
    data["obligations"].append(dict(data["obligations"][0]))
    kept, problems = validate_obligations(data)
    assert len(kept) == 1 and problems


def test_a_bare_on_key_is_read_the_way_desktop_reads_it():
    """YAML 1.1 turns a bare `on:` into True; Desktop's YAML 1.2 keeps "on"."""
    from app.catalog import validate_obligations

    when = yaml.safe_load("when: {every: month, on: 1, due_days: 30}")["when"]
    assert True in when
    kept, problems = validate_obligations(_obligation_service(when=when))
    assert not problems and kept[0]["when"]["on"] == 1


def test_a_bad_rule_is_dropped_and_the_service_still_loads(tmp_path, caplog):
    from app import catalog

    data = yaml.safe_load((SERVICES_DIR / "depin" / "grass.yml").read_text())
    phish = dict(data["obligations"][0], id="phish", url="https://grass-claim.io/")
    data["obligations"].append(phish)
    assert catalog._validate(data, tmp_path / "grass.yml") == []
    assert [r["id"] for r in data["obligations"]] == ["claim-stage2-usdc"]
    assert "obligations[phish]" in caplog.text
