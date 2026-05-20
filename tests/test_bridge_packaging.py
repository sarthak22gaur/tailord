from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_ROOT = REPO_ROOT / "tools" / "jd-bridge"


class BridgePackagingTests(unittest.TestCase):
    def test_pyproject_lists_every_runtime_bridge_asset(self) -> None:
        with (REPO_ROOT / "pyproject.toml").open("rb") as f:
            pyproject = tomllib.load(f)

        data_files = pyproject["tool"]["setuptools"]["data-files"]
        listed = {
            Path(path)
            for target, paths in data_files.items()
            if target.startswith("share/tailord/jd-bridge")
            for path in paths
        }
        actual = {
            BRIDGE_ROOT / ".env.example",
            BRIDGE_ROOT / "package.json",
            BRIDGE_ROOT / "package-lock.json",
            *sorted((BRIDGE_ROOT / "config").rglob("*.*")),
            *sorted((BRIDGE_ROOT / "src").rglob("*.js")),
        }
        actual = {path.relative_to(REPO_ROOT) for path in actual if path.is_file()}

        self.assertEqual(listed, actual)


if __name__ == "__main__":
    unittest.main()
