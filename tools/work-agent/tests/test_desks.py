#!/usr/bin/env python3
"""Tests for the Pixel Agents office pieces: desks.py, pixel/make_layout.py, pixel_office.sh. No model, no network."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pixel"))
import desks  # noqa: E402
import make_layout  # noqa: E402


def wr(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def jr(path):
    with open(path) as f:
        return json.load(f)


class TidyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.proj = os.path.join(self.tmp, "projects")
        os.environ["CLAUDE_PROJECTS_DIR"] = self.proj

    def tearDown(self):
        os.environ.pop("CLAUDE_PROJECTS_DIR", None)
        shutil.rmtree(self.tmp)

    def test_keeps_only_the_current_transcript_of_a_desk(self):
        d = os.path.join(self.proj, "-Users-me-beomstar-tools-work-agent-state-office-desks-gate")
        for sid in ("aaaa", "bbbb", "cccc"):
            wr(os.path.join(d, sid + ".jsonl"), "{}")
        wr(os.path.join(d, "notes.txt"), "keep")
        self.assertEqual(desks.tidy_transcripts("cccc"), 2)
        self.assertEqual(sorted(os.listdir(d)), ["cccc.jsonl", "notes.txt"])

    def test_never_touches_non_desk_projects(self):
        d = os.path.join(self.proj, "-Users-me-beomstar-git")
        wr(os.path.join(d, "aaaa.jsonl"), "{}")
        wr(os.path.join(d, "bbbb.jsonl"), "{}")
        self.assertEqual(desks.tidy_transcripts("bbbb"), 0)
        self.assertEqual(len(os.listdir(d)), 2)

    def test_bad_ids_are_ignored(self):
        self.assertEqual(desks.tidy_transcripts(""), 0)
        self.assertEqual(desks.tidy_transcripts("../x"), 0)
        self.assertEqual(desks.tidy_transcripts("a/b"), 0)

    def test_desk_dir_is_created_and_unknown_names_fall_back_to_runner(self):
        self.assertTrue(desks.desk_dir(self.tmp, "gate").endswith("/office/desks/gate"))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "office", "desks", "gate")))
        self.assertTrue(desks.desk_dir(self.tmp, "weird-name").endswith("/office/desks/runner"))


class LayoutTests(unittest.TestCase):
    def test_generated_layout_matches_the_checked_in_file(self):
        with open(os.path.join(ROOT, "pixel", "base-layout.json")) as f:
            base = json.load(f)
        built = make_layout.build(base)
        with open(os.path.join(ROOT, "pixel", "layout-office.json")) as f:
            shipped = json.load(f)
        self.assertEqual(built, shipped, "run python3 pixel/make_layout.py after changing AREAS")

    def test_areas_cover_their_seats_and_only_floor(self):
        with open(os.path.join(ROOT, "pixel", "layout-office.json")) as f:
            lay = json.load(f)
        cols = lay["cols"]
        labels = [a["label"] for a in lay["areas"]]
        self.assertEqual(labels, ["요청비서", "게이트담당", "공지문서", "원가담당", "사무보조"])
        self.assertTrue(all(a["color"].startswith("#") and len(a["color"]) == 7 for a in lay["areas"]))
        self.assertEqual(len(lay["areaTiles"]), len(lay["tiles"]))
        for label, _, (c, r), _ in make_layout.AREAS:
            self.assertEqual(lay["areaTiles"][r * cols + c], label)
        for i, a in enumerate(lay["areaTiles"]):
            if a is not None:
                self.assertNotIn(lay["tiles"][i], (0, 255))
        with open(os.path.join(ROOT, "pixel", "config-office.json")) as f:
            mapping = json.load(f)["standalone"]["areaMappings"]
        self.assertEqual(set(sum(mapping.values(), [])), set(labels), "every area has a desk mapped to it")
        self.assertEqual(set(mapping), set(desks.DESKS))
        self.assertTrue(all("-" not in k for k in mapping), "Pixel labels are the last '-' token of the folder name")


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "pa")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_sh(self, *args):
        env = dict(os.environ, PIXEL_AGENTS_HOME=self.home)
        return subprocess.run(["bash", os.path.join(ROOT, "pixel_office.sh")] + list(args), capture_output=True, text=True, env=env)

    def test_install_merges_settings_and_keeps_existing_layout(self):
        os.makedirs(self.home)
        wr(os.path.join(self.home, "config.json"), json.dumps({"standalone": {"soundEnabled": False, "areaMappings": {"mine": ["내 구역"]}},
                                                                "externalAssetDirectories": ["/x"]}))
        wr(os.path.join(self.home, "layout.json"), json.dumps({"version": 1, "cols": 1, "rows": 1, "tiles": [1], "furniture": []}))
        p = self.run_sh("install")
        self.assertEqual(p.returncode, 0, p.stderr)
        cfg = jr(os.path.join(self.home, "config.json"))
        std = cfg["standalone"]
        self.assertEqual((std["watchAllSessions"], std["alwaysShowLabels"], std["showAreas"], std["ghostHeadlessAgents"]), (True, True, True, False))
        self.assertEqual(std["soundEnabled"], False, "unrelated settings survive")
        self.assertEqual(std["areaMappings"]["mine"], ["내 구역"], "existing mappings survive")
        self.assertEqual(std["areaMappings"]["gate"], ["게이트담당"])
        self.assertEqual(cfg["externalAssetDirectories"], ["/x"])
        self.assertTrue(any(n.startswith("config.json.bak-") for n in os.listdir(self.home)))
        self.assertEqual(jr(os.path.join(self.home, "layout.json"))["cols"], 1, "layout untouched without --force")
        self.assertIn("layout kept", p.stdout)
        p = self.run_sh("install", "--force")
        self.assertEqual(jr(os.path.join(self.home, "layout.json"))["cols"], 21)
        self.assertTrue(any(n.startswith("layout.json.bak-") for n in os.listdir(self.home)))

    def test_install_from_scratch_and_status(self):
        p = self.run_sh("install")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.home, "layout.json")))
        p = self.run_sh("status")
        self.assertIn("watchAllSessions     True", p.stdout)
        self.assertIn("게이트담당", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
