# Checks

Every check has an ID, a **round** and a **source**:

- **fix**: applied directly in the fix round. When a particular instance is ambiguous (meaning could change, several valid fixes), it goes to the report instead.
- **report**: never edited; it becomes a finding in `finishing-report.md`.
- **script**: `scripts/check_paper.py` reports it under the same ID. Lines marked `hint` are heuristics; confirm them by reading the text. **read**: only a careful read finds it.

A check marked with a stage (double-blind, camera-ready) runs only at that stage.

## L: LaTeX and build

**L1 Clean build** · report · script (log)
The build has no errors, undefined references or citations, multiply-defined labels, missing files, or overfull boxes of 1pt or more. Fix the cause when it is obvious, e.g. a typo in a label; report the rest.

**L2 Labels and references resolve** · report · script
Every `\ref`-family command points to an existing `\label`, and no label is defined twice.

**L3 Floats referenced** · report · script
Every figure, table, listing and algorithm has a label, is referenced in the text, and appears in the PDF after its first reference.

**L4 No leftovers** · report · script
No TODOs, FIXMEs, `\todo`, author note macros, highlighted or colored review text, `draft`/`showframe` options, active todonotes/fixme/changes packages, or blocks of commented-out prose.

**L5 No placeholders** · report · script
No placeholder URLs (`\url{}`, example.com, `<link>`), empty or dummy citation keys (`\cite{}`, `\cite{TODO}`, `[?]`), "citation needed", or lorem ipsum. This also covers placeholder values in bib entries.

**L6 Non-breaking space** · fix · script
Every `\cite` and `\ref`-family command (`\ref`, `\eqref`, `\cref`, `\autoref`, ...) is preceded by `~` instead of a space: `as shown~\cite{x}`, `Fig.~\ref{f}`. Exceptions: at the start of a sentence, after an opening bracket, after a command, and for textual citations (`\citet`, `\citeauthor`).

**L7 Citation mechanics** · fix · script
Adjacent citations are merged (`\cite{a,b}` instead of `\cite{a}\cite{b}`). A citation comes before the sentence's final punctuation: `... shown~\cite{x}.`, not `... shown.\cite{x}`.

**L8 Quotes and dashes** · fix · script
Quotes are written ``` ``text'' ```, never `"text"`. Unicode quotes and dashes are covered by L10. Number ranges and page ranges use `--` (`3--5`). A dash inside a sentence uses one style throughout: either `---` or a spaced `--`, never a spaced hyphen.

**L9 URLs** · fix (`\url` wrapping), report (the rest) · script
Every URL is set with `\url{}` or `\href{}`. Footnote URLs carry a last-accessed date; report any that are missing it, because the access date has to come from the author. Reachability is optional: when you have web access, spot-check that links resolve and report dead ones.

