import copy
import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_VERSION = "0.38.2"
UVX_COMMAND = ["uvx", "--from", f"check-jsonschema=={VALIDATOR_VERSION}", "check-jsonschema"]
VALIDATION_FAILURE_MARKER = "Schema validation errors were encountered."
CONFIG_SCHEMA_PATH = ROOT / "schemas/config.schema.json"
SUBSCRIPTION_SCHEMA_PATH = ROOT / "schemas/subscription.schema.json"
CONTROL_SCHEMA_PATH = ROOT / "schemas/control-api.schema.json"
CONTROL_RESPONSE_SCHEMA_PATH = ROOT / "schemas/control-response.schema.json"
ENGINE_LOCK_SCHEMA_PATH = ROOT / "schemas/engine-lock.schema.json"
ENGINE_LOCK_PATH = ROOT / "engines.lock.json"
CONTROL_FIXTURE_DIR = ROOT / "fixtures/control"
PARSED_SHARE_LINK_FIXTURE = ROOT / "fixtures/subscriptions/parsed-share-link.json"

SECRET_KEYS = [
    "password",
    "passwd",
    "passphrase",
    "pwd",
    "psk",
    "token",
    "secret",
    "uuid",
    "credential",
    "private key",
    "private_key",
    "private-key",
    "authorization",
    "Proxy-Authorization",
    "p-wd",
    "to-ken",
    "co-okie",
    "a-uth",
]
SAFE_KEYS = ["host", "path", "serviceName", "alpn", "monkey"]
RAW_SHARE_LINK_VALUES = [
    "vmess://00000000-0000-0000-0000-000000000001@synthetic.example:443?token=canary#Raw",
    "vless://00000000-0000-0000-0000-000000000001@synthetic.example:443#Raw",
    "trojan://password@synthetic.example:443#Raw",
    "ss://YWVzLTI1Ni1nY206cGFzcw@synthetic.example:443#Raw",
    "ssr://00000000-0000-0000-0000-000000000001:synthetic.example:443#Raw",
]
POSITIVE_CONFIG_FIXTURES = [
    "minimal.json",
    "sanitized-source-metadata.json",
    "secret-reference-key-at-limit.json",
]
NEGATIVE_CONFIG_FIXTURES = [
    "unsupported-version.json",
    "secret-bearing-transport.json",
    "secret-bearing-transport-obfuscated.json",
    "raw-pasted-share-link.json",
    "raw-file-share-link.json",
    "raw-ssr-share-link.json",
    "raw-ssr-url-source.json",
    "url-userinfo-source.json",
    "secret-reference-key-not-printable.json",
    "secret-reference-key-oversized.json",
    "secret-reference-credential-key-not-printable.json",
]
POSITIVE_SUBSCRIPTION_FIXTURES = ["sanitized-source-metadata.json"]
NEGATIVE_SUBSCRIPTION_FIXTURES = [
    "raw-pasted-share-link.json",
    "raw-file-share-link.json",
    "raw-ssr-share-link.json",
    "raw-ssr-url-source.json",
    "url-userinfo-source.json",
]
POSITIVE_CONTROL_FIXTURES = [
    "routing-diagnostic.json",
    "group-selection-decision.json",
    "status-request.json",
]
# The response contract. A request schema that the provider's own answers do not
# satisfy is a schema that describes a protocol nobody implemented, so the
# response envelope has permanent positive and negative fixtures of its own.
POSITIVE_CONTROL_RESPONSE_FIXTURES = [
    "status-response.json",
    "not-implemented-response.json",
    "invalid-request-response.json",
]
NEGATIVE_CONTROL_REQUEST_FIXTURES = [
    "oversized-request-id.json",
    "request-with-extra-field.json",
]
NEGATIVE_CONTROL_RESPONSE_FIXTURES = [
    "status-response-with-error.json",
    "not-implemented-response-with-result.json",
    "response-with-extra-field.json",
    "response-without-ok.json",
    "response-with-unknown-error-code.json",
    "response-with-raw-result-field.json",
]
CONTROL_REQUEST_ID_MAX_LENGTH = 128
CONTROL_RESPONSE_KEYS = {"apiVersion", "requestID", "ok", "result", "error"}
CONTROL_ERROR_CODES = {"invalid-request", "not-implemented"}
MATCHER_REASON_CODES = {"matcherMatched", "matcherDidNotMatch"}
RULE_REASON_CODES = {
    "ruleDisabled",
    "noMatchers",
    "noMatchingMatcher",
    "firstMatchingRule",
    "shadowedByEarlierMatch",
}
DIAGNOSTIC_REASON_CODES = {"firstMatchingRule", "defaultAction", "invalidInput"}
GROUP_REASON_CODES = {
    "selected",
    "emptyGroup",
    "manualSelectionRequired",
    "requestedServerNotMember",
    "noHealthyCandidate",
    "noValidLatency",
    "staleHealthSample",
    "invalidGroup",
}


