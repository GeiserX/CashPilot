"""An exported file with a host path nobody supplied must still be a valid Compose file.

Exporting Storj without its directories wrote "<Identity directory>" as the
host path. As a host path it reads as a named volume, so the file declared a
volume called "<Identity directory>" and Compose rejected the whole file with
an error that named neither setting. An unfilled path is now ${KEY:?...}:
Compose fills it from the user's .env or shell, and refuses to run without it,
naming the variable. Checked with docker compose config on Compose v2.40.
"""

from __future__ import annotations

import yaml

from app import compose_generator


def _storj(env_vars=None):
    return yaml.safe_load(compose_generator.generate_compose_single("storj", env_vars=env_vars))


def test_an_unfilled_path_is_a_required_variable_not_a_placeholder():
    compose = _storj()
    volumes = compose["services"]["cashpilot-storj"]["volumes"]
    assert any(v.startswith("${IDENTITY_DIR:?") and v.endswith(":/app/identity") for v in volumes), volumes
    assert any(v.startswith("${STORAGE_DIR:?") and v.endswith(":/app/config") for v in volumes), volumes
    assert not any("<" in v for v in volumes), "a placeholder must never be a host path"


def test_it_is_not_declared_as_a_named_volume():
    assert "volumes" not in _storj(), "only real named volumes belong in the top-level block"


def test_supplied_paths_are_written_as_they_are():
    compose = _storj({"IDENTITY_DIR": "/srv/storj/identity", "STORAGE_DIR": "/srv/storj/data"})
    volumes = compose["services"]["cashpilot-storj"]["volumes"]
    assert "/srv/storj/identity:/app/identity" in volumes
    assert "/srv/storj/data:/app/config" in volumes


def test_a_real_named_volume_is_still_declared():
    compose = yaml.safe_load(compose_generator.generate_compose_single("mysterium"))
    assert "mysterium-data" in compose["volumes"]


def test_the_message_cannot_break_out_of_the_variable():
    """The label sits inside Compose's own ${...}: a } or $ in it would end or nest it."""
    entry = {
        "name": "X",
        "slug": "x",
        "docker": {
            "image": "x/x:1.0.0",
            "env": [{"key": "DATA", "label": "Data dir } $HOME", "required": True}],
            "volumes": ["${DATA}:/data"],
        },
    }
    volume = compose_generator._service_to_compose(entry)["volumes"][0]
    message = volume[len("${DATA:?") : volume.rindex("}")]
    assert "}" not in message and "$" not in message, volume


def test_a_blank_required_path_is_unfilled_too():
    """Supplied but empty must not export the mount ":/app/identity"."""
    compose = _storj({"IDENTITY_DIR": "", "STORAGE_DIR": "   "})
    volumes = compose["services"]["cashpilot-storj"]["volumes"]
    assert any(v.startswith("${IDENTITY_DIR:?") for v in volumes), volumes
    assert any(v.startswith("${STORAGE_DIR:?") for v in volumes), volumes
    assert not any(v.startswith(":") or v.startswith(" ") for v in volumes), volumes


def test_a_blank_optional_value_is_still_written_as_given():
    """Only REQUIRED settings fall back: a deliberately empty optional value stays empty."""
    entry = {
        "name": "X",
        "slug": "x",
        "docker": {"image": "x/x:1.0.0", "env": [{"key": "OPT", "required": False, "default": "d"}]},
    }
    assert compose_generator._service_to_compose(entry, env_vars={"OPT": ""})["environment"]["OPT"] == ""
