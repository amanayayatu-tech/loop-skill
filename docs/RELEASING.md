# Release process

`VERSION` is the release source of truth. A release is complete only after the
release commit is merged to `main`, required GitHub Actions checks pass, the
annotated tag points to that exact `main` commit, and the GitHub Release exists.

## Checklist

1. Update `VERSION` and `CHANGELOG.md`.
2. Regenerate any intentionally changed examples and update their fixture hashes.
3. Run the local release gate:

   ```bash
   python3 -m pip install -r requirements-test.txt
   python3 -W error -m compileall -q codex-loop-prompt-architect/scripts tests
   python3 codex-loop-prompt-architect/scripts/validate_skill.py
   bash -n scripts/install.sh
   python3 -W error -m unittest discover -s tests -v
   ADAPTIVE_FUZZ_CASES=5000 ADAPTIVE_STATE_FUZZ_CASES=5000 \
     python3 -W error -m unittest discover -s tests -q
   coverage run -m unittest discover -s tests
   coverage report
   ```

4. Install into an isolated `CODEX_HOME` and validate the installed copy.
5. Inspect `git status`, the staged diff, and risky artifacts. Do not include
   `.codex-loop/**`, databases, archives, secrets, generated Controller Packs,
   or unrelated evidence without explicit release scope.
6. Push a release branch, open a pull request, and wait for all required checks.
7. Merge the pull request.
8. Create an annotated tag on the exact merge commit and push the tag.
9. Create the GitHub Release from the matching changelog entry.

Green local checks and a bounded Codex App smoke do not independently prove
merge completion, release publication, or broader acceptance.