def load_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def installed_validator_command():
    executable = shutil.which("check-jsonschema")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stdout + result.stderr
    match = re.search(r"\bversion\s+(\d+\.\d+\.\d+)\b", output)
    if result.returncode == 0 and match is not None and match.group(1) == VALIDATOR_VERSION:
        return [executable]
    return None


@lru_cache(maxsize=1)
def validator_command():
    installed = installed_validator_command()
    if installed is not None:
        return installed
    if shutil.which("uvx") is not None:
        return UVX_COMMAND
    raise RuntimeError(
        f"schema validator unavailable: install check-jsonschema=={VALIDATOR_VERSION} or uvx for the pinned fallback"
    )


def is_validation_failure(returncode, stdout, stderr):
    return returncode != 0 and VALIDATION_FAILURE_MARKER in (stdout + stderr)


def run_validator(arguments, expected_success, label):
    try:
        result = subprocess.run(
            validator_command() + arguments,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"schema validator could not run: {label}") from error

    if expected_success and result.returncode != 0:
        raise RuntimeError(f"schema validation failed: {label}")
    if not expected_success and result.returncode == 0:
        raise RuntimeError(f"schema validation unexpectedly passed: {label}")
    if not expected_success and not is_validation_failure(result.returncode, result.stdout, result.stderr):
        raise RuntimeError(f"schema validator failed before validation: {label}")


def validate_metaschemas(schema_paths):
    arguments = ["--check-metaschema", "--quiet", "--color", "never"]
    arguments.extend(str(path) for path in schema_paths)
    run_validator(arguments, True, "schema metaschema")


def validate_instances(schema_path, instance_paths, expected_success, label):
    arguments = [
        "--schemafile",
        str(schema_path),
        "--color",
        "never",
    ]
    arguments.extend(str(path) for path in instance_paths)
    run_validator(arguments, expected_success, label)


def is_valid_parsed_host(host):
    if not isinstance(host, str) or not host or len(host.encode("utf-8")) > 253:
        return False
    if not host.isascii() or host != host.lower() or host.endswith("."):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    labels = host.split(".")
    if not all(
        label
        and len(label) <= 63
        and label[0].isalnum() and label[-1].isalnum()
        and all(character.isascii() and (character.isalnum() or character == "-") for character in label)
        for label in labels
    ):
        return False
    return not all(label.isdigit() for label in labels)


def validate_canonical_parsed_share_link(instance):
    rejected = RuntimeError("canonical parsed share-link metadata rejected")
    if not isinstance(instance, dict):
        raise rejected
    server = instance.get("server")
    display = instance.get("displayValue")
    if not isinstance(server, dict) or not isinstance(display, str):
        raise rejected
    protocol = server.get("protocolKind")
    expected_names = {
        "vless": ("VLESS server", "vless"),
        "trojan": ("Trojan server", "trojan"),
        "shadowsocks": ("Shadowsocks server", "ss"),
    }
    if protocol not in expected_names:
        raise rejected
    expected_name, scheme = expected_names[protocol]
    endpoint = server.get("endpoint")
    if not isinstance(endpoint, dict):
        raise rejected
    host = endpoint.get("host")
    port = endpoint.get("port")
    if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
        raise rejected
    if not is_valid_parsed_host(host):
        raise rejected
    tls = server.get("tls")
    if tls is not None:
        if not isinstance(tls, dict) or not is_valid_parsed_host(tls.get("serverName")):
            raise rejected
    authority_host = f"[{host}]" if ":" in host else host
    expected_display = f"{scheme}://{authority_host}:{port}/••••••••"
    if server.get("name") != expected_name:
        raise rejected
    if server.get("tags") != ["share-link", protocol]:
        raise rejected
    if display != expected_display or len(display.encode("utf-8")) > 512:
        raise rejected
    credential = server.get("credential")
    if not isinstance(credential, dict) or not isinstance(credential.get("key"), str):
        raise rejected
    key_bytes = credential["key"].encode("utf-8")
    if not 1 <= len(key_bytes) <= 512 or any(byte < 33 or byte > 126 for byte in key_bytes):
        raise rejected

    transport = server.get("transport")
    if not isinstance(transport, dict) or not isinstance(transport.get("options"), dict):
        raise rejected
    if "host" in transport["options"] and not is_valid_parsed_host(transport["options"]["host"]):
        raise rejected
    for key, value in transport["options"].items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise rejected
        value_bytes = value.encode("utf-8")
        if not key or len(key.encode("utf-8")) > 64 or not value or len(value_bytes) > 2048:
            raise rejected
        if any(byte < 33 or byte > 126 for byte in key.encode("utf-8") + value_bytes):
            raise rejected


