# Roadmap

code-bloat-review exists to stop accidental bloat before it reaches `main`.

Writing code got cheap: an agent produces a feature in minutes, and one more layer, wrapper or
copied helper costs it nothing. Running and maintaining that code did not get cheaper: every
extra line and dependency means longer CI runs, more scanner alerts and more to patch. The
directions below keep the tool on the prevention side, in CI, with reasons a reviewer can check.

Two uses, in this order:

1. **Taking over code.** When you sit down to code you are about to be responsible for, one
   run tells you whether it is proportionate to what it does, and where it is not. That is
   what v1 does: fully for applications, partly for pipelines (see below).
2. **Stopping it from growing.** The next step is to stop bloat in the changes coming in,
   pull request by pull request. Most of this roadmap serves that step.

This is a plan, not a promise. Use cases and ideas are welcome in issues.

## Next

### Ratchet: no pull request makes it worse

`fail-above` is a fixed threshold: a project already over the line blocks every pull request,
and one under it can keep growing until it hits the line. A ratchet compares the pull request
with its base branch and fails only when the score goes up by more than a set margin.

- CLI `--compare-to <ref>`, action input `compare: base`
- the report shows before → after for each score component

### Team rules on top of Clean Code

Clean Code stays the default yardstick: a finding named "G5 Duplication" is a heuristic anyone
can look up, not the tool's opinion. Teams can switch a rule off or change its weight when a
pattern is a deliberate trade-off (FastAPI's repeated keyword arguments, for example):

```toml
[tool.code-bloat-review.rules]
duplicate-code = { weight = 0.5 }
trivial-accessor = "off"
```

### Adoption guide

A recommended path in the README: job summary first, then the pull request comment, then a
gate once the team trusts the results.

## Later

### Score the change, not only the project

A pull request report that says what the change brings in: "this PR adds 400 lines; 120 of
them are duplication or dead code". Reviewers see the problem where it is being added.

### Ops yardstick: what code costs to run

A second set of rules next to Clean Code, from the operations side. Each rule gets a name, the
cost it causes, how it is detected and how to silence it.

- unused dependencies weighted as supply-chain surface, not only clutter
- several libraries for the same job (`requests` and `httpx`)
- generated or vendored code committed to the repository
- CI workflows copied with one line changed

### Pipelines and infrastructure as first-class code

Taking over a pipeline should get the same answer as taking over an application. Today shell,
PowerShell and Terraform get duplication and commented-out code checks; YAML workflows,
Kubernetes manifests, Bicep, Jenkinsfiles and Dockerfiles are only read to find references to
code, and are not judged. Candidates: duplicated jobs and steps across workflows, copied
Bicep/Terraform modules, unused parameters and outputs, stages that do nothing.

## Known limits to work on

- Libraries that ship a CLI (FastAPI) are judged as apps by default; the report suggests
  `--mode library`. A hybrid mode could count both the public API and the commands.
- The structural rules (dead code, abstractions, accessors) are Python-only.
