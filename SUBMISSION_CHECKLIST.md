# Submission checklist — VoiceOps 2026 (final)

## 1. What goes on GitHub (public repo)

Push **this whole project folder** as a public repository named
`voiceops-2026`. It must contain exactly:

```
README.md                 <- install steps + exact run command (done)
.env.example              <- variable names only, NO keys (done)
requirements.txt          <- gnani-vachana only; core is stdlib (done)
run.py / run.sh           <- official batch run command (done)
src/                      <- agent, conversation, kb, voice, baseline,
                             evaluate, dates/lang utils, tools adapter
scripts/                  <- run_evaluation.py, make_report_pdf.py
report.pdf / report.md    <- 4-page report with Step 1 vs Step 2 scores
sample_outputs/           <- real run outputs (text + JSON + evidence IDs)
evaluation_results.json   <- full scores, incl. failure lists (empty)
demo/                     <- 2-min demo script + recordable lines
SUBMISSION_CHECKLIST.md   <- this file
```

**Never push:** the dataset folder/zip (organisers supply it; brief
forbids a dataset copy), a real `.env` or any API key, `__pycache__/`,
`tickets_created.csv`. The repo `.gitignore` already covers all of
these — it was scanned before packaging.

### Push commands (one-time, after `gh auth login`)

```
cd voiceops-2026/project
gh repo create anshssh/voiceops-2026 --public --source=. --remote=origin --push
```

(or create the empty public repo on github.com and run
`git remote add origin https://github.com/anshssh/voiceops-2026.git`
then `git push -u origin main` — the local git history is already
committed and clean.)

## 2. The submission ZIP

`team_name_voiceops.zip` mirrors the repo, with `report.pdf` at the
root and `sample_outputs/` included, per the brief. The ready-made
package is `shivansh_voiceops.zip` next to this project folder —
**rename it to your team name** before submitting if your team name
isn't "shivansh".

## 3. Final numbers (re-run and locked 22 Oct 2026)

| Check | Result |
| --- | --- |
| Step 1 prompt-only baseline | 6 / 52 (11.5%) |
| Step 2 RAG agent — practice questions | **52 / 52**, decisions 52/52, gold-evidence hit 100% |
| Step 2 on ASR-style transcripts | **52 / 52** |
| Step 3 — practice conversations | **96 / 96 turns** |
| Dataset validation (organisers' script) | PASS |

## 4. The only two hand-moves left (both are yours by the rules)

1. **Gnani key** — the brief requires each participant to use their
   *own* Gnani account. Create it at app.gnani.ai/voice, set
   `GNANI_API_KEY`, record the demo lines in `demo/`, run the two
   `run.py` commands in `demo/DEMO_SCRIPT.md`, and your `demo.mp4`
   is the screen recording of that run (≤ 2 min).
2. **GitHub login** — `gh` on this machine is not logged in, so the
   push above needs your one-time `gh auth login` (or create the repo
   in the browser). After that the push is a single command.

Everything else — code, evaluation, report, sample outputs, demo
script, package — is done.
