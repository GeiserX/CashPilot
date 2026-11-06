"""The importer's parser and its mapping onto the catalog (app/importers).

Fixtures in tests/fixtures/importers are written in each tool's own format
with fake values; their README names the upstream files they follow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import catalog
from app.collectors import _COLLECTOR_ARGS
from app.importers import parse

FIX = Path(__file__).parent / "fixtures" / "importers"
DOCS = Path(__file__).resolve().parents[1] / "docs" / "migrate"


@pytest.fixture(autouse=True, scope="module")
def _catalog():
    catalog.load_services()


def _files(*paths: str) -> list[dict[str, str]]:
    return [{"name": Path(p).name, "content": (FIX / p).read_text(encoding="utf-8")} for p in paths]


def _preview(files, source="auto", extra=None):
    read = parse.read_files(files, source)
    detected = parse.detect_source(read, source)
    return parse.build_preview(read, detected, catalog.get_service, extra)


def _rows(preview):
    return {r["slug"]: r for r in preview["rows"]}


def _field(row, key):
    return next(f for f in row["fields"] if f["key"] == key)


# ---------------------------------------------------------------------------
# Each format
# ---------------------------------------------------------------------------


class TestMoney4bandJson:
    def test_every_app_lands_on_its_catalog_fields(self):
        rows = _rows(_preview(_files("money4band/user-config.json")))
        assert rows["honeygain"]["env"] == {
            "HONEYGAIN_EMAIL": "hg@example.com",
            "HONEYGAIN_PASSWORD": "fake-pass-honeygain",
        }
        assert rows["iproyal"]["env"]["IPROYALPAWNS_EMAIL"] == "ip@example.com"
        assert rows["earnapp"]["env"] == {"EARNAPP_UUID": "sdk-node-0123456789abcdef0123456789abcdef"}
        assert rows["repocket"]["env"] == {
            "RP_EMAIL": "rp@example.com",
            "RP_API_KEY": "11111111-2222-4333-8444-555555555555",
        }
        assert rows["proxyrack"]["env"]["UUID"].startswith("ABCDEF")
        assert rows["proxylite"]["env"] == {"USER_ID": "123456"}
        assert {r["state"] for s, r in rows.items() if s in ("honeygain", "earnapp", "repocket", "bitping")} == {
            "ready"
        }

    def test_a_dollar_in_json_is_the_real_value(self):
        """JSON is what the user typed; only a shell or Compose would expand it."""
        rows = _rows(_preview(_files("money4band/user-config.json")))
        assert rows["iproyal"]["env"]["IPROYALPAWNS_PASSWORD"] == "fake-pass-$iproyal"

    def test_an_app_turned_off_comes_in_unticked(self):
        row = _rows(_preview(_files("money4band/user-config.json")))["earnfm"]
        assert row["state"] == "ready"
        assert row["selected"] is False
        assert row["off_in_source"] is True

    def test_mysterium_comes_in_with_the_identity_warning(self):
        row = _rows(_preview(_files("money4band/user-config.json")))["mysterium"]
        assert row["state"] == "ready"
        assert "new identity" in row["reason"]

    def test_unusable_and_retired_services_are_refused_with_a_reason(self):
        rows = _rows(_preview(_files("money4band/user-config.json")))
        assert rows["proxybase"]["state"] == "unusable"
        assert rows["grass"]["state"] == "unusable"
        assert rows["peer2profit"]["state"] == "not_deployable"
        assert not any(r["selected"] for s, r in rows.items() if s in ("proxybase", "grass", "peer2profit"))

    def test_what_is_left_out_is_listed_by_name(self):
        preview = _preview(_files("money4band/user-config.json"))
        skipped = {s["key"]: s["reason"] for s in preview["not_imported"]}
        assert "antgain" in skipped and "no such service" in skipped["antgain"]
        assert "proxies" in skipped
        assert "device_info" in skipped
        assert "notifications" not in skipped, "a disabled notifications block is not news"
        assert any("Proxy" in n for n in preview["notices"])
        # CashPilot runs proxied copies, so the text points there instead of saying it cannot.
        assert "Fleet page" in skipped["proxies"]
        assert any("Proxies section of the Fleet page" in n for n in preview["notices"])


class TestMoney4bandEnv:
    def test_the_generated_env_maps_like_the_json(self):
        rows = _rows(_preview(_files("money4band/generated.env")))
        assert rows["honeygain"]["env"]["HONEYGAIN_PASSWORD"] == "fake-pass-honeygain"
        assert rows["repocket"]["env"]["RP_API_KEY"] == "11111111-2222-4333-8444-555555555555"
        assert rows["mysterium"]["state"] == "ready"

    def test_the_v3_aliases_work(self):
        rows = _rows(_preview(_files("money4band/v3.env")))
        assert rows["honeygain"]["env"]["HONEYGAIN_PASSWORD"] == "fake-pass-honeygain"
        assert rows["earnapp"]["env"]["EARNAPP_UUID"] == "sdk-node-0123456789abcdef0123456789abcdef"
        assert rows["proxyrack"]["env"]["UUID"].startswith("ABCDEF")
        assert rows["bitping"]["env"]["BITPING_PASSWORD"] == "fake-pass-bitping"

    def test_a_command_substitution_is_never_imported(self):
        row = _rows(_preview(_files("money4band/v3.env")))["iproyal"]
        assert _field(row, "IPROYALPAWNS_PASSWORD")["state"] == "retype"
        assert "IPROYALPAWNS_PASSWORD" not in row["env"]
        assert row["state"] == "missing_fields"

    def test_an_untouched_template_imports_nothing(self):
        assert _preview(_files("money4band/template.env"))["rows"] == []

    def test_an_untouched_json_template_imports_nothing(self):
        # Every app off with placeholder values: the user never set any of them up.
        assert _preview(_files("money4band/template-user-config.json"))["rows"] == []

    def test_only_the_app_filled_in_on_a_json_template_comes_in(self):
        content = (FIX / "money4band/template-user-config.json").read_text(encoding="utf-8")
        content = content.replace(
            '"enabled": false, "email": "yourHONEYGAINMail"', '"enabled": true, "email": "hg@example.com"'
        )
        assert list(_rows(_preview([{"name": "user-config.json", "content": content}]))) == ["honeygain"]

    def test_only_the_service_filled_in_on_a_template_comes_in(self):
        content = (FIX / "money4band/template.env").read_text(encoding="utf-8")
        content = content.replace("yourHONEYGAINMail", "hg@example.com").replace("yourHONEYGAINPw", "fake-pass-x")
        rows = _rows(_preview([{"name": ".env", "content": content}]))
        assert list(rows) == ["honeygain"]
        assert rows["honeygain"]["selected"] and rows["honeygain"]["state"] == "ready"

    def test_a_partly_filled_service_still_comes_in_to_be_completed(self):
        content = "COMPOSE_PROJECT_NAME=money4band\nHONEYGAIN_EMAIL=hg@example.com\nHONEYGAIN_PASSWD=yourHONEYGAINPw\n"
        row = _rows(_preview([{"name": ".env", "content": content}]))["honeygain"]
        assert row["state"] == "missing_fields"
        assert _field(row, "HONEYGAIN_PASSWORD")["state"] == "placeholder"

    def test_the_v3_template_dashboard_port_does_not_turn_mysterium_on(self):
        # money4band 3.x's .env.template always holds MYSTNODE_DASHBOARD_PORT=4449.
        assert "mysterium" not in _rows(_preview(_files("money4band/v3.env")))

    def test_ignored_settings_are_not_listed(self):
        preview = _preview(_files("money4band/generated.env"))
        assert {s["key"] for s in preview["not_imported"]} == {"DEVICE_NAME"}
        # The generator always writes STACK_PROXY_URL_EXAMPLE; it is not a proxy the user set.
        assert not any("Proxy settings" in n for n in preview["notices"])


class TestCashFactory:
    def test_the_env_maps_with_its_own_key_names(self):
        rows = _rows(_preview(_files("cashfactory/.env.sample")))
        assert rows["earnapp"]["env"]["EARNAPP_UUID"] == "sdk-node-0123456789abcdef0123456789abcdef"
        assert rows["honeygain"]["env"]["HONEYGAIN_PASSWORD"] == "fake-pass-honeygain"
        assert rows["proxyrack"]["env"]["UUID"].startswith("ABCDEF")
        assert rows["earnfm"]["env"]["EARNFM_TOKEN"] == "fake-token-earnfm"

    def test_quotes_and_inline_comments_are_read_like_compose(self):
        rows = _rows(_preview(_files("cashfactory/.env.sample")))
        assert rows["repocket"]["env"]["RP_EMAIL"] == "rp@example.com"
        assert rows["traffmonetizer"]["env"]["TRAFFMONETIZER_TOKEN"] == "fake-token-traffmonetizer"
        assert rows["iproyal"]["env"]["IPROYALPAWNS_PASSWORD"] == "fake-pass-iproyal"

    def test_the_template_placeholders_are_unset(self):
        assert _preview(_files("cashfactory/template.env"))["rows"] == []

    def test_one_service_filled_in_on_the_template_is_the_only_row(self):
        content = (FIX / "cashfactory/template.env").read_text(encoding="utf-8")
        content = content.replace("HONEYGAIN_EMAIL=<email>", "HONEYGAIN_EMAIL=hg@example.com")
        content = content.replace("HONEYGAIN_PASSWD=<password>", "HONEYGAIN_PASSWD=fake-pass-x")
        rows = _rows(_preview([{"name": ".env", "content": content}]))
        assert [slug for slug, r in rows.items() if r["selected"]] == ["honeygain"]
        assert rows["honeygain"]["state"] == "ready"


class TestInternetIncome:
    FILES = ("internetincome/properties.conf", "internetincome/earnapp.txt", "internetincome/proxyrack.txt")

    def test_properties_and_state_files_map(self):
        rows = _rows(_preview(_files(*self.FILES)))
        assert rows["earnapp"]["env"] == {"EARNAPP_UUID": "sdk-node-0123456789abcdef0123456789abcdef"}
        assert rows["proxyrack"]["env"] == {
            "API_KEY": "fake-key-proxyrack",
            "UUID": "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",
        }
        assert rows["proxybase"]["env"] == {"ID": "fake-token-proxybase"}
        assert rows["earnfm"]["env"] == {"EARNFM_TOKEN": "fake-token-earnfm"}
        assert rows["mysterium"]["state"] == "ready"

    def test_a_proxies_list_is_recognised_and_carries_no_values(self):
        text = "socks5://user:fake-pass@192.0.2.1:1080\nhttp://192.0.2.2:8080\n"
        got = parse._state_file("proxies.txt", text)
        assert got is not None and got.kind == "proxies" and got.env == {} and got.extra_lines == 2

    @pytest.mark.parametrize("line", ["0" * 20000, "socks5://", "://192.0.2.1:1080", "HTTP://192.0.2.1", "http://a b"])
    def test_a_line_that_is_not_a_proxy_url_is_not_a_proxies_list(self, line):
        assert parse._state_file("proxies.txt", line + "\n") is None

    def test_single_quotes_keep_a_literal_dollar(self):
        rows = _rows(_preview(_files(*self.FILES)))
        assert rows["iproyal"]["env"]["IPROYALPAWNS_PASSWORD"] == "fake-pass-$dollar"

    def test_an_unquoted_variable_is_marked_for_retyping(self):
        row = _rows(_preview(_files(*self.FILES)))["honeygain"]
        assert _field(row, "HONEYGAIN_PASSWORD")["state"] == "retype"
        assert "HONEYGAIN_PASSWORD" not in row["env"]

    def test_extra_earnapp_lines_are_reported_not_imported(self):
        preview = _preview(_files(*self.FILES))
        assert any("1 more device" in n for n in preview["notices"])
        assert "fedcba" not in json.dumps(preview["rows"])

    def test_a_required_field_the_tool_never_had_is_asked_for(self):
        row = _rows(_preview(_files(*self.FILES)))["repocket"]
        assert _field(row, "RP_EMAIL")["state"] == "missing"
        assert row["state"] == "missing_fields"

    def test_blank_values_and_false_switches_are_off(self):
        preview = _preview(_files("internetincome/template.conf"), "internetincome")
        assert preview["rows"] == []
        assert {s["key"] for s in preview["not_imported"]} == {"DEVICE_NAME"}

    def test_an_unmarked_file_is_read_like_internetincome_when_another_file_says_so(self):
        # Only earnapp.txt names the tool, but every value still went through InternetIncome's shell.
        files = [
            {"name": "properties.conf", "content": "HONEYGAIN_EMAIL=a@example.com\nHONEYGAIN_PASSWORD=p\\@ss~x\n"},
            *_files("internetincome/earnapp.txt"),
        ]
        auto = _rows(_preview(files))["honeygain"]
        assert _field(auto, "HONEYGAIN_PASSWORD")["state"] == "retype"
        assert "HONEYGAIN_PASSWORD" not in auto["env"]
        picked = _rows(_preview(files, "internetincome"))["honeygain"]
        assert _field(picked, "HONEYGAIN_PASSWORD")["state"] == "retype"

    def test_earnapp_on_without_its_file_asks_for_the_device(self):
        files = [{"name": "properties.conf", "content": "EARNAPP=true\nREPOCKET_API=\n"}]
        row = _rows(_preview(files, "internetincome"))["earnapp"]
        assert row["state"] == "missing_fields"
        assert "earnapp.txt" in row["reason"]


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


class TestValues:
    @pytest.mark.parametrize(
        ("raw", "shell", "expected"),
        [
            ("plain", False, "plain"),
            ("'sin$gle'", False, "sin$gle"),
            ("'sin$gle'", True, "sin$gle"),
            ('"dou ble"', False, "dou ble"),
            ("value # comment", False, "value"),
            ("pa#ss", False, "pa#ss"),
            ("", False, ""),
        ],
    )
    def test_read(self, raw, shell, expected):
        assert parse._read_env_value(raw, shell) == parse.Value(expected)

    @pytest.mark.parametrize(
        ("raw", "shell"),
        [
            ("$(id)", False),
            ("pre$VAR", False),
            ("`id`", False),
            ('"has $VAR"', False),
            ('"back\\slash"', False),
            ("'unterminated", False),
            ("'it'\\''s'", True),
            ("a*b", True),
            ("semi;colon", True),
            ("back\\slash", True),
        ],
    )
    def test_anything_a_shell_or_compose_would_change_needs_retyping(self, raw, shell):
        assert parse._read_env_value(raw, shell) == parse.Value(None, retype=True)

    @pytest.mark.parametrize(
        "text", ["", "  ", "<email>", "sdk-node-<md5sum>", "yourHONEYGAINMail", "sdk-node-yourEARNAPPDeviceUUID"]
    )
    def test_placeholders(self, text):
        assert parse.is_placeholder(text)

    @pytest.mark.parametrize("text", ["hg@example.com", "your-own-pass", "123456"])
    def test_real_values_are_not_placeholders(self, text):
        assert not parse.is_placeholder(text)

    def test_a_bad_earnapp_id_is_invalid_and_shown(self):
        files = [{"name": ".env", "content": "_COMPOSE_PROJECT_NAME=cashfactory\nEARNAPP_DEVICE_ID=sdk-node-XYZ\n"}]
        row = _rows(_preview(files))["earnapp"]
        assert row["state"] == "invalid"
        field = _field(row, "EARNAPP_UUID")
        assert field["state"] == "invalid" and field["value"] == "sdk-node-XYZ"
        assert row["env"] == {}

    def test_a_typed_value_fills_a_missing_field_and_is_checked(self):
        files = _files("internetincome/properties.conf")
        good = _rows(_preview(files, extra={"repocket": {"RP_EMAIL": "rp@example.com"}}))["repocket"]
        assert good["state"] == "ready" and good["env"]["RP_EMAIL"] == "rp@example.com"
        bad = _rows(_preview(files, extra={"earnapp": {"EARNAPP_UUID": "nope"}}))["earnapp"]
        assert bad["state"] == "invalid"

    def test_a_secret_is_never_in_a_field_entry(self):
        rows = _preview(_files("money4band/user-config.json"))["rows"]
        for row in rows:
            for field in row["fields"]:
                if field["secret"]:
                    assert "value" not in field


# ---------------------------------------------------------------------------
# Which tool
# ---------------------------------------------------------------------------


class TestDetection:
    @pytest.mark.parametrize(
        ("path", "tool"),
        [
            ("money4band/user-config.json", "money4band"),
            ("money4band/generated.env", "money4band"),
            ("money4band/v3.env", "money4band"),
            ("cashfactory/.env.sample", "cashfactory"),
            ("internetincome/properties.conf", "internetincome"),
            ("internetincome/earnapp.txt", "internetincome"),
        ],
    )
    def test_each_tool_is_recognised(self, path, tool):
        assert parse.detect_source(parse.read_files(_files(path))) == tool

    def test_two_tools_at_once_are_refused(self):
        files = _files("money4band/user-config.json", "cashfactory/.env.sample")
        with pytest.raises(parse.ImportRefused, match="different tools"):
            parse.detect_source(parse.read_files(files))

    def test_one_file_with_two_tools_markers_is_refused(self):
        content = "COMPOSE_PROJECT_NAME=money4band\n_COMPOSE_PROJECT_NAME=cashfactory\nPACKETSTREAM_CID=FakeCid1\n"
        with pytest.raises(parse.ImportRefused, match="more than one tool"):
            parse.detect_source(parse.read_files([{"name": ".env", "content": content}]))

    def test_a_file_that_names_no_tool_asks_the_owner(self):
        with pytest.raises(parse.ImportRefused, match="Pick the tool"):
            parse.detect_source(parse.read_files([{"name": "x", "content": "HONEYGAIN_EMAIL=a@example.com\n"}]))

    def test_the_owner_can_pick_for_an_unmarked_file(self):
        files = [{"name": "x", "content": "HONEYGAIN_EMAIL=a@example.com\nHONEYGAIN_PASSWD=fake-pass-x\n"}]
        assert parse.detect_source(parse.read_files(files, "cashfactory"), "cashfactory") == "cashfactory"

    def test_a_pick_that_contradicts_the_files_is_refused(self):
        files = _files("cashfactory/.env.sample")
        with pytest.raises(parse.ImportRefused, match="CashFactory"):
            parse.detect_source(parse.read_files(files, "money4band"), "money4band")

    def test_no_two_tools_share_a_marker(self):
        tools = parse.SOURCES_DATA["tools"]
        seen: dict[str, str] = {}
        for name, spec in tools.items():
            for key in spec["markers"]["keys"]:
                assert key not in seen, f"{key} marks both {seen[key]} and {name}"
                seen[key] = name


# ---------------------------------------------------------------------------
# Hostile input
# ---------------------------------------------------------------------------


class TestHostileInput:
    def test_too_many_files(self):
        with pytest.raises(parse.ImportRefused):
            parse.read_files([{"name": str(i), "content": "A=1"} for i in range(5)])

    def test_too_big_is_413(self):
        with pytest.raises(parse.ImportRefused) as err:
            parse.read_files([{"name": "big", "content": "A=" + "x" * (parse.MAX_TOTAL_BYTES)}])
        assert err.value.status == 413

    def test_too_many_lines(self):
        with pytest.raises(parse.ImportRefused, match="lines"):
            parse.read_files([{"name": "f", "content": "\n" * 6000}])

    def test_a_long_line(self):
        with pytest.raises(parse.ImportRefused, match="line longer"):
            parse.read_files([{"name": "f", "content": "A=" + "x" * 9000}])

    def test_a_nul_byte(self):
        with pytest.raises(parse.ImportRefused, match="not a text file"):
            parse.read_files([{"name": "f", "content": "A=1\x00"}])

    def test_a_lone_surrogate(self):
        with pytest.raises(parse.ImportRefused, match="UTF-8"):
            parse.read_files([{"name": "f", "content": "A=\ud800"}])

    def test_a_decoded_nul_is_an_invalid_value(self):
        # The raw text has no NUL, so read_files passes it; the JSON escape decodes to one.
        conf = {"enabled": True, "email": "hg@example.com"}
        conf["password"] = "a\x00b"  # ggignore: fake test value, not a credential
        content = json.dumps({"apps": {"honeygain": conf}})
        assert "\\u0000" in content and "\x00" not in content
        row = _rows(_preview([{"name": "user-config.json", "content": content}], "money4band"))["honeygain"]
        assert row["state"] != "ready"
        assert _field(row, "HONEYGAIN_PASSWORD")["state"] == "invalid"

    @pytest.mark.parametrize("depth", [25, 5000])
    def test_deep_json(self, depth):
        with pytest.raises(parse.ImportRefused):
            parse.read_files([{"name": "f.json", "content": '{"a":' * depth + "1" + "}" * depth}])

    def test_too_many_json_keys(self):
        content = json.dumps({f"k{i}": 1 for i in range(1200)}, indent=0)
        with pytest.raises(parse.ImportRefused, match="keys"):
            parse.read_files([{"name": "f.json", "content": content}])

    def test_json_that_is_not_an_object(self):
        with pytest.raises(parse.ImportRefused):
            parse.read_files([{"name": "f.json", "content": "{"}])

    @pytest.mark.parametrize("files", [None, [], "x", [1], [{"name": "a"}], [{"name": "a", "content": 3}]])
    def test_malformed_file_lists(self, files):
        with pytest.raises(parse.ImportRefused):
            parse.read_files(files)

    def test_a_bom_and_crlf_are_fine(self):
        content = "\ufeff_COMPOSE_PROJECT_NAME=cashfactory\r\nPACKETSTREAM_CID=FakeCid1\r\n"
        rows = _rows(_preview([{"name": ".env", "content": content}]))
        assert rows["packetstream"]["env"] == {"CID": "FakeCid1"}

    def test_odd_lines_are_skipped_not_fatal(self):
        content = "_COMPOSE_PROJECT_NAME=cashfactory\nnot a setting\n1BAD=x\n=x\nexport PACKETSTREAM_CID=FakeCid1\n"
        rows = _rows(_preview([{"name": ".env", "content": content}]))
        assert rows["packetstream"]["env"] == {"CID": "FakeCid1"}

    def test_a_huge_json_value_is_not_imported(self):
        data = {"apps": {"honeygain": {"enabled": True, "email": "a@example.com", "password": "x" * 5000}}}
        row = _rows(_preview([{"name": "u.json", "content": json.dumps(data)}]))["honeygain"]
        assert _field(row, "HONEYGAIN_PASSWORD")["state"] == "retype"

    def test_non_string_json_leaves_are_ignored(self):
        data = {"apps": {"honeygain": {"enabled": True, "email": ["a"], "password": {"x": 1}}, "earnapp": "nope"}}
        row = _rows(_preview([{"name": "u.json", "content": json.dumps(data)}]))["honeygain"]
        assert row["env"] == {}


# ---------------------------------------------------------------------------
# The mapping stays true to the catalog
# ---------------------------------------------------------------------------


def _all_apps():
    for tool, spec in parse.SOURCES_DATA["tools"].items():
        for app_name, app in spec["apps"].items():
            yield tool, app_name, app


class TestMappingIntegrity:
    @pytest.mark.parametrize(
        ("tool", "app_name", "app"), list(_all_apps()), ids=lambda v: v if isinstance(v, str) else ""
    )
    def test_every_slug_and_field_exists_in_the_catalog(self, tool, app_name, app):
        svc = catalog.get_service(app["slug"])
        assert svc, f"{tool}.{app_name}: no catalog service {app['slug']}"
        env = {v["key"]: v for v in (svc.get("docker") or {}).get("env") or []}
        for key in app.get("fields") or {}:
            assert key in env, f"{tool}.{app_name}: {app['slug']} has no env {key}"
            # Only the pattern is checked in the dry run; a port_range field
            # would need api_deploy's range check too.
            assert not env[key].get("port_range"), f"{key} has a port_range the dry run does not check"

    def test_collector_links_match_the_collectors_and_the_catalog(self):
        for slug, mapping in parse.SOURCES_DATA["collector_links"].items():
            args = [a.lstrip("?") for a in _COLLECTOR_ARGS[slug]]
            env = {v["key"] for v in catalog.get_service(slug)["docker"]["env"]}
            for key, arg in mapping.items():
                assert key in env
                assert arg in args

    @pytest.mark.parametrize("tool", sorted(parse.SOURCES_DATA["tools"]))
    def test_every_app_is_named_in_the_tools_guide(self, tool):
        page = (DOCS / f"{tool}.md").read_text(encoding="utf-8")
        for app_name in parse.SOURCES_DATA["tools"][tool]["apps"]:
            assert f"`{app_name}`" in page, f"docs/migrate/{tool}.md does not mention {app_name}"
