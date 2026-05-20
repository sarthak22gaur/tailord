"""Validation for master.yaml and every variant.

Catches the failure modes most likely to trip up an agent edit:

  * malformed YAML (raised early as a parse error)
  * duplicate bullet / experience / project / education IDs
  * bullets missing required fields (id, text)
  * bullets with no tags (silently dropped by tag filters → easy to miss)
  * variants referencing tags that no bullet has (typo guard)
  * required profile fields missing
  * estimated overflow past one page in any variant render

Exit status is non-zero on any error. Warnings do not fail the build.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

import yaml

from tailord.paths import (
    COVER_VARIANTS_DIR,
    JOBS_GENERATED_DIR,
    MASTER_PATH,
    USER_PREFERENCES_PATH,
    VARIANTS_DIR,
    VAULT_ROOT,
)
from tailord.render import (
    apply_variant,
    find_forbidden_tokens,
    load_master,
    load_variant,
    render_html,
)
from tailord.schema import validate as schema_validate

REQUIRED_PROFILE = ["name", "email"]
REQUIRED_EXPERIENCE = ["id", "company", "role", "start"]
REQUIRED_PROJECT = ["id", "name"]
REQUIRED_EDUCATION = ["id", "institution", "degree"]
REQUIRED_BULLET = ["id", "text"]

# Rough heuristic: one US Letter page of this template (normal mode) fits
# ~3300 chars of _approx_text content. Past ~3600 risks spilling to page 2.
# Calibrate by running `make all` and checking output/*.pdf page counts.
PAGE_TEXT_BUDGET = 3600


class Issue:
    __slots__ = ("level", "where", "message")

    def __init__(self, level: str, where: str, message: str):
        self.level = level
        self.where = where
        self.message = message

    def __str__(self) -> str:
        return f"[{self.level}] {self.where}: {self.message}"


def _missing(d: dict, fields: list[str]) -> list[str]:
    return [f for f in fields if not d.get(f)]


def _all_bullets(master: dict) -> Iterable[tuple[str, dict]]:
    for job in master.get("experience") or []:
        for b in job.get("bullets") or []:
            yield f"experience:{job.get('id', '?')}", b
    for proj in master.get("projects") or []:
        for b in proj.get("bullets") or []:
            yield f"projects:{proj.get('id', '?')}", b


def validate_master(master: dict) -> list[Issue]:
    issues: list[Issue] = []

    miss = _missing(master.get("profile") or {}, REQUIRED_PROFILE)
    if miss:
        issues.append(Issue("error", "profile", f"missing fields: {', '.join(miss)}"))

    for parent_key, required in [
        ("experience", REQUIRED_EXPERIENCE),
        ("projects", REQUIRED_PROJECT),
        ("education", REQUIRED_EDUCATION),
    ]:
        ids = []
        for i, entry in enumerate(master.get(parent_key) or []):
            where = f"{parent_key}[{i}]"
            miss = _missing(entry, required)
            if miss:
                issues.append(Issue("error", where, f"missing: {', '.join(miss)}"))
            if entry.get("id"):
                ids.append(entry["id"])
        for ident, count in Counter(ids).items():
            if count > 1:
                issues.append(Issue("error", parent_key, f"duplicate id '{ident}' ({count} occurrences)"))

    bullet_ids: list[str] = []
    for where, b in _all_bullets(master):
        miss = _missing(b, REQUIRED_BULLET)
        if miss:
            issues.append(Issue("error", where, f"bullet missing: {', '.join(miss)}"))
        if not b.get("tags"):
            issues.append(Issue("warn", where, f"bullet '{b.get('id', '?')}' has no tags"))
        if b.get("id"):
            bullet_ids.append(b["id"])
    for ident, count in Counter(bullet_ids).items():
        if count > 1:
            issues.append(Issue("error", "bullets", f"duplicate bullet id '{ident}' ({count} occurrences)"))

    # Long single bullets compress poorly when the page-fit pass shrinks
    # density — flag them so the author splits or trims before render time.
    for where, b in _all_bullets(master):
        if b.get("text") and len(b["text"]) > 320:
            issues.append(Issue(
                "warn", where,
                f"bullet '{b.get('id','?')}' is {len(b['text'])} chars; consider trimming under ~300"
            ))

    return issues


def validate_variant(name: str, master: dict) -> list[Issue]:
    issues: list[Issue] = []
    try:
        variant = load_variant(name)
    except Exception as e:  # noqa: BLE001
        return [Issue("error", f"variant:{name}", f"failed to load: {e}")]

    all_tags = {t for _, b in _all_bullets(master) for t in (b.get("tags") or [])}
    for kind in ("include_tags", "exclude_tags"):
        for tag in variant.get(kind) or []:
            if tag not in all_tags:
                issues.append(Issue(
                    "warn", f"variant:{name}", f"{kind} references unknown tag '{tag}'"
                ))

    filtered = apply_variant(master, variant)
    text_blob = _approx_text(filtered)
    if len(text_blob) > PAGE_TEXT_BUDGET:
        issues.append(Issue(
            "warn", f"variant:{name}",
            f"estimated overflow: ~{len(text_blob)} text chars (budget {PAGE_TEXT_BUDGET})."
            " Consider lowering max_bullets_per_role or using mode: compact."
        ))

    # Surface roles/projects the renderer dropped because filtering+backfill
    # couldn't reach min_bullets_per_role|project. Usually means exclude_tags
    # vetoed too much; loosen them or add an explicit bullet_select.
    role_min = variant.get("min_bullets_per_role") or 0
    proj_min = variant.get("min_bullets_per_project") or 0
    rendered_role_ids = {j.get("id") for j in filtered.get("experience") or []}
    rendered_project_ids = {p.get("id") for p in filtered.get("projects") or []}
    if role_min:
        for job in master.get("experience") or []:
            if job.get("id") not in rendered_role_ids:
                issues.append(Issue(
                    "warn", f"variant:{name}",
                    f"role '{job.get('id')}' was dropped (filter produced fewer than min={role_min} bullets). "
                    "Loosen exclude_tags or add a bullet_select override if you want it in."
                ))
    if proj_min:
        for proj in master.get("projects") or []:
            if proj.get("id") not in rendered_project_ids:
                issues.append(Issue(
                    "warn", f"variant:{name}",
                    f"project '{proj.get('id')}' was dropped (filter produced fewer than min={proj_min} bullets)."
                ))

    # Real render here so template errors surface in validate (not just at
    # PDF-build time), and so the forbidden-tokens guard runs against the
    # final HTML rather than the unrendered master.
    try:
        html = render_html(name)
    except Exception as e:  # noqa: BLE001
        issues.append(Issue("error", f"variant:{name}", f"render failed: {e}"))
        return issues

    for tok, n in find_forbidden_tokens(html):
        issues.append(Issue(
            "error", f"variant:{name}",
            f"forbidden token/claim {tok!r} appears {n}× in rendered output. "
            "Use public-safe, evidence-backed wording — see skills/resume-evidence-review."
        ))

    issues.extend(_validate_references(name, master))

    return issues


def _validate_references(variant_name: str, master: dict) -> list[Issue]:
    """For job-style variants, every id in bullet_select / bullet_overrides /
    extra_bullets must resolve to a real entity in master.yaml (or, for
    bullet_overrides, an id defined by extra_bullets in this same variant)."""
    issues: list[Issue] = []
    try:
        variant = load_variant(variant_name)
    except Exception:  # noqa: BLE001
        return issues

    role_ids = {j.get("id") for j in master.get("experience") or [] if j.get("id")}
    proj_ids = {p.get("id") for p in master.get("projects") or [] if p.get("id")}
    valid_entity_ids = role_ids | proj_ids

    def bullet_ids_for(entity_id: str) -> set[str]:
        ids: set[str] = set()
        for j in master.get("experience") or []:
            if j.get("id") == entity_id:
                ids.update(b.get("id") for b in j.get("bullets") or [] if b.get("id"))
        for p in master.get("projects") or []:
            if p.get("id") == entity_id:
                ids.update(b.get("id") for b in p.get("bullets") or [] if b.get("id"))
        for extra in (variant.get("extra_bullets") or {}).get(entity_id) or []:
            if extra.get("id"):
                ids.add(extra["id"])
        return ids

    for entity_id, bullet_list in (variant.get("bullet_select") or {}).items():
        if entity_id not in valid_entity_ids:
            issues.append(Issue(
                "error", f"variant:{variant_name}",
                f"bullet_select role/project key '{entity_id}' does not exist in master.yaml."
            ))
            continue
        known = bullet_ids_for(entity_id)
        for bid in bullet_list or []:
            if bid not in known:
                issues.append(Issue(
                    "error", f"variant:{variant_name}",
                    f"bullet_select[{entity_id}] references unknown bullet id '{bid}'."
                ))

    extra_ids: list[str] = []
    for entity_id, extras in (variant.get("extra_bullets") or {}).items():
        if entity_id not in valid_entity_ids:
            issues.append(Issue(
                "error", f"variant:{variant_name}",
                f"extra_bullets key '{entity_id}' does not exist in master.yaml."
            ))
        for e in extras or []:
            if not e.get("id"):
                issues.append(Issue("error", f"variant:{variant_name}",
                    f"extra_bullets[{entity_id}] item is missing `id`"))
                continue
            extra_ids.append(e["id"])
    # extra-bullet ids must not collide with master bullet ids — otherwise
    # bullet_overrides becomes ambiguous about which one it targets.
    master_bullet_ids: set[str] = set()
    for j in master.get("experience") or []:
        master_bullet_ids.update(b.get("id") for b in j.get("bullets") or [] if b.get("id"))
    for p in master.get("projects") or []:
        master_bullet_ids.update(b.get("id") for b in p.get("bullets") or [] if b.get("id"))
    for eid in extra_ids:
        if eid in master_bullet_ids:
            issues.append(Issue(
                "error", f"variant:{variant_name}",
                f"extra_bullets id '{eid}' collides with a bullet id in master.yaml."
            ))

    all_known = master_bullet_ids | set(extra_ids)
    for bid in (variant.get("bullet_overrides") or {}).keys():
        if bid not in all_known:
            issues.append(Issue(
                "error", f"variant:{variant_name}",
                f"bullet_overrides references unknown bullet id '{bid}'."
            ))

    return issues


_HTML_TAG = re.compile(r"<[^>]+>")


def _approx_text(filtered: dict) -> str:
    parts: list[str] = []
    p = filtered.get("profile") or {}
    parts.extend([p.get("name", ""), p.get("location", ""), p.get("email", ""), p.get("phone", "")])
    for job in filtered.get("experience") or []:
        parts.extend([job.get("company", ""), job.get("role", ""), job.get("location", "")])
        for b in job.get("bullets") or []:
            parts.append(b.get("text", ""))
    for proj in filtered.get("projects") or []:
        parts.extend([proj.get("name", ""), proj.get("subtitle", "")])
        for b in proj.get("bullets") or []:
            parts.append(b.get("text", ""))
    for group in filtered.get("skills") or []:
        parts.append(group.get("category", ""))
        parts.extend(group.get("items") or [])
    for edu in filtered.get("education") or []:
        parts.extend([edu.get("institution", ""), edu.get("degree", ""), edu.get("location", "")])
        parts.extend(edu.get("details") or [])
        parts.extend(edu.get("coursework") or [])
    blob = " ".join(parts)
    return _HTML_TAG.sub("", blob)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _schema_issues(schema_name: str, where: str, document: dict) -> list[Issue]:
    return [
        Issue("error", f"schema:{where}", f"{path}: {msg}")
        for path, msg in schema_validate(schema_name, document)
    ]


def validate_vault_against_schemas() -> list[Issue]:
    """Run JSON-Schema validation across every vault file. Soft-fails on
    missing optional files (user-preferences / cover-letter-variants) so
    a partially-populated vault still validates."""
    issues: list[Issue] = []
    if MASTER_PATH.exists():
        issues += _schema_issues("master", MASTER_PATH.name, _load_yaml(MASTER_PATH))
    if USER_PREFERENCES_PATH.exists():
        issues += _schema_issues(
            "user-preferences", USER_PREFERENCES_PATH.name, _load_yaml(USER_PREFERENCES_PATH)
        )
    for variant_path in sorted(VARIANTS_DIR.glob("*.yaml")):
        issues += _schema_issues("variant", f"variants/{variant_path.name}", _load_yaml(variant_path))
    for cl_path in sorted(COVER_VARIANTS_DIR.glob("*.yaml")):
        issues += _schema_issues(
            "cover-letter-variant", f"cover-letter-variants/{cl_path.name}", _load_yaml(cl_path)
        )
    return issues


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate resume data")
    p.add_argument("--variant", "-v", action="append", help="only validate listed variant(s)")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.add_argument("--skip-schema", action="store_true", help="skip JSON-Schema validation")
    args = p.parse_args(argv)

    try:
        master = load_master()
    except yaml.YAMLError as e:
        print(f"[error] master.yaml is malformed: {e}", file=sys.stderr)
        return 2

    issues: list[Issue] = []
    if not args.skip_schema:
        issues += validate_vault_against_schemas()
    issues += validate_master(master)

    variants = args.variant or sorted(p_.stem for p_ in VARIANTS_DIR.glob("*.yaml"))
    for name in variants:
        issues.extend(validate_variant(name, master))

    # Also auto-validate job-specific variants — skipped when the user
    # narrowed scope with --variant.
    if not args.variant:
        for job_path in sorted(JOBS_GENERATED_DIR.glob("*/variant.yaml")):
            issues.extend(validate_variant(str(job_path.relative_to(VAULT_ROOT)), master))

    errors = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warn"]

    for i in issues:
        print(i)
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s).")
    if errors:
        return 1
    if warns and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
