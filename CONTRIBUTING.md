# Contributing

Thanks for looking.

## The gate

```bash
make check
```

That's everything a change has to pass, and CI runs exactly it on every push and
pull request.

**This repository installs no commit hook and declares no hook framework.** If
you want the gate to run before each commit, wire one up yourself:

```bash
printf '#!/bin/sh\nexec make check\n' > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

`make check` needs `terraform`, `packer`, `terraform-docs` and `shellcheck` on
your `PATH`, plus `uv` for everything Python. A missing one fails loudly rather
than being skipped.

## What a change should look like

- One concern per pull request, with the reasoning in the description.
- `make check` green.
- A test that fails before your change and passes after it. **One direction
  isn't a test**: something that fires isn't evidence it can be quiet, and
  something quiet isn't evidence it can fire.
- An entry in `CHANGELOG.md` under a new heading, saying what changed for
  somebody using this rather than what the diff did.
- Comments say what the code does or what it guards against, in a sentence or
  two. History belongs in the commit message and the changelog.

## Security

Don't open a public issue for a vulnerability.
[SECURITY.md](SECURITY.md) has the reporting route.
