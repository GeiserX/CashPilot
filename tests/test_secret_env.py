"""CASHPILOT_EARNER_SECRETS=file: earner credentials outside Docker's config (app/secret_env.py)."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import secret_env

ROOT = Path(__file__).resolve().parent.parent

HONEYGAIN = {
    "slug": "honeygain",
    "docker": {
        "env": [
            {"key": "HONEYGAIN_EMAIL"},
            {"key": "HONEYGAIN_PASSWORD", "secret": True},
            {"key": "HONEYGAIN_DEVICE_NAME"},
        ]
    },
}
ENV = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "hunter2", "HONEYGAIN_DEVICE_NAME": "box"}
COMMAND = "-tou-accept -email me@example.com -pass hunter2 -device box"


@pytest.fixture
def on(monkeypatch, tmp_path):
    shim = tmp_path / "cashpilot-env"
    shim.write_bytes(b"\x7fELF shim")
    monkeypatch.setattr(secret_env, "SHIM_BINARY", shim)
    monkeypatch.setenv(secret_env.MODE_ENV, "file")
    return shim


def _plan(**over):
    kwargs = dict(
        slug="honeygain",
        service=HONEYGAIN,
        env=dict(ENV),
        command=COMMAND,
        entrypoint=None,
        image_config={"Entrypoint": ["/app/honeygain"], "Cmd": ["-h"]},
    )
    kwargs.update(over)
    return secret_env.plan(**kwargs)


class TestOffByDefault:
    def test_unset_means_the_plain_environment(self, monkeypatch):
        monkeypatch.delenv(secret_env.MODE_ENV, raising=False)
        assert secret_env.mode() == "env"
        assert _plan() is None

    def test_any_other_value_too(self, on, monkeypatch):
        monkeypatch.setenv(secret_env.MODE_ENV, "yes")
        assert _plan() is None


class TestThePlan:
    def test_the_secret_leaves_the_environment_and_the_command(self, on):
        p = _plan()
        assert p.env == {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_DEVICE_NAME": "box"}
        assert p.entrypoint == [secret_env.SHIM_PATH]
        assert p.command == [
            "/app/honeygain",
            "-tou-accept",
            "-email",
            "me@example.com",
            "-pass",
            "${HONEYGAIN_PASSWORD}",
            "-device",
            "box",
        ]
        assert "hunter2" not in str(p.env) + str(p.command) + str(p.labels())
        assert p.labels() == {secret_env.LABEL_KEYS: "HONEYGAIN_PASSWORD", secret_env.LABEL_ENTRYPOINT_LEN: "1"}
        assert p.files["env"] == b"HONEYGAIN_PASSWORD=hunter2\0"

    def test_no_command_keeps_the_image_cmd(self, on):
        p = _plan(command=None)
        assert p.command == ["/app/honeygain", "-h"]

    def test_a_catalog_entrypoint_drops_the_image_cmd_as_docker_does(self, on):
        p = _plan(command=None, entrypoint=["/bin/sh", "-c", 'exec /entrypoint "$@"', "--"])
        assert p.command == ["/bin/sh", "-c", 'exec /entrypoint "$@"', "--"]
        assert p.entrypoint_len == 4

    def test_an_empty_secret_stays_as_it_was(self, on):
        assert _plan(env={**ENV, "HONEYGAIN_PASSWORD": ""}) is None

    def test_a_custom_service_is_never_covered(self, on):
        assert _plan(slug="custom-foo") is None

    def test_a_service_can_opt_out(self, on):
        svc = {**HONEYGAIN, "docker": {**HONEYGAIN["docker"], "secrets_in_file": False}}
        assert _plan(service=svc) is None

    def test_a_worker_image_without_the_shim_keeps_the_environment(self, on):
        on.unlink()
        assert _plan() is None

    def test_an_unreadable_shim_keeps_the_environment_and_never_raises(self, on, monkeypatch):
        """The deploy plans after stopping the old earner, before its rollback: a raise would leave it down."""

        def refuse(self):
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(type(on), "read_bytes", refuse)
        assert _plan() is None

    def test_a_command_that_cannot_be_split_keeps_the_environment_and_never_raises(self, on):
        assert _plan(command="-pass 'hunter2") is None

    def test_a_command_with_the_placeholder_already_is_left_alone(self, on):
        assert _plan(command="-pass ${HONEYGAIN_PASSWORD}") is None

    def test_nothing_to_run_is_left_alone(self, on):
        assert _plan(command=None, image_config={}) is None

    def test_a_password_inside_another_argument_is_hidden_there_too(self, on):
        p = _plan(command="--login=me:hunter2@host")
        assert p.command[-1] == "--login=me:${HONEYGAIN_PASSWORD}@host"


class TestHide:
    @pytest.mark.parametrize(
        ("token", "values"),
        [
            ("PASS", {"BITPING_PASSWORD": "PASS", "X": "ASS"}),
            ("abcab", {"A": "ab", "B": "abc"}),
            ("${abc}", {"A": "abc"}),
            ("$", {"A": "$"}),
            ("plain", {"A": "zzz"}),
        ],
    )
    def test_the_shim_gives_the_token_back(self, token, values):
        hidden = secret_env._hide(token, values)
        assert _expand(hidden, values) == token

    def test_a_placeholder_is_never_searched_again(self):
        # "ASS" is inside the placeholder's own name; a second pass would break it.
        assert secret_env._hide("PASS", {"BITPING_PASSWORD": "PASS", "X": "ASS"}) == "${BITPING_PASSWORD}"


def _expand(text: str, values: dict[str, str]) -> str:
    """The shim's one pass, in Python (the C test below runs the real one)."""
    out, i = [], 0
    while i < len(text):
        if text.startswith("${", i) and (end := text.find("}", i + 2)) >= 0 and text[i + 2 : end] in values:
            out.append(values[text[i + 2 : end]])
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