def validate_parsed_share_link(subscription_schema_path, fixture_path, directory):
    validate_canonical_parsed_share_link(load_json(fixture_path))
    subscription_schema = load_json(subscription_schema_path)
    parsed_schema = {
        "$schema": subscription_schema["$schema"],
        "$ref": "#/$defs/parsedShareLink",
        "$defs": subscription_schema["$defs"],
    }
    parsed_schema_path = directory / "parsed-share-link.schema.json"
    write_json(parsed_schema_path, parsed_schema)
    validate_instances(
        parsed_schema_path,
        [fixture_path],
        True,
        "canonical parsed share-link fixture",
    )


def source_instances(fixture, directory, prefix):
    instances = []
    for index, subscription in enumerate(fixture.get("subscriptions", [])):
        path = directory / f"{prefix}-{index}.json"
        write_json(path, subscription)
        instances.append(path)
    return instances


def _control_reject(condition):
    if not condition:
        raise RuntimeError("control API semantic validation failed")


def _control_exact_keys(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def _control_keys_within(value, keys):
    """True when every key is allowed. The response envelope is not an exact
    set, because `result` and `error` are mutually exclusive; the if/then
    branches in the schema are what make the union of the two shapes closed."""
    return isinstance(value, dict) and set(value) <= set(keys)


def _control_uuid(value):
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except (AttributeError, ValueError):
        return False
    return True


def _control_uuid_list(value):
    return isinstance(value, list) and all(_control_uuid(item) for item in value)


def _control_route_action(value):
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        return False
    action_type = value["type"]
    if action_type in {"direct", "block"}:
        return _control_exact_keys(value, {"type"})
    if action_type == "group":
        return _control_exact_keys(value, {"type", "id"}) and _control_uuid(value.get("id"))
    return False


def _validate_control_diagnostic(payload):
    expected = {
        "inputSummary",
        "rules",
        "matchers",
        "finalDecision",
        "selectedGroup",
        "selectedServer",
        "reasonCode",
    }
    _control_reject(_control_exact_keys(payload, expected))
    summary = payload["inputSummary"]
    _control_reject(
        _control_exact_keys(summary, {"hasHost", "hasIP", "hasPort", "hasNetwork"})
        and all(isinstance(summary[key], bool) for key in summary)
    )
    _control_reject(isinstance(payload["rules"], list))
    _control_reject(isinstance(payload["matchers"], list))
    flattened = []
    for rule in payload["rules"]:
        _control_reject(
            _control_exact_keys(rule, {"ruleID", "enabled", "matched", "selected", "reasonCode", "matchers"})
        )
        _control_reject(_control_uuid(rule["ruleID"]))
        _control_reject(all(isinstance(rule[key], bool) for key in ("enabled", "matched", "selected")))
        _control_reject(rule["reasonCode"] in RULE_REASON_CODES)
        _control_reject(isinstance(rule["matchers"], list))
        for matcher in rule["matchers"]:
            _control_validate_matcher(matcher, rule["ruleID"], rule["enabled"])
            flattened.append(matcher)
    _control_reject(flattened == payload["matchers"])
    _control_reject(_control_route_action(payload["finalDecision"]))
    _control_reject(_control_uuid(payload["selectedGroup"]))
    _control_reject(_control_uuid(payload["selectedServer"]))
    _control_reject(payload["reasonCode"] in DIAGNOSTIC_REASON_CODES)


def _control_validate_matcher(matcher, rule_id, rule_enabled):
    expected = {
        "ruleID",
        "matcherIndex",
        "matcherType",
        "matched",
        "selected",
        "applied",
        "ruleEnabled",
        "reasonCode",
    }
    _control_reject(_control_exact_keys(matcher, expected))
    _control_reject(matcher["ruleID"] == rule_id)
    _control_reject(isinstance(matcher["matcherIndex"], int) and not isinstance(matcher["matcherIndex"], bool))
    _control_reject(matcher["matcherIndex"] >= 0)
    _control_reject(
        matcher["matcherType"]
        in {"domain", "domainSuffix", "ipCIDR", "port", "portRange", "network"}
    )
    _control_reject(all(isinstance(matcher[key], bool) for key in ("matched", "selected", "applied", "ruleEnabled")))
    _control_reject(matcher["ruleEnabled"] == rule_enabled)
    _control_reject(matcher["reasonCode"] in MATCHER_REASON_CODES)


def _validate_control_group_selection(payload):
    _control_reject(
        _control_exact_keys(payload, {"groupID", "policy", "selectedServerID", "reasonCode"})
    )
    _control_reject(_control_uuid(payload["groupID"]))
    _control_reject(payload["policy"] in {"manual", "lowestLatency", "failover"})
    _control_reject(_control_uuid(payload["selectedServerID"]))
    _control_reject(payload["reasonCode"] in GROUP_REASON_CODES)


def validate_control_api_semantics(instance):
    _control_reject(
        _control_exact_keys(instance, {"apiVersion", "requestID", "method", "payload"})
    )
    _control_reject(instance["apiVersion"] == 1)
    # The same 1 to 128 the schema states and PacketTunnelProvider enforces.
    _control_reject(
        isinstance(instance["requestID"], str)
        and 0 < len(instance["requestID"]) <= CONTROL_REQUEST_ID_MAX_LENGTH
    )
    method = instance["method"]
    if method == "status.get":
        _control_reject(_control_exact_keys(instance["payload"], set()))
    elif method == "routing.explain":
        _validate_control_diagnostic(instance["payload"])
    elif method == "group.select":
        _validate_control_group_selection(instance["payload"])
    else:
        raise RuntimeError("control API semantic validation failed")


def control_api_negative_probes(root):
    routing = load_json(root / "fixtures/control/routing-diagnostic.json")
    selection = load_json(root / "fixtures/control/group-selection-decision.json")
    probes = []

    matcher_extra = copy.deepcopy(routing)
    matcher_extra["payload"]["rules"][0]["matchers"][0]["rawInput"] = "control-field-canary"
    probes.append(("matcher-extra-field", matcher_extra))

    matcher_cross_role = copy.deepcopy(routing)
    matcher_cross_role["payload"]["rules"][0]["matchers"][0]["reasonCode"] = "firstMatchingRule"
    probes.append(("matcher-cross-role", matcher_cross_role))

    rule_extra = copy.deepcopy(routing)
    rule_extra["payload"]["rules"][0]["rawInput"] = "control-field-canary"
    probes.append(("rule-extra-field", rule_extra))

    rule_cross_role = copy.deepcopy(routing)
    rule_cross_role["payload"]["rules"][0]["reasonCode"] = "matcherMatched"
    probes.append(("rule-cross-role", rule_cross_role))

    diagnostic_extra = copy.deepcopy(routing)
    diagnostic_extra["payload"]["rawInput"] = "control-field-canary"
    probes.append(("diagnostic-extra-field", diagnostic_extra))

    diagnostic_cross_role = copy.deepcopy(routing)
    diagnostic_cross_role["payload"]["reasonCode"] = "matcherDidNotMatch"
    probes.append(("diagnostic-cross-role", diagnostic_cross_role))

    selection_extra = copy.deepcopy(selection)
    selection_extra["payload"]["rawInput"] = "control-field-canary"
    probes.append(("selection-extra-field", selection_extra))

    selection_cross_role = copy.deepcopy(selection)
    selection_cross_role["payload"]["reasonCode"] = "matcherMatched"
    probes.append(("selection-cross-role", selection_cross_role))

    api_version = copy.deepcopy(selection)
    api_version["apiVersion"] = 2
    probes.append(("api-version", api_version))

    status = load_json(root / "fixtures/control/status-request.json")
    status_payload = copy.deepcopy(status)
    status_payload["payload"]["state"] = "connected"
    probes.append(("status-payload-field", status_payload))

    status_extra = copy.deepcopy(status)
    status_extra["rawInput"] = "control-field-canary"
    probes.append(("status-extra-field", status_extra))

    # The requestID bound. The response schema states the same number, and a host
    # that may not send a longer identifier has to be able to match a refusal to
    # its own request.
    oversized_id = copy.deepcopy(status)
    oversized_id["requestID"] = "r" * 129
    probes.append(("request-id-oversized", oversized_id))

    at_bound = copy.deepcopy(status)
    at_bound["requestID"] = "r" * 128
    probes.append(("request-id-at-the-bound", at_bound))

    return probes


def validate_control_api(root, directory):
    schema_path = root / "schemas/control-api.schema.json"
    fixture_dir = root / "fixtures/control"
    validate_metaschemas([schema_path])
    positive_paths = [fixture_dir / name for name in POSITIVE_CONTROL_FIXTURES]
    for path in positive_paths:
        validate_control_api_semantics(load_json(path))
    validate_instances(schema_path, positive_paths, True, "positive control fixture")
    for name in NEGATIVE_CONTROL_REQUEST_FIXTURES:
        instance = load_json(fixture_dir / name)
        try:
            validate_control_api_semantics(instance)
        except RuntimeError:
            pass
        else:
            raise RuntimeError(f"control request negative fixture was accepted: {name}")
        validate_instances(
            schema_path, [fixture_dir / name], False, f"negative control request fixture: {name}"
        )
    for label, instance in control_api_negative_probes(root):
        path = directory / f"{label}.json"
        write_json(path, instance)
        expected = label == "request-id-at-the-bound"
        if not expected:
            try:
                validate_control_api_semantics(instance)
            except RuntimeError:
                pass
            else:
                raise RuntimeError(f"control API semantic probe unexpectedly accepted: {label}")
        # The bound itself is a positive case: a requestID of exactly 128 is
        # valid, and a probe that only ever checked refusals would not notice if
        # the bound were tightened to 127.
        validate_instances(schema_path, [path], expected, f"control API probe: {label}")


def validate_control_response_semantics(instance):
    """The part of the response contract a JSON Schema cannot express on its own.

    The schema closes the envelope; this checks the same rules the extension
    obeys, so a fixture that validates is also a fixture whose shape the provider
    could actually have produced.
    """
    _control_reject(_control_keys_within(instance, CONTROL_RESPONSE_KEYS))
    # The three envelope fields are checked for presence before they are read, so
    # a fixture that drops one is refused by this function rather than crashing
    # it with a KeyError. The schema refuses it too; this is the second reader.
    _control_reject(
        isinstance(instance, dict) and {"apiVersion", "requestID", "ok"} <= set(instance)
    )
    _control_reject(instance["apiVersion"] == 1)
    _control_reject(isinstance(instance["requestID"], str) and 0 < len(instance["requestID"]) <= 128)
    _control_reject(isinstance(instance["ok"], bool))
    if instance["ok"]:
        _control_reject("result" in instance)
        _control_reject("error" not in instance)
        result = instance["result"]
        _control_reject(isinstance(result, dict))
        _control_reject(_control_exact_keys(result, {"state"}))
        _control_reject(isinstance(result["state"], str) and 0 < len(result["state"]) <= 64)
    else:
        _control_reject("error" in instance)
        _control_reject("result" not in instance)
        _control_reject(instance["error"] in CONTROL_ERROR_CODES)


def control_response_negative_probes(root):
    """One weakening per probe, so a probe that stops failing names its rule."""
    status = load_json(root / "fixtures/control/status-response.json")
    refused = load_json(root / "fixtures/control/not-implemented-response.json")
    probes = []

    api_version = copy.deepcopy(status)
    api_version["apiVersion"] = 2
    probes.append(("response-api-version", api_version))

    empty_request_id = copy.deepcopy(status)
    empty_request_id["requestID"] = ""
    probes.append(("response-empty-request-id", empty_request_id))

    missing_result = copy.deepcopy(status)
    del missing_result["result"]
    probes.append(("response-missing-result", missing_result))

    empty_state = copy.deepcopy(status)
    empty_state["result"]["state"] = ""
    probes.append(("response-empty-state", empty_state))

    result_extra = copy.deepcopy(status)
    result_extra["result"]["engineStatus"] = "connected"
    probes.append(("response-result-extra-field", result_extra))

    refused_with_result = copy.deepcopy(refused)
    refused_with_result["result"] = {"state": "disconnected"}
    probes.append(("response-refused-with-result", refused_with_result))

    missing_error = copy.deepcopy(refused)
    del missing_error["error"]
    probes.append(("response-missing-error", missing_error))

    unknown_error = copy.deepcopy(refused)
    unknown_error["error"] = "engine-crashed"
    probes.append(("response-unknown-error", unknown_error))

    return probes


def validate_control_response(root, directory):
    schema_path = root / "schemas/control-response.schema.json"
    fixture_dir = root / "fixtures/control"
    validate_metaschemas([schema_path])
    positive_paths = [fixture_dir / name for name in POSITIVE_CONTROL_RESPONSE_FIXTURES]
    for path in positive_paths:
        validate_control_response_semantics(load_json(path))
    validate_instances(schema_path, positive_paths, True, "positive control response fixture")
    for name in NEGATIVE_CONTROL_RESPONSE_FIXTURES:
        instance = load_json(fixture_dir / name)
        try:
            validate_control_response_semantics(instance)
        except RuntimeError:
            pass
        else:
            raise RuntimeError(f"control response negative fixture was accepted: {name}")
        validate_instances(
            schema_path, [fixture_dir / name], False, f"negative control response fixture: {name}"
        )
    for label, instance in control_response_negative_probes(root):
        path = directory / f"{label}.json"
        write_json(path, instance)
        try:
            validate_control_response_semantics(instance)
        except RuntimeError:
            pass
        else:
            raise RuntimeError(f"control response semantic probe unexpectedly accepted: {label}")
        validate_instances(schema_path, [path], False, f"negative control response probe: {label}")


APPROVED_ENGINE_FIELDS = {
    "enabled": True,
    "source": "https://github.com/XTLS/libXray",
    "version": "25.6.3",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "sourceArchiveSha256": "a" * 64,
    "artifact": "third_party/libXray.aar",
    "sha256": "b" * 64,
    "goVersion": "1.24.0",
    "toolchain": "go1.24.0 darwin/arm64",
    "architectures": ["arm64"],
    "buildFlags": ["-trimpath"],
    "linkedFrameworks": ["Network.framework"],
    "approval": "approved",
    "license": "MIT",
}


def approved_engine_lock():
    """A lock that a release could be built from, used as the probe baseline."""
    return {
        "schemaVersion": 1,
        "runtimePolicy": {
            "maxGoRuntimesPerProcess": 1,
            "allowedProductionEngine": "xray",
        },
        "productionEngines": ["xray"],
        "candidates": {
            "xray": dict(APPROVED_ENGINE_FIELDS),
            "sing-box": {
                "enabled": False,
                "source": "https://github.com/SagerNet/sing-box",
                "version": None,
                "commit": None,
                "sourceArchiveSha256": None,
                "artifact": None,
                "sha256": None,
                "goVersion": None,
                "toolchain": None,
                "architectures": [],
                "buildFlags": [],
                "linkedFrameworks": [],
                "approval": "pending",
                "license": "GPL-3.0-or-later",
            },
        },
    }


def engine_lock_probes():
    """Every way the engine lock could become weaker than the code expects.

    Each probe starts from a fully approved lock and weakens exactly one field,
    so a probe that stops failing identifies the constraint it was covering
    rather than an unrelated required field.
    """

    def mutate(**changes):
        probe = copy.deepcopy(approved_engine_lock())
        for path, value in changes.items():
            target = probe
            *parents, leaf = path.split("__")
            for parent in parents:
                target = target[parent]
            if value is None and leaf in target:
                del target[leaf]
            else:
                target[leaf] = value
        return probe

    def candidate(**changes):
        probe = approved_engine_lock()
        probe["candidates"]["xray"].update(changes)
        return probe

    return [
        ("engine-two-production", mutate(productionEngines=["xray", "xray"])),
        ("engine-unknown-production", mutate(productionEngines=["wireguard"])),
        ("engine-pending-approval", candidate(approval="pending")),
        ("engine-not-enabled", candidate(enabled=False)),
        ("engine-short-commit", candidate(commit="abc1234")),
        ("engine-missing-commit", candidate(commit=None)),
        ("engine-short-digest", candidate(sha256="deadbeef")),
        ("engine-missing-artifact", candidate(artifact=None)),
        ("engine-empty-architectures", candidate(architectures=[])),
        ("engine-empty-build-flags", candidate(buildFlags=[])),
        ("engine-unknown-approval", candidate(approval="self-approved")),
        ("engine-unknown-field", mutate(engine="xray")),
        ("engine-two-go-runtimes", mutate(runtimePolicy={"maxGoRuntimesPerProcess": 2, "allowedProductionEngine": "xray"})),
        ("engine-disallowed-policy", mutate(runtimePolicy={"maxGoRuntimesPerProcess": 1, "allowedProductionEngine": "sing-box"})),
        ("engine-unsupported-schema", mutate(schemaVersion=2)),
        ("engine-missing-candidate", mutate(candidates={})),
        (
            "engine-approved-not-a-production-engine",
            mutate(productionEngines=[], candidates__xray=dict(APPROVED_ENGINE_FIELDS)),
        ),
        (
            "engine-missing-license",
            mutate(
                candidates__xray={
                    key: value
                    for key, value in APPROVED_ENGINE_FIELDS.items()
                    if key != "license"
                }
            ),
        ),
        (
            "engine-unknown-license",
            mutate(candidates__xray=dict(APPROVED_ENGINE_FIELDS, license="WTFPL")),
        ),
        (
            "engine-license-not-a-string",
            mutate(candidates__xray=dict(APPROVED_ENGINE_FIELDS, license=1)),
        ),
    ]
    # A lock that pairs one source with another project's license is not a
    # schema error: the schema constrains `license` to a known identifier and
    # cannot relate it to `source`. tools/reproducibility/generate-sbom.py holds
    # the source-to-license table and refuses the mismatch, and
    # tools/reproducibility/test_generate_sbom.py pins that the schema's enum and
    # the generator's table are the same set.


def validate_engine_lock(root, directory):
    schema_path = root / "schemas/engine-lock.schema.json"
    lock_path = root / "engines.lock.json"
    validate_metaschemas([schema_path])
    validate_instances(schema_path, [lock_path], True, "repository engine lock")

    approved_path = directory / "engine-approved.json"
    write_json(approved_path, approved_engine_lock())
    validate_instances(schema_path, [approved_path], True, "approved engine lock")

    for label, instance in engine_lock_probes():
        path = directory / f"{label}.json"
        write_json(path, instance)
        validate_instances(schema_path, [path], False, f"negative engine lock probe: {label}")


def validate_key_vocabulary(schema_path, minimal, directory):
    for index, key in enumerate(SECRET_KEYS):
        instance = copy.deepcopy(minimal)
        instance["servers"][0]["transport"]["options"] = {key: "synthetic-value"}
        path = directory / f"secret-key-{index}.json"
        write_json(path, instance)
        validate_instances(schema_path, [path], False, "secret transport key")

    for index, key in enumerate(SAFE_KEYS):
        instance = copy.deepcopy(minimal)
        instance["servers"][0]["transport"]["options"] = {key: "synthetic-value"}
        path = directory / f"safe-key-{index}.json"
        write_json(path, instance)
        validate_instances(schema_path, [path], True, "safe transport key")


def secret_reference_key_probes(minimal):
    """One weakness per probe, for the rule the schema states about a key.

    A key is a name, not data: printable ASCII without spaces, at most 512
    characters. Each probe weakens exactly one of those, so a probe that stops
    failing names the constraint it covered.
    """
    probes = []

    def with_key(key):
        instance = copy.deepcopy(minimal)
        instance["subscriptions"] = [
            {
                "id": "00000000-0000-0000-0000-000000000503",
                "name": "Sanitized URL source",
                "source": {
                    "kind": "url",
                    "displayValue": "https://synthetic.example/\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022",
                    "secretReference": {"kind": "keychain", "key": key},
                },
                "serverIDs": [],
                "refreshPolicy": {"mode": "manual", "interval": None},
            }
        ]
        return instance

    for label, key in (
        ("secret-key-space", "subscription/ sanitized"),
        ("secret-key-control", "subscription/sanitized\u0007"),
        ("secret-key-trailing-newline", "subscription/sanitized\n"),
        ("secret-key-non-ascii", "server/credential-\u2705"),
        ("secret-key-oversized", "k" * 513),
    ):
        probes.append((label, with_key(key)))

    empty = with_key("")
    probes.append(("secret-key-empty", empty))

    return probes


def validate_secret_reference_keys(schema_path, minimal, directory):
    for label, instance in secret_reference_key_probes(minimal):
        path = directory / f"{label}.json"
        write_json(path, instance)
        validate_instances(schema_path, [path], False, f"secret reference key probe: {label}")
    at_limit = copy.deepcopy(minimal)
    at_limit["subscriptions"] = secret_reference_key_probes(minimal)[0][1]["subscriptions"]
    at_limit["subscriptions"][0]["source"]["secretReference"]["key"] = "k" * 512
    path = directory / "secret-key-at-limit.json"
    write_json(path, at_limit)
    validate_instances(schema_path, [path], True, "secret reference key at the limit")


def validate_constraint_sentinels(schema_path, minimal, directory):
    missing_required = copy.deepcopy(minimal)
    del missing_required["servers"]
    missing_required_path = directory / "missing-required.json"
    write_json(missing_required_path, missing_required)
    validate_instances(schema_path, [missing_required_path], False, "required constraint")

    invalid_credential = copy.deepcopy(minimal)
    invalid_credential["servers"][0]["credential"] = True
    invalid_credential_path = directory / "invalid-credential.json"
    write_json(invalid_credential_path, invalid_credential)
    validate_instances(schema_path, [invalid_credential_path], False, "oneOf constraint")


def validate_root(root):
    config_schema_path = root / "schemas/config.schema.json"
    subscription_schema_path = root / "schemas/subscription.schema.json"
    fixture_dir = root / "fixtures/config"
    minimal = load_json(fixture_dir / "minimal.json")

    validate_metaschemas(
        [
            config_schema_path,
            subscription_schema_path,
            root / "schemas/control-api.schema.json",
            root / "schemas/control-response.schema.json",
            root / "schemas/engine-lock.schema.json",
        ]
    )

    positive_paths = [fixture_dir / name for name in POSITIVE_CONFIG_FIXTURES]
    validate_instances(config_schema_path, positive_paths, True, "positive config fixture")
    negative_paths = [fixture_dir / name for name in NEGATIVE_CONFIG_FIXTURES]
    for path in negative_paths:
        validate_instances(config_schema_path, [path], False, "negative config fixture")

    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        positive_subscription_paths = []
        for name in POSITIVE_SUBSCRIPTION_FIXTURES:
            positive_subscription_paths.extend(
                source_instances(load_json(fixture_dir / name), directory, "positive-subscription")
            )
        validate_instances(subscription_schema_path, positive_subscription_paths, True, "positive subscription fixture")

        for name in NEGATIVE_SUBSCRIPTION_FIXTURES:
            negative_subscription_paths = source_instances(
                load_json(fixture_dir / name), directory, "negative-subscription"
            )
            validate_instances(subscription_schema_path, negative_subscription_paths, False, "negative subscription fixture")

        validate_key_vocabulary(config_schema_path, minimal, directory)
        validate_constraint_sentinels(config_schema_path, minimal, directory)
        validate_secret_reference_keys(config_schema_path, minimal, directory)
        validate_parsed_share_link(
            subscription_schema_path,
            root / "fixtures/subscriptions/parsed-share-link.json",
            directory,
        )
        validate_control_api(root, directory)
        validate_control_response(root, directory)
        validate_engine_lock(root, directory)

    print(f"Semantic schema checks OK (check-jsonschema {VALIDATOR_VERSION})")


def main():
    validate_root(ROOT)


if __name__ == "__main__":
    main()
