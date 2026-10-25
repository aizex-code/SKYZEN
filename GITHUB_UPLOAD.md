# Upload this folder to GitHub

This folder is the complete Skyzen repository root. Publish the contents of `sk_zen_ai` as the repository, not the parent folder containing it.

## GitHub Desktop

1. Extract `sk_zen_ai_github_ready.zip`.
2. In GitHub Desktop, choose **File → Add Local Repository** and select the extracted `sk_zen_ai` folder.
3. If GitHub Desktop says it is not a Git repository, choose **File → New Repository** and set the local path so the repository root is this `sk_zen_ai` folder. Do not create a nested `sk_zen_ai\sk_zen_ai` folder.
4. Review the file list. Confirm `.venv`, local projects, media, logs, and build output are not included.
5. Commit with a message such as `Initial Skyzen community release`.
6. Publish to GitHub as a **Public** repository if that is your intention.

## Before publishing publicly

- Read `LICENSE.md` and understand that the non-commercial restriction makes this source-available, not OSI-approved open source.
- Complete the checklist in `docs/REPOSITORY_RELEASE_CHECKLIST.md`.
- In particular, review `docs/THIRD_PARTY_AUDIT.md`. The `docs/concat_reference/` folder includes third-party AGPL-3.0-or-later reference source. Preserve its notices and do not claim the third-party audit is complete until it has been done.
- Do not commit personal projects, media, credentials, or crash logs.
- Check the repository's **Settings → Collaborators** and branch protections after publishing, if you want to manage contributions.

The archive is prepared from the supplied source snapshot. Python syntax was checked, but a full Windows GUI run and dependency-based test suite were not run in this environment.
