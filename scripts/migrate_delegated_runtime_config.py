#!/usr/bin/env python3
"""Migrate and validate delegated runtime config sections for production deploys."""

from __future__ import annotations

import re
import sys
from pathlib import Path

TOP_LEVEL_RE = re.compile(r"^[A-Za-z0-9_-]+:")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(lines), encoding="utf-8")


def find_top_level_block(lines: list[str], key: str) -> tuple[int, int] | None:
    start = None
    for idx, line in enumerate(lines):
        if line == f"{key}:\n" or line == f"{key}:":
            start = idx
            break
    if start is None:
        return None

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if TOP_LEVEL_RE.match(lines[idx]):
            end = idx
            break
    return start, end


def has_child(lines: list[str], parent: str, child: str) -> bool:
    block_range = find_top_level_block(lines, parent)
    if block_range is None:
        return False
    start, end = block_range
    child_re = re.compile(rf"^  {re.escape(child)}:")
    return any(child_re.match(line) for line in lines[start + 1 : end])


def find_child_block(lines: list[str], parent: str, child: str) -> list[str]:
    block_range = find_top_level_block(lines, parent)
    if block_range is None:
        raise SystemExit(f"Template is missing required {parent}: block")
    start, end = block_range
    child_re = re.compile(rf"^  {re.escape(child)}:")
    next_child_re = re.compile(r"^  [A-Za-z0-9_-]+:")

    child_start = None
    for idx in range(start + 1, end):
        if child_re.match(lines[idx]):
            child_start = idx
            break
    if child_start is None:
        raise SystemExit(f"Template is missing required {parent}.{child} block")

    child_end = end
    for idx in range(child_start + 1, end):
        if next_child_re.match(lines[idx]):
            child_end = idx
            break
    return lines[child_start:child_end]


def required_lines(block: list[str]) -> list[str]:
    return [line.strip() for line in block if line.strip() and not line.lstrip().startswith("#")]


def validate_required_lines(config_block: list[str], template_block: list[str], label: str, config_path: Path) -> None:
    existing = set(required_lines(config_block))
    missing = [line for line in required_lines(template_block) if line not in existing]
    if missing:
        missing_text = "\n  - ".join(missing)
        raise SystemExit(
            f"Existing {label} block in {config_path} is stale or partial. "
            "Refusing to deploy silently. Reconcile this block with the template first. "
            f"Missing required lines:\n  - {missing_text}"
        )


def ensure_top_level_block(config: list[str], template: list[str], key: str, config_path: Path) -> tuple[list[str], bool]:
    existing_range = find_top_level_block(config, key)
    if existing_range is not None:
        template_range = find_top_level_block(template, key)
        if template_range is None:
            raise SystemExit(f"Template is missing required {key}: block")
        existing_start, existing_end = existing_range
        template_start, template_end = template_range
        validate_required_lines(
            config[existing_start:existing_end],
            template[template_start:template_end],
            key,
            config_path,
        )
        return config, False

    block_range = find_top_level_block(template, key)
    if block_range is None:
        raise SystemExit(f"Template is missing required {key}: block")
    start, end = block_range
    if config and not config[-1].endswith("\n"):
        config[-1] += "\n"
    if config and config[-1].strip():
        config.append("\n")
    config.extend(template[start:end])
    if config and config[-1].strip():
        config.append("\n")
    return config, True


def ensure_child_block(config: list[str], template: list[str], parent: str, child: str, config_path: Path) -> tuple[list[str], bool]:
    parent_range = find_top_level_block(config, parent)
    if parent_range is None:
        return ensure_top_level_block(config, template, parent, config_path)
    if has_child(config, parent, child):
        start, end = parent_range
        child_re = re.compile(rf"^  {re.escape(child)}:")
        next_child_re = re.compile(r"^  [A-Za-z0-9_-]+:")
        child_start = None
        child_end = end
        for idx in range(start + 1, end):
            if child_re.match(config[idx]):
                child_start = idx
                break
        if child_start is None:
            raise SystemExit(f"Existing {parent}: block state is inconsistent for {child}")
        for idx in range(child_start + 1, end):
            if next_child_re.match(config[idx]):
                child_end = idx
                break
        validate_required_lines(
            config[child_start:child_end],
            find_child_block(template, parent, child),
            f"{parent}.{child}",
            config_path,
        )
        return config, False

    child_block = find_child_block(template, parent, child)
    _, parent_end = parent_range
    insert = list(child_block)
    if parent_end > 0 and config[parent_end - 1].strip():
        insert.insert(0, "\n")
    config[parent_end:parent_end] = insert
    return config, True


def migrate(config_path: Path, template_path: Path) -> bool:
    config_lines = read_lines(config_path)
    template_lines = read_lines(template_path)
    changed = False

    config_lines, did_change = ensure_child_block(config_lines, template_lines, "acp_agents", "openhands", config_path)
    changed = changed or did_change
    config_lines, did_change = ensure_top_level_block(config_lines, template_lines, "feynman", config_path)
    changed = changed or did_change

    if changed:
        write_lines(config_path, config_lines)
    return changed


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: migrate_delegated_runtime_config.py <config.yaml> <config.template.yaml>", file=sys.stderr)
        return 2

    config_path = Path(sys.argv[1])
    template_path = Path(sys.argv[2])
    changed = migrate(config_path, template_path)
    if changed:
        print(f"Migrated delegated runtime config sections into {config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
