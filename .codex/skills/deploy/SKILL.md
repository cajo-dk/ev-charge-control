---
name: deploy
description: Perform the full release workflow for the ev-charge-control repository. Use when the user asks to deploy, release, publish, tag, or make the latest EVCC version available, including committing pending release changes, verifying the release is prepared on main, merging any intended fr- or fix-branches into main, pushing main, creating the version tag, publishing the matching GitHub Release, and cleaning up merged release branches or stray non-v tags.
---

# Deploy

Release `ev-charge-control` by following the repository's documented workflow exactly.

## Workflow

1. Verify the repository context before changing anything.
Read `CONTEXT.md`, `VERSIONING.md`, `ev_charge_control/config.yaml`, `ev_charge_control/CHANGELOG.md`, and the latest file in `doc/fixes/` when preparing a fix release.

2. Confirm the release starts from `main`.
Run `git branch --show-current`.
If the current branch is not `main`, switch to `main` before releasing.

3. Check for release-bound topic branches.
List local and remote branches matching `fr-*` and `fix-*`.
If any of those branches contain work intended for the release, merge them into `main` before proceeding.
Delete merged `fr-*` and `fix-*` branches locally and on `origin` after they are incorporated.

4. Determine the next version and required documentation.
Use the repository versioning scheme `release.feature.fix`.
For fix releases, determine the next available `doc/fixes/fix-xxx.md` number and create the corresponding deployed fix record before the release commit.
Update `ev_charge_control/CHANGELOG.md` before creating the release commit.
Keep the newest changelog heading aligned with `ev_charge_control/config.yaml`.

5. Keep version metadata consistent.
Update all project version locations that are meant to stay aligned for a release:
- `ev_charge_control/config.yaml`
- `ev_charge_control/CHANGELOG.md`
- `pyproject.toml`
- `ev_charge_control/src/evcc/__init__.py`

6. Validate the release scope.
Run the tests that are appropriate for the change.
For documentation-only governance releases, document that no runtime tests were necessary.
Do not claim validation you did not perform.

7. Create the release commit on `main`.
Stage only the release-relevant files.
Create a release commit such as `release: 1.7.4`.

8. Create the correct tag format.
Use `v`-prefixed tags for this repository's public release history, for example `v1.7.4`.
Do not leave a plain `1.7.4` tag behind.
If a plain numeric tag was created accidentally, delete it locally and on `origin`.

9. Push the release.
Push `main` to `origin`.
Push the `vX.Y.Z` tag to `origin`.

10. Publish the GitHub Release object.
Create or update the GitHub Release with `gh release create` or `gh release edit`.
Use the `vX.Y.Z` tag.
Mark it as `--latest` when it is the newest release.
Use concise notes derived from `ev_charge_control/CHANGELOG.md`.

11. Verify the published state.
Confirm:
- `origin/main` points to the release commit
- `refs/tags/vX.Y.Z` points to the same commit
- `gh release list` shows the new release
- the worktree is clean after the release

## Operating Rules

- Release only from `main`.
- Merge any intended `fr-*` and `fix-*` branches into `main` before the release commit.
- Remove merged `fr-*` and `fix-*` branches after merging.
- Never skip the fix document for a fix-level release.
- Never create the release tag before the release commit exists.
- Prefer non-interactive Git commands.
- If GitHub already has a previous release object but only a plain local tag exists for the new version, create the proper `v`-prefixed tag and GitHub Release instead of assuming the push was sufficient.

## Command Pattern

Use this sequence as the default shape, adjusting the version and file set to match the actual release:

```powershell
git branch --show-current
git branch --format="%(refname:short)"
git branch -r --format="%(refname:short)"
git status --short
git add <release-files>
git commit -m "release: X.Y.Z"
git tag -a vX.Y.Z HEAD -m "Release vX.Y.Z"
git push origin main
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "<release notes>" --latest
git ls-remote --heads origin main
git ls-remote --tags origin refs/tags/vX.Y.Z
gh release list
```

If `gh release create` fails because the release already exists, run `gh release edit vX.Y.Z --latest --notes "<release notes>"`.

## Response Pattern

When using this skill, report:
- the release version
- the release commit hash
- the pushed `v` tag
- whether tests were run
- whether the GitHub Release object was created or updated
- whether any merged topic branches or stray plain tags were removed
