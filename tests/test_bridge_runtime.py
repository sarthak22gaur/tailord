from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tailord import bridge_runtime as br


class BridgeRuntimeTests(unittest.TestCase):
    def test_repo_root_walks_up_to_editable_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            framework = repo / "src" / "tailord"
            (repo / "tools" / "jd-bridge").mkdir(parents=True)
            (repo / "pyproject.toml").write_text("[project]\nname = 'tailord'\n", encoding="utf-8")
            framework.mkdir(parents=True)

            self.assertEqual(br.repo_root(framework), repo)

    def test_bridge_source_dir_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bridge"
            source.mkdir()
            (source / "package.json").write_text("{}", encoding="utf-8")
            with mock.patch.dict(os.environ, {"TAILORD_BRIDGE_SOURCE": str(source)}, clear=False):
                self.assertEqual(br.bridge_source_dir(Path(td) / "framework"), source.resolve())

    def test_installed_data_bridge_dir_can_use_metadata_files_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            package_json = Path(td) / "odd-layout" / "share" / "tailord" / "jd-bridge" / "package.json"
            package_json.parent.mkdir(parents=True)
            package_json.write_text("{}", encoding="utf-8")

            class FakePackagePath:
                def __str__(self) -> str:
                    return "tailord-0.1.0.data/data/share/tailord/jd-bridge/package.json"

                def locate(self) -> Path:
                    return package_json

            with (
                mock.patch.object(sys, "prefix", str(Path(td) / "empty-prefix")),
                mock.patch.object(br.metadata, "files", return_value=[FakePackagePath()]),
            ):
                self.assertEqual(br._installed_data_bridge_dir(), package_json.parent.resolve())

    def test_ensure_bridge_runtime_copies_packaged_assets_to_user_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            runtime = root / "runtime"
            (source / "src").mkdir(parents=True)
            (source / "config").mkdir()
            (source / "package.json").write_text("{}", encoding="utf-8")
            (source / "package-lock.json").write_text("{}", encoding="utf-8")
            (source / ".env.example").write_text("BRIDGE_PORT=8787\n", encoding="utf-8")
            (source / "src" / "server.js").write_text("console.log('ok');\n", encoding="utf-8")
            (source / "config" / "prompt.yaml").write_text("evaluate_template: x\n", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "TAILORD_BRIDGE_SOURCE": str(source),
                    "TAILORD_BRIDGE_DIR": str(runtime),
                },
                clear=False,
            ):
                self.assertEqual(br.ensure_bridge_runtime(root / "framework"), runtime.resolve())

            self.assertTrue((runtime / "src" / "server.js").is_file())
            self.assertTrue((runtime / "config" / "prompt.yaml").is_file())
            self.assertTrue((runtime / ".env.example").is_file())

    def test_copy_claude_skills_copies_subdirectories_and_prunes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root = root / "skills"
            skill = source_root / "resume-tailoring"
            (skill / "examples").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: resume-tailoring\n---\n", encoding="utf-8")
            (skill / "examples" / "foo.md").write_text("example\n", encoding="utf-8")

            workspace = root / "workspace"
            stale_skill = workspace / ".claude" / "skills" / "resume-tailoring"
            custom_skill = workspace / ".claude" / "skills" / "my-custom"
            stale_skill.mkdir(parents=True)
            custom_skill.mkdir()
            (stale_skill / "old.md").write_text("old\n", encoding="utf-8")
            (custom_skill / "SKILL.md").write_text("custom\n", encoding="utf-8")

            br._copy_claude_skills(source_root, workspace)

            self.assertTrue((stale_skill / "SKILL.md").is_file())
            self.assertTrue((stale_skill / "examples" / "foo.md").is_file())
            self.assertFalse((stale_skill / "old.md").exists())
            self.assertFalse(custom_skill.exists())

    def test_refresh_vault_links_replaces_wrong_symlink_but_keeps_real_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = root / "vault"
            workspace = root / "workspace"
            wrong = root / "wrong"
            (vault / "data").mkdir(parents=True)
            (vault / "docs").mkdir()
            (vault / "jobs").mkdir()
            workspace.mkdir()
            wrong.mkdir()
            (workspace / "data").symlink_to(wrong, target_is_directory=True)
            (workspace / "docs").mkdir()

            br._refresh_vault_links(workspace, vault)

            self.assertEqual((workspace / "data").resolve(), (vault / "data").resolve())
            self.assertFalse((workspace / "docs").is_symlink())
            self.assertTrue((workspace / "jobs").is_symlink())
            self.assertFalse((workspace / "output").exists())


if __name__ == "__main__":
    unittest.main()
