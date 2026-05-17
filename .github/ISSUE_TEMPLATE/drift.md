---
name: Drift (code does not match a convention)
about: The codebase doesn't match what a doc, ADR, or convention says it should. The convention is older than the drift.
title: "drift: <short symptom> in <file or area>"
labels: drift
assignees: ""
---

## Symptom

What does the doc/convention say? What does the code do instead? One sentence.

## Evidence

Quote the convention. Quote the offending code (file + line numbers). The reader of this issue should not have to grep.

```
# from <file>:<line>
<offending code>
```

## What "done" looks like

Concrete changes, in order:

1. ...
2. ...
3. Strike the corresponding bullet from `docs/observability.md` § Known drift (or wherever the convention lives).

## Why it's a drift, not a feature gap

The convention came first. The code drifted from it. This issue closes the gap honestly. If the convention itself is wrong, that's a different issue — open one against the doc.

## References

- Link to the convention/doc.
- Link to the lesson that names this discipline.
