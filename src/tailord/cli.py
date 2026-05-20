"""Unified CLI entrypoint — `tailord <subcommand>`.

Every cmd_* function imports its dependencies *inside* the body so that
`main()` can rewrite RESUME_VAULT in os.environ before `tailord.paths` /
`tailord.config` snapshot it into module-level constants (VAULT_ROOT,
MASTER_PATH, etc.). Without lazy imports, --vault would be applied too
late on subcommands that touch the vault.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _framework_root() -> Path:
    from tailord.config import FRAMEWORK_ROOT
    return FRAMEWORK_ROOT


def _repo_root() -> Path | None:
    """Return the editable-clone repo root, if this CLI is running from one."""
    from tailord.bridge_runtime import repo_root
    return repo_root(_framework_root())


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw or default


def _node_version_ok(node_bin: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [node_bin, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        return False, str(e)
    raw = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0:
        return False, raw or f"node exited with code {result.returncode}"
    version = raw.removeprefix("v")
    try:
        major, minor, patch = (int(part) for part in version.split(".")[:3])
    except ValueError:
        return False, raw
    return (major, minor, patch) >= (20, 6, 0), raw


def _playwright_module_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _chromium_installed() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    try:
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).is_file()
    except Exception:  # noqa: BLE001 - doctor should report, not crash.
        return False


def cmd_init(args: argparse.Namespace) -> int:
    from tailord.config import CONFIG_FILENAME

    sample_vault = _framework_root() / "examples" / "sample-vault"
    if not sample_vault.exists():
        print(f"sample vault missing at {sample_vault} — broken install?", file=sys.stderr)
        return 2

    target = Path(args.path).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        print(f"refusing to init: {target} exists and is non-empty", file=sys.stderr)
        return 2

    print(f"\nInitializing vault at {target}")
    print("Press Enter to accept a default, or type a value to override.\n")
    name = _prompt("name", "Jane Doe")
    email = _prompt("email", "you@example.com")
    location = _prompt("location", "Brooklyn, NY")
    needs_sponsorship = _prompt("requires visa sponsorship? (y/n)", "n").lower().startswith("y")

    # dirs_exist_ok lets us scaffold into a pre-created empty dir
    # (e.g. one the user just created via mkdir).
    shutil.copytree(sample_vault, target, dirs_exist_ok=True)

    master_path = target / "data" / "master.yaml"
    text = master_path.read_text(encoding="utf-8")
    text = (
        text.replace("Jane Doe", name)
            .replace("jane.doe@example.com", email)
            .replace("Brooklyn, NY", location)
    )
    master_path.write_text(text, encoding="utf-8")

    if needs_sponsorship:
        prefs_path = target / "data" / "user-preferences.yaml"
        prefs_text = prefs_path.read_text(encoding="utf-8")
        prefs_text = prefs_text.replace(
            "requires_sponsorship: false", "requires_sponsorship: true"
        )
        prefs_path.write_text(prefs_text, encoding="utf-8")

    # Drop a .resumerc.yaml at the vault root so future commands resolve
    # the vault without needing RESUME_VAULT in the environment.
    (target / CONFIG_FILENAME).write_text(f"vault: {target}\n", encoding="utf-8")

    print(f"\n✓ Scaffolded vault at {target}")
    print(f"✓ Wrote {target / CONFIG_FILENAME}")
    print("\nNext steps:")
    print(f"  1. cd {target}")
    print("  2. edit data/master.yaml with your real work history")
    print("  3. tailord validate")
    print("  4. tailord build")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from tailord import validate as validate_mod

    forwarded: list[str] = []
    if args.variant:
        for v in args.variant:
            forwarded += ["--variant", v]
    if args.strict:
        forwarded.append("--strict")
    return validate_mod.main(forwarded)


def cmd_doctor(args: argparse.Namespace) -> int:
    from tailord import validate as validate_mod
    from tailord.config import Config

    cfg = Config.load()
    print(f"vault         {cfg.vault}")
    print(f"  source      {cfg.source}")
    print(f"framework     {_framework_root()}")
    print(f"model_runner  {cfg.model_runner}")

    checks: list[tuple[str, bool]] = []
    checks.append(("claude CLI", shutil.which("claude") is not None))
    checks.append(("playwright module", _playwright_module_available()))
    checks.append(("chromium browser", _chromium_installed()))
    checks.append(("ANTHROPIC_API_KEY set", bool(os.environ.get("ANTHROPIC_API_KEY"))))
    has_vault = (cfg.vault / "data" / "master.yaml").is_file()
    checks.append(("vault data/master.yaml", has_vault))

    print("")
    for label, ok in checks:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {label}")

    print("")
    if not has_vault and cfg.source == "defaults":
        print(
            "No vault discovered yet. Run `tailord init <path>` or pass "
            "`--vault <path>` once you have one."
        )
        return 0
    return validate_mod.main([])


def cmd_install_browsers(args: argparse.Namespace) -> int:
    if not _playwright_module_available():
        print(
            "Playwright is not installed. Install tailord with the PDF extra first:\n"
            "  pipx install 'tailord[pdf] @ git+https://github.com/sarthak22gaur/tailord.git'\n"
            "or, from a clone:\n"
            "  pip install -e '.[pdf]'",
            file=sys.stderr,
        )
        return 2
    return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


def cmd_build(args: argparse.Namespace) -> int:
    from tailord import build as build_mod

    forwarded: list[str] = []
    if args.all:
        forwarded.append("--all")
    elif args.variant:
        forwarded += ["--variant", args.variant]
    if args.out_dir:
        forwarded += ["--out-dir", str(args.out_dir)]
    if args.out_name:
        forwarded += ["--out-name", args.out_name]
    return build_mod.main(forwarded)


def cmd_cover(args: argparse.Namespace) -> int:
    from tailord import cover_letter as cover_mod

    forwarded = ["--variant", args.variant]
    if args.out_dir:
        forwarded += ["--out-dir", str(args.out_dir)]
    if args.out_name:
        forwarded += ["--out-name", args.out_name]
    if args.html_only:
        forwarded.append("--html-only")
    return cover_mod.main(forwarded)


def cmd_preview(args: argparse.Namespace) -> int:
    from tailord import render as render_mod

    forwarded = ["--serve", "--variant", args.variant, "--port", str(args.port)]
    return render_mod.main(forwarded)


def cmd_setup_bridge(args: argparse.Namespace) -> int:
    import secrets
    from tailord.bridge_runtime import ensure_bridge_runtime, ensure_framework_workspace
    from tailord.config import Config

    cfg = Config.load()
    try:
        bridge_dir = ensure_bridge_runtime(_framework_root())
        framework_dir = ensure_framework_workspace(_framework_root(), cfg.vault)
    except FileNotFoundError as e:
        print(
            f"✗ {e}",
            file=sys.stderr,
        )
        return 2

    env_path = bridge_dir / ".env"
    write_env = args.force or not env_path.exists()

    if not args.skip_npm:
        node_bin = shutil.which("node")
        if node_bin is None:
            print(
                "✗ node not found on PATH. Install Node.js 20.6+ first, then "
                "re-run `tailord setup-bridge`.",
                file=sys.stderr,
            )
            return 2
        ok, version = _node_version_ok(node_bin)
        if not ok:
            print(
                f"✗ Node.js 20.6+ is required for `node --env-file`; found {version or 'unknown'}.\n"
                "  Upgrade Node.js, then re-run `tailord setup-bridge`.",
                file=sys.stderr,
            )
            return 2
        if shutil.which("npm") is None:
            print(
                "✗ npm not found on PATH. Install Node.js 20.6+ with npm, then "
                "re-run `tailord setup-bridge`.",
                file=sys.stderr,
            )
            return 2

    if write_env:
        env_text = "\n".join([
            "# Generated by `tailord setup-bridge`. Safe to hand-edit.",
            "BRIDGE_PORT=8787",
            f"BRIDGE_TOKEN={secrets.token_hex(24)}",
            "BRIDGE_ALLOW_NO_TOKEN=0",
            "BRIDGE_ALLOWED_ORIGINS=",
            "CONCURRENCY=4",
            "CLAUDE_TIMEOUT_MS=1800000",
            "CLAUDE_OUTPUT_LIMIT_BYTES=2097152",
            f"RESUME_VAULT={cfg.vault}",
            f"RESUME_FRAMEWORK={framework_dir}",
            f"PYTHON={sys.executable}",
            "CLAUDE_BIN=claude",
            "CLAUDE_FLAGS=--dangerously-skip-permissions --output-format=json",
            "CLAUDE_MODEL_EVALUATE=claude-sonnet-4-6",
            "CLAUDE_MODEL_GENERATE=claude-opus-4-7",
            "",
        ])
        env_path.write_text(env_text, encoding="utf-8")
        print(f"✓ wrote {env_path}")
    else:
        print(f"✓ reusing existing {env_path}")
        print("  re-run with --force to regenerate BRIDGE_TOKEN and rewrite .env")
    print(f"  RESUME_VAULT={cfg.vault}")
    print(f"  RESUME_FRAMEWORK={framework_dir}")
    print(f"  bridge runtime={bridge_dir}")
    print("  runtime files are refreshed by setup-bridge/serve; edit a clone for custom bridge or skill code")

    if not args.skip_npm:
        print(f"\nrunning npm install in {bridge_dir} (this can take a minute)...")
        rc = subprocess.call(["npm", "install"], cwd=bridge_dir)
        if rc != 0:
            print(
                f"✗ npm install failed with code {rc}. Re-run "
                "`tailord setup-bridge --force` after fixing the npm error.",
                file=sys.stderr,
            )
            return rc
        print("✓ npm dependencies installed")

    print("\nBridge is set up. To start it:")
    print("  tailord serve")
    print("\nThen open the Tailord extension's Options and use:")
    print("  Bridge URL:   http://127.0.0.1:8787")
    print(f"  Bridge token: (copy from the BRIDGE_TOKEN line in {env_path})")
    print("  Test connection should report the bridge queue status.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from tailord.bridge_runtime import ensure_bridge_runtime, ensure_framework_workspace
    from tailord.config import Config

    cfg = Config.load()
    try:
        bridge_dir = ensure_bridge_runtime(_framework_root())
        framework_dir = ensure_framework_workspace(_framework_root(), cfg.vault)
    except FileNotFoundError as e:
        print(
            f"✗ {e}",
            file=sys.stderr,
        )
        return 2

    node_bin = shutil.which("node")
    if node_bin is None:
        print(
            "node not found on PATH. Install Node.js 20.6+ and run "
            "`tailord setup-bridge` first.",
            file=sys.stderr,
        )
        return 2
    ok, version = _node_version_ok(node_bin)
    if not ok:
        print(
            f"Node.js 20.6+ is required for the bridge; found {version or 'unknown'}.",
            file=sys.stderr,
        )
        return 2

    cmd = [node_bin, "src/server.js"]
    env_file = bridge_dir / ".env"
    if env_file.exists():
        cmd = [node_bin, f"--env-file={env_file}", "src/server.js"]
    elif not os.environ.get("BRIDGE_TOKEN"):
        print(
            f"bridge is not set up yet: {env_file} is missing.\n"
            "Run `tailord setup-bridge` first.",
            file=sys.stderr,
        )
        return 2

    # Hand the bridge the resolved vault + framework so a split-vault setup
    # works without the user keeping tools/jd-bridge/.env in sync.
    env = {
        **os.environ,
        "RESUME_VAULT": str(cfg.vault),
        "RESUME_FRAMEWORK": str(framework_dir),
        "PYTHON": sys.executable,
    }

    print(f"starting jd-bridge in {bridge_dir} (Ctrl-C to stop)")
    print(f"  RESUME_VAULT={cfg.vault}")
    print(f"  RESUME_FRAMEWORK={framework_dir}")
    return subprocess.call(cmd, cwd=bridge_dir, env=env)


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


IMPORT_START_MARKER = "---MASTER YAML---"
IMPORT_END_MARKER = "---END MASTER YAML---"
METRIC_RE = re.compile(r"(\d|%|\$)")
BOLD_RE = re.compile(r"\*\*.+?\*\*", re.DOTALL)


class ImportSourceError(Exception):
    pass


def _read_resume_source(source: Path) -> str:
    if str(source) == "-":
        return sys.stdin.read()

    suffix = source.suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return source.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ImportSourceError(f"resume file not found: {source}") from None
        except OSError as e:
            raise ImportSourceError(f"could not read resume file {source}: {e}") from e

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ImportSourceError(
                "pypdf is required for PDF import. Reinstall tailord or run:\n"
                "  pip install 'pypdf>=4.0'"
            ) from e
        try:
            with source.open("rb") as f:
                reader = PdfReader(f)
                return "\f".join((page.extract_text() or "").strip() for page in reader.pages)
        except FileNotFoundError:
            raise ImportSourceError(f"resume file not found: {source}") from None
        except OSError as e:
            raise ImportSourceError(f"could not read resume file {source}: {e}") from e

    raise ImportSourceError("unsupported file type; convert to PDF or paste into a .txt file")


def _extract_marked_yaml(response: str) -> str:
    start = response.find(IMPORT_START_MARKER)
    end = response.find(IMPORT_END_MARKER, start + len(IMPORT_START_MARKER))
    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            f"model response did not include {IMPORT_START_MARKER} / {IMPORT_END_MARKER} markers"
        )
    return response[start + len(IMPORT_START_MARKER):end].strip()


def _write_import_debug(vault_root: Path, raw_yaml: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug_dir = vault_root / "jobs" / "imports" / stamp
    debug_dir.mkdir(parents=True, exist_ok=True)
    raw_path = debug_dir / "raw.yaml"
    raw_path.write_text(raw_yaml.rstrip() + "\n", encoding="utf-8")
    return raw_path


def _load_yaml_text(text: str) -> Any:
    import yaml

    return yaml.safe_load(text)


def _dump_yaml(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=1000)


def _is_sample_master(master_path: Path, framework_root: Path) -> bool:
    import copy
    import yaml

    if not master_path.exists():
        return False
    sample_path = framework_root / "examples" / "sample-vault" / "data" / "master.yaml"
    try:
        existing = yaml.safe_load(master_path.read_text(encoding="utf-8")) or {}
        sample = yaml.safe_load(sample_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return False

    def normalized(document: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(document)
        out["profile"] = {}
        experience = out.get("experience") or []
        if experience:
            experience[0].pop("location", None)
        return out

    return normalized(existing) == normalized(sample)


def _schema_errors(document: Any) -> list[str]:
    from tailord.schema import validate as schema_validate

    if not isinstance(document, dict):
        return ["(root): expected a YAML mapping/object"]
    return [f"{path}: {message}" for path, message in schema_validate("master", document)]


def _all_import_bullets(master: dict[str, Any]) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    for job in master.get("experience") or []:
        bullets.extend(job.get("bullets") or [])
    for project in master.get("projects") or []:
        bullets.extend(project.get("bullets") or [])
    return bullets


def _bullets_without_anchor(master: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for bullet in _all_import_bullets(master):
        text = bullet.get("text") or ""
        if not METRIC_RE.search(text) and not BOLD_RE.search(text):
            missing.append(str(bullet.get("id") or "<no-id>"))
    return missing


def _print_import_report(master: dict[str, Any], *, stream: Any) -> None:
    experience = master.get("experience") or []
    projects = master.get("projects") or []
    skills = master.get("skills") or []
    education = master.get("education") or []
    bullet_count = sum(len(job.get("bullets") or []) for job in experience)
    weak_anchor_ids = _bullets_without_anchor(master)

    print("", file=stream)
    print("Import sanity report:", file=stream)
    print(f"  Experience: {len(experience)} entries, {bullet_count} bullets", file=stream)
    print(f"  Projects: {len(projects)}", file=stream)
    print(f"  Skill categories: {len(skills)}", file=stream)
    print(f"  Education: {len(education)}", file=stream)
    print("  Bullets without a metric / **bold** anchor:", file=stream)
    if weak_anchor_ids:
        for bullet_id in weak_anchor_ids:
            print(f"    - {bullet_id}", file=stream)
    else:
        print("    none", file=stream)
    print("    Tip: run `python -m tailord.lint_bullets` after edits.", file=stream)
    print("", file=stream)
    print("Next steps:", file=stream)
    print("  1. edit data/master.yaml to fix anything obviously wrong", file=stream)
    print("  2. tailord validate", file=stream)
    print("  3. tailord build --variant master", file=stream)


def cmd_import_resume(args: argparse.Namespace) -> int:
    from tailord.events import log_runner_call
    from tailord.paths import MASTER_PATH, VAULT_ROOT
    from tailord.runners import build_runner

    framework = _framework_root()
    try:
        resume_text = _read_resume_source(args.source)
    except ImportSourceError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not resume_text.strip():
        print("no resume content (file empty or stdin closed)", file=sys.stderr)
        return 2

    if MASTER_PATH.exists() and not args.force and not args.dry_run:
        if not _is_sample_master(MASTER_PATH, framework):
            print(
                f"refusing to overwrite existing {MASTER_PATH}\n"
                "  re-run with --force to replace it, or use --dry-run to inspect output.",
                file=sys.stderr,
            )
            return 2

    skill_path = framework / "skills" / "resume-importing" / "SKILL.md"
    schema_path = framework / "schemas" / "master.schema.yaml"
    skill_text = _read_optional(skill_path)
    schema_text = _read_optional(schema_path)
    system = "\n\n".join([
        "You are the resume-importing skill.",
        skill_text,
        f"--- master.schema.yaml ---\n{schema_text}",
        (
            "Strict output contract: return exactly one master.yaml document between "
            f"{IMPORT_START_MARKER} and {IMPORT_END_MARKER}. Do not include prose, "
            "markdown fences, comments, or any text outside those markers."
        ),
    ])
    user = (
        "Extract a draft data/master.yaml from the resume text below.\n\n"
        f"---BEGIN RESUME---\n{resume_text}\n---END RESUME---"
    )

    runner = build_runner(args.runner)
    print(f"# runner: {runner.name}", file=sys.stderr)
    started = time.perf_counter()
    run_result = runner.run(system=system, user=user, max_tokens=8000)
    log_runner_call("import", run_result, int((time.perf_counter() - started) * 1000))
    response = run_result.text

    try:
        raw_yaml = _extract_marked_yaml(response)
    except ValueError as e:
        raw_path = _write_import_debug(VAULT_ROOT, response)
        print(f"[error] raw.yaml: {e}", file=sys.stderr)
        print(f"raw output saved to {raw_path}", file=sys.stderr)
        return 2

    try:
        document = _load_yaml_text(raw_yaml)
    except Exception as e:  # noqa: BLE001 - YAML libraries expose several subclasses.
        raw_path = _write_import_debug(VAULT_ROOT, raw_yaml)
        mark = getattr(e, "problem_mark", None)
        if mark is not None:
            print(
                f"[error] raw.yaml:{mark.line + 1}:{mark.column + 1}: malformed YAML: {e}",
                file=sys.stderr,
            )
        else:
            print(f"[error] raw.yaml: malformed YAML: {e}", file=sys.stderr)
        print(f"raw YAML saved to {raw_path}", file=sys.stderr)
        return 2

    errors = _schema_errors(document)
    if errors:
        raw_path = _write_import_debug(VAULT_ROOT, raw_yaml)
        for error in errors:
            print(f"[error] raw.yaml:{error}", file=sys.stderr)
        print(f"raw YAML saved to {raw_path}", file=sys.stderr)
        return 2

    output_yaml = _dump_yaml(document)
    if args.dry_run:
        sys.stdout.write(output_yaml)
        if not output_yaml.endswith("\n"):
            sys.stdout.write("\n")
        _print_import_report(document, stream=sys.stderr)
        return 0

    MASTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    MASTER_PATH.write_text(output_yaml, encoding="utf-8")
    print(f"✓ wrote {MASTER_PATH}")
    _print_import_report(document, stream=sys.stdout)
    return 0


# Loose ceiling for evidence-corpus embedding. ~120K chars ≈ 30K tokens,
# fits comfortably with cache-control on Sonnet/Opus 200K windows.
EVIDENCE_BUDGET_CHARS = 120_000


def _collect_evidence(evidence_dir: Path) -> tuple[str, list[str]]:
    """Concatenate every *.md file under `evidence_dir` until the budget
    is hit. Returns (concatenated_text, included_filenames)."""
    if not evidence_dir.exists():
        return "", []
    chunks: list[str] = []
    included: list[str] = []
    total = 0
    for path in sorted(evidence_dir.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        header = f"--- {path.relative_to(evidence_dir)} ---\n"
        size = len(header) + len(text) + 2
        if total + size > EVIDENCE_BUDGET_CHARS:
            break
        chunks.append(header + text)
        included.append(str(path.relative_to(evidence_dir)))
        total += size
    return "\n\n".join(chunks), included


def cmd_score_job(args: argparse.Namespace) -> int:
    from tailord.events import log_runner_call
    from tailord.paths import MASTER_PATH, USER_PREFERENCES_PATH, VAULT_ROOT
    from tailord.runners import build_runner

    framework = _framework_root()
    skill_path = framework / "skills" / "resume-job-fit-evaluator" / "SKILL.md"

    if args.jd == Path("-"):
        jd_text = sys.stdin.read()
    else:
        try:
            jd_text = args.jd.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(
                f"JD file not found: {args.jd}\n"
                "Create a text file with the job description, or pass `-` "
                "and pipe the JD on stdin.",
                file=sys.stderr,
            )
            return 2
        except OSError as e:
            print(f"Could not read JD file {args.jd}: {e}", file=sys.stderr)
            return 2
    if not jd_text.strip():
        print("no JD content (file empty or stdin closed)", file=sys.stderr)
        return 2

    skill_text = _read_optional(skill_path)
    master_text = _read_optional(MASTER_PATH)
    prefs_text = _read_optional(USER_PREFERENCES_PATH)

    evidence_dir_rel = "docs/resume-research"
    if prefs_text:
        import yaml as _yaml
        try:
            prefs = _yaml.safe_load(prefs_text) or {}
            evidence_dir_rel = str(prefs.get("evidence_corpus_dir") or evidence_dir_rel)
        except _yaml.YAMLError:
            pass
    evidence_dir = (VAULT_ROOT / evidence_dir_rel).resolve()
    evidence_text, included_files = _collect_evidence(evidence_dir)

    sections: list[str] = ["You are the resume-job-fit-evaluator skill.", skill_text]
    if master_text:
        sections.append(f"--- data/master.yaml ---\n{master_text}")
    if prefs_text:
        sections.append(f"--- data/user-preferences.yaml ---\n{prefs_text}")
    if evidence_text:
        sections.append(f"--- evidence corpus ({evidence_dir_rel}) ---\n{evidence_text}")

    system = "\n\n".join(s for s in sections if s)
    user = (
        "Score the following JD using the rubric above. "
        "Return only the scorecard markdown.\n\n"
        f"---BEGIN JD---\n{jd_text}\n---END JD---"
    )

    runner = build_runner(args.runner)
    print(f"# runner: {runner.name}", file=sys.stderr)
    if included_files:
        print(
            f"# evidence corpus: {len(included_files)} file(s) included from {evidence_dir_rel}",
            file=sys.stderr,
        )
    elif evidence_dir.exists():
        print(
            f"# evidence corpus: {evidence_dir_rel} present but empty / too large to embed",
            file=sys.stderr,
        )
    else:
        print(
            f"# evidence corpus: not embedded (no {evidence_dir_rel} in vault)",
            file=sys.stderr,
        )
    started = time.perf_counter()
    run_result = runner.run(system=system, user=user, max_tokens=4096)
    log_runner_call("score-job", run_result, int((time.perf_counter() - started) * 1000))
    output = run_result.text
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from tailord import stats as stats_mod

    return stats_mod.print_usage_stats(since=args.since, by=args.by, csv_output=args.csv)


def cmd_lint(args: argparse.Namespace) -> int:
    from tailord import lint_bullets as lint_mod

    forwarded: list[str] = []
    if args.include_jobs:
        forwarded.append("--include-jobs")
    return lint_mod.main(forwarded)


def cmd_sync_skills(args: argparse.Namespace) -> int:
    from tailord import sync_skills as sync_mod

    forwarded: list[str] = []
    if args.check:
        forwarded.append("--check")
    if args.framework_root:
        forwarded += ["--framework-root", str(args.framework_root)]
    return sync_mod.main(forwarded)


def cmd_tailor_job(args: argparse.Namespace) -> int:
    print(
        "`tailord tailor-job` is deferred — it needs file-writing "
        "tool use, which doesn't fit cleanly into the current one-shot "
        "runner shape. Use `tailord serve` + the browser extension "
        "for the full pipeline, or run `claude` interactively in the repo "
        "and invoke the `resume-tailoring` skill yourself.",
        file=sys.stderr,
    )
    return 64


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tailord",
        description="Local, evidence-backed job-application workbench.",
    )
    p.add_argument("--vault", help="override RESUME_VAULT / .resumerc.yaml for this command")
    sub = p.add_subparsers(dest="subcommand", required=True)

    init = sub.add_parser("init", help="scaffold a new vault from the sample")
    init.add_argument("path", help="where to create the vault (e.g. ~/resume-vault)")
    init.set_defaults(func=cmd_init)

    val = sub.add_parser("validate", help="schema + structural checks")
    val.add_argument("--variant", "-v", action="append")
    val.add_argument("--strict", action="store_true")
    val.set_defaults(func=cmd_validate)

    doc = sub.add_parser("doctor", help="show config + check tool availability")
    doc.set_defaults(func=cmd_doctor)

    browsers = sub.add_parser("install-browsers", help="install Chromium for PDF rendering")
    browsers.set_defaults(func=cmd_install_browsers)

    bld = sub.add_parser("build", help="render a resume PDF")
    bg = bld.add_mutually_exclusive_group()
    bg.add_argument("--variant", "-v", default="master")
    bg.add_argument("--all", action="store_true", help="build every static variant")
    bld.add_argument("--out-dir", type=Path)
    bld.add_argument("--out-name")
    bld.set_defaults(func=cmd_build)

    cov = sub.add_parser("cover", help="render a cover-letter PDF")
    cov.add_argument("--variant", "-v", default="master")
    cov.add_argument("--out-dir", type=Path)
    cov.add_argument("--out-name")
    cov.add_argument("--html-only", action="store_true")
    cov.set_defaults(func=cmd_cover)

    prev = sub.add_parser("preview", help="hot-reload preview server for a variant")
    prev.add_argument("--variant", "-v", default="master")
    prev.add_argument("--port", type=int, default=8000)
    prev.set_defaults(func=cmd_preview)

    setup = sub.add_parser("setup-bridge", help="scaffold tools/jd-bridge/.env + npm install for the bridge")
    setup.add_argument("--force", action="store_true", help="overwrite an existing .env")
    setup.add_argument("--skip-npm", action="store_true", help="skip `npm install` step")
    setup.set_defaults(func=cmd_setup_bridge)

    srv = sub.add_parser("serve", help="start the jd-bridge HTTP server")
    srv.set_defaults(func=cmd_serve)

    score = sub.add_parser("score-job", help="score a JD against the vault via the job-fit-evaluator skill")
    score.add_argument("jd", type=Path, help="path to a JD text file, or - for stdin")
    score.add_argument("--runner", choices=["claude_cli", "anthropic_api"], help="override config.model_runner")
    score.set_defaults(func=cmd_score_job)

    stats = sub.add_parser("stats", help="summarize local LLM token usage and cost")
    stats.add_argument("--since", default="30d", help="lookback window, e.g. 7d or 24h (default: 30d)")
    stats.add_argument("--by", choices=["kind", "model"], action="append", help="group summary by field")
    stats.add_argument("--csv", action="store_true", help="print one row per call as CSV")
    stats.set_defaults(func=cmd_stats)

    imp = sub.add_parser("import", help="extract data/master.yaml from an existing resume")
    imp.add_argument("source", type=Path, metavar="path", help="resume .txt/.md/.pdf path, or - for stdin")
    imp.add_argument("--dry-run", action="store_true", help="print YAML to stdout without writing")
    imp.add_argument("--force", action="store_true", help="overwrite existing data/master.yaml")
    imp.add_argument("--runner", choices=["claude_cli", "anthropic_api"], help="override config.model_runner")
    imp.set_defaults(func=cmd_import_resume)

    lint = sub.add_parser("lint", help="house-style lint over bullets (weak verbs, AI filler, oversize)")
    lint.add_argument("--include-jobs", action="store_true", help="also lint job-specific variants under jobs/generated/")
    lint.set_defaults(func=cmd_lint)

    sync = sub.add_parser("sync-skills", help="sync source skills to .claude/, .codex/, .opencode/ output dirs")
    sync.add_argument("--check", action="store_true", help="exit non-zero if outputs are stale (CI mode)")
    sync.add_argument("--framework-root", type=Path, help="override repo-root detection")
    sync.set_defaults(func=cmd_sync_skills)

    tailor = sub.add_parser("tailor-job", help="(deferred) run the full tailoring pipeline against a JD")
    tailor.set_defaults(func=cmd_tailor_job)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "vault", None):
        os.environ["RESUME_VAULT"] = str(Path(args.vault).expanduser().resolve())
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
