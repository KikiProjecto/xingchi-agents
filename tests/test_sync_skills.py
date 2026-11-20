import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_skills", ROOT / "scripts/sync-skills.py")
sync_skills = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_skills
SPEC.loader.exec_module(sync_skills)


def make_skill(path: Path, name: str, body: str = "content") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}\n", encoding="utf-8")


class SyncSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def run_sync(self, *sources):
        output = self.root / "project" / "skills"
        project = output.parent
        project.mkdir(parents=True)
        args = ["--project-root", str(project)]
        for source in sources:
            args.extend(["--source", str(source)])
        self.assertEqual(sync_skills.main(args), 0)
        return output

    def test_deduplicates_identical_and_renames_divergent_variants(self):
        first = self.root / "first"
        second = self.root / "second"
        make_skill(first / "same", "same", "one")
        make_skill(second / "same-copy", "same", "one")
        make_skill(second / "different", "same", "two")

        output = self.run_sync(first, second)
        self.assertTrue((output / "same" / "SKILL.md").is_file())
        variants = list(output.glob("same--variant-*/SKILL.md"))
        self.assertEqual(len(variants), 1)
        inventory = (output / "LIST.md").read_text(encoding="utf-8")
        self.assertIn("Identical duplicates omitted: 1", inventory)
        self.assertIn("Divergent variants renamed: 1", inventory)

    def test_excludes_runtime_files_and_redacts_home_paths(self):
        source = self.root / "source"
        make_skill(source / "safe", "safe", f"path={Path.home()}")
        (source / "safe" / "node_modules").mkdir()
        (source / "safe" / "node_modules" / "ignored.js").write_text("x", encoding="utf-8")
        (source / "safe" / ".env").write_text("TOKEN=secret", encoding="utf-8")
        (source / "safe" / "notes.md").write_text(f"home={Path.home()}\n", encoding="utf-8")

        output = self.run_sync(source)
        text = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*.md"))
        self.assertIn("<HOME>", text)
        self.assertNotIn(str(Path.home()), text)
        self.assertFalse((output / "safe" / "node_modules").exists())
        self.assertFalse((output / "safe" / ".env").exists())

    def test_does_not_copy_symlinks_or_follow_external_skill_tree(self):
        source = self.root / "source"
        external = self.root / "external"
        make_skill(source / "local", "local")
        make_skill(external / "external", "external")
        (source / "linked").symlink_to(external, target_is_directory=True)

        output = self.run_sync(source)
        self.assertTrue((output / "local" / "SKILL.md").is_file())
        self.assertFalse((output / "external").exists())
        self.assertFalse(any(path.is_symlink() for path in output.rglob("*")))

    def test_refuses_nonempty_output(self):
        source = self.root / "source"
        project = self.root / "project"
        output = project / "skills"
        make_skill(source / "skill", "skill")
        output.mkdir(parents=True)
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        self.assertEqual(sync_skills.main(["--project-root", str(project), "--source", str(source)]), 2)
        self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
