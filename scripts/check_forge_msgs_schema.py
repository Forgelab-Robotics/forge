from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "interfaces" / "forge_msgs"
VERSIONS_PATH = ROOT / "versions.toml"
ALLOWED_IMPLEMENTATIONS = {"python", "rust", "cpp"}


class SchemaError(ValueError):
    pass


def _interface_version() -> int:
    try:
        with VERSIONS_PATH.open("rb") as handle:
            value = tomllib.load(handle)["interfaces"]["msgs"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise SchemaError(f"{VERSIONS_PATH}: failed to load Msgs interface version: {exc}") from exc
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchemaError(f"{VERSIONS_PATH}: interfaces.msgs must be a positive integer")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"{path}: failed to load YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise SchemaError(f"{path}: top-level value must be a mapping")
    return value


def _require_equal(
    path: Path, document: dict[str, Any], key: str, expected: Any
) -> None:
    actual = document.get(key)
    if actual != expected:
        raise SchemaError(f"{path}: {key} must be {expected!r}, got {actual!r}")


def _validate_message(path: Path, name: str, message: Any) -> None:
    if not isinstance(name, str) or not name:
        raise SchemaError(f"{path}: message names must be non-empty strings")
    if not isinstance(message, dict):
        raise SchemaError(f"{path}: message {name} must be a mapping")
    if not isinstance(message.get("purpose"), str) or not message["purpose"]:
        raise SchemaError(f"{path}: message {name} must define a purpose")
    if message.get("row_count") != "single":
        raise SchemaError(f"{path}: message {name} must use row_count: single")

    fields = message.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise SchemaError(f"{path}: message {name} must define at least one field")
    for field_name, field in fields.items():
        if not isinstance(field_name, str) or not field_name:
            raise SchemaError(f"{path}: {name} field names must be non-empty strings")
        if not isinstance(field, dict):
            raise SchemaError(f"{path}: {name}.{field_name} must be a mapping")
        if not isinstance(field.get("arrow"), str) or not field["arrow"]:
            raise SchemaError(f"{path}: {name}.{field_name} must define an Arrow type")
        if not isinstance(field.get("required"), bool):
            raise SchemaError(f"{path}: {name}.{field_name} must define required: bool")

    implementations = message.get("implementations")
    if implementations is not None:
        if not isinstance(implementations, list) or not implementations:
            raise SchemaError(
                f"{path}: {name}.implementations must be a non-empty list"
            )
        unknown = set(implementations) - ALLOWED_IMPLEMENTATIONS
        if unknown:
            raise SchemaError(
                f"{path}: {name}.implementations contains unsupported values: "
                f"{sorted(unknown)}"
            )


def validate() -> list[str]:
    interface_version = _interface_version()
    manifest_path = SCHEMA_DIR / f"forge_msgs.v{interface_version}.yaml"
    manifest = _load_yaml(manifest_path)
    version = manifest.get("version")
    package = manifest.get("package")
    if not isinstance(version, int) or version < 1:
        raise SchemaError(f"{manifest_path}: version must be a positive integer")
    if version != interface_version:
        raise SchemaError(
            f"{manifest_path}: version must match versions.toml interfaces.msgs={interface_version}"
        )
    if not isinstance(package, str) or not package:
        raise SchemaError(f"{manifest_path}: package must be a non-empty string")

    schema_files = manifest.get("schema_files")
    if not isinstance(schema_files, dict) or not schema_files:
        raise SchemaError(f"{manifest_path}: schema_files must be a non-empty mapping")
    if "common" not in schema_files:
        raise SchemaError(f"{manifest_path}: schema_files must include common")

    seen_messages: dict[str, Path] = {}
    loaded_files: set[Path] = set()
    summaries: list[str] = []

    for domain, filename in schema_files.items():
        if not isinstance(domain, str) or not domain:
            raise SchemaError(f"{manifest_path}: schema domain names must be non-empty")
        if not isinstance(filename, str) or not filename:
            raise SchemaError(f"{manifest_path}: schema filenames must be non-empty")

        path = SCHEMA_DIR / filename
        if path in loaded_files:
            raise SchemaError(
                f"{manifest_path}: schema file referenced twice: {filename}"
            )
        if not path.is_file():
            raise SchemaError(f"{manifest_path}: missing schema file: {filename}")
        loaded_files.add(path)

        document = _load_yaml(path)
        _require_equal(path, document, "version", version)
        _require_equal(path, document, "package", package)
        _require_equal(path, document, "domain", domain)

        if domain == "common":
            if not isinstance(document.get("conventions"), dict):
                raise SchemaError(f"{path}: common schema must define conventions")
            if "messages" in document:
                raise SchemaError(f"{path}: common schema must not define messages")
            summaries.append(f"{domain}: conventions")
            continue

        messages = document.get("messages")
        if not isinstance(messages, dict):
            raise SchemaError(f"{path}: messages must be a mapping")
        for name, message in messages.items():
            previous = seen_messages.get(name)
            if previous is not None:
                raise SchemaError(
                    f"{path}: duplicate message {name}; already defined in {previous}"
                )
            _validate_message(path, name, message)
            seen_messages[name] = path
        summaries.append(f"{domain}: {len(messages)} messages")

    unreferenced = sorted(
        path.name
        for path in SCHEMA_DIR.glob(f"*.v{interface_version}.yaml")
        if path != manifest_path and path not in loaded_files
    )
    if unreferenced:
        raise SchemaError(
            f"{manifest_path}: unreferenced v{interface_version} schema files: {unreferenced}"
        )

    summaries.append(f"total: {len(seen_messages)} messages")
    return summaries


def main() -> int:
    try:
        summaries = validate()
    except SchemaError as exc:
        print(f"forge_msgs schema check failed: {exc}", file=sys.stderr)
        return 1
    print("forge_msgs schema check passed")
    for summary in summaries:
        print(f"- {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
