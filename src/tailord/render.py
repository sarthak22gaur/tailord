"""HTML rendering.

Variant filtering rules — non-obvious enough to spell out once:

  Static variants use tag-based filtering:
    * include_tags / exclude_tags drop bullets by tag.
    * Bullets with `pinned: true` survive any filter and ignore caps.
    * Surviving bullets are sorted by `priority` desc, then truncated to
      `max_bullets_per_role` / `max_bullets_per_project`.

  Job-specific variants add explicit selection on top of that:
    * `bullet_select.<entity_id>: [bullet_id, ...]` — exact bullets, in
      order. When set, tag filters and caps are ignored for that entity.
    * `bullet_overrides.<bullet_id>: <new text>` — rewrite an existing
      bullet's text while keeping its tags/priority/etc.
    * `extra_bullets.<entity_id>: [{...}, ...]` — inject new bullets
      (typically derived from research docs) into a role/project.
    * `summary` / `skills_override` — optional overrides for those sections.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import re
import socketserver
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from tailord.paths import (
    MASTER_PATH,
    TEMPLATES_DIR,
    VARIANTS_DIR,
    VAULT_ROOT,
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_master() -> dict[str, Any]:
    return load_yaml(MASTER_PATH)


def resolve_variant_path(name_or_path: str) -> Path:
    """Accept either a variant name (looked up under data/variants/) or a path
    to a yaml file. A value containing a slash or ending in .yaml is treated as
    a path; otherwise as a name.

    Path-shaped values anchor on VAULT_ROOT, not CWD — otherwise calling
    `tailord validate` from anywhere outside the vault dir would fail to
    locate any `jobs/generated/*/variant.yaml`."""
    if "/" in name_or_path or name_or_path.endswith(".yaml") or name_or_path.endswith(".yml"):
        p = Path(name_or_path)
        if not p.is_absolute():
            p = VAULT_ROOT / p
        return p.resolve()
    return VARIANTS_DIR / f"{name_or_path}.yaml"


def load_variant(name_or_path: str) -> dict[str, Any]:
    path = resolve_variant_path(name_or_path)
    if not path.exists():
        if path.parent == VARIANTS_DIR:
            available = sorted(p.stem for p in VARIANTS_DIR.glob("*.yaml"))
            raise FileNotFoundError(
                f"Variant '{name_or_path}' not found. Available: {', '.join(available)}"
            )
        raise FileNotFoundError(f"Variant file does not exist: {path}")

    v = load_yaml(path)
    inferred_name = path.stem if path.parent == VARIANTS_DIR else (v.get("name") or path.parent.name)
    v.setdefault("name", inferred_name)
    v.setdefault("display_name", inferred_name.replace("_", " ").replace("-", " ").title())
    v.setdefault("output_filename", f"resume_{inferred_name}")
    v.setdefault("page_format", "Letter")
    v.setdefault("mode", "normal")
    v.setdefault("include_tags", [])
    v.setdefault("exclude_tags", [])
    v.setdefault("max_bullets_per_role", None)
    v.setdefault("max_bullets_per_project", None)
    # Floor — if filtering drops a role/project below this, backfill from
    # include-rejected bullets (never from exclude-rejected ones). Set to 0
    # to allow a role/project to render with 0 or 1 bullets.
    v.setdefault("min_bullets_per_role", 2)
    v.setdefault("min_bullets_per_project", 2)
    v.setdefault("section_order", ["profile", "experience", "projects", "skills", "education"])
    # Job-variant opt-ins (defaults make them no-ops).
    v.setdefault("bullet_select", {})
    v.setdefault("bullet_overrides", {})
    v.setdefault("extra_bullets", {})
    v.setdefault("summary", None)
    v.setdefault("skills_override", None)
    v["_source_path"] = str(path)
    return v


@dataclass(frozen=True)
class FilterResult:
    selected: list[dict]
    dropped: list[dict]


def _select_bullets(
    bullets: list[dict],
    include: set[str],
    exclude: set[str],
    cap: int | None,
    min_n: int = 0,
) -> FilterResult:
    """Apply tag-based filtering with priority ordering and an optional cap.

    Backfill rule: if the final selected list is shorter than `min_n`, top up
    from bullets that were dropped *only* by `include_tags`. Bullets dropped
    by `exclude_tags` are never backfilled — exclusion is treated as an
    intentional veto."""
    pinned: list[dict] = []
    survivors: list[dict] = []
    include_only_drop: list[dict] = []
    exclude_drop: list[dict] = []

    for b in bullets or []:
        tags = set(b.get("tags") or [])
        if b.get("pinned"):
            pinned.append(b)
            continue
        if exclude and tags & exclude:
            exclude_drop.append(b)
            continue
        if include and not (tags & include):
            include_only_drop.append(b)
            continue
        survivors.append(b)

    survivors.sort(key=lambda b: -(b.get("priority") or 0))
    include_only_drop.sort(key=lambda b: -(b.get("priority") or 0))

    if cap is not None:
        slots = max(0, cap - len(pinned))
        kept_survivors = survivors[:slots]
        truncated = survivors[slots:]
    else:
        kept_survivors = survivors
        truncated = []

    selected = pinned + kept_survivors
    if min_n and len(selected) < min_n:
        needed = min_n - len(selected)
        selected = selected + include_only_drop[:needed]

    selected.sort(key=lambda b: -(b.get("priority") or 0))
    return FilterResult(selected=selected, dropped=truncated + include_only_drop + exclude_drop)


def _bullets_for_entity(
    *,
    base_bullets: list[dict],
    entity_id: str | None,
    variant: dict,
    cap: int | None,
    min_n: int,
) -> list[dict]:
    """Resolve the final bullet list for an experience/project entity.

    Order of operations:
      1. Merge `extra_bullets[entity_id]` from the variant into the pool.
      2. If `bullet_select[entity_id]` exists, take exactly those bullets in
         that order. Tag filters, caps, and min_n are skipped — explicit
         selection means the agent has decided.
      3. Otherwise apply tag-based filtering with the cap and the min-bullet
         backfill rule (see `_select_bullets`).
      4. Apply `bullet_overrides` (text rewrites) as the last step.
    """
    extras = (variant.get("extra_bullets") or {}).get(entity_id) or []
    pool = list(base_bullets or []) + list(extras)

    select_map = variant.get("bullet_select") or {}
    if entity_id in select_map:
        wanted = select_map[entity_id] or []
        by_id = {b.get("id"): b for b in pool if b.get("id")}
        selected = [by_id[bid] for bid in wanted if bid in by_id]
    else:
        include = set(variant.get("include_tags") or [])
        exclude = set(variant.get("exclude_tags") or [])
        selected = _select_bullets(pool, include, exclude, cap, min_n=min_n).selected

    overrides = variant.get("bullet_overrides") or {}
    if overrides:
        selected = [
            {**b, "text": overrides[b["id"]]} if b.get("id") in overrides else b
            for b in selected
        ]
    return selected


def apply_variant(master: dict, variant: dict) -> dict:
    """Return a deep-ish copy of master with bullets filtered/overridden per variant."""
    role_cap = variant.get("max_bullets_per_role")
    project_cap = variant.get("max_bullets_per_project")
    role_min = variant.get("min_bullets_per_role") or 0
    project_min = variant.get("min_bullets_per_project") or 0

    profile = dict(master.get("profile") or {})
    if variant.get("summary"):
        profile["summary"] = variant["summary"]

    skills = variant.get("skills_override") or master.get("skills") or []

    out: dict[str, Any] = {
        "profile": profile,
        "skills": skills,
        "education": master.get("education") or [],
        "experience": [],
        "projects": [],
    }

    # Whole-entry drop policy: if a role/project can't meet its min bullet
    # count (after backfill), drop it entirely — a 1-bullet stub looks worse
    # than a clean omission, and a tailored job variant can always force-
    # include via `bullet_select`.
    select_map = variant.get("bullet_select") or {}

    for job in master.get("experience") or []:
        bullets = _bullets_for_entity(
            base_bullets=job.get("bullets") or [],
            entity_id=job.get("id"),
            variant=variant,
            cap=role_cap,
            min_n=role_min,
        )
        explicit = job.get("id") in select_map
        if not bullets:
            continue
        if role_min and not explicit and len(bullets) < role_min:
            continue
        out["experience"].append({**job, "bullets": bullets})

    for proj in master.get("projects") or []:
        bullets = _bullets_for_entity(
            base_bullets=proj.get("bullets") or [],
            entity_id=proj.get("id"),
            variant=variant,
            cap=project_cap,
            min_n=project_min,
        )
        explicit = proj.get("id") in select_map
        if not bullets:
            continue
        if project_min and not explicit and len(bullets) < project_min:
            continue
        out["projects"].append({**proj, "bullets": bullets})

    return out


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


# Substrings that must never appear in rendered output (case-sensitive, run
# over visible text after stripping HTML tags). Backstop for the
# resume-evidence-review skill — the agent is *told* not to write these,
# but the renderer hard-fails so a slip never ships. Empty by default;
# populate via the RESUME_FORBIDDEN_TOKENS env var (comma-separated) at
# render time.
FORBIDDEN_TOKENS: list[str] = []
import os as _os  # noqa: E402
_env_tokens = _os.environ.get("RESUME_FORBIDDEN_TOKENS", "").strip()
if _env_tokens:
    FORBIDDEN_TOKENS = [t.strip() for t in _env_tokens.split(",") if t.strip()]

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def find_forbidden_tokens(html: str) -> list[tuple[str, int]]:
    """Return [(token, occurrence_count), …] for any forbidden token present
    in the visible text of ``html`` (HTML tags stripped to avoid CSS / class
    name false positives)."""
    text = _HTML_TAG_RE.sub(" ", html)
    found: list[tuple[str, int]] = []
    for tok in FORBIDDEN_TOKENS:
        n = text.count(tok)
        if n:
            found.append((tok, n))
    return found


def md_inline(text: str) -> Markup:
    """Convert ``**bold**`` to ``<strong>bold</strong>``. Everything else is escaped."""
    if text is None:
        return Markup("")
    parts: list[str] = []
    last = 0
    for m in _BOLD_RE.finditer(text):
        parts.append(str(escape(text[last:m.start()])))
        parts.append(f"<strong>{escape(m.group(1))}</strong>")
        last = m.end()
    parts.append(str(escape(text[last:])))
    return Markup("".join(parts).replace("\n", " "))


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["md_inline"] = md_inline
    return env


def render_html(variant_name: str, *, preview: bool = False) -> str:
    master = load_master()
    variant = load_variant(variant_name)
    filtered = apply_variant(master, variant)

    css = (TEMPLATES_DIR / "resume.css").read_text(encoding="utf-8")
    env = _build_env()
    template = env.get_template("resume.html.j2")

    return template.render(
        profile=filtered["profile"],
        experience=filtered["experience"],
        projects=filtered["projects"],
        skills=filtered["skills"],
        education=filtered["education"],
        variant=variant,
        section_order=variant.get("section_order"),
        css=css,
        preview=preview,
    )


def _source_hash(extra_paths: list[Path] | None = None) -> str:
    h = hashlib.sha256()
    paths = [
        MASTER_PATH,
        *VARIANTS_DIR.glob("*.yaml"),
        *TEMPLATES_DIR.glob("*"),
    ]
    if extra_paths:
        paths.extend(extra_paths)
    for p in sorted(set(paths)):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def serve(variant_name: str, port: int) -> None:
    # Touch once early so a bad variant fails before the socket binds.
    initial = load_variant(variant_name)
    variant_path = Path(initial["_source_path"])

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def do_GET(self):
            if self.path == "/_hash":
                body = _source_hash([variant_path]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                html = render_html(variant_name, preview=True)
            except Exception as e:  # noqa: BLE001
                msg = f"<pre style='color:#b00;padding:24px;font:13px/1.4 monospace'>Render error: {escape(str(e))}</pre>"
                body = msg.encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with socketserver.TCPServer(("127.0.0.1", port), Handler) as srv:
        srv.allow_reuse_address = True
        print(f"Preview ready: http://127.0.0.1:{port}  (variant={variant_name}) — Ctrl-C to stop")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nPreview stopped.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render resume HTML")
    p.add_argument("--variant", "-v", default="master", help="variant name (file in data/variants)")
    p.add_argument("--out", "-o", type=Path, help="write HTML to this path; default: stdout")
    p.add_argument("--serve", action="store_true", help="run a hot-reload preview server")
    p.add_argument("--port", type=int, default=8000, help="preview server port (default 8000)")
    args = p.parse_args(argv)

    if args.serve:
        serve(args.variant, args.port)
        return 0

    html = render_html(args.variant)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
