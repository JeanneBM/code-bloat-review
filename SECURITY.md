# Security

## What the action touches

- It reads the checked-out code and needs only `contents: read`. It never writes to the
  repository and needs no token.
- Symbolic links are skipped, so a link in the reviewed code cannot pull a file from
  outside the project into the report or the LLM digest.
- By default it is fully static: no code or data leaves the runner. The only download is
  Python from `actions/setup-python`.
- Inputs reach the scripts through environment variables, never by expression expansion
  inside the scripts, so an input cannot inject shell or Python code.

## With `--llm`

- A digest of the project (at most 30,000 characters: README excerpt, file list with SLOC,
  detected capabilities, findings and code signatures) goes to the provider you choose.
  Full source files are never sent.
- API keys are read from environment variables only. In GitHub Actions, pass them from
  secrets. Pull requests from forks get no secrets, so `--llm` is skipped there by GitHub.
- The README and code of the reviewed project end up in the prompt, so a pull request can
  try to sway the model. Gate CI on the static score (the default) and treat the LLM part
  as a second opinion.

## Reporting a vulnerability

Please report it privately through
[GitHub's vulnerability reporting](https://github.com/JeanneBM/code-bloat-review/security/advisories/new)
rather than in a public issue.
