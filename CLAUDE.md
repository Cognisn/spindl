# Project configuration
- Kvasir library: devwork (tag project-spindl); fallback: none
- Issue tracker: github
- GitHub repository: Cognisn/spindl
- Default branch: main
- Release branch style: release/v<version>
- Merge to main: merge (pull request from the release branch with a merge commit, as #17 and #18)
- Commit scopes: core, server, registry, tool, auth, wsgi, transports, spooler, skills, sample, docs, deps, ci, dev, release, graph
- Shared modules: pyproject.toml, uv.lock, requirements/, scripts/lock-ci.sh, .github/, src/spindl/__init__.py, src/spindl/server.py, src/spindl/registry.py, src/spindl/tool.py, src/spindl/auth (module, a package from Wave 3), CHANGELOG.md

## What spindl is

spindl (`cognisn-spindl` on PyPI) is a Python library for building MCP servers,
with hierarchical tool prefixing, skills guides and response spooling. It is a
library only: it has no Compose services and no testcontainers, so nothing in
this repository is a heavy workload.

## Checks

Run each as its own command, in the project's virtual environment:

```
black --check src/ tests/ sample/
isort --check-only src/ tests/ sample/
mypy src/spindl
pytest --timeout=60
```

All four must be green before a commit, and again after every merge on the
release branch.

## Dependency locks

The workflows install only from hash-locked files in `requirements/`, always
with `pip install --require-hashes --only-binary :all:`. After changing
dependencies in `pyproject.toml` or `requirements/build.in`, regenerate the
locks with `bash scripts/lock-ci.sh`. It runs in Git Bash and needs `uv`.

## CHANGELOG

`CHANGELOG.md` keeps an `[Unreleased]` section. Workstream sessions never edit
it. Each workstream records its changelog lines in its Kvasir session summary,
and the integration session writes them under `[Unreleased]` when it merges
that workstream. This is because `scripts/bump-version.sh` rolls
`[Unreleased]` into a dated section at every stamp, so workstream edits would
conflict at nearly every merge.

## Integration procedure

The integration session works in the main clone on the release branch and
merges one workstream at a time:

1. Confirm CI is green on the workstream branch tip.
2. `git merge --no-ff <workstream branch>`.
3. Rerun the full checks above.
4. Write that workstream's changelog lines under `[Unreleased]`, from its
   session summary.
5. Stamp with `bash scripts/bump-version.sh <version>`, which sets
   `src/spindl/_version.txt` and rolls `[Unreleased]` into a dated section.
6. Commit as `chore(release): stamp <version>`.
7. Push the release branch and confirm CI is green on its tip.
8. Record the merge and the stamp in Skuld.

## Publishing

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which
builds, tests and publishes to PyPI. Merging the release branch to `main`,
tagging and publishing happen only on Matthew's word.
