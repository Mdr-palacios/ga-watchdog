---
name: Gap (doc promises something the code doesn't have)
about: A doc, ADR, or roadmap promises a thing the codebase doesn't have yet. The promise is older than the implementation.
title: "gap: <missing artifact>"
labels: gap
assignees: ""
---

## Gap

What does the doc/roadmap promise? Quote it.

## Evidence

Show the gap is real. A grep that returns nothing is a good form here:

```
$ grep -rn "<the missing thing>" <where it would live>
# (no results)
```

## Why now

Why does this gap need closing? Either:

- A runbook or lesson currently depends on this artifact existing, or
- The next phase of work assumes it, or
- The doc would lie until it's there.

If none of these apply, the gap might be acceptable. Say so in the doc instead of opening an issue.

## What "done" looks like

The smallest thing that makes the doc honest:

1. ...
2. ...
3. Update the promising doc to reference the artifact instead of a "TODO" note.

## References

- The doc that names the gap.
- The lesson that names the discipline.
