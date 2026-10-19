import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


CONTRACT = Path(__file__).resolve().parents[1] / "contracts" / "workbench"
FIXTURES = sorted((CONTRACT / "fixtures").glob("*.json"))


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load((CONTRACT / "openapi.yaml").read_text())


def _resolve(contract, value):
    while "$ref" in value:
        reference = value["$ref"]
        assert reference.startswith("#/"), reference
        value = contract
        for part in reference[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _operation(contract, operation_id):
    matches = [
        operation
        for path in contract["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    ]
    assert len(matches) == 1, operation_id
    return matches[0]


def _validator(contract, schema):
    schema = {**schema, "components": contract["components"]}
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _request_validator(contract, operation_id):
    body = _resolve(contract, _operation(contract, operation_id)["requestBody"])
    return _validator(contract, body["content"]["application/json"]["schema"])


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda path: path.name)
def test_fixture_matches_declared_response(contract, fixture_path):
    operation_id = fixture_path.name.split(".", 1)[0]
    if operation_id == "error":
        schemas = [{"$ref": "#/components/schemas/Error"}]
    else:
        schemas = []
        for status, response in _operation(contract, operation_id)["responses"].items():
            response = _resolve(contract, response)
            if str(status).startswith("2") and "application/json" in response.get("content", {}):
                schemas.append(response["content"]["application/json"]["schema"])
    assert schemas, fixture_path.name
    _validator(contract, {"anyOf": schemas}).validate(json.loads(fixture_path.read_text()))


@pytest.mark.parametrize("missing", [
    ("database_generation",),
    ("expected_schema_version",),
    ("rows", 0, "id"),
    ("rows", 0, "expected_revision"),
])
def test_patch_rejects_missing_write_guards(contract, missing):
    payload = {
        "database_generation": 2,
        "expected_schema_version": 3,
        "mode": "patch",
        "rows": [{"id": "row_1", "expected_revision": 4, "values": {"email": "a@example.test"}}],
    }
    validator = _request_validator(contract, "writeRows")
    validator.validate(payload)
    target = payload
    for part in missing[:-1]:
        target = target[part]
    del target[missing[-1]]
    with pytest.raises(ValidationError):
        validator.validate(payload)


def test_create_table_does_not_accept_imported_rows(contract):
    payload = {
        "name": "leads",
        "columns": [{"sql_name": "email", "storage_type": "TEXT", "nullable": True}],
    }
    validator = _request_validator(contract, "createTable")
    validator.validate(payload)
    with pytest.raises(ValidationError):
        validator.validate({**payload, "rows": [{"email": "a@example.test"}]})


def test_table_metadata_update_requires_compare_and_set_revision(contract):
    payload = {"name": "renamed-leads", "expected_metadata_revision": 2}
    validator = _request_validator(contract, "updateTable")
    validator.validate(payload)
    for revision in (None, 0):
        invalid = {"name": payload["name"]}
        if revision is not None:
            invalid["expected_metadata_revision"] = revision
        with pytest.raises(ValidationError):
            validator.validate(invalid)


@pytest.mark.parametrize("field", ["database_generation", "schema_version"])
def test_ready_table_requires_verified_versions(contract, field):
    table = json.loads((CONTRACT / "fixtures" / "getTable.leads.json").read_text())
    validator = _validator(contract, {"$ref": "#/components/schemas/Table"})
    validator.validate(table)
    for version in (None, 0):
        invalid = copy.deepcopy(table)
        invalid[field] = version
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_creating_table_does_not_claim_verified_versions(contract):
    table = json.loads((CONTRACT / "fixtures" / "getTable.creating.json").read_text())
    _validator(contract, {"$ref": "#/components/schemas/Table"}).validate(table)
    assert table["status"] == "creating"
    assert table["database_generation"] is None
    assert table["schema_version"] is None
