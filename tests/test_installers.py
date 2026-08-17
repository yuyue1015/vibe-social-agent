"""Regression tests for clean Skill installation and updates."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"
INSTALL_SH = ROOT / "scripts" / "install.sh"
UNINSTALL_PS1 = ROOT / "scripts" / "uninstall.ps1"
UNINSTALL_SH = ROOT / "scripts" / "uninstall.sh"


class InstallerCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows installer acceptance runs on Windows")
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name) / "target-project"
        self.target.mkdir()
        self.cache_dir = SKILLS_ROOT / "vibe-social" / "scripts" / "__pycache__"

    def tearDown(self) -> None:
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
        self.temp.cleanup()

    def add_fake_cache(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "fake.cpython-311.pyc").write_bytes(b"not executable cache")

    def assert_target_has_skills_without_cache(self) -> None:
        for skill in ("vibe-social", "weibo-publish"):
            skill_dir = self.target / ".agents" / "skills" / skill
            self.assertTrue((skill_dir / "SKILL.md").is_file())
            self.assertTrue((skill_dir / "agents" / "openai.yaml").is_file())
        installed_files = self.target / ".agents" / "skills"
        self.assertFalse(any(path.name == "__pycache__" for path in installed_files.rglob("*")))
        self.assertFalse(any(path.suffix.lower() in {".pyc", ".pyo"} for path in installed_files.rglob("*")))

    def run_powershell_installer(self, *extra: str) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is unavailable")
        result = subprocess.run(
            [shell, "-NoProfile", "-File", str(INSTALL_PS1), "-TargetRoot", str(self.target), "-Apply", *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def run_bash_installer(self, *extra: str) -> None:
        shell = shutil.which("bash") or shutil.which("bash.exe")
        if not shell:
            for candidate in (Path(r"C:\Program Files\Git\bin\bash.exe"), Path(r"C:\Program Files\Git\usr\bin\bash.exe")):
                if candidate.is_file():
                    shell = str(candidate)
                    break
        if not shell:
            self.skipTest("Bash is unavailable")
        command = " ".join(
            [
                "bash scripts/install.sh",
                "--target",
                shlex.quote(self.target.as_posix()),
                "--apply",
                *(shlex.quote(value) for value in extra),
            ]
        )
        result = subprocess.run(
            [shell, "-lc", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_powershell_install_and_update_exclude_python_cache(self) -> None:
        self.add_fake_cache()
        self.run_powershell_installer()
        self.assert_target_has_skills_without_cache()

        self.add_fake_cache()
        self.run_powershell_installer("-Update")
        self.assert_target_has_skills_without_cache()

    def test_bash_install_and_update_exclude_python_cache(self) -> None:
        self.add_fake_cache()
        self.run_bash_installer()
        self.assert_target_has_skills_without_cache()

        self.add_fake_cache()
        self.run_bash_installer("--update")
        self.assert_target_has_skills_without_cache()


class UninstallerOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows uninstall acceptance runs on Windows")
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name) / "target-project"
        for relative in (
            ".agents/skills/vibe-social/SKILL.md",
            ".agents/skills/weibo-publish/SKILL.md",
            ".agents/skills/other-test-skill/KEEP_ME.txt",
            ".vibesocial/writing-style.md",
        ):
            path = self.target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("UNINSTALL_OUTPUT_TEST\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assert_dry_run_output(self, output: str) -> None:
        for text in (
            ".agents/skills/vibe-social/",
            ".agents/skills/weibo-publish/",
            ".vibesocial/",
            "将保留：",
            "不会删除：",
            "DRY RUN",
        ):
            self.assertIn(text, output)

    def assert_apply_output(self, output: str) -> None:
        self.assertNotIn("DRY RUN", output)
        self.assertIn("已删除：", output)
        self.assertIn(".agents/skills/vibe-social/", output)
        self.assertIn(".agents/skills/weibo-publish/", output)
        self.assertIn("已保留：", output)
        self.assertIn(".vibesocial/", output)

    def assert_apply_scope(self) -> None:
        skills = self.target / ".agents" / "skills"
        self.assertFalse((skills / "vibe-social").exists())
        self.assertFalse((skills / "weibo-publish").exists())
        self.assertEqual("UNINSTALL_OUTPUT_TEST\n", (skills / "other-test-skill" / "KEEP_ME.txt").read_text(encoding="utf-8"))
        self.assertEqual("UNINSTALL_OUTPUT_TEST\n", (self.target / ".vibesocial" / "writing-style.md").read_text(encoding="utf-8"))

    def run_powershell_uninstaller(self, *extra: str, mode: str = "1", input_text: str | None = None) -> str:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is unavailable")
        result = subprocess.run(
            [shell, "-NoProfile", "-File", str(UNINSTALL_PS1), "-TargetRoot", str(self.target), "-Mode", mode, *extra],
            cwd=ROOT,
            capture_output=True,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def run_bash_uninstaller(self, *extra: str, mode: str = "1", input_text: str | None = None) -> str:
        shell = shutil.which("bash") or shutil.which("bash.exe")
        if not shell:
            for candidate in (Path(r"C:\Program Files\Git\bin\bash.exe"), Path(r"C:\Program Files\Git\usr\bin\bash.exe")):
                if candidate.is_file():
                    shell = str(candidate)
                    break
        if not shell:
            self.skipTest("Bash is unavailable")
        command = " ".join(
            [
                "bash scripts/uninstall.sh",
                "--target",
                shlex.quote(self.target.as_posix()),
                "--mode",
                mode,
                *(shlex.quote(value) for value in extra),
            ]
        )
        if input_text is not None:
            command = f"printf %s {shlex.quote(input_text)} | {command}"
        result = subprocess.run(
            [shell, "-lc", command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_powershell_mode1_dry_run_and_apply_output(self) -> None:
        dry_run = self.run_powershell_uninstaller()
        self.assert_dry_run_output(dry_run)
        self.assertTrue((self.target / ".agents/skills/vibe-social").exists())

        applied = self.run_powershell_uninstaller("-Apply")
        self.assert_apply_output(applied)
        self.assert_apply_scope()

    def assert_mode2_warning(self, output: str) -> None:
        for text in (
            "这是完整删除模式",
            ".vibesocial/",
            "永久删除",
            "草稿",
            "Writing Memory",
            "发布记录",
            "DRY RUN",
        ):
            self.assertIn(text, output)

    def assert_mode2_unchanged(self) -> None:
        self.assertTrue((self.target / ".agents/skills/vibe-social").exists())
        self.assertTrue((self.target / ".agents/skills/weibo-publish").exists())
        self.assertEqual(
            "UNINSTALL_OUTPUT_TEST\n",
            (self.target / ".vibesocial/writing-style.md").read_text(encoding="utf-8"),
        )
        self.assertTrue((self.target / ".agents/skills/other-test-skill/KEEP_ME.txt").is_file())

    def test_powershell_mode2_warning_and_cancel_preserve_files(self) -> None:
        dry_run = self.run_powershell_uninstaller(mode="2", input_text="DELETE\n")
        self.assert_mode2_warning(dry_run)
        self.assert_mode2_unchanged()

        self.run_powershell_uninstaller("-Apply", mode="2", input_text="\n")
        self.assert_mode2_unchanged()

    def test_bash_mode2_warning_and_cancel_preserve_files(self) -> None:
        dry_run = self.run_bash_uninstaller(mode="2", input_text="DELETE\n")
        self.assert_mode2_warning(dry_run)
        self.assert_mode2_unchanged()

        self.run_bash_uninstaller("--apply", mode="2", input_text="\n")
        self.assert_mode2_unchanged()

    def test_bash_mode1_dry_run_and_apply_output(self) -> None:
        dry_run = self.run_bash_uninstaller()
        self.assert_dry_run_output(dry_run)
        self.assertTrue((self.target / ".agents/skills/vibe-social").exists())

        applied = self.run_bash_uninstaller("--apply")
        self.assert_apply_output(applied)
        self.assert_apply_scope()


if __name__ == "__main__":
    unittest.main()