**L10 No pasted Unicode** · fix (known replacements), report (emojis, unknown symbols) · script
The `.tex` sources and the `.bib` files in use contain only ASCII outside comments. Pasted text brings in characters that break the build, disappear, or render wrong. Replace them:
- **Dashes and quotes:** em dash → `---`, en dash → `--`, minus sign → `$-$`, curly quotes → ``` `` '' ```/`` ` ' ``.
- **Invisible characters:** no-break space → `~`, thin space → `\,`. Delete zero-width spaces, zero-width joiners, soft hyphens and byte-order marks.
- **PDF ligatures:** ﬁ, ﬂ, ﬀ, ﬃ, ﬄ → plain letters.
- **Accented letters:** ä → `{\"a}`, é → `{\'e}`, ç → `\c{c}`, ß → `{\ss}`; this also applies to author names in the `.bib`.
- **Math and symbols:** × ≤ ≥ → ± ° µ → `$\times$`, `$\leq$`, and so on; … → `\ldots{}`.

The script suggests a replacement for each character. Emojis, pictographs and characters without a known replacement are reported, because removing them may change the content.

## S: Springer notation

**S1 Reference names** · fix · script
When the name is followed by a number or `\ref`:

| Inside a sentence | At the start of a sentence |
|---|---|
| Fig. / Figs. | Figure / Figures |
| Sect. / Sects. | Section / Sections |
| Eq. / Eqs. | Equation / Equations |
| Chap. / Chaps. | Chapter / Chapters |
| Table / Tables | Table / Tables |

*Table* is never abbreviated. *Sec.* and *Tab.* are wrong everywhere. Starts of captions, footnotes and list items count as sentence starts. With `cleveref`, set `\crefname` to the abbreviated forms, use `\Cref` at sentence start and `\cref` inside a sentence. `\autoref` always prints the full name, so replace it wherever the abbreviation is needed.

## T: Template and venue

**T1 Template adherence** · fix (unambiguous deviations), report (the rest) · read
The paper follows the template the user pointed to, down to the details. Extract the requirements from the template and its author instructions during intake, then check each one. Examples: document class and options, required and forbidden packages, no layout changes (margins, fonts, line spacing, negative `\vspace`, `\small` bodies), front-matter format (title, running heads, authors, institutes, ORCID, emails), abstract and keyword format and limits, heading and caption style and caption placement, bibliography style, and required sections or statements.

**T2 Page limit** · report · script (page count) + read
Run this last, on the PDF built after the fix round. Apply the rule from the page the user pointed to: the number of pages, and whether references, appendices or supplementary material count. Read the PDF to find where the counted part ends. Report the verdict, and when the paper is over the limit, report by how much.

**T3 Anonymization** · report · double-blind only · read
The PDF and sources contain no author names, affiliations, emails, ORCIDs or acknowledgments; no funding, project or grant identifiers; and no revealing URLs, such as personal GitHub accounts or institutional hosts (use anonymized repositories instead). Self-citations are in third person ("Smith et al. showed", not "we showed in [3]"). The PDF metadata (`\hypersetup{pdfauthor}`) is also free of author information.

**T4 Camera-ready metadata** · report · camera-ready only · read
All authors, affiliations, emails and ORCIDs are complete and correct. Acknowledgments and funding statements are present, as are any statements the venue requires (e.g., disclosure of interests). Nothing from the review version is left over, such as an anonymized repository link instead of the real one, "anonymous" authors, or reviewer-response text.

## B: Bibliography

New citations go into one large library that is shared across papers. The final paper doesn't use that library: it uses a **shortened `.bib`**, generated with JabRef from the paper's `.aux` file (*Tools → New sublibrary based on AUX file*) and holding exactly the cited entries. The library stores venue names on purpose in both a full and an abbreviated form, so leave venue naming alone.

Bib fixes (B5) go into the shortened `.bib` and also into the full library when its path is known, so a regenerated subset keeps them. B2–B4 findings name the full library as the place to fix them.

**B1 Shortened bibliography** · report · script
- **Full library in use:** `\bibliography` (or `\addbibresource`) points to the full library instead of a shortened `.bib`. This is **blocking**. If no shortened `.bib` exists, alert the user to create one with JabRef from the `.aux`. If a matching one exists next to the paper but isn't used, name it.
- **Stale subset:** the shortened `.bib` holds entries that are no longer cited, or lacks cited keys. Regenerate it from the current `.aux`.
- **Missing keys:** a cited key exists in no `.bib` at all.
- **`\nocite{*}`:** present anywhere in the paper.

**B2 Duplicate entries** · report · script
Each paper is cited under only one key: same title or DOI, different keys.

**B3 Entry completeness** · report · script
Every cited entry has authors, a title, a year and its venue field (`journal`, `booktitle`, `publisher`, `school` or `institution`, depending on the entry type). Articles and proceedings papers also have pages or a DOI.

**B4 Preprints** · report · script + web search
For every cited arXiv, CoRR or other preprint entry, search whether a peer-reviewed version has been published. Report each one found with its venue, year and DOI.

**B5 Title capitalization** · fix · script
Title words whose capitals must survive the bibliography style are braced: acronyms and mixed case (`{LiDAR}`, `{CNN}s`), and proper nouns (`{Bayesian}`, `{Python}`). The script finds the first group; find proper nouns by reading the titles.

## G: Language and style

**G1 Spelling, grammar, punctuation** · fix (clear errors), report (rewrites) · read
Fix typos, agreement errors, missing articles, wrong prepositions and comma errors that have a single correct fix. Report awkward or unclear sentences with a suggested rewrite.

**G2 Spelling variant** · fix · script
Use the variant chosen during intake (American or British) throughout: *-ize*/*-ise*, *-yze*/*-yse*, *behavior*/*behaviour*, *modeling*/*modelling*, and so on. Quoted titles and proper names keep their original spelling.

**G3 Hyphenation** · fix · script
Compounds are written the same way everywhere (*dataset* vs. *data set*, *runtime* vs. *run-time*). Adjective compounds before a noun are hyphenated (*real-world data*), and the same words used as a noun phrase are not (*in the real world*).

**G4 Latin abbreviations** · fix · script
*e.g.,* and *i.e.,* are always followed by a comma in American English; British English is consistent either way. *et al.*, *cf.* and *vs.* take a period, and *etc.* is not followed by a second period at the end of a sentence.

**G5 Numbers and units** · fix · script
Numbers from zero to nine are spelled out in prose unless they carry a unit, are part of a series with larger numbers, or are identifiers. Values have a space before their unit (`10\,ms`, or `siunitx` if the paper uses it). Comparable values use the same number of decimal places.

**G6 Formal register** · fix · script
No contractions (*don't*, *it's*) and no informal wording (*a lot of*, *basically*, *huge*).

**G7 Sentence openings** · fix · script + read
No sentence starts with a digit, a math symbol, or a bare citation. Rephrase these: "Three runs ...", "The variable $x$ ...", "Smith et al.~\cite{x} ...".

**G8 Lists** · fix · read
Items within one list, and lists of the same kind across the paper, share capitalization, punctuation and grammatical form.

**G9 Tense and voice** · report · read
The tense is used consistently: present tense for what the paper does and shows, past tense for the experimental procedure, and one convention for related work. The paper uses one voice, typically "we".

## C: Content consistency

**C1 Sections filled** · report · script + read
No section is empty, a stub, or just a heading followed by a list. Report every section whose content does not fulfill what its heading promises.

**C2 Roadmap** · fix (numbering and reference mechanics), report (content) · script + read
The "remainder of this paper" paragraph names every following section, in document order, through `\ref` (never literal numbers). Its description of each section matches that section's actual content and title.

**C3 Terminology** · fix (spelling and capitalization variants), report (term choice) · script + read
Each term is introduced (defined or explained) at its first use and is used the same way throughout: one term per concept, one concept per term, the same capitalization and spelling. Synonyms swapped in for variety are a finding.

**C4 Abbreviations** · fix · script
Each abbreviation is introduced as "Long Form (LF)" at its first use in the body, exactly once. Afterwards only the short form is used. The abstract is separate: an abbreviation introduced there is introduced again in the body. Abbreviations that are used only once or never after being defined are reported, since they can probably be dropped. Widely known ones (e.g., *GPU*, *API*) may stay undefined if the venue allows it; report them as optional.

**C5 No duplicate support** · fix (identical footnotes), report (the rest) · script + read
The same footnote, or the same URL in a footnote, appears only once; later mentions point back to it. A claim is supported once: the same citation or footnote isn't repeated for the same claim within a passage.

**C6 Citation integration** · fix · script + read
A citation is never a sentence part ("[3] shows", "in [3]"). Integrate it in one of these ways:
- **Name the work in the sentence:** "Smith et al.~\cite{x} show ...", "The approach of Smith et al.~\cite{x} ...".
- **Support a claim:** "Scenario-based testing is widely used~\cite{x}."
- **Mark it with cf., e.g., or i.e.:** *cf.* for comparison or further reading, *e.g.* for one example of many, *i.e.* when the citation is the one thing meant: "(cf.~\cite{x})", "several tools (e.g.,~\cite{a,b})".

**C7 Claims delivered** · report · read
Every contribution listed in the introduction is delivered and evaluated in the paper. The abstract and conclusion claim no more than the results show, and name no result the paper doesn't contain.

**C8 Math notation** · report · read
Every symbol is defined before its first use. One symbol means one thing throughout, and each thing has one symbol. Vectors, sets and functions use one typographic style (bold, calligraphic, ...).

**C9 Names** · fix · read
Product, tool, dataset and organization names are spelled as their owners spell them, the same way everywhere (*GitHub*, *LaTeX*, *PyTorch*, *OpenAI*).

## F: Figures

**F1 Figures** · report · script + read (open each figure file)
Every graphics file exists. Plots and diagrams are vector graphics (PDF/EPS) rather than raster images. Text in figures is readable at print size: roughly no smaller than the caption font. Figures stay understandable in grayscale and for colorblind readers: colors are not the only way series are told apart, and red/green isn't used as a contrast pair. Axes are labeled, with units.
