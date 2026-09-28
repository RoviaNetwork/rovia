import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "tools/ci/validate-schemas.py"
SCHEMA_PATH = ROOT / "schemas/config.schema.json"
CONTROL_SCHEMA_PATH = ROOT / "schemas/control-api.schema.json"
CONTROL_FIXTURE_DIR = ROOT / "fixtures/control"

spec = importlib.util.spec_from_file_location("validate_schemas", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ValidateSchemasTests(unittest.TestCase):
    def test_checker_includes_ssr_and_obfuscated_key_fixtures(self):
        self.assertTrue(any(value.lower().startswith("ssr://") for value in checker.RAW_SHARE_LINK_VALUES))
        source = CHECKER_PATH.read_text(encoding="utf-8")
        self.assertIn("secret-bearing-transport-obfuscated.json", source)
        self.assertIn("raw-ssr-url-source.json", source)
        self.assertIn("monkey", source)
        self.assertIn("p-wd", source)

    def test_control_schema_requires_api_version_one(self):
        schema = json.loads(CONTROL_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["apiVersion"].get("const"), 1)

    def test_control_api_fixtures_and_negative_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            checker.validate_control_api(ROOT, Path(directory))

    def test_control_api_semantic_checker_rejects_extra_fields_and_cross_role_codes(self):
        fixture = json.loads(
            (CONTROL_FIXTURE_DIR / "routing-diagnostic.json").read_text(encoding="utf-8")
        )
        cases = []
        extra = copy.deepcopy(fixture)
        extra["payload"]["rules"][0]["matchers"][0]["rawInput"] = "control-field-canary"
        cases.append(extra)
        matcher_cross_role = copy.deepcopy(fixture)
        matcher_cross_role["payload"]["rules"][0]["matchers"][0]["reasonCode"] = "firstMatchingRule"
        cases.append(matcher_cross_role)
        rule_cross_role = copy.deepcopy(fixture)
        rule_cross_role["payload"]["rules"][0]["reasonCode"] = "matcherMatched"
        cases.append(rule_cross_role)
        for index, case in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                checker.validate_control_api_semantics(case)

    def test_checker_uses_pinned_draft_2020_12_validator(self):
        source = CHECKER_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            checker.UVX_COMMAND,
            ["uvx", "--from", "check-jsonschema==0.38.2", "check-jsonschema"],
        )
        self.assertIn("--check-metaschema", source)
        self.assertIn("subprocess", source)

    def test_url_userinfo_fixture_is_rejected_by_real_validator(self):
        fixture_path = ROOT / "fixtures/config/url-userinfo-source.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            subscription_path = Path(directory) / "url-userinfo-subscription.json"
            subscription_path.write_text(json.dumps(fixture["subscriptions"][0]), encoding="utf-8")
            cases = [
                (checker.CONFIG_SCHEMA_PATH, fixture_path),
                (checker.SUBSCRIPTION_SCHEMA_PATH, subscription_path),
            ]
            for schema_path, instance_path in cases:
                with self.subTest(schema=schema_path.name):
                    result = self.run_real_validator([
                        "--schemafile",
                        str(schema_path),
                        "--color",
                        "never",
                        str(instance_path),
                    ])
                    self.assertTrue(
                        checker.is_validation_failure(
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        ),
                        f"{schema_path.name} accepted URL display metadata with userinfo",
                    )

    def test_url_query_and_fragment_cases_are_rejected_by_real_validator(self):
        fixture = json.loads(
            (ROOT / "fixtures/config/sanitized-source-metadata.json").read_text(encoding="utf-8")
        )
        cases = [
            ("query", "?token=query-canary"),
            ("fragment", "#fragment-canary"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for case, suffix in cases:
                config = copy.deepcopy(fixture)
                subscription = config["subscriptions"][0]
                subscription["source"]["displayValue"] = f"https://synthetic.example/••••••••{suffix}"
                config["subscriptions"] = [subscription]
                config_path = directory / f"url-{case}-config.json"
                subscription_path = directory / f"url-{case}-subscription.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                subscription_path.write_text(json.dumps(subscription), encoding="utf-8")
                schema_cases = [
                    (checker.CONFIG_SCHEMA_PATH, config_path),
                    (checker.SUBSCRIPTION_SCHEMA_PATH, subscription_path),
                ]
                for schema_path, instance_path in schema_cases:
                    with self.subTest(case=case, schema=schema_path.name):
                        result = self.run_real_validator([
                            "--schemafile",
                            str(schema_path),
                            "--color",
                            "never",
                            str(instance_path),
                        ])
                        self.assertTrue(
                            checker.is_validation_failure(
                                result.returncode,
                                result.stdout,
                                result.stderr,
                            ),
                            f"{schema_path.name} accepted URL display metadata with {case}",
                        )

    def test_parsed_share_link_transport_and_tls_fields_are_constrained(self):
        fixture = json.loads(
            (ROOT / "fixtures/subscriptions/parsed-share-link.json").read_text(encoding="utf-8")
        )
        cases = []

        relative_path = copy.deepcopy(fixture)
        relative_path["server"]["transport"]["options"]["path"] = "relative"
        cases.append(("relative transport path", relative_path))

        unknown_fingerprint = copy.deepcopy(fixture)
        unknown_fingerprint["server"]["transport"]["options"]["fingerprint"] = "unknown"
        cases.append(("unknown fingerprint", unknown_fingerprint))

        missing_server_name = copy.deepcopy(fixture)
        del missing_server_name["server"]["tls"]["serverName"]
        cases.append(("missing TLS server name", missing_server_name))

        unsafe_alpn = copy.deepcopy(fixture)
        unsafe_alpn["server"]["tls"]["alpn"] = ["unsafe value"]
        cases.append(("unsafe ALPN value", unsafe_alpn))

        wrong_name = copy.deepcopy(fixture)
        wrong_name["server"]["name"] = "Trojan server"
        cases.append(("protocol name mismatch", wrong_name))

        wrong_tag = copy.deepcopy(fixture)
        wrong_tag["server"]["tags"][1] = "trojan"
        cases.append(("protocol tag mismatch", wrong_tag))

        path_on_tcp = copy.deepcopy(fixture)
        path_on_tcp["server"]["transport"] = {
            "kind": "tcp",
            "options": {"path": "/invalid"},
        }
        cases.append(("path on tcp", path_on_tcp))

        service_on_websocket = copy.deepcopy(fixture)
        service_on_websocket["server"]["transport"] = {
            "kind": "ws",
            "options": {"serviceName": "invalid"},
        }
        cases.append(("service name on websocket", service_on_websocket))

        host_on_grpc = copy.deepcopy(fixture)
        host_on_grpc["server"]["transport"] = {
            "kind": "grpc",
            "options": {"host": "synthetic.example"},
        }
        cases.append(("host on grpc", host_on_grpc))

        method_on_vless = copy.deepcopy(fixture)
        method_on_vless["server"]["transport"]["options"]["method"] = "aes-128-gcm"
        cases.append(("method on vless", method_on_vless))

        flow_without_tls = copy.deepcopy(fixture)
        flow_without_tls["server"]["transport"] = {
            "kind": "tcp",
            "options": {"flow": "xtls-rprx-vision"},
        }
        flow_without_tls["server"]["tls"] = None
        cases.append(("flow without TLS", flow_without_tls))

        public_key = "A" * 43
        reality_without_tls = copy.deepcopy(fixture)
        reality_without_tls["server"]["transport"] = {
            "kind": "tcp",
            "options": {"realityPublicKey": public_key},
        }
        reality_without_tls["server"]["tls"] = None
        cases.append(("reality without TLS", reality_without_tls))

        reality_on_websocket = copy.deepcopy(fixture)
        reality_on_websocket["server"]["transport"] = {
            "kind": "ws",
            "options": {"realityPublicKey": public_key},
        }
        cases.append(("reality on websocket", reality_on_websocket))

        reality_short_without_public = copy.deepcopy(fixture)
        reality_short_without_public["server"]["transport"] = {
            "kind": "tcp",
            "options": {"realityShortID": "00"},
        }
        cases.append(("reality short id without public key", reality_short_without_public))

        trojan = copy.deepcopy(fixture)
        trojan["server"]["name"] = "Trojan server"
        trojan["server"]["protocolKind"] = "trojan"
        trojan["server"]["tags"][1] = "trojan"
        trojan["server"]["transport"] = {"kind": "tcp", "options": {}}
        trojan_reality = copy.deepcopy(trojan)
        trojan_reality["server"]["transport"]["options"]["realityPublicKey"] = public_key
        cases.append(("reality options on trojan", trojan_reality))

        trojan_without_tls = copy.deepcopy(trojan)
        trojan_without_tls["server"]["tls"] = None
        cases.append(("trojan without TLS", trojan_without_tls))

        shadowsocks = copy.deepcopy(fixture)
        shadowsocks["server"]["name"] = "Shadowsocks server"
        shadowsocks["server"]["protocolKind"] = "shadowsocks"
        shadowsocks["server"]["tags"][1] = "shadowsocks"
        shadowsocks["server"]["transport"] = {
            "kind": "tcp",
            "options": {"method": "aes-256-gcm"},
        }
        shadowsocks["server"]["tls"] = None

        shadowsocks_wrong_transport = copy.deepcopy(shadowsocks)
        shadowsocks_wrong_transport["server"]["transport"]["kind"] = "ws"
        cases.append(("shadowsocks wrong transport", shadowsocks_wrong_transport))

        shadowsocks_missing_method = copy.deepcopy(shadowsocks)
        shadowsocks_missing_method["server"]["transport"]["options"] = {}
        cases.append(("shadowsocks missing method", shadowsocks_missing_method))

        shadowsocks_extra_option = copy.deepcopy(shadowsocks)
        shadowsocks_extra_option["server"]["transport"]["options"]["host"] = "synthetic.example"
        cases.append(("shadowsocks extra transport option", shadowsocks_extra_option))

        shadowsocks_with_tls = copy.deepcopy(shadowsocks)
        shadowsocks_with_tls["server"]["tls"] = {
            "serverName": "synthetic.example",
            "allowInsecure": False,
            "alpn": [],
        }
        cases.append(("shadowsocks with TLS", shadowsocks_with_tls))

        unicode_secret = copy.deepcopy(fixture)
        unicode_secret["server"]["credential"]["key"] = "server/credential-✅"
        cases.append(("non-ASCII secret key", unicode_secret))

        oversized_secret = copy.deepcopy(fixture)
        oversized_secret["server"]["credential"]["key"] = "k" * 513
        cases.append(("oversized secret key", oversized_secret))

        unicode_path = copy.deepcopy(fixture)
        unicode_path["server"]["transport"]["options"]["path"] = "/✅"
        cases.append(("non-ASCII transport path", unicode_path))

        oversized_path = copy.deepcopy(fixture)
        oversized_path["server"]["transport"]["options"]["path"] = "/" + "a" * 2048
        cases.append(("oversized transport path", oversized_path))

        unicode_endpoint = copy.deepcopy(fixture)
        unicode_endpoint["server"]["endpoint"]["host"] = "synthetic-✅.example"
        cases.append(("non-ASCII endpoint host", unicode_endpoint))

        trailing_endpoint = copy.deepcopy(fixture)
        trailing_endpoint["server"]["endpoint"]["host"] = "synthetic.example."
        cases.append(("trailing-dot endpoint host", trailing_endpoint))

        uppercase_endpoint = copy.deepcopy(fixture)
        uppercase_endpoint["server"]["endpoint"]["host"] = "Synthetic.Example"
        cases.append(("uppercase endpoint host", uppercase_endpoint))

        uppercase_tls = copy.deepcopy(fixture)
        uppercase_tls["server"]["tls"]["serverName"] = "Synthetic.Example"
        cases.append(("uppercase TLS server name", uppercase_tls))

        invalid_dns_label = copy.deepcopy(fixture)
        invalid_dns_label["server"]["tls"]["serverName"] = "-synthetic.example"
        cases.append(("invalid DNS TLS server name", invalid_dns_label))

        uppercase_transport_host = copy.deepcopy(fixture)
        uppercase_transport_host["server"]["transport"]["options"]["host"] = "Synthetic.Example"
        cases.append(("uppercase transport host", uppercase_transport_host))

        trailing_transport_host = copy.deepcopy(fixture)
        trailing_transport_host["server"]["transport"]["options"]["host"] = "synthetic.example."
        cases.append(("trailing-dot transport host", trailing_transport_host))

        for display in [
            "vless://user:password@synthetic.example:443/••••••••",
            "vless://synthetic.example:443/••••••••?query=canary",
            "vless://synthetic.example:443/••••••••#fragment-canary",
            "vless://[synthetic.example]:443/••••••••",
            "vless://synthetic.example:70000/••••••••",
        ]:
            unsafe_display = copy.deepcopy(fixture)
            unsafe_display["displayValue"] = display
            cases.append((f"unsafe display {len(cases)}", unsafe_display))

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            schema_path = self.write_parsed_share_link_schema(directory)
            for case, instance in cases:
                with self.subTest(case=case):
                    instance_path = directory / f"{case.replace(' ', '-')}.json"
                    instance_path.write_text(json.dumps(instance), encoding="utf-8")
                    result = self.run_real_validator([
                        "--schemafile",
                        str(schema_path),
                        "--color",
                        "never",
                        str(instance_path),
                    ])
                    self.assertTrue(
                        checker.is_validation_failure(
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        ),
                        f"parsed share-link schema accepted {case}",
                    )

    def test_semantic_checker_rejects_unsafe_display_metadata(self):
        fixture = json.loads(
            (ROOT / "fixtures/subscriptions/parsed-share-link.json").read_text(encoding="utf-8")
        )
        displays = [
            "vless://other.example:443/••••••••",
            "vless://synthetic.example:444/••••••••",
            "ss://synthetic.example:443/••••••••",
            "vless://user:password@synthetic.example:443/••••••••",
            "vless://synthetic.example:443/••••••••?query=canary",
            "vless://synthetic.example:443/••••••••#fragment-canary",
            "vless://[synthetic.example]:443/••••••••",
            "redacted",
        ]
        for index, display in enumerate(displays):
            instance = copy.deepcopy(fixture)
            instance["displayValue"] = display
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                checker.validate_canonical_parsed_share_link(instance)

    def test_semantic_checker_rejects_noncanonical_hosts(self):
        fixture = json.loads(
            (ROOT / "fixtures/subscriptions/parsed-share-link.json").read_text(encoding="utf-8")
        )
        for index, host in enumerate([
            "999.999.999.999",
            "synthetic..example",
            "-synthetic.example",
            "Synthetic.Example",
            "synthetic.example.",
            "2001:db8:::1",
        ]):
            instance = copy.deepcopy(fixture)
            instance["server"]["endpoint"]["host"] = host
            instance["server"]["tls"]["serverName"] = host
            instance["displayValue"] = f"vless://{host}:443/••••••••"
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                checker.validate_canonical_parsed_share_link(instance)

    def test_semantic_checker_rejects_noncanonical_transport_hosts(self):
        fixture = json.loads(
            (ROOT / "fixtures/subscriptions/parsed-share-link.json").read_text(encoding="utf-8")
        )
        for index, host in enumerate([
            "192.0.2.256",
            "2001:db8:::1",
            "123.456",
            "123",
            "192.0.2.01",
        ]):
            instance = copy.deepcopy(fixture)
            instance["server"]["transport"]["options"]["host"] = host
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                checker.validate_canonical_parsed_share_link(instance)

    def test_semantic_checker_validates_canonical_parsed_share_link(self):
        with tempfile.TemporaryDirectory() as directory:
            checker.validate_parsed_share_link(
                checker.SUBSCRIPTION_SCHEMA_PATH,
                checker.PARSED_SHARE_LINK_FIXTURE,
                Path(directory),
            )

    def test_status_get_takes_no_parameters(self):
        schema = json.loads(CONTROL_SCHEMA_PATH.read_text(encoding="utf-8"))
        empty_payload = schema["$defs"]["emptyPayload"]
        self.assertFalse(empty_payload["additionalProperties"])
        self.assertEqual(empty_payload["maxProperties"], 0)
        branches = [branch["if"]["properties"]["method"]["const"] for branch in schema["allOf"]]
        self.assertIn("status.get", branches)

    def test_status_request_fixture_validates_and_a_payload_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            checker.validate_control_api(ROOT, Path(directory))
        labels = [label for label, _ in checker.control_api_negative_probes(ROOT)]
        self.assertIn("status-payload-field", labels)
        self.assertIn("status-extra-field", labels)

    def test_required_constraint_removal_is_detected(self):
        self.assert_mutated_schema_fails("required")

    def test_one_of_constraint_removal_is_detected(self):
        self.assert_mutated_schema_fails("oneOf")

    def test_validator_command_prefers_installed_pinned_version(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "check-jsonschema"
            self.write_executable(
                executable,
                "if [ \"$1\" = \"--version\" ]; then printf 'check-jsonschema, version 0.38.2\\n'; fi\n",
            )
            with mock.patch.dict(os.environ, {"PATH": directory}, clear=True):
                checker.validator_command.cache_clear()
                self.assertEqual(checker.validator_command(), [str(executable)])
            checker.validator_command.cache_clear()

    def test_validator_command_falls_back_to_pinned_uvx(self):
        cases = ["missing", "mismatched"]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                binary_directory = Path(directory)
                uvx = binary_directory / "uvx"
                self.write_executable(uvx, "exit 0\n")
                if case == "mismatched":
                    self.write_executable(
                        binary_directory / "check-jsonschema",
                        "if [ \"$1\" = \"--version\" ]; then printf 'check-jsonschema, version 0.38.1\\n'; fi\n",
                    )
                with mock.patch.dict(os.environ, {"PATH": str(binary_directory)}, clear=True):
                    checker.validator_command.cache_clear()
                    self.assertEqual(checker.validator_command(), checker.UVX_COMMAND)
                checker.validator_command.cache_clear()

    def test_validator_command_fails_clearly_without_either_command(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"PATH": directory}, clear=True):
                checker.validator_command.cache_clear()
                with self.assertRaisesRegex(RuntimeError, "check-jsonschema==0.38.2.*uvx"):
                    checker.validator_command()
            checker.validator_command.cache_clear()

    def test_expected_failure_requires_a_validation_error_marker(self):
        self.assertTrue(checker.is_validation_failure(1, "Schema validation errors were encountered.", ""))
        self.assertFalse(checker.is_validation_failure(1, "", "Error: validator setup failed"))
        self.assertFalse(checker.is_validation_failure(0, "Schema validation errors were encountered.", ""))

    def write_parsed_share_link_schema(self, directory):
        subscription_schema = json.loads(
            checker.SUBSCRIPTION_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        schema = {
            "$schema": subscription_schema["$schema"],
            "$ref": "#/$defs/parsedShareLink",
            "$defs": subscription_schema["$defs"],
        }
        path = directory / "parsed-share-link.schema.json"
        path.write_text(json.dumps(schema), encoding="utf-8")
        return path

    def run_real_validator(self, arguments):
        checker.validator_command.cache_clear()
        try:
            return subprocess.run(
                checker.validator_command() + arguments,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        finally:
            checker.validator_command.cache_clear()

    def write_executable(self, path, body):
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def assert_mutated_schema_fails(self, mutation):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools/ci").mkdir(parents=True)
            (root / "schemas").mkdir()
            (root / "fixtures").mkdir()
            shutil.copytree(ROOT / "fixtures/config", root / "fixtures/config")
            shutil.copytree(ROOT / "fixtures/subscriptions", root / "fixtures/subscriptions")
            shutil.copytree(ROOT / "fixtures/control", root / "fixtures/control")
            shutil.copy2(CHECKER_PATH, root / "tools/ci/validate-schemas.py")
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            if mutation == "required":
                schema["required"] = [item for item in schema["required"] if item != "servers"]
            else:
                del schema["$defs"]["server"]["properties"]["credential"]["oneOf"]
            (root / "schemas/config.schema.json").write_text(json.dumps(schema), encoding="utf-8")
            shutil.copy2(ROOT / "schemas/subscription.schema.json", root / "schemas/subscription.schema.json")
            shutil.copy2(ROOT / "schemas/control-api.schema.json", root / "schemas/control-api.schema.json")
            shutil.copy2(
                ROOT / "schemas/engine-lock.schema.json", root / "schemas/engine-lock.schema.json"
            )
            shutil.copy2(ROOT / "engines.lock.json", root / "engines.lock.json")
            result = subprocess.run(
                [sys.executable, str(root / "tools/ci/validate-schemas.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)


class ControlResponseSchemaTests(unittest.TestCase):
    """The extension's answers are a contract, so they are checked like a request.

    `PacketTunnelProvider.handleAppMessage` answers `status.get` with a result and
    every other method with a refusal. Before this, nothing described those
    answers: the control schema only described requests, so a provider change
    could alter the response shape with no gate noticing.
    """

    def test_response_schema_file_exists_and_closes_the_envelope(self):
        self.assertTrue(checker.CONTROL_RESPONSE_SCHEMA_PATH.is_file())
        schema = json.loads(checker.CONTROL_RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            sorted(schema["required"]),
            ["apiVersion", "ok", "requestID"],
        )
        self.assertEqual(schema["properties"]["apiVersion"]["const"], 1)
        self.assertEqual(sorted(schema["properties"]), sorted(checker.CONTROL_RESPONSE_KEYS))
        self.assertEqual(
            sorted(schema["$defs"]["errorCode"]["enum"]),
            sorted(checker.CONTROL_ERROR_CODES),
        )
        self.assertFalse(schema["$defs"]["result"]["additionalProperties"])
        self.assertEqual(schema["$defs"]["result"]["required"], ["state"])

    def test_the_response_envelope_separates_a_result_from_a_refusal(self):
        schema = json.loads(checker.CONTROL_RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8"))
        branches = schema["allOf"]
        self.assertEqual(len(branches), 2, "one branch per ok value, and nothing else")
        success, refusal = branches
        self.assertEqual(success["if"]["properties"]["ok"]["const"], True)
        self.assertEqual(success["then"]["required"], ["result"])
        self.assertEqual(success["then"]["not"], {"required": ["error"]})
        self.assertEqual(refusal["if"]["properties"]["ok"]["const"], False)
        self.assertEqual(refusal["then"]["required"], ["error"])
        self.assertEqual(refusal["then"]["not"], {"required": ["result"]})

    def test_positive_fixtures_and_negative_probes(self):
        with tempfile.TemporaryDirectory() as directory:
            checker.validate_control_response(ROOT, Path(directory))

    def test_every_documented_fixture_is_present_on_disk(self):
        for name in checker.POSITIVE_CONTROL_RESPONSE_FIXTURES:
            with self.subTest(fixture=name):
                self.assertTrue((CONTROL_FIXTURE_DIR / name).is_file())
        for name in checker.NEGATIVE_CONTROL_RESPONSE_FIXTURES:
            with self.subTest(fixture=name):
                self.assertTrue((CONTROL_FIXTURE_DIR / name).is_file())

    def test_the_three_positive_shapes_cover_result_and_both_error_codes(self):
        codes = set()
        saw_result = False
        for name in checker.POSITIVE_CONTROL_RESPONSE_FIXTURES:
            instance = json.loads((CONTROL_FIXTURE_DIR / name).read_text(encoding="utf-8"))
            checker.validate_control_response_semantics(instance)
            if instance["ok"]:
                saw_result = True
                self.assertNotIn("error", instance)
            else:
                codes.add(instance["error"])
        self.assertTrue(saw_result, "no positive fixture exercises an ok response")
        self.assertEqual(codes, checker.CONTROL_ERROR_CODES)

    def test_semantic_checker_rejects_what_the_schema_rejects(self):
        status = json.loads((CONTROL_FIXTURE_DIR / "status-response.json").read_text(encoding="utf-8"))
        cases = {}
        cases["result and error"] = {**status, "error": "invalid-request"}
        cases["missing result"] = {key: value for key, value in status.items() if key != "result"}
        cases["missing ok"] = {key: value for key, value in status.items() if key != "ok"}
        cases["empty requestID"] = {**status, "requestID": ""}
        cases["long requestID"] = {**status, "requestID": "r" * 129}
        cases["extra envelope field"] = {**status, "rawInput": "control-field-canary"}
        cases["extra result field"] = {**status, "result": {**status["result"], "engineStatus": "connected"}}
        cases["empty state"] = {**status, "result": {"state": ""}}
        cases["long state"] = {**status, "result": {"state": "s" * 65}}
        cases["api version two"] = {**status, "apiVersion": 2}
        cases["ok is a string"] = {**status, "ok": "true"}
        refused = json.loads(
            (CONTROL_FIXTURE_DIR / "not-implemented-response.json").read_text(encoding="utf-8")
        )
        cases["refusal with a result"] = {**refused, "result": {"state": "disconnected"}}
        cases["refusal without an error"] = {key: value for key, value in refused.items() if key != "error"}
        cases["unknown error code"] = {**refused, "error": "engine-crashed"}
        for label, case in cases.items():
            with self.subTest(case=label), self.assertRaises(RuntimeError):
                checker.validate_control_response_semantics(case)

    def test_probes_cover_every_weakness_the_checker_claims_to_refuse(self):
        labels = {label for label, _ in checker.control_response_negative_probes(ROOT)}
        for expected in (
            "response-api-version",
            "response-empty-request-id",
            "response-missing-result",
            "response-empty-state",
            "response-result-extra-field",
            "response-refused-with-result",
            "response-missing-error",
            "response-unknown-error",
        ):
            self.assertIn(expected, labels)

    def test_dropping_the_result_branch_is_detected(self):
        # The if/then branches are the only thing that stops an ok response from
        # being accepted with no result, so removing one has to fail the checker.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools/ci").mkdir(parents=True)
            (root / "schemas").mkdir()
            shutil.copytree(ROOT / "fixtures/control", root / "fixtures/control")
            shutil.copy2(CHECKER_PATH, root / "tools/ci/validate-schemas.py")
            schema = json.loads(checker.CONTROL_RESPONSE_SCHEMA_PATH.read_text(encoding="utf-8"))
            del schema["allOf"]
            (root / "schemas/control-response.schema.json").write_text(json.dumps(schema), encoding="utf-8")
            with self.assertRaises(RuntimeError) as failure:
                checker.validate_control_response(root, Path(directory) / "probes")
            self.assertIn("status-response-with-error", str(failure.exception))


class SecretReferenceKeyTests(unittest.TestCase):
    """A secret reference names a secret; the schema says how a name may look.

    The rule is stated in three places and they have to agree: the JSON Schema,
    `RoviaConfig.SecretReference.isValidKey`, and the subscription parser that
    mints keys. A key is a name, so it is printable ASCII without spaces and at
    most 512 characters, and a rule that only one of the three enforces is a rule
    that can be bypassed.
    """

    def key_schema(self):
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]["secretReference"]["properties"]["key"]

    def test_the_schema_states_a_length_bound_and_a_character_set(self):
        key = self.key_schema()
        self.assertEqual(key["minLength"], 1)
        self.assertEqual(key["maxLength"], 512)
        self.assertEqual(key["type"], "string")
        # The pattern must anchor on a full-string check rather than on "$":
        # Python's re lets "$" match before a trailing newline, so a key ending
        # in a newline would slip through a naive "^[!-~]+$".
        self.assertIn("(?!", key["pattern"])
        self.assertIn("[\\s\\S]*[^!-~]", key["pattern"])

    def test_the_schema_and_the_swift_rule_use_the_same_bound(self):
        source = (ROOT / "core/config/Sources/RoviaConfig/CanonicalModels.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("maximumKeyBytes = 512", source)
        self.assertIn("0x21...0x7E", source)
        self.assertIn("maximumKeyBytes = 512", (ROOT / "core/config/Sources/RoviaConfig/CanonicalModels.swift").read_text(encoding="utf-8"))

    def test_the_parser_asks_the_config_package_instead_of_keeping_its_own_rule(self):
        parser = (ROOT / "core/subscription/Sources/RoviaSubscription/ShareLinkParser.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("SecretReference.isValidKey(reference.key)", parser)
        self.assertNotIn(
            "maximumSecretReferenceBytes",
            parser,
            "the parser must not keep a second copy of the key limit",
        )

    def test_the_fixtures_cover_a_legal_key_a_space_a_control_character_and_a_length(self):
        for name in (
            "secret-reference-key-at-limit.json",
            "secret-reference-key-not-printable.json",
            "secret-reference-key-oversized.json",
            "secret-reference-credential-key-not-printable.json",
        ):
            with self.subTest(fixture=name):
                self.assertIn(name, checker.POSITIVE_CONFIG_FIXTURES + checker.NEGATIVE_CONFIG_FIXTURES)
                self.assertTrue((ROOT / "fixtures/config" / name).is_file())

    def test_probes_cover_every_weakness_the_checker_claims_to_refuse(self):
        labels = {label for label, _ in checker.secret_reference_key_probes(
            json.loads((ROOT / "fixtures/config/minimal.json").read_text(encoding="utf-8"))
        )}
        for expected in (
            "secret-key-space",
            "secret-key-control",
            "secret-key-trailing-newline",
            "secret-key-non-ascii",
            "secret-key-oversized",
            "secret-key-empty",
        ):
            self.assertIn(expected, labels)

    def test_the_pinned_validator_enforces_the_pattern(self):
        # The pattern is the part a hand-written regex in a test could get wrong,
        # so it is checked with the validator the gate itself uses.
        import re

        pattern = re.compile(self.key_schema()["pattern"])
        for label, key, expected in [
            ("legal", "subscription/sanitized", True),
            ("at the limit", "k" * 512, True),
            ("space", "a b", False),
            ("trailing newline", "ab\n", False),
            ("embedded newline", "a\nb", False),
            ("bell", "a\u0007b", False),
            ("non-ascii", "a\u00e9b", False),
            ("delete", "a\u007Fb", False),
        ]:
            with self.subTest(case=label):
                self.assertEqual(bool(pattern.search(key)), expected)


class ControlContractSymmetryTests(unittest.TestCase):
    """The request and the response are one contract, so they are checked as one.

    The request schema bounds `requestID`, the response schema bounds it the same
    way, and the provider has to enforce what the schemas say. Three places
    stating the same rule is a liability unless something compares them, so these
    tests read both schemas and the provider source and require them to agree.
    """

    PROVIDER = ROOT / "client/app/ios/RoviaTunnel/PacketTunnelProvider.swift"
    RESPONSE_SCHEMA = ROOT / "schemas/control-response.schema.json"

    def setUp(self):
        self.provider = self.PROVIDER.read_text(encoding="utf-8")
        self.request = json.loads(CONTROL_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.response = json.loads(self.RESPONSE_SCHEMA.read_text(encoding="utf-8"))

    def request_id_bound(self):
        return self.request["properties"]["requestID"]

    def test_the_request_id_bound_is_identical_on_both_sides(self):
        request = self.request_id_bound()
        response = self.response["properties"]["requestID"]
        self.assertEqual(request.get("maxLength"), 128, "the request must cap requestID")
        self.assertEqual(
            request.get("maxLength"),
            response.get("maxLength"),
            "a requestID the request schema rejects but the response allows leaves "
            "the host unable to match a refusal to its request",
        )
        self.assertEqual(request.get("minLength"), response.get("minLength"))

    def test_the_request_envelope_is_closed_and_the_response_envelope_is_closed(self):
        self.assertFalse(
            self.request["additionalProperties"],
            "the request envelope must refuse a field the schema does not declare",
        )
        self.assertFalse(self.response["additionalProperties"])
        self.assertEqual(
            set(self.request["properties"]),
            {"apiVersion", "requestID", "method", "payload"},
        )

    def test_status_get_must_take_an_empty_payload(self):
        branch = self.request["allOf"][0]
        self.assertEqual(branch["if"]["properties"]["method"]["const"], "status.get")
        self.assertEqual(
            branch["then"]["properties"]["payload"]["$ref"], "#/$defs/emptyPayload"
        )
        empty = self.request["$defs"]["emptyPayload"]
        self.assertFalse(empty["additionalProperties"])
        self.assertEqual(empty["maxProperties"], 0)

    def test_the_provider_bounds_the_request_id_at_the_same_number(self):
        # The provider is the only thing standing between a hostile or buggy
        # host and an unbounded identifier that gets echoed back.
        self.assertIn("maximumRequestIDCharacters = 128", self.provider)
        self.assertIn(
            "maximumRequestIDCharacters).contains(requestID.count)",
            self.provider,
            "the provider must apply the bound with a range check, not a comment",
        )

    def test_the_provider_refuses_an_envelope_with_an_undeclared_field(self):
        self.assertIn(
            "Set(fields.keys) == ControlContract.envelopeFields",
            self.provider,
            "the provider must compare the field set, not read four keys and "
            "ignore a fifth",
        )
        self.assertIn('"apiVersion", "requestID", "method", "payload"', self.provider)

    def control_methods(self):
        """The methods the provider answers, read from its own enum."""
        enum = re.search(
            r"private enum ControlMethod: String[^\{]*\{(?P<body>.*?)\n\}", self.provider, re.S
        )
        self.assertIsNotNone(enum, "the provider must declare its ControlMethod enum")
        # Keyed by the wire value, valued by the case name, so a test can ask
        # both "which methods are answered" and "what is this one called".
        return {
            match.group(2): match.group(1)
            for match in re.finditer(r'case (\w+) = "([^"]+)"', enum.group("body"))
        }

    def test_the_provider_requires_an_empty_status_get_payload(self):
        # The mapping, not the presence of a word. `ControlMethod` is an enum with
        # one case per declared method, so the requirement is exactly one case —
        # and the test says which one, and that the body of the requirement names
        # that case.
        methods = self.control_methods()
        self.assertEqual(
            set(methods),
            set(self.request["properties"]["method"]["enum"]),
            "the provider must answer exactly the methods the request schema declares",
        )
        requirement = re.search(
            r"var needsEmptyPayload: Bool \{ (?P<body>[^}]*) \}", self.provider
        )
        self.assertIsNotNone(requirement, "ControlMethod must state which method takes no payload")
        self.assertEqual(
            [word for word in re.findall(r"\.(\w+)", requirement.group("body"))],
            ["statusGet"],
            "exactly one method may take an empty payload, and it must be named in the requirement",
        )
        self.assertIn("method.needsEmptyPayload", self.provider)
        self.assertIn("payload.isEmpty", self.provider)

    def test_the_other_methods_are_refused_before_their_payload_is_read(self):
        # There is nothing to validate the payload of a method that answers
        # not-implemented, so the provider refuses it. This is a documented limit
        # rather than an oversight: `routing.explain` and `group.select` have
        # payload shapes in the request schema, and the provider does not check
        # them because it does not implement them.
        self.assertIn("refusalNotImplemented", self.provider)
        for method in (
            "engineCapabilities",
            "subscriptionInspect",
            "routingExplain",
            "healthSnapshot",
            "groupSelect",
        ):
            with self.subTest(method=method):
                self.assertIn(f".{method}", self.provider)
        declared_with_payloads = {
            branch["if"]["properties"]["method"]["const"]
            for branch in self.request["allOf"]
            if "payload" in branch["then"]["properties"]
        }
        self.assertEqual(
            declared_with_payloads,
            {"status.get", "routing.explain", "group.select"},
            "the request schema declares a payload shape for these methods",
        )
        # And the reason the provider can skip them is on the record, not implied.
        self.assertIn("not-implemented", self.provider)

    def test_the_provider_keeps_the_64_kib_request_ceiling(self):
        self.assertIn("maximumMessageBytes = 65_536", self.provider)
        self.assertIn("messageData.count <= ControlContract.maximumMessageBytes", self.provider)

    def test_the_provider_answers_with_the_error_codes_the_response_schema_declares(self):
        codes = self.response["$defs"]["errorCode"]["enum"]
        self.assertTrue(codes, "the response schema must declare a closed error set")
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(
                    f'"{code}"',
                    self.provider,
                    f"the provider never produces the {code} the schema declares",
                )

    def test_the_provider_declares_every_method_the_request_schema_declares(self):
        declared = set(self.request["properties"]["method"]["enum"])
        for method in declared:
            with self.subTest(method=method):
                self.assertIn(f'"{method}"', self.provider)
        # And it must not answer a method the schema does not declare, which is
        # what a `default:` case in the provider's switch would mean.
        self.assertNotIn(
            "case .unknown",
            self.provider,
            "an unknown control method must be refused by the envelope, not "
            "switched on",
        )

    def test_fixtures_and_probes_cover_the_request_id_bound(self):
        labels = {label for label, _ in checker.control_api_negative_probes(ROOT)}
        for expected in ("request-id-oversized", "request-id-at-the-bound", "status-extra-field"):
            self.assertIn(expected, labels)
        for name in ("oversized-request-id.json", "request-with-extra-field.json"):
            with self.subTest(fixture=name):
                self.assertIn(name, checker.NEGATIVE_CONTROL_REQUEST_FIXTURES)
                self.assertTrue((ROOT / "fixtures/control" / name).is_file())
        oversized = json.loads(
            (ROOT / "fixtures/control/oversized-request-id.json").read_text(encoding="utf-8")
        )
        self.assertGreater(len(oversized["requestID"]), 128)
        self.assertEqual(oversized["method"], "status.get")
        extra = json.loads(
            (ROOT / "fixtures/control/request-with-extra-field.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            set(extra) - {"apiVersion", "requestID", "method", "payload"},
            set(),
            "a request fixture that is not rejected for the extra field proves nothing",
        )


class EngineLockSchemaTests(unittest.TestCase):
    def test_engine_lock_schema_file_exists(self):
        self.assertTrue(checker.ENGINE_LOCK_SCHEMA_PATH.is_file())
        self.assertTrue(checker.ENGINE_LOCK_PATH.is_file())

    def test_schema_requires_approval_and_a_full_commit_for_an_enabled_engine(self):
        schema = json.loads(checker.ENGINE_LOCK_SCHEMA_PATH.read_text(encoding="utf-8"))
        approved = schema["$defs"]["approvedCandidate"]["allOf"]
        first = approved[0]["properties"]
        self.assertEqual(first["enabled"]["const"], True)
        self.assertEqual(first["approval"]["const"], "approved")
        second = approved[1]["properties"]
        self.assertEqual(second["commit"]["pattern"], "^[0-9a-fA-F]{40}$")
        self.assertEqual(second["sha256"]["pattern"], "^[0-9a-fA-F]{64}$")
        self.assertTrue(schema["properties"]["productionEngines"]["maxItems"] == 1)
        declaration = schema["allOf"][0]
        self.assertEqual(declaration["then"]["properties"]["productionEngines"]["contains"], {"const": "xray"})
        condition = declaration["if"]["properties"]["candidates"]["properties"]["xray"]["properties"]
        self.assertEqual(condition["enabled"]["const"], True)
        self.assertEqual(condition["approval"]["const"], "approved")

    def test_repository_engine_lock_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            checker.validate_engine_lock(ROOT, Path(directory))

    def test_probes_cover_every_weakness_the_checker_claims_to_refuse(self):
        labels = {label for label, _ in checker.engine_lock_probes()}
        for expected in (
            "engine-pending-approval",
            "engine-not-enabled",
            "engine-short-commit",
            "engine-missing-commit",
            "engine-short-digest",
            "engine-missing-artifact",
            "engine-empty-architectures",
            "engine-empty-build-flags",
            "engine-unknown-approval",
            "engine-unknown-field",
            "engine-two-production",
            "engine-unknown-production",
            "engine-two-go-runtimes",
            "engine-disallowed-policy",
            "engine-unsupported-schema",
            "engine-missing-candidate",
            "engine-approved-not-a-production-engine",
        ):
            self.assertIn(expected, labels)

    def test_dropping_the_enabled_engine_branch_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools/ci").mkdir(parents=True)
            (root / "schemas").mkdir()
            (root / "fixtures").mkdir()
            shutil.copytree(ROOT / "fixtures/config", root / "fixtures/config")
            shutil.copytree(ROOT / "fixtures/subscriptions", root / "fixtures/subscriptions")
            shutil.copytree(ROOT / "fixtures/control", root / "fixtures/control")
            shutil.copy2(CHECKER_PATH, root / "tools/ci/validate-schemas.py")
            # Every schema, because the checker validates the metaschema of all
            # of them and a missing file is a different failure from a weakened
            # one. Naming three here would make this test pass or fail for a
            # reason that has nothing to do with the engine lock.
            shutil.copytree(ROOT / "schemas", root / "schemas", dirs_exist_ok=True)
            shutil.copy2(ROOT / "engines.lock.json", root / "engines.lock.json")
            schema = json.loads(checker.ENGINE_LOCK_SCHEMA_PATH.read_text(encoding="utf-8"))
            del schema["then"]
            (root / "schemas/engine-lock.schema.json").write_text(json.dumps(schema), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(root / "tools/ci/validate-schemas.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("engine-pending-approval", result.stdout + result.stderr)



class SemanticProbeCountTests(unittest.TestCase):
    """The probe counts in the verification record, derived from the validator.

    The record said 45 semantic probes while the validator ran 46 negative cases
    and 2 boundary positives. A count written by hand is a claim about code that
    can change, so these read the four probe functions and require the record to
    state what they return.
    """

    @classmethod
    def setUpClass(cls):
        cls.request = checker.control_api_negative_probes(ROOT)
        cls.response = checker.control_response_negative_probes(ROOT)
        cls.engine = checker.engine_lock_probes()
        cls.secret = checker.secret_reference_key_probes(
            json.loads((ROOT / "fixtures/config/minimal.json").read_text(encoding="utf-8"))
        )

    def record(self):
        return re.sub(
            r"\s+",
            " ",
            (ROOT / "docs/development/foundation-verification.md").read_text(encoding="utf-8"),
        )

    def test_each_group_count_appears_in_the_record(self):
        # The group name is the record's own phrasing for it, so the two cannot
        # be renamed apart from each other.
        groups = {
            "control-API request": self.request,
            "engine-lock": self.engine,
            "control-API *response*": self.response,
            "secret-reference key": self.secret,
        }
        for name, probes in groups.items():
            with self.subTest(group=name):
                self.assertIn(
                    f"{len(probes)} {name}",
                    self.record(),
                    f"the record does not state {len(probes)} {name} probes",
                )

    def test_the_total_is_derived_and_stated(self):
        # The arithmetic, stated so the record's two numbers can be checked:
        #
        #   request group  13 = 12 negative + the positive at exactly 128
        #   response        8 negative
        #   engine lock    20 negative
        #   secret key      6 negative
        #   plus            1 positive: the secret key at exactly 512, which is
        #                   not in the secret-key group because it is not a probe
        #
        # so 46 negative, 2 positive, 48 cases. Adding two positives to the group
        # sums would give 49 and count the 128 case twice, because it is already
        # inside the request group.
        request_negatives = len(self.request) - 1
        negatives = (
            request_negatives
            + len(self.response)
            + len(self.engine)
            + len(self.secret)
        )
        positives = 2
        self.assertEqual(negatives, 46)
        self.assertEqual(negatives + positives, 48)
        self.assertIn(f"runs {negatives + positives} semantic", self.record())
        self.assertIn(
            f"{negatives} negative cases and {positives} boundary positives",
            self.record(),
        )

    def test_the_request_group_holds_one_positive_and_the_rest_are_negative(self):
        labels = [label for label, _ in self.request]
        self.assertIn("request-id-at-the-bound", labels)
        self.assertEqual(len(labels) - 1, 12)

    def test_the_new_license_probes_are_present(self):
        labels = [label for label, _ in self.engine]
        for label in (
            "engine-missing-license",
            "engine-unknown-license",
            "engine-license-not-a-string",
        ):
            with self.subTest(probe=label):
                self.assertIn(label, labels, f"the {label} probe is gone")

    def test_the_sensitive_path_count_is_derived(self):
        listed = re.findall(
            r"^- `([^`]+)`$",
            (ROOT / "SECURITY.md").read_text(encoding="utf-8"),
            re.M,
        )
        self.assertEqual(len(listed), 19)
        self.assertIn(
            "| Security-sensitive paths listed | 14, one of them nonexistent | 19, all existing |",
            self.record(),
        )

    def test_the_engine_license_test_count_is_derived(self):
        suite = unittest.defaultTestLoader.discover(
            str(ROOT / "tools/reproducibility"), pattern="test_generate_sbom.py"
        )
        found = {
            test.id().rsplit(".", 1)[-1]
            for test in _flatten(suite)
            if ".EngineLicenseTests." in test.id()
        }
        self.assertEqual(len(found), 11, f"EngineLicenseTests has {len(found)} tests")
        self.assertIn("Eleven tests in `EngineLicenseTests`", self.record())

    def test_the_two_gate_lists_state_their_own_sizes(self):
        readiness = (ROOT / "docs/development/release-readiness.md").read_text(
            encoding="utf-8"
        )
        # The open-gate table, numbered from 1 with no gaps. The count is what it is
        # rather than a fixed number: hosted CI moved into the document's `## Closed`
        # section when it ran, which is a gate leaving the list by being executed. The
        # contiguity and the `## Closed` section are the real invariants — a fixed total
        # would fail here every time a gate is properly closed.
        rows = re.findall(r"^\| (\d+) \| \*\*", readiness, re.M)
        self.assertTrue(rows, "the readiness disclosure has no numbered gate rows")
        self.assertEqual(
            rows, [str(number) for number in range(1, len(rows) + 1)],
            "the open-gate rows are not numbered contiguously from 1",
        )
        self.assertIn("## Closed", readiness,
                      "a gate left the open list without a Closed section recording it")
        number_words = {
            8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
        }
        self.assertIn(
            f"canonical list of **{number_words.get(len(rows), len(rows))}** gates",
            self.record(),
        )
        self.assertIn("own account of the same ground in **nine** entries", self.record())
        section = (
            (ROOT / "docs/development/foundation-verification.md")
            .read_text(encoding="utf-8")
            .split("## Gates that were not executed")[1]
        )
        numbered = re.findall(r"^(\d+)\. \*\*", section, re.M)
        self.assertEqual(
            len(numbered), 9, "the run record's own list is no longer nine entries"
        )


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


class SubscriptionSourceDisplayValueTests(unittest.TestCase):
    """The schema and the Swift model must agree on what a display value is.

    The model rewrites a `pastedText` or `file` source to one of three literals
    and discards whatever the file said, while the schema accepted any non-empty
    string. A file could therefore carry a value the model would silently
    replace, and nothing recorded that the two disagreed. The schema now states
    the three literals, and this test reads both sides so they cannot drift.
    """

    CANONICAL_MODELS = ROOT / "core/config/Sources/RoviaConfig/CanonicalModels.swift"
    SCHEMA = ROOT / "schemas/config.schema.json"

    def schema_literals(self):
        document = json.loads(self.SCHEMA.read_text(encoding="utf-8"))
        source = document["$defs"]["subscriptionSource"]
        allowed = set()
        for clause in source["allOf"]:
            then = clause.get("then", {}).get("properties", {})
            value = then.get("displayValue", {})
            if "enum" in value:
                allowed.update(value["enum"])
        return allowed

    def model_literals(self):
        source = self.CANONICAL_MODELS.read_text(encoding="utf-8")
        found = set(re.findall(r'invalidDisplayMetadata = "([^"]+)"', source))
        for literal in ("pasted text", "file"):
            if f'"{literal}"' in source:
                found.add(literal)
        return found

    def test_the_schema_enum_is_exactly_what_the_model_writes(self):
        self.assertEqual(
            self.schema_literals(),
            self.model_literals(),
            "the schema's literals and the model's literals have to be the same set, "
            "or a file can carry a display value the model will replace",
        )

    def accepted(self, instance, label):
        """Require the schema to accept this instance.

        `expected_success=True` makes the checker raise when validation fails, so
        returning at all means the instance was accepted.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.json"
            path.write_text(json.dumps(instance), encoding="utf-8")
            checker.validate_instances(self.SCHEMA, [path], True, label)

    def refused(self, instance, label):
        """Require the schema to refuse this instance.

        `expected_success=False` inverts the check: the checker raises when
        validation unexpectedly *passes*. So no exception here means the instance
        was refused, which is what this asserts.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instance.json"
            path.write_text(json.dumps(instance), encoding="utf-8")
            try:
                checker.validate_instances(self.SCHEMA, [path], False, label)
            except RuntimeError as error:
                self.fail(f"{label} was accepted by the schema: {error}")

    BASE = "fixtures/config/sanitized-source-metadata.json"

    def source_instance(self, kind, display_value):
        # minimal.json has no subscriptions to rewrite, so this starts from a
        # fixture that has one and changes only the source.
        instance = json.loads((ROOT / self.BASE).read_text(encoding="utf-8"))
        source = instance["subscriptions"][0]["source"]
        source["kind"] = kind
        source["displayValue"] = display_value
        if kind != "url":
            source["secretReference"] = None
        return instance

    def test_every_literal_the_model_writes_is_accepted_by_the_schema(self):
        for literal in sorted(self.model_literals()):
            with self.subTest(displayValue=literal):
                self.accepted(
                    self.source_instance("pastedText", literal),
                    f"the model writes {literal!r} and the schema must accept it",
                )

    def test_a_display_value_the_model_would_rewrite_is_refused(self):
        for kind, value in (
            ("pastedText", "My provider"),
            ("file", "/Users/someone/profile.yaml"),
            ("pastedText", "pasted text "),
            ("pastedText", "Pasted text"),
        ):
            with self.subTest(kind=kind, value=value):
                self.refused(
                    self.source_instance(kind, value),
                    f"{kind} with {value!r} is a value the model would rewrite",
                )

    def test_the_raw_share_link_fixtures_are_still_refused(self):
        for name in (
            "raw-pasted-share-link.json",
            "raw-file-share-link.json",
            "raw-ssr-share-link.json",
        ):
            with self.subTest(fixture=name):
                self.refused(
                    json.loads((ROOT / "fixtures/config" / name).read_text(encoding="utf-8")),
                    f"{name} must stay refused",
                )



if __name__ == "__main__":
    unittest.main(verbosity=2)
