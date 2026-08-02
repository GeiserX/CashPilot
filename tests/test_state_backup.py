"""Encrypted state export (CashPilot-qqo).

The tests that matter here are not "does it round-trip" — that is the easy half.
They are the ones asserting the properties that make this feature safe to have
at all, because a backup feature that CashPilot can decrypt is a worse thing to
own than no backup feature.
"""

from __future__ import annotations

import json

import pytest

from app import state_backup as sb


def _module_ast():
    import ast
    import pathlib

    return ast.parse(pathlib.Path(sb.__file__).read_text(encoding="utf-8"))


def _modules_imported() -> set[str]:
    import ast

    found: set[str] = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _names_used() -> set[str]:
    import ast

    found: set[str] = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _strings_used() -> set[str]:
    import ast

    tree = _module_ast()
    docstrings = {
        ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, ast.Module | ast.FunctionDef | ast.ClassDef)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings
    }


PASSPHRASE = "a-long-enough-passphrase"
PAYLOAD = b"node-identity-keystore-bytes"


class TestTheInstallationCannotDecryptItsOwnExports:
    """The single property the whole design exists to provide."""

    def test_a_recipient_bundle_needs_the_private_key_nobody_here_holds(self):
        _, public = sb.generate_recipient_keypair()
        bundle = sb.seal(PAYLOAD, recipient_public_key=public)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bundle, passphrase=PASSPHRASE)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bundle)

    def test_the_public_key_alone_cannot_open_it(self):
        _, public = sb.generate_recipient_keypair()
        bundle = sb.seal(PAYLOAD, recipient_public_key=public)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bundle, recipient_private_key=public)

    def test_a_different_private_key_cannot_open_it(self):
        _, public = sb.generate_recipient_keypair()
        other_private, _ = sb.generate_recipient_keypair()
        bundle = sb.seal(PAYLOAD, recipient_public_key=public)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bundle, recipient_private_key=other_private)

    def test_the_generated_private_key_is_returned_and_not_retained(self):
        """It is handed to the caller once; nothing here may keep a copy."""
        private, public = sb.generate_recipient_keypair()
        assert private != public
        assert len(bytes.fromhex(private)) == 32
        assert not (_names_used() & {"write_text", "write_bytes", "sqlite3", "connect"}), (
            "the backup module must not persist anything"
        )

    def test_no_fernet_or_server_key_is_referenced_in_code(self):
        """Checked against the AST, not the text.

        A substring search over the source also matches the docstring that
        EXPLAINS why there is no server-held key, so it fails on the very
        comment documenting the property. Only real references count.
        """
        forbidden = {"Fernet", "fernet_key", "CASHPILOT_ENCRYPTION_KEY", "CASHPILOT_SECRET_KEY"}
        used = _names_used() | _strings_used()
        assert not (used & forbidden), (
            f"{used & forbidden} referenced in the backup module — a server-held key would let a "
            "compromised installation open every bundle it ever produced"
        )


class TestThereIsNoWayToSendABundleAnywhere:
    """The absence of transport code is the control, not a policy."""

    def test_the_module_imports_no_network_client(self):
        """Checked against the import graph, not the text.

        The docstring mentions "the Docker socket" while explaining the threat
        model, so a substring search reports a socket import that does not
        exist.
        """
        forbidden = {"httpx", "requests", "urllib", "urllib.request", "smtplib", "boto3", "socket", "ftplib"}
        imported = _modules_imported()
        assert not (imported & forbidden), f"{imported & forbidden} would make an upload path possible"

    def test_it_imports_only_stdlib_and_the_existing_crypto_dependency(self):
        allowed_prefixes = ("hashlib", "json", "secrets", "typing", "cryptography", "__future__", "os", "pathlib")
        stray = {m for m in _modules_imported() if not m.startswith(allowed_prefixes)}
        assert not stray, f"unexpected dependency in the backup module: {stray}"


