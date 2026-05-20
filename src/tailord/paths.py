"""Vault & framework path discovery.

Callers must not read $RESUME_VAULT directly — go through this module so the
discovery rules in `tailord.config` stay the single source of truth across
CLI, bridge, and tests.
"""
from __future__ import annotations

from tailord.config import FRAMEWORK_ROOT, Config

VAULT_ROOT = Config.load().vault

TEMPLATES_DIR = FRAMEWORK_ROOT / "templates"
SCHEMAS_DIR = FRAMEWORK_ROOT / "schemas"

DATA_DIR = VAULT_ROOT / "data"
VARIANTS_DIR = DATA_DIR / "variants"
COVER_VARIANTS_DIR = DATA_DIR / "cover-letter-variants"
RESEARCH_DIR = VAULT_ROOT / "docs" / "resume-research"
JOBS_GENERATED_DIR = VAULT_ROOT / "jobs" / "generated"
OUTPUT_DIR = VAULT_ROOT / "output"

MASTER_PATH = DATA_DIR / "master.yaml"
USER_PREFERENCES_PATH = DATA_DIR / "user-preferences.yaml"
