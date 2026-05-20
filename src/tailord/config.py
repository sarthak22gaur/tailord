"""User-config discovery for tailord.

Resolution order (first hit wins) — env values override file-based ones so
short-lived sessions can point at a different vault without editing a file:

  1. Explicit kwargs (e.g. `Config.load(vault="...")`).
  2. RESUME_VAULT env var.
  3. `.resumerc.yaml` in CWD or any ancestor (git-style discovery).
  4. `$XDG_CONFIG_HOME/tailord/config.yaml`
     (or `~/.config/tailord/config.yaml` if XDG is unset).
  5. Defaults: vault = framework root (back-compat).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Inline here (not imported from tailord.paths) so paths.py can import this
# module without a cycle. Resolves to <repo>/src/tailord/ in editable installs
# and <site-packages>/tailord/ in wheel installs — templates, schemas, skills,
# and the sample vault all live below it as package_data.
FRAMEWORK_ROOT = Path(__file__).resolve().parent

CONFIG_FILENAME = ".resumerc.yaml"
USER_CONFIG_RELATIVE = Path("tailord") / "config.yaml"


@dataclass
class BridgeConfig:
    port: int = 8787


@dataclass
class Config:
    vault: Path
    model_runner: str = "claude_cli"
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    source: str = "defaults"  # for diagnostics: "env", path string, or "defaults"

    @classmethod
    def load(cls, *, vault: str | Path | None = None) -> "Config":
        if vault is not None:
            return cls(vault=Path(vault).expanduser().resolve(), source="explicit")

        env_vault = os.environ.get("RESUME_VAULT")
        if env_vault:
            return cls(vault=Path(env_vault).expanduser().resolve(), source="env:RESUME_VAULT")

        loaded = _discover_file()
        if loaded is not None:
            path, data = loaded
            return _from_dict(data, source=str(path))

        return cls(vault=FRAMEWORK_ROOT, source="defaults")


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config"


def _ancestors(start: Path) -> list[Path]:
    seen: list[Path] = [start]
    cur = start
    while cur.parent != cur:
        cur = cur.parent
        seen.append(cur)
    return seen


def _discover_file() -> tuple[Path, dict[str, Any]] | None:
    for parent in _ancestors(Path.cwd().resolve()):
        candidate = parent / CONFIG_FILENAME
        if candidate.is_file():
            return candidate, _read(candidate)
    user_cfg = _xdg_config_home() / USER_CONFIG_RELATIVE
    if user_cfg.is_file():
        return user_cfg, _read(user_cfg)
    return None


def _read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _from_dict(data: dict[str, Any], *, source: str) -> Config:
    vault_raw = data.get("vault")
    vault = Path(vault_raw).expanduser().resolve() if vault_raw else FRAMEWORK_ROOT
    bridge_data = data.get("bridge") or {}
    bridge = BridgeConfig(port=int(bridge_data.get("port", 8787)))
    return Config(
        vault=vault,
        model_runner=str(data.get("model_runner") or "claude_cli"),
        bridge=bridge,
        source=source,
    )
