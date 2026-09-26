---
name: paper-finishing
description: Final finishing pass over a finished LaTeX paper before submission or camera-ready. Asks about the venue, fixes mechanical issues (Springer reference names, non-breaking spaces, citations, spelling), then reports everything that needs the author's judgment (references, TODOs, template, page limit, terminology, bibliography). Re-runnable, and remembers findings between runs. Use when a paper is done and needs its final check, proofread, or pre-submission polish.
---

# Paper finishing

A finishing pass over a paper that is done in content. It runs in four phases: **intake**, **baseline**, **fix round** and **report round**. Every check has an ID and a round tag in [CHECKS.md](CHECKS.md). Fix-tagged checks are applied in the fix round; report-tagged checks become findings in the report. `scripts/check_paper.py` covers the deterministic part of the checks. The rest comes from reading the paper, which is the core of this workflow, not optional.

The skill is meant to be run again and again as the paper evolves. Each run picks up where the last one ended: it doesn't ask the intake questions again, doesn't bring back findings the user has dismissed, and marks findings as new or resolved.

## State: the `finishing/` folder

All state lives in `finishing/` next to the main file. Recommend committing it with the paper, so decisions persist and co-authors see them.

| File | Written by | Content |
|---|---|---|
| `config.md` | intake | Intake answers, template requirements, page-limit rule |
| `report.md` | report round | Current findings, resolved findings, run history |
| `dismissed.md` | user, or agent for false positives | Findings that stay as they are and are never reported again |
| `state.json` | script with `--save` | Script findings of the last completed run, used to compare runs |

**Finding IDs.** Script findings carry an 8-character ID, e.g. `[3f9a1c2e]`. It is computed from the check, the file and the words around the finding, so it doesn't depend on line numbers and survives edits elsewhere. Findings from reading get a readable ID instead: `<check>-<slug>`, e.g. `C7-abstract-speedup-claim`. Reuse that ID for the same finding in later runs.

**Dismissing.** `dismissed.md` has one line per finding:
`- <id> · <check> · <file> · <what> · <reason>`
The script skips every 8-character ID listed there, and the agent skips the readable IDs. The user dismisses findings by editing the file or by telling you; in the second case, add the line with their reason. You may dismiss a script hint on your own only when it is a clear false positive, with the reason `false positive: <why>`. Intentional deviations are the user's call.

## 1. Intake

1. Find the main file: the `.tex` file containing `\documentclass` and `\begin{document}`.
2. **Re-run** (`finishing/config.md` exists): read it and summarize it in two lines. Then ask a single question: is it still valid, or what changed? A stage change, e.g. to camera-ready, switches T3 off and T4 on. Re-read the template or page-limit page only if its source changed. Update `config.md` accordingly.
3. **First run:** run the script once without state to get an overview and the American/British counts (G2): `python <skill-dir>/scripts/check_paper.py <main.tex>`. Then ask all open questions in a single round, and don't edit anything before the answers are in. Use the question tool for choices and plain questions for links:
   - **Stage:** initial submission, revision, or camera-ready.
   - **Review mode** (skip for camera-ready): double-blind or single-blind.
   - **Template:** a path or URL to the template the paper must follow, plus its author instructions if they are separate.
   - **Page limit:** the URL of the call for papers or submission-guidelines page that states the limit.
   - **Spelling variant:** American or British. Propose the variant the paper mostly uses already.
   - **Full library:** the path to the large, shared `.bib` library (optional). With it, B5 fixes also go into the library, so they survive the next time the shortened `.bib` is regenerated from the `.aux`.
   - **Main file:** only if several candidates exist.

   Read the template and the page-limit page (ask before downloading an archive), then write `finishing/config.md` with:
   - all answers;
   - **template requirements:** a checklist of everything T1 lists that the template or its instructions pin down;
   - **page-limit rule:** the number of pages, and which parts count (references, appendix, supplementary material).

Done when `config.md` holds current answers and both lists.

## 2. Baseline

1. **Safety net.** In a git repository, the working tree must be clean apart from `finishing/`; if it isn't, ask the user to commit or stash first, so the fix round becomes one reviewable diff. Without git, copy the sources to the scratchpad as a backup.
2. **Build** with the project's own build setup (`latexmkrc`, `Makefile`, the Overleaf compiler setting), or else run `latexmk -pdf <main.tex>`. If the build fails, stop and report: finishing starts from a paper that compiles.
3. **Run the script** with state but without saving:
   `python <skill-dir>/scripts/check_paper.py <main.tex> --log <main.log> --variant us|uk --state finishing`
   Add `--todo-macros a,b` for author note macros the script didn't detect on its own (it lists the ones it found).
4. **Read the whole paper**, every input file in document order, along with the `.bib` entries it cites. On a re-run, also read `finishing/report.md` and `finishing/dismissed.md`.

## 3. Fix round

Apply every fix-tagged check to the whole paper. Use the script findings as a starting point, but cover what the script can't see (G1, G8, C3, C6, C9 and others) while reading. Leave dismissed findings alone.

- **Change form, never content.** Claims, numbers, results, citation targets and the argument stay exactly as they are.
- **When in doubt, report.** If an instance has more than one reasonable fix, or fixing it could change the meaning, it goes to the report instead of being edited.
- **Keep the diff minimal.** Keep the existing line breaks and don't reflow paragraphs, so every change is visible in the diff.
- **Keep a tally** of fixes per check ID for the report.

Done when the paper builds with no new warnings, and the script, run again with `--state finishing --save`, shows no remaining finding for any fix-tagged check other than those deliberately moved to the report. That saved run is the reference point for the next run's new/resolved comparison.

## 4. Report round

Apply every report-tagged check that belongs to the current stage (T3 only for double-blind, T4 only for camera-ready). Confirm each script hint by reading the text; dismiss clear false positives as described above. B4 needs a web search for each preprint. Run T2, the page limit, last, on the PDF from the final build.

On a re-run, check every open finding from reading in the previous `report.md` again. If it's still there, it stays open with the same ID; if not, it moves to Resolved. Script findings get their new/resolved status from the script output.

Rewrite `finishing/report.md`, keeping the run history rows from the previous version and adding one row for this run:

```markdown
# Finishing report: <paper title>
Stage: <stage>, <review mode> · Template: <link> · Page limit: <rule> · Last run: <date>

## Blocking
<Findings that make the paper unsubmittable: build errors, unresolved references,
TODOs/placeholders, full library instead of the shortened .bib, page limit exceeded,
anonymization leaks, template violations.>

## Findings
### <check ID> <check name>
- [<id>] `file.tex:42`: <what is wrong> → <suggested change> (new)

## Resolved since the last run
- [<id>] <check ID>: <what it was>

## Fixed in this run
| Check | Fixes | Note |

## Dismissed
<N> findings, listed in dismissed.md.

## Run history
| Date | Stage | Fixed | Open | New | Resolved | Dismissed |
```

Every applicable report-tagged check gets its own section, including those with no findings ("No findings"). That way the report shows the check was run and not skipped.

Done when every applicable report-tagged check has a section, the Blocking section is complete, and the run history has a row for this run.

## 5. Hand-off

Tell the user in a few lines:
- the number of fixes per check;
- the blocking findings;
- what's new and what's resolved since the last run;
- the page-limit verdict;
- the path to `finishing/report.md`.

Also explain how to dismiss findings: reply with the IDs and reasons, or edit `finishing/dismissed.md`. Leave the changes uncommitted so the user reviews the diff first.
