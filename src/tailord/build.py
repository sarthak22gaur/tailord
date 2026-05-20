"""PDF build pipeline: render a variant to HTML, then drive Chromium via
Playwright to produce a deterministic PDF."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tailord.paths import OUTPUT_DIR, VARIANTS_DIR, VAULT_ROOT
from tailord.render import (
    find_forbidden_tokens,
    load_variant,
    render_html,
)


def _rel(p: Path) -> Path | str:
    """Format a path for display: vault-relative when possible, else as-is."""
    try:
        return p.resolve().relative_to(VAULT_ROOT)
    except ValueError:
        return p


def _pdf_format(variant: dict) -> str:
    fmt = (variant.get("page_format") or "Letter").strip().capitalize()
    if fmt not in {"Letter", "A4", "Legal"}:
        raise ValueError(f"Unsupported page_format '{fmt}' (allowed: Letter, A4, Legal)")
    return fmt


# Logical (CSS) page heights at 96dpi. Used by the page-fit pass to compute
# how much vertical space is available before content overflows page 1.
_PAGE_HEIGHT_PX = {"Letter": 1056, "A4": 1122, "Legal": 1344}

# Density bounds. Below 0.92 the text starts looking cramped; above 1.40 the
# generous line-height makes the resume read like a marketing brochure.
_DENSITY_MIN = 0.92
_DENSITY_MAX = 1.40
# Target fill ratio. ~0.99 lets us spend 99% of the page on content while
# keeping a hair of bottom margin so the printer doesn't clip the last line.
_TARGET_FILL = 0.99


def _page_inner_height_px(variant: dict) -> float:
    """Approximate print-area height in CSS pixels (for callers without a
    live Playwright page). The actual fit pass reads `--page-margin-y` from
    the rendered document, so this constant is only a fallback."""
    total = _PAGE_HEIGHT_PX.get(_pdf_format(variant), 1056)
    return total - 2 * (0.32 * 96)


def _fit_density(page, variant: dict) -> float:
    """Find a `--density` value that makes content fill the page without
    overflowing. Returns the final multiplier (already applied to the page)."""
    fmt = _pdf_format(variant)
    page_h = _PAGE_HEIGHT_PX.get(fmt, 1056)

    def measure() -> tuple[float, float]:
        return page.evaluate(
            """() => {
                const root = getComputedStyle(document.documentElement);
                const marginInches = parseFloat(root.getPropertyValue('--page-margin-y'));
                const dpi = 96;
                const inner = document.querySelector('.resume').getBoundingClientRect().height;
                return [inner, marginInches * dpi];
            }"""
        )

    content_h, margin_px = measure()
    target_h = (page_h - 2 * margin_px) * _TARGET_FILL
    if content_h <= 0:
        return 1.0

    desired = target_h / content_h
    multiplier = max(_DENSITY_MIN, min(_DENSITY_MAX, desired))

    # Apply, re-measure, refine once. One refinement is enough for the
    # values we work with — the relationship is nearly linear over [0.9, 1.4].
    page.evaluate(
        "(m) => document.documentElement.style.setProperty('--density', String(m))",
        multiplier,
    )
    content_h, margin_px = measure()
    target_h = (page_h - 2 * margin_px) * _TARGET_FILL
    if content_h > 0:
        refined = max(_DENSITY_MIN, min(_DENSITY_MAX, multiplier * target_h / content_h))
        if abs(refined - multiplier) > 0.01:
            multiplier = refined
            page.evaluate(
                "(m) => document.documentElement.style.setProperty('--density', String(m))",
                multiplier,
            )
    return multiplier


def build_pdf(
    variant_name: str,
    *,
    output_dir: Path | None = None,
    out_name: str | None = None,
    fit_page: bool = True,
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

    variant = load_variant(variant_name)
    html = render_html(variant_name)

    # Hard-fail when a forbidden token leaks into rendered output (see
    # FORBIDDEN_TOKENS in tailord/render.py). The agent edits content
    # mostly via tool use, and a wording slip can otherwise survive review.
    leaks = find_forbidden_tokens(html)
    if leaks:
        detail = ", ".join(f"{t!r} (×{n})" for t, n in leaks)
        raise SystemExit(
            f"Resume text guard: forbidden token/claim(s) in rendered output for "
            f"variant {variant_name!r}: {detail}.\n"
            f"Use public-safe, evidence-backed wording. See "
            f"skills/resume-evidence-review/SKILL.md."
        )

    out_dir = (output_dir or OUTPUT_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_name or variant["output_filename"]
    out_path = out_dir / f"{stem}.pdf"

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
            context = browser.new_context()
            page = context.new_page()
            page.set_content(html, wait_until="networkidle")
            page.emulate_media(media="print")
            if fit_page:
                _fit_density(page, variant)
            page.pdf(
                path=str(out_path),
                format=_pdf_format(variant),
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build resume PDFs via Playwright")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--variant", "-v",
                   help="variant name (data/variants/<name>.yaml) OR path to a variant yaml")
    g.add_argument("--all", action="store_true", help="build every static variant in data/variants")
    p.add_argument("--out-dir", "-o", type=Path,
                   help=f"directory to write the PDF to (default: {OUTPUT_DIR.name}/)")
    p.add_argument("--out-name", "-n",
                   help="output filename stem; default: variant.output_filename")
    p.add_argument("--no-fit", dest="fit_page", action="store_false", default=True,
                   help="skip the auto page-fit pass (use raw CSS density)")
    args = p.parse_args(argv)

    if args.all:
        variants = sorted(p_.stem for p_ in VARIANTS_DIR.glob("*.yaml"))
        out_dir = args.out_dir or OUTPUT_DIR
        failures: list[tuple[str, Exception]] = []
        for name in variants:
            try:
                path = build_pdf(name, output_dir=out_dir, fit_page=args.fit_page)
                print(f"[ok] {name:<14} → {_rel(path)}")
            except Exception as e:  # noqa: BLE001
                failures.append((name, e))
                print(f"[fail] {name}: {e}", file=sys.stderr)
        return 1 if failures else 0

    name_or_path = args.variant or "master"
    try:
        path = build_pdf(name_or_path,
                         output_dir=args.out_dir,
                         out_name=args.out_name,
                         fit_page=args.fit_page)
        print(f"[ok] → {_rel(path)}")
    except Exception as e:  # noqa: BLE001
        print(f"[fail] {name_or_path}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