class TestTamperingIsDetected:
    def test_a_modified_ciphertext_is_rejected(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        flipped = bytearray(bundle)
        flipped[-1] ^= 0x01
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bytes(flipped), passphrase=PASSPHRASE)

    def test_swapping_the_metadata_invalidates_the_bundle(self):
        """The header is authenticated, so a bundle cannot be relabelled.

        The replacement keeps the header LENGTH identical, so this really does
        exercise the AEAD rather than tripping the length prefix.
        """
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE, metadata={"slug": "mysterium"})
        relabelled = bundle.replace(b'"slug":"mysterium"', b'"slug":"MYSTERIUM"')
        assert relabelled != bundle
        assert len(relabelled) == len(bundle)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(relabelled, passphrase=PASSPHRASE)

    def test_a_truncated_bundle_is_rejected(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        with pytest.raises(sb.BackupError):
            sb.open_bundle(bundle[:-4], passphrase=PASSPHRASE)

    @pytest.mark.parametrize("junk", [b"", b"abc", b"\x00\x00\x00\x05hello", b"x" * 200])
    def test_junk_is_not_mistaken_for_a_bundle(self, junk):
        assert sb.looks_like_bundle(junk) is False
        with pytest.raises(sb.BackupError):
            sb.read_header(junk)


class TestPassphraseMode:
    def test_it_round_trips(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        assert sb.open_bundle(bundle, passphrase=PASSPHRASE) == PAYLOAD

    def test_a_wrong_passphrase_fails_without_saying_which_part_was_wrong(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        with pytest.raises(sb.BackupError) as exc:
            sb.open_bundle(bundle, passphrase="a-different-passphrase")
        assert "no recovery" in str(exc.value).lower()

    def test_a_short_passphrase_is_refused_at_creation(self):
        """The only thing between a stolen bundle and a node identity."""
        with pytest.raises(sb.BackupError) as exc:
            sb.seal(PAYLOAD, passphrase="short")
        assert str(sb.MIN_PASSPHRASE_LENGTH) in str(exc.value)

    def test_two_bundles_of_the_same_payload_differ(self):
        """Fresh salt and nonce each time, so bundles are not comparable."""
        a = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        b = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        assert a != b


class TestModeSelection:
    def test_exactly_one_target_is_required(self):
        with pytest.raises(sb.BackupError):
            sb.seal(PAYLOAD)
        with pytest.raises(sb.BackupError):
            sb.seal(PAYLOAD, passphrase=PASSPHRASE, recipient_public_key="00" * 32)

    def test_a_malformed_recipient_key_is_refused(self):
        for bad in ("not-hex", "aa", "zz" * 32):
            with pytest.raises(sb.BackupError):
                sb.seal(PAYLOAD, recipient_public_key=bad)


class TestTheHeaderNeverCarriesSecrets:
    def test_no_key_material_appears_in_the_header(self):
        _, public = sb.generate_recipient_keypair()
        for bundle in (
            sb.seal(PAYLOAD, passphrase=PASSPHRASE, metadata={"slug": "storj"}),
            sb.seal(PAYLOAD, recipient_public_key=public, metadata={"slug": "storj"}),
        ):
            header = json.dumps(sb.read_header(bundle))
            assert PASSPHRASE not in header
            assert PAYLOAD.decode() not in header

    def test_the_header_is_readable_without_any_secret(self):
        """A user must be able to see WHICH service a bundle belongs to."""
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE, metadata={"slug": "mysterium", "worker": "watchtower"})
        header = sb.read_header(bundle)
        assert header["metadata"]["slug"] == "mysterium"
        assert header["mode"] == sb.MODE_PASSPHRASE


class TestVerifyAnswersIsMyBackupActuallyGood:
    def test_a_matching_backup_reports_a_match(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        out = sb.verify(bundle, PAYLOAD, passphrase=PASSPHRASE)
        assert out["ok"] is True and out["matches"] is True

    def test_a_stale_backup_reports_a_mismatch_rather_than_failing(self):
        """Out of date is a different answer from broken, and both matter."""
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        out = sb.verify(bundle, b"the volume has moved on since", passphrase=PASSPHRASE)
        assert out["ok"] is True
        assert out["matches"] is False
        assert "out of date" in out["reason"]

    def test_an_unopenable_backup_reports_not_ok(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        out = sb.verify(bundle, PAYLOAD, passphrase="the-wrong-passphrase")
        assert out["ok"] is False and out["matches"] is False

    def test_verify_compares_digests_not_plaintext(self):
        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        out = sb.verify(bundle, PAYLOAD, passphrase=PASSPHRASE)
        assert PAYLOAD.decode() not in json.dumps(out)
        assert out["backup_sha256"] == out["live_sha256"]


class TestLargerPayloads:
    def test_a_realistic_keystore_sized_payload_round_trips(self):
        import os

        payload = os.urandom(256 * 1024)
        bundle = sb.seal(payload, passphrase=PASSPHRASE)
        assert sb.open_bundle(bundle, passphrase=PASSPHRASE) == payload

    def test_an_empty_payload_is_still_authenticated(self):
        bundle = sb.seal(b"", passphrase=PASSPHRASE)
        assert sb.open_bundle(bundle, passphrase=PASSPHRASE) == b""


class TestTheWorkerReadsOnlyIrreplaceableState:
    """It reads the catalog's critical_volumes, never the whole container."""

    def _container(self, status="running"):
        from unittest.mock import MagicMock

        c = MagicMock()
        c.status = status
        c.get_archive.return_value = ([b"tar-bytes"], {})
        return c

    def test_a_service_with_no_critical_volumes_is_refused(self):
        from unittest.mock import patch

        from app import orchestrator

        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value=None),
            pytest.raises(ValueError, match="no critical_volumes"),
        ):
            orchestrator.read_critical_state("honeygain")

    def test_only_the_declared_targets_are_read(self):
        from unittest.mock import patch

        from app import orchestrator

        container = self._container()
        targets = {"/var/lib/mysterium/keystore": "node identity"}
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value=targets),
            patch.object(orchestrator, "_find_container", return_value=container),
        ):
            payload, read = orchestrator.read_critical_state("mysterium")
        assert read == ["/var/lib/mysterium/keystore"]
        assert payload == b"tar-bytes"
        container.get_archive.assert_called_once_with("/var/lib/mysterium/keystore")

    def test_a_running_container_is_paused_and_unpaused(self):
        """A keystore copied mid-write restores a corrupt node."""
        from unittest.mock import patch

        from app import orchestrator

        container = self._container(status="running")
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value={"/data": "x"}),
            patch.object(orchestrator, "_find_container", return_value=container),
        ):
            orchestrator.read_critical_state("storj")
        container.pause.assert_called_once()
        container.unpause.assert_called_once()

    def test_it_unpauses_even_when_the_read_fails(self):
        """Leaving a paused earner behind would stop the income silently."""
        from unittest.mock import patch

        from app import orchestrator

        container = self._container(status="running")
        container.get_archive.side_effect = RuntimeError("docker exploded")
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value={"/data": "x"}),
            patch.object(orchestrator, "_find_container", return_value=container),
            pytest.raises(RuntimeError),
        ):
            orchestrator.read_critical_state("storj")
        container.unpause.assert_called_once()

    def test_a_stopped_container_is_not_paused(self):
        from unittest.mock import patch

        from app import orchestrator

        container = self._container(status="exited")
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value={"/data": "x"}),
            patch.object(orchestrator, "_find_container", return_value=container),
        ):
            orchestrator.read_critical_state("storj")
        container.pause.assert_not_called()
        container.unpause.assert_not_called()