class TestTheFiles:
    def test_root_images_get_a_root_only_file(self, on):
        p = _plan()
        with tarfile.open(fileobj=io.BytesIO(secret_env.archive(p))) as tar:
            members = {m.name: m for m in tar}
        assert members["env"].uid == 0 and members["env"].mode == 0o400
        assert members["cashpilot-env"].mode == 0o555
        assert not any(m.mode & 0o6000 for m in members.values())

    @pytest.mark.parametrize(
        ("user", "uid", "mode"), [("1000", 1000, 0o400), ("1000:1000", 1000, 0o400), ("node", 0, 0o444)]
    )
    def test_the_file_belongs_to_the_user_that_reads_it(self, on, user, uid, mode):
        p = _plan(image_config={"Entrypoint": ["/x"], "User": user})
        assert (p.uid, p.mode) == (uid, mode)


class TestTheContainer:
    def test_its_shape_is_the_earners(self, on):
        p = _plan()
        attrs = {
            "Config": {"Entrypoint": [secret_env.SHIM_PATH], "Cmd": p.command, "Labels": p.labels()},
            "Mounts": [{"Type": "volume", "Name": p.volume, "Destination": secret_env.SECRET_DIR}],
        }
        assert secret_env.is_shimmed(attrs)
        assert secret_env.logical_view(attrs) == (["/app/honeygain"], ["HONEYGAIN_PASSWORD"])
        container = MagicMock(attrs=attrs)
        assert secret_env.volume_of(container) == p.volume

    def test_an_ordinary_container_is_not_shimmed(self):
        attrs = {"Config": {"Entrypoint": ["/app/honeygain"], "Labels": {}}, "Mounts": []}
        assert not secret_env.is_shimmed(attrs)
        assert secret_env.volume_of(MagicMock(attrs=attrs)) is None

    def test_a_volume_in_use_is_left(self):
        client = MagicMock()
        client.volumes.get.return_value.remove.side_effect = RuntimeError("volume is in use")
        secret_env.remove_volume(client, "cashpilot-secret-x")  # must not raise


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("shim")
    env_file = out / "env"
    binary = out / "cashpilot-env"
    subprocess.run(
        [
            cc,
            "-Os",
            "-Wall",
            "-Werror",
            f'-DENV_FILE="{env_file}"',
            "-o",
            str(binary),
            str(ROOT / "app/shim/cashpilot-env.c"),
        ],
        check=True,
        capture_output=True,
    )
    return binary, env_file


class TestTheShim:
    def test_it_sets_the_variables_and_fills_the_arguments(self, shim):
        binary, env_file = shim
        env_file.write_bytes(b"PASS=s3cr=t $x\0TOKEN=abc\0")
        out = subprocess.run(
            [
                str(binary),
                "sh",
                "-c",
                'printf "%s|%s|%s|%s" "$PASS" "$TOKEN" "$1" "$2"',
                "--",
                "-p=${PASS}",
                "${OTHER}${TOKEN}",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert out == "s3cr=t $x|abc|-p=s3cr=t $x|${OTHER}abc"

    def test_a_missing_file_stops_the_earner(self, shim):
        binary, env_file = shim
        env_file.unlink(missing_ok=True)
        res = subprocess.run([str(binary), "true"], capture_output=True, text=True)
        assert res.returncode == 126 and "cannot open" in res.stderr

    def test_a_missing_program_says_so(self, shim):
        binary, env_file = shim
        env_file.write_bytes(b"A=b\0")
        res = subprocess.run([str(binary), "/nonexistent/earner"], capture_output=True, text=True)
        assert res.returncode == 127 and "/nonexistent/earner" in res.stderr
