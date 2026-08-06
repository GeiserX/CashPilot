"""A service that MINTS a wallet must declare the volume holding it.

Found while starting tier 3 (CashPilot-e8u), which is about minted wallets, so
the mislabel was directly in the way: services/bandwidth/proxybase.yml declared
``payout.model: minted`` while authenticating with an account access token,
cashing out by dashboard redirect, and mounting no volumes at all. It pays to an
ACCOUNT. I introduced that error myself in #267 by carrying the payout block
across from its similarly named sibling.

THE INVARIANT THAT MAKES THE CLASS IMPOSSIBLE TO REINTRODUCE:

    a DEPLOYABLE service declared `minted` must declare `critical_volumes`

because minting a wallet means irreplaceable local state, and a wallet with no
persisted, flagged volume dies with the container — taking the money with it.
Either the label is wrong (as here) or the service is one recreate away from
destroying funds. Both are worth failing a build over.

Services with an empty ``docker.image`` are exempt: the catalog lists those as
present but not Docker-deployable (app/catalog.py, the "Extension/app-only
services" branch), so there is no container and no volume to speak of.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SERVICES = sorted(Path("services").glob("*/*.yml"))


def _load(path: Path) -> dict:
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def _minted_and_deployable() -> list[tuple[Path, dict]]:
    out = []
    for path in SERVICES:
        if path.name.startswith("_"):
            continue
        data = _load(path)
        payout = data.get("payout") or {}
        docker = data.get("docker") or {}
        if payout.get("model") == "minted" and (docker.get("image") or "").strip():
            out.append((path, data))
    return out


def test_the_catalog_still_has_minted_services():
    """CONTROL. If nothing were classified `minted`, the invariant below would
    hold vacuously and prove nothing at all — which is exactly how this kind of
    check rots into decoration."""
    assert _minted_and_deployable(), "no deployable minted service found; the test below is vacuous"


@pytest.mark.parametrize("path", [p for p, _ in _minted_and_deployable()], ids=lambda p: p.stem)
def test_a_minted_service_declares_the_volume_that_holds_the_wallet(path):
    data = _load(path)
    critical = (data.get("docker") or {}).get("critical_volumes")
    assert critical, (
        f"{path} declares payout.model 'minted' but no docker.critical_volumes. "
        "Either it does not actually mint a wallet — check whether it authenticates "
        "with an account credential and cashes out via a dashboard, which is the "
        "'internal' model — or it does, and every container recreate destroys the "
        "funds."
    )


@pytest.mark.parametrize("path", [p for p, _ in _minted_and_deployable()], ids=lambda p: p.stem)
def test_the_critical_volume_is_actually_mounted(path):
    """Declaring a volume critical while never mounting it protects nothing.

    The delete guard reads `critical_volumes` (app/catalog.py), so a target that
    appears in neither `volumes` nor the mount list is a warning about a path
    the container does not have.
    """
    docker = _load(path).get("docker") or {}
    mounted = " ".join(str(v) for v in (docker.get("volumes") or []))
    for entry in docker.get("critical_volumes") or []:
        target = (entry or {}).get("target")
        assert target, f"{path}: a critical_volumes entry has no target"
        assert target in mounted, f"{path}: critical volume {target!r} is not among docker.volumes ({mounted!r})"


def test_proxybase_and_proxybase_xyz_are_not_confused_for_each_other():
    """The specific regression. Same org, similar names, opposite payout models:
    peer-cli pays an ACCOUNT, Markets mints a local wallet."""
    peer = _load(Path("services/bandwidth/proxybase.yml"))
    markets = _load(Path("services/bandwidth/proxybase-xyz.yml"))

    assert peer["payout"]["model"] == "internal", "proxybase (peer-cli) pays to an account, not a minted wallet"
    assert markets["payout"]["model"] == "minted", "proxybase-xyz (Markets) does mint its own wallet"
    # And the evidence for that split, so a future edit has to confront it.
    assert not (peer.get("docker") or {}).get("volumes"), (
        "peer-cli keeps no state; a volume would contradict 'internal'"
    )
    assert (markets.get("docker") or {}).get("critical_volumes"), "Markets' wallet volume must stay flagged critical"
