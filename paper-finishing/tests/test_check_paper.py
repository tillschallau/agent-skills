"""Regression tests for scripts/check_paper.py (the automated part of the checks).

Run from the repository root:
    python -m unittest discover -s paper-finishing/tests -v

Each fixture under fixtures/ is a small LaTeX paper:
    clean     - a well-formed paper; must produce no findings (guards against false positives)
    flawed    - one or more violations for most script checks
    cleveref  - cleveref usage, sentence starts in captions and lists, a build log
    unicode   - pasted Unicode in the .tex and the .bib
    library   - the full bib library is used instead of the shortened one
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
SCRIPT = HERE.parent / "scripts" / "check_paper.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_paper as cp  # noqa: E402


class FixtureCase(unittest.TestCase):
    fixture = ""
    variant = None

    @classmethod
    def setUpClass(cls):
        cls.report = cp.run(FIXTURES / cls.fixture / "main.tex", variant=cls.variant)
        cls.found = cls.report.compare(None).open

    def matches(self, check, parts, where):
        return [f for f in self.found if f.check == check
                and all(p in f.msg for p in parts) and (where is None or f.where == where)]

    def assertFinding(self, check, *parts, where=None):
        if not self.matches(check, parts, where):
            got = "\n".join(f.line() for f in self.found if f.check == check) or "(none)"
            self.fail(f"expected {check} finding containing {parts} at {where}; {check} has:\n{got}")

    def assertNoFinding(self, check, *parts, where=None):
        hits = self.matches(check, parts, where)
        if hits:
            self.fail(f"unexpected {check} finding:\n" + "\n".join(f.line() for f in hits))


class CleanPaper(FixtureCase):
    fixture = "clean"
    variant = "us"

    def test_no_findings(self):
        self.assertEqual([], [f.line() for f in self.found])

    def test_structure_is_listed(self):
        outline = "\n".join(self.report.infos["C2"])
        for title in ("Introduction", "Related Work", "Method", "Evaluation", "Conclusion"):
            self.assertIn(title, outline)


class FlawedPaper(FixtureCase):
    fixture = "flawed"
    variant = "us"

    def test_L2_undefined_label(self):
        self.assertFinding("L2", "undefined label 'eq:x'", where="method.tex:14")

    def test_L3_float_order(self):
        self.assertFinding("L3", "fig:unused")

    def test_L4_leftovers(self):
        self.assertFinding("L4", "note/markup command", "\\till")
        self.assertFinding("L4", "marker", "TODO")
        self.assertFinding("L4", "\\documentclass options", "draft")
        self.assertFinding("L4", "todonotes")
        self.assertFinding("L4", "commented-out text block")

    def test_L5_placeholders(self):
        self.assertFinding("L5", "\\cite{}")

    def test_L6_tilde(self):
        self.assertFinding("L6", "'systems \\cite' -> 'systems~\\cite'", where="main.tex:16")
        self.assertFinding("L6", "'Section \\ref' -> 'Section~\\ref'", where="main.tex:20")

    def test_L7_citation_mechanics(self):
        self.assertFinding("L7", "consecutive citations", where="main.tex:17")
        self.assertFinding("L7", "citation after '.'", where="main.tex:24")

    def test_L8_quotes_and_ranges(self):
        self.assertFinding("L8", "straight double quotes")
        self.assertFinding("L8", "range with hyphen '3-5'")

    def test_L9_urls(self):
        self.assertFinding("L9", "bare URL", "example.org")
        self.assertFinding("L9", "footnote URL without access date")

    def test_S1_springer_names(self):
        self.assertFinding("S1", "'Figure' -> 'Fig.' (inside a sentence)", where="main.tex:18")
        self.assertFinding("S1", "'Fig.' -> 'Figure' (sentence start)", where="main.tex:19")
        self.assertFinding("S1", "'Section' -> 'Sect.' (inside a sentence)", where="main.tex:20")
        self.assertFinding("S1", "'Tab.' -> 'Table' (sentence start)", where="main.tex:27")
        self.assertFinding("S1", "'Figures' -> 'Figs.' (inside a sentence)", where="method.tex:14")

    def test_B1_keys_and_stale_subset(self):
        self.assertFinding("B1", "'missingkey' not found")
        self.assertFinding("B1", "shortened .bib is stale", "unusedentry")

    def test_B2_duplicates(self):
        self.assertFinding("B2", "doe2021, smith2020")

    def test_B4_preprint(self):
        self.assertFinding("B4", "preprint 'doe2021'")

    def test_B5_title_braces(self):
        self.assertFinding("B5", "'smith2020'", "LiDAR")
        self.assertFinding("B5", "'doe2021'", "CNNs")

    def test_G2_variant(self):
        for word in ("behaviour", "modelled", "colour", "optimised"):
            self.assertFinding("G2", f"'{word}' is British")
        self.assertNoFinding("G2", "'analyses'")
        self.assertNoFinding("G2", "'Unsupervised'")

    def test_G3_hyphenation(self):
        self.assertFinding("G3", "'real-world'", "'real world'")

    def test_G4_eg_comma(self):
        self.assertFinding("G4", "'e.g.' without comma")

    def test_G5_units(self):
        self.assertFinding("G5", "'10ms'")

    def test_G6_contractions(self):
        self.assertFinding("G6", "contraction 'It's'")

    def test_C1_empty_section(self):
        self.assertFinding("C1", "\\section{Evaluation} is empty")

    def test_C2_roadmap(self):
        self.assertFinding("C2", "out of document order")
        self.assertFinding("C2", "not referenced in it", "Evaluation", "Conclusion")

    def test_C3_name_variants(self):
        self.assertFinding("C3", "OpenAI", "Openai")

    def test_C4_abbreviations(self):
        self.assertFinding("C4", "'AD' is defined only in the abstract")
        self.assertFinding("C4", "'SBT' defined 2 times")
        self.assertFinding("C4", "long form 'Scenario-based Testing'")

    def test_C5_duplicate_footnotes(self):
        self.assertFinding("C5", "duplicate footnote")

    def test_C6_citation_as_noun(self):
        self.assertFinding("C6", "citation used as a noun")

    def test_F1_missing_graphics(self):
        self.assertFinding("F1", "graphics file not found: arch")


class CleverefPaper(FixtureCase):
    fixture = "cleveref"
    variant = "us"

    def test_L1_log(self):
        self.assertFinding("L1", "undefined reference 'fig:b'")
        self.assertFinding("L1", "overfull box 12.5pt")
        self.assertTrue(any("3 pages" in i for i in self.report.infos["T2"]))

    def test_S1_cleveref(self):
        self.assertFinding("S1", "\\Cref inside a sentence", where="main.tex:6")
        self.assertFinding("S1", "\\cref at sentence start", where="main.tex:7")
        self.assertFinding("S1", "\\crefname{section}{Sect.}{Sects.}")
        self.assertNoFinding("S1", "\\crefname{figure}")

    def test_S1_sentence_starts(self):
        self.assertFinding("S1", "'Fig.' -> 'Figure' (sentence start)", where="main.tex:10")
        self.assertFinding("S1", "'Sect.' -> 'Section' (sentence start)", where="main.tex:11")
        self.assertNoFinding("S1", where="main.tex:8")  # "Figure" opening a caption is right

    def test_L6_not_after_heading(self):
        self.assertNoFinding("L6", "\\section{Intro}")


class UnicodePaper(FixtureCase):
    fixture = "unicode"

    def test_L10_replacements(self):
        for name, repl in [("EM DASH", "---"), ("EN DASH", "--"), ("NO-BREAK SPACE", "~"),
                           ("ZERO WIDTH SPACE", "(delete)"), ("LIGATURE FFI", "ffi"),
                           ("U WITH DIAERESIS", '{\\"u}'), ("C WITH CEDILLA", "\\c{c}"),
                           ("SHARP S", "{\\ss}"), ("MULTIPLICATION SIGN", "$\\times$"),
                           ("LEFT DOUBLE QUOTATION MARK", "``")]:
            self.assertFinding("L10", name, f"-> {repl}")

    def test_L10_emoji(self):
        self.assertFinding("L10", "emoji/pictograph ROCKET")
        self.assertFinding("L10", "emoji/pictograph WHITE HEAVY CHECK MARK")

    def test_L10_bib(self):
        self.assertFinding("L10", "O WITH DIAERESIS", where="r.bib:1")

    def test_L10_ignores_comments(self):
        self.assertNoFinding("L10", where="main.tex:7")


class LibraryPaper(FixtureCase):
    fixture = "library"

    def test_B1_full_library_is_blocking(self):
        self.assertFinding("B1", "BLOCKING", "full library", where="library.bib")

    def test_B1_points_to_shortened_bib(self):
        self.assertFinding("B1", "is not used", where="paper.bib")


class FingerprintTest(unittest.TestCase):
    def test_ignores_line_numbers_and_counts(self):
        a = cp.fingerprint("C1", "main.tex:10", "\\section{X} has only 12 words")
        b = cp.fingerprint("C1", "main.tex:42", "\\section{X} has only 30 words")
        self.assertEqual(a, b)

    def test_depends_on_check_file_and_text(self):
        base = cp.fingerprint("L6", "main.tex:1", "'in \\cite' -> 'in~\\cite': found in \\cite{a}")
        self.assertNotEqual(base, cp.fingerprint("L7", "main.tex:1", "'in \\cite' -> 'in~\\cite': found in \\cite{a}"))
        self.assertNotEqual(base, cp.fingerprint("L6", "other.tex:1", "'in \\cite' -> 'in~\\cite': found in \\cite{a}"))
        self.assertNotEqual(base, cp.fingerprint("L6", "main.tex:1", "'in \\cite' -> 'in~\\cite': seen in \\cite{a}"))

    def test_identical_findings_get_distinct_ids(self):
        rep = cp.Report()
        rep.add("G6", "main.tex:1", "contraction 'it's'")
        rep.add("G6", "main.tex:9", "contraction 'it's'")
        ids = [f.id for f in rep.items["G6"]]
        self.assertEqual(2, len(set(ids)))


class RerunTest(unittest.TestCase):
    """Runs the CLI twice on a copy of the flawed paper with finishing/ state in between."""

    def cli(self, *args):
        out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
        return json.loads(out)

    def test_new_resolved_dismissed(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper = Path(tmp) / "paper"
            shutil.copytree(FIXTURES / "flawed", paper)
            main, state = paper / "main.tex", paper / "finishing"

            first = self.cli(str(main), "--state", str(state), "--save", "--json")
            self.assertTrue((state / "state.json").is_file())
            by_msg = {f["msg"]: f["id"] for f in first["findings"]}
            fixed = next(i for m, i in by_msg.items() if m.startswith("'approach \\cite'"))
            dismissed = next(i for m, i in by_msg.items() if m.startswith("'Section \\ref'"))

            text = main.read_text(encoding="utf-8")
            text = text.replace("\\documentclass", "% shifts every line\n\\documentclass", 1)
            text = text.replace("approach \\cite", "approach~\\cite")
            text = text.replace("We conclude.", "We conclude. It's done.")
            main.write_text(text, encoding="utf-8")
            (state / "dismissed.md").write_text(
                f"# Dismissed findings\n\n- {dismissed} · L6 · main.tex · test · reason: intentional\n",
                encoding="utf-8")

            second = self.cli(str(main), "--state", str(state), "--json")
            ids = {f["id"] for f in second["findings"]}
            new = [f for f in second["findings"] if f["new"]]

            self.assertEqual(1, len(new), new)
            self.assertIn("It's done", new[0]["msg"])
            self.assertIn(fixed, second["resolved"])
            self.assertEqual(1, second["dismissed"])
            self.assertNotIn(dismissed, ids)
            unchanged = set(by_msg.values()) - {fixed, dismissed}
            self.assertEqual(set(), unchanged - ids, "IDs changed although the finding did not")


if __name__ == "__main__":
    unittest.main()
