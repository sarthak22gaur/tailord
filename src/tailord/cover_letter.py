"""Cover-letter render + PDF build.

Variant resolution mirrors the resume — a bare name (e.g. "master") looks
under `data/cover-letter-variants/`; a path-shaped value is loaded directly.
Contact info comes from `data/master.yaml`'s `profile` block; voice and
length policy come from `data/user-preferences.yaml` under `cover_letter`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from tailord.paths import (
    COVER_VARIANTS_DIR,
    MASTER_PATH,
    OUTPUT_DIR,
    TEMPLATES_DIR,
    USER_PREFERENCES_PATH,
    VAULT_ROOT,
)
from tailord.render import md_inline

TEMPLATE_NAME = "cover-letter.html.j2"
CSS_NAME = "cover-letter.css"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_variant_path(name_or_path: str) -> Path:
    if "/" in name_or_path or name_or_path.endswith((".yaml", ".yml")):
        p = Path(name_or_path)
        if not p.is_absolute():
            p = VAULT_ROOT / p
        return p.resolve()
    return COVER_VARIANTS_DIR / f"{name_or_path}.yaml"


def load_cover_letter_master() -> dict[str, Any]:
    """Returns the cover-letter voice + policy block.

    Source is `data/user-preferences.yaml` under the `cover_letter` key.
    Returns an empty dict if the file or block is missing — callers
    should treat every field as optional and fall back to safe defaults.
    """
    if not USER_PREFERENCES_PATH.exists():
        return {}
    prefs = _load_yaml(USER_PREFERENCES_PATH)
    return prefs.get("cover_letter") or {}


def load_resume_master_profile() -> dict[str, Any]:
    return _load_yaml(MASTER_PATH).get("profile") or {}


def load_variant(name_or_path: str) -> dict[str, Any]:
    path = _resolve_variant_path(name_or_path)
    if not path.exists():
        if path.parent == COVER_VARIANTS_DIR:
            available = sorted(p.stem for p in COVER_VARIANTS_DIR.glob("*.yaml"))
            raise FileNotFoundError(
                f"Cover-letter variant '{name_or_path}' not found. "
                f"Available: {', '.join(available)}"
            )
        raise FileNotFoundError(f"Cover-letter variant file does not exist: {path}")

    v = _load_yaml(path)
    inferred = path.stem if path.parent == COVER_VARIANTS_DIR else (v.get("name") or path.parent.name)
    v.setdefault("name", inferred)
    v.setdefault("display_name", inferred.replace("_", " ").replace("-", " ").title())
    v.setdefault("output_filename", f"cover_letter_{inferred}")
    v.setdefault("page_format", "Letter")
    v.setdefault("recipient", {})
    v.setdefault("sections", {})
    for k in ("opening_hook", "why_them", "why_me", "closing"):
        v["sections"].setdefault(k, "")
    return v


def _word_count(variant: dict[str, Any]) -> int:
    body = " ".join((variant["sections"].get(k) or "") for k in ("opening_hook", "why_them", "why_me", "closing"))
    return len(re.findall(r"\b\w+\b", body))


def render_html(variant_name_or_path: str) -> tuple[str, dict[str, Any]]:
    variant = load_variant(variant_name_or_path)
    master = load_cover_letter_master()
    profile = load_resume_master_profile()
    if not profile.get("name"):
        raise SystemExit("data/master.yaml is missing profile.name — cannot render cover letter.")

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["md_inline"] = md_inline
    template = env.get_template(TEMPLATE_NAME)
    css = (TEMPLATES_DIR / CSS_NAME).read_text(encoding="utf-8")
    today = _dt.date.today().strftime("%B %-d, %Y") if sys.platform != "win32" else _dt.date.today().strftime("%B %d, %Y")
    html = template.render(
        profile=profile,
        cover_letter=variant,
        master=master,
        css=css,
        date_text=today,
        preview=False,
    )
    return html, variant


def _length_warning(variant: dict[str, Any], master: dict[str, Any]) -> str | None:
    length = master.get("length") or {}
    lo = int(length.get("min_words") or 0)
    hi = int(length.get("max_words") or 10_000)
    wc = _word_count(variant)
    if wc < lo:
        return f"⚠ cover-letter body is {wc} words; below recommended minimum {lo}."
    if wc > hi:
        return f"⚠ cover-letter body is {wc} words; above recommended maximum {hi}."
    return None


def build_pdf(
    variant_name_or_path: str,
    *,
    output_dir: Path | None = None,
    out_name: str | None = None,
) -> Path:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise SystemExit(
            "Playwright is required. Install with:\n"
            "  pip install -e '.[pdf]'\n"
            "  tailord install-browsers\n"
            f"(import error: {e})"
        )

    html, variant = render_html(variant_name_or_path)
    master = load_cover_letter_master()
    warning = _length_warning(variant, master)
    if warning:
        print(warning, file=sys.stderr)

    out_dir = (output_dir or OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_name or variant["output_filename"]
    out_path = out_dir / f"{stem}.pdf"

    fmt = (variant.get("page_format") or "Letter").strip().capitalize()
    if fmt not in {"Letter", "A4", "Legal"}:
        raise ValueError(f"Unsupported page_format '{fmt}'")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except PlaywrightError as e:
            raise SystemExit(
                "Chromium is required for PDF rendering. Install it with:\n"
                "  tailord install-browsers\n"
                f"(Playwright error: {e})"
            ) from e
        try:
            page = browser.new_context().new_page()
            page.set_content(html, wait_until="networkidle")
            page.emulate_media(media="print")
            page.pdf(
                path=str(out_path),
                format=fmt,
                print_background=True,
                prefer_css_page_size=True,
            )
        finally:
            browser.close()

    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render and build a cover-letter PDF.")
    ap.add_argument(
        "--variant",
        required=True,
        help='Variant name (e.g. "master") or path to a YAML file.',
    )
    ap.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: output/).")
    ap.add_argument("--out-name", default=None, help="Output filename stem (default: from variant).")
    ap.add_argument("--html-only", action="store_true", help="Print HTML to stdout instead of building a PDF.")
    args = ap.parse_args(argv)

    if args.html_only:
        html, _ = render_html(args.variant)
        sys.stdout.write(html)
        return 0

    out_path = build_pdf(args.variant, output_dir=args.out_dir, out_name=args.out_name)
    try:
        display = out_path.resolve().relative_to(VAULT_ROOT)
    except ValueError:
        display = out_path
    print(f"wrote {display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