class TestTheWorkerEndpoints:
    def _call(self, coro):
        import asyncio

        return asyncio.run(coro)

    def _request(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_export_returns_ciphertext_the_ui_cannot_read(self):
        import base64
        from unittest.mock import patch

        from app import worker_api

        body = worker_api.BackupRequest(passphrase=PASSPHRASE)
        with (
            patch.object(worker_api, "_verify_api_key", lambda r: None),
            patch.object(worker_api.orchestrator, "read_critical_state", return_value=(PAYLOAD, ["/data"])),
        ):
            out = self._call(worker_api.api_backup("mysterium", body, self._request()))

        bundle = base64.b64decode(out["bundle_b64"])
        assert PAYLOAD not in bundle, "the plaintext state appears in the response"
        assert sb.open_bundle(bundle, passphrase=PASSPHRASE) == PAYLOAD
        assert sb.read_header(bundle)["metadata"]["slug"] == "mysterium"

    def test_export_rejects_a_short_passphrase_without_reading_state(self):
        from unittest.mock import patch

        from fastapi import HTTPException

        from app import worker_api

        body = worker_api.BackupRequest(passphrase="short")
        with (
            patch.object(worker_api, "_verify_api_key", lambda r: None),
            patch.object(worker_api.orchestrator, "read_critical_state", return_value=(PAYLOAD, ["/data"])),
            pytest.raises(HTTPException) as exc,
        ):
            self._call(worker_api.api_backup("mysterium", body, self._request()))
        assert exc.value.status_code == 400

    @pytest.mark.parametrize("name", ["api_backup", "api_backup_verify"])
    def test_both_routes_check_the_fleet_key_first(self, name):
        import ast
        import inspect
        import textwrap

        from app import worker_api

        fn = getattr(worker_api, name)
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        calls = [n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert "_verify_api_key" in calls, f"{name} does not verify the fleet key"

    def test_verify_reports_a_match_without_producing_plaintext(self):
        import base64
        import json as _json
        from unittest.mock import patch

        from app import worker_api

        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE, metadata={"slug": "mysterium"})
        body = worker_api.VerifyRequest(passphrase=PASSPHRASE, bundle_b64=base64.b64encode(bundle).decode())
        with (
            patch.object(worker_api, "_verify_api_key", lambda r: None),
            patch.object(worker_api.orchestrator, "read_critical_state", return_value=(PAYLOAD, ["/data"])),
        ):
            out = self._call(worker_api.api_backup_verify("mysterium", body, self._request()))
        assert out["matches"] is True
        assert PAYLOAD.decode() not in _json.dumps(out)

    def test_verify_reports_a_stale_backup(self):
        import base64
        from unittest.mock import patch

        from app import worker_api

        bundle = sb.seal(PAYLOAD, passphrase=PASSPHRASE)
        body = worker_api.VerifyRequest(passphrase=PASSPHRASE, bundle_b64=base64.b64encode(bundle).decode())
        with (
            patch.object(worker_api, "_verify_api_key", lambda r: None),
            patch.object(worker_api.orchestrator, "read_critical_state", return_value=(b"moved on", ["/data"])),
        ):
            out = self._call(worker_api.api_backup_verify("mysterium", body, self._request()))
        assert out["ok"] is True and out["matches"] is False

    def test_verify_rejects_a_file_that_is_not_a_bundle(self):
        import base64
        from unittest.mock import patch

        from fastapi import HTTPException

        from app import worker_api

        body = worker_api.VerifyRequest(passphrase=PASSPHRASE, bundle_b64=base64.b64encode(b"holiday.jpg").decode())
        with patch.object(worker_api, "_verify_api_key", lambda r: None), pytest.raises(HTTPException) as exc:
            self._call(worker_api.api_backup_verify("mysterium", body, self._request()))
        assert exc.value.status_code == 400

    def test_no_worker_route_uploads_a_bundle_anywhere(self):
        """The only egress is the authenticated response.

        Checked against the AST: the docstrings EXPLAIN that there is no upload
        path, so a substring search matches the very prose documenting the
        guarantee.
        """
        import ast
        import inspect
        import textwrap

        from app import worker_api

        forbidden = {"post", "put", "send", "upload", "publish"}
        for fn in (worker_api.api_backup, worker_api.api_backup_verify):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            # Only statements INSIDE the function. The route decorator is
            # `@app.post(...)`, so walking the whole tree flags the very thing
            # that makes it an endpoint.
            statements = [
                stmt
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
                for stmt in node.body
            ]
            attrs = {
                n.func.attr
                for stmt in statements
                for n in ast.walk(stmt)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
            leaked = attrs & forbidden
            assert not leaked, f"{fn.__name__} calls {leaked}, which could send a bundle somewhere"
