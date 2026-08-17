"""Read-only contract checks for the installable Skill packages.

These fixtures describe intended trigger boundaries. They do not claim to
measure host-level trigger precision, which is controlled by the host.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
SKILL_DIRS = {
    "vibe-social": SKILLS_ROOT / "vibe-social",
    "weibo-publish": SKILLS_ROOT / "weibo-publish",
}
FORBIDDEN_PACKAGE_FILES = {
    "README",
    "INSTALL",
    "INSTALLATION_GUIDE",
    "CHANGELOG",
    "QUICK_REFERENCE",
}
TRIGGER_FIXTURES = {
    "vibe-social": {
        "should_trigger": ["更新最近开发进度", "生成 VibeSocial 草稿"],
        "should_not_trigger": ["修改 CSS 风格", "总结代码", "讨论产品方向"],
    },
    "weibo-publish": {
        "should_trigger": ["发微博", "发布 APPROVED 微博草稿"],
        "should_not_trigger": ["npm publish", "GitHub release", "部署网站"],
    },
}


def read_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != "---":
        raise AssertionError(f"missing frontmatter: {path}")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError(f"unterminated frontmatter: {path}") from exc
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator:
            metadata[key.strip()] = value.strip().strip('"')
    return metadata, text


class SkillContractTests(unittest.TestCase):
    def test_frontmatter_name_and_description(self) -> None:
        for name, skill_dir in SKILL_DIRS.items():
            metadata, _ = read_frontmatter(skill_dir / "SKILL.md")
            self.assertEqual(name, metadata.get("name"))
            description = metadata.get("description", "")
            self.assertGreater(len(description), 80)
            display_name = "vibesocial" if name == "vibe-social" else "weibo"
            self.assertIn(display_name, description.lower())
            self.assertRegex(description.lower(), r"use only|only when|use when")

    def test_agents_openai_yaml_exists_and_mentions_skill(self) -> None:
        for name, skill_dir in SKILL_DIRS.items():
            path = skill_dir / "agents" / "openai.yaml"
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"${name}", text)
            self.assertIn("default_prompt:", text)

    def test_all_markdown_links_resolve(self) -> None:
        markdown_link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for skill_dir in SKILL_DIRS.values():
            for markdown in skill_dir.rglob("*.md"):
                for target in markdown_link.findall(markdown.read_text(encoding="utf-8")):
                    if target.startswith(("http://", "https://", "#")):
                        continue
                    local_target = target.split("#", 1)[0]
                    self.assertTrue(
                        (markdown.parent / local_target).resolve().is_file(),
                        f"dangling reference in {markdown}: {target}",
                    )

    def test_required_progressive_disclosure_references_exist(self) -> None:
        expected = {
            "getting-started.md",
            "scan-boundary.md",
            "writing-memory.md",
            "performance-learning.md",
        }
        actual = {path.name for path in (SKILL_DIRS["vibe-social"] / "references").glob("*.md")}
        self.assertTrue(expected <= actual)
        main = (SKILL_DIRS["vibe-social"] / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("story-aggregation.md", main)

    def test_skill_packages_do_not_contain_repository_style_docs(self) -> None:
        for skill_dir in SKILL_DIRS.values():
            for path in skill_dir.rglob("*"):
                if path.is_file() and path.stem.upper() in FORBIDDEN_PACKAGE_FILES:
                    self.fail(f"repository-style document inside Skill package: {path}")

    def test_skill_context_budget(self) -> None:
        for skill_dir in SKILL_DIRS.values():
            path = skill_dir / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            self.assertLessEqual(len(text), 12_000, path)
            self.assertLessEqual(len(text.splitlines()), 180, path)

    def test_trigger_fixtures_are_fixed_without_fake_precision(self) -> None:
        for name, fixture in TRIGGER_FIXTURES.items():
            self.assertTrue(fixture["should_trigger"])
            self.assertTrue(fixture["should_not_trigger"])
            self.assertFalse(set(fixture["should_trigger"]) & set(fixture["should_not_trigger"]))

    def test_trigger_boundaries_are_explicit(self) -> None:
        vibe_description, _ = read_frontmatter(SKILL_DIRS["vibe-social"] / "SKILL.md")
        weibo_description, _ = read_frontmatter(SKILL_DIRS["weibo-publish"] / "SKILL.md")
        vibe_text = vibe_description["description"].lower()
        weibo_text = weibo_description["description"].lower()
        for phrase in ("ordinary code summaries", "deployment", "npm/github release"):
            self.assertIn(phrase, vibe_text)
        for phrase in ("发布到微博", "generic publish", "github release", "website deployment"):
            self.assertIn(phrase, weibo_text)
        self.assertNotIn("普通代码总结", vibe_text)


if __name__ == "__main__":
    unittest.main()
