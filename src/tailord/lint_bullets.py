"""House-style linter for resume bullets — mirrors the rules called out in
`skills/resume-bullet-writing/SKILL.md`:

  * Weak verbs / passive framing ("worked on", "helped with", "responsible for")
  * AI filler ("leveraged", "synergies", "best-in-class", …)
  * Bullets past the readable budget (~35 words)
  * Bullets with no **bold** anchor

Exits non-zero on any finding so CI can gate on it.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass

import yaml

from tailord.paths import (
    JOBS_GENERATED_DIR as JOBS_DIR,
    MASTER_PATH,
    VAULT_ROOT as ROOT,
)

# Patterns are case-insensitive, whole-word. The `\b` anchors keep
# substrings inside other words from triggering false positives.
WEAK_VERBS = [
    r"\bworked on\b",
    r"\bhelped with\b",
    r"\b(?:was )?responsible for\b",
    r"\bparticipated in\b",
    r"\bcontributed to\b",
    r"\bassisted with\b",
    r"\bgained exposure to\b",
    r"\binvolved in\b",
]
AI_FILLER = [
    r"\bleverag(?:e|ed|ing|es)\b",
    r"\bsynergies\b",
    r"\bbest[- ]in[- ]class\b",
    r"\bcutting[- ]edge\b",
    r"\bstate[- ]of[- ]the[- ]art\b",
    r"\bworld[- ]class\b",
    r"\bseamlessly\b",
    r"\bsynergistic\b",
    # "robust", "scalable" alone are too context-sensitive — only flag the
    # tell-tale phrasings.
    r"\brobust(?:,? scalable|,? reliable)\b",
    r"\bscalable(?:,? robust|,? reliable)\b",
]

WEAK_RE = re.compile("|".join(WEAK_VERBS), re.IGNORECASE)
AI_RE = re.compile("|".join(AI_FILLER), re.IGNORECASE)
BOLD_RE = re.compile(r"\*\*.+?\*\*", re.DOTALL)
MAX_WORDS = 35


@dataclass
class Finding:
    where: str
    bullet_id: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"  [{self.rule}] {self.where}:{self.bullet_id}\n    {self.detail}"


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _check_bullet(where: str, bullet: dict) -> list[Finding]:
    bid = bullet.get("id") or "<no-id>"
    text = (bullet.get("text") or "").strip()
    findings: list[Finding] = []

    if not text:
        return [Finding(where, bid, "empty", "bullet has no text")]

    for m in WEAK_RE.finditer(text):
        findings.append(Finding(where, bid, "weak-verb",
                                f"contains '{m.group(0)}' — use a specific action verb"))
    for m in AI_RE.finditer(text):
        findings.append(Finding(where, bid, "ai-filler",
                                f"contains '{m.group(0)}' — strip filler"))

    wc = _word_count(text)
    if wc > MAX_WORDS:
        findings.append(Finding(where, bid, "too-long",
                                f"{wc} words (target ≤ {MAX_WORDS})"))

    if not BOLD_RE.search(text):
        findings.append(Finding(where, bid, "no-bold",
                                "bullet has no **bold** anchor — bold the metric or tech"))

    return findings


def lint_master() -> list[Finding]:
    data = yaml.safe_load(MASTER_PATH.read_text(encoding="utf-8")) or {}
    out: list[Finding] = []
    for j in data.get("experience") or []:
        where = f"experience:{j.get('id', '?')}"
        for b in j.get("bullets") or []:
            out.extend(_check_bullet(where, b))
    for p in data.get("projects") or []:
        where = f"projects:{p.get('id', '?')}"
        for b in p.get("bullets") or []:
            out.extend(_check_bullet(where, b))
    return out


def lint_jobs() -> list[Finding]:
    out: list[Finding] = []
    for path in sorted(JOBS_DIR.glob("*/variant.yaml")):
        rel = path.relative_to(ROOT)
        v = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entity_id, extras in (v.get("extra_bullets") or {}).items():
            for b in extras or []:
                out.extend(_check_bullet(f"{rel}:extra:{entity_id}", b))
        for bid, text in (v.get("bullet_overrides") or {}).items():
            out.extend(_check_bullet(f"{rel}:override", {"id": bid, "text": text}))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lint resume bullets against house style")
    p.add_argument("--include-jobs", action="store_true",
                   help="also lint extra_bullets + bullet_overrides under jobs/generated/")
    args = p.parse_args(argv)

    findings = lint_master()
    if args.include_jobs:
        findings.extend(lint_jobs())

    if not findings:
        print("All bullets clean ✓")
        return 0

    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)

    for rule in sorted(by_rule):
        print(f"\n{rule} ({len(by_rule[rule])} occurrence(s)):")
        for f in by_rule[rule]:
            print(f)
    print(f"\n{len(findings)} finding(s) across {len(by_rule)} rule(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
