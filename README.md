# agent-skills
A list of my own agent-skills

## Skills

- [paper-finishing](paper-finishing/SKILL.md): final pass over a finished LaTeX paper (Springer notation, references, TODOs, template and page limit, language, bibliography), with a fix round and a findings report.

## Tests

The automated checks of `paper-finishing` are covered by regression tests on small fixture papers, run by GitHub Actions on every change:

```bash
python -m unittest discover -s paper-finishing/tests -v
```
