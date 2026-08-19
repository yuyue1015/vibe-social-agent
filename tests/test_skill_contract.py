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

    def test_draft_edit_is_low_freedom_and_has_one_route(self) -> None:
        skill = (SKILL_DIRS["vibe-social"] / "SKILL.md").read_text(encoding="utf-8")
        openai = (SKILL_DIRS["vibe-social"] / "agents" / "openai.yaml").read_text(encoding="utf-8")
        interaction = (SKILL_DIRS["vibe-social"] / "references" / "interaction-flow.md").read_text(encoding="utf-8")
        workflow = (SKILL_DIRS["vibe-social"] / "references" / "workflow.md").read_text(encoding="utf-8")

        self.assertIn("**LOW:** DRAFT title/wording edits", skill)
        self.assertNotIn("**MEDIUM:** Story Ranking, Story Journey selection, Story Generate, draft wording changes", skill)
        self.assertIn("draft-edit exactly once", openai)
        self.assertIn("or rescan the project", openai)
        self.assertIn("draft-edit", skill)
        fast_edit_route = next(
            line for line in skill.splitlines() if line.startswith("| DRAFT Fast Edit |")
        )
        self.assertIn("**No references.**", fast_edit_route)
        self.assertIn("draft-edit` exactly once", fast_edit_route)
        self.assertIn("full_draft.title", fast_edit_route)
        self.assertIn("full_draft.body", fast_edit_route)
        self.assertIn("current_state", fast_edit_route)
        self.assertIn("next", fast_edit_route)
        self.assertNotIn("interaction-flow.md", fast_edit_route)
        self.assertNotIn("data-contracts.md", fast_edit_route)
        other_revision_route = next(
            line for line in skill.splitlines() if line.startswith("| Other Revision / Fact Check |")
        )
        self.assertIn("creating a revision after `APPROVED`", other_revision_route)
        self.assertIn("verifying a fact/changed number", other_revision_route)
        self.assertIn("non-ordinary edit", other_revision_route)
        self.assertIn("interaction-flow.md", other_revision_route)
        self.assertIn("data-contracts.md", other_revision_route)
        for forbidden in (
            "revise-pr",
            "--help",
            "scan_guard.py",
            "story_detect.py",
            "story_generate.py",
            "story_aggregate.py",
            "performance.py",
            "Story Ranking",
            "Publish Readiness",
        ):
            self.assertIn(forbidden, skill)
            self.assertIn(forbidden, interaction)

        self.assertIn("vibe_state.py \\", interaction)
        self.assertIn("draft-edit", interaction)
        self.assertIn("--replace-old", interaction)
        self.assertIn("--replace-new", interaction)
        self.assertIn("full_draft.title", interaction)
        self.assertIn("full_draft.body", interaction)
        self.assertIn("current_state", interaction)
        self.assertIn("next", interaction)
        self.assertIn("【完整标题】", interaction)
        self.assertIn("禁止只展示修改句、diff、修改摘要", interaction)
        self.assertIn("[2] 继续修改", interaction)
        self.assertIn("所有“继续修改”选项统一显示为“继续修改”", workflow)
        self.assertIn("当前 DRAFT 的 `vibe_state.py draft-edit` 唯一路径", workflow)
        self.assertNotIn("继续修改 + 输入修改内容", workflow)


if __name__ == "__main__":
    unittest.main()
