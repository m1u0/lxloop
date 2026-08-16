# lxloop research program

You are conducting one human-directed performance research run against a dedicated
`llama.cpp` Git worktree. Read this file completely, then read `task.md`. The
engineer chooses the research direction; do not broaden it silently.

Your job is to make measured inference improvements on the real RISC-V target.
Code that merely looks faster is not a result.

## Fixed boundaries

- Modify source only under `ggml/src/ggml-cpu/` in the configured subject checkout.
- Do not modify files elsewhere in `llama.cpp`.
- Do not modify lxloop's evaluator, configuration, or permanent instructions during
  a research run.
- The evaluator enforces the source boundary mechanically. It is protection against
  accidental or malformed edits, not an adversarial security sandbox.
- Work only on the `autoresearch/*` branch in the dedicated, initially clean
  subject worktree named by `config.py`.
- Keep the target exclusively reserved for this research run.

Inside `ggml-cpu`, use the breadth justified by `task.md`. You may substantially
change implementations, use RISC-V intrinsics, or add files there when the
hypothesis requires it. Do not restructure code without a measured reason.

## Hardware context

The target is proprietary 64-core RISC-V hardware with a 1024-byte vector length.
Four additional accelerator components and their operating-system coordination
exist, but that architecture is outside this research run. RISC-V vector
intrinsics are promising, not mandatory. The current internal implementation is
already roughly 10× faster than its original baseline.

The target has no compiler and no Internet access. Cross-compilation, research
logic, parsing, and logs stay on the workstation. The target only receives a
prepared deploy directory and executes correctness and benchmark commands.

## Before the loop

1. Read `task.md` and restate its scope, primary metric, permitted trade-offs,
   and constraints.
2. Read the relevant in-scope source and the recent Git history.
3. Confirm the subject checkout is clean, is a linked worktree, and is on the
   intended `autoresearch/<tag>` branch based on the configured immutable upstream
   commit. `UPSTREAM_REF` must be the full commit ID, not a movable branch or tag.
4. Run `python3 evaluate.py` before changing source. This untouched baseline is
   also the end-to-end smoke test for the cross-toolchain, deployment, target
   runtime, correctness suite, and benchmark command.
5. Stop for engineer help if the baseline does not return `status: ok`.
6. Create `results.tsv` if needed with this header:

   ```text
   commit	prefill_tps	decode_tps	status	description
   ```

7. Record the baseline as the first row, including the configured upstream ref
   and its commit in the description.

The evaluator prints a short contract like:

```text
---
status: ok
commit: b4e2f1a
prefill_tps: 142.310 ± 1.850 (n=5)
decode_tps: 9.874 ± 0.041 (n=5)
log: logs/20260817T031412Z_b4e2f1a
```

Full command output is under the reported log directory. Read phase logs only
when the summary requires diagnosis; do not stream large logs into your context.

## Loop forever

Repeat until the engineer interrupts you or repeated infrastructure failures make
measurement impossible:

1. Inspect the current baseline and the relevant source.
2. Form one concrete optimization hypothesis within `task.md`.
3. Make the smallest coherent source change that tests that hypothesis.
4. Review the diff. Revert accidental or unrelated edits.
5. Stage only `ggml/src/ggml-cpu/` and commit the candidate with a short message
   describing the hypothesis.
6. Save the candidate commit identity.
7. Run `python3 evaluate.py`.
8. Apply the failure or acceptance policy below.
9. Append one row to `results.tsv`.
10. Continue from the last kept baseline.

Never keep a candidate without target correctness and benchmark evidence. Never
combine unrelated hypotheses merely to reduce the number of experiments.

## Correctness and performance

The configured correctness command is authoritative:

- exit zero: the candidate is valid and benchmarking may run;
- non-zero: reject the candidate.

Do not reinterpret floating-point tolerances or substitute your own correctness
judgment.

Unless `task.md` overrides it, decode is the primary metric. For the provisional
v0 policy:

- Let the required primary gain be the greater of 1% of the baseline mean and
  twice the larger reported standard deviation of the baseline and candidate.
- Keep only if the candidate primary mean exceeds the baseline mean by more than
  that required gain.
- Reject if the secondary mean regresses by more than 1%.
- A kept candidate's measured result becomes the next baseline.

If `task.md` designates prefill as primary or explicitly allows a different
trade-off, follow it and record the policy in the experiment description.

Measurement noise, model choice, quantization, prompt length, generation length,
threads, batches, and repetitions are configured externally. Do not change them
mid-run to make a candidate look better.

## Git decisions

A candidate is committed before evaluation.

On keep:

- leave the candidate commit on the branch;
- record `keep` in `results.tsv`;
- use its measurement as the next baseline.

On reject:

- record the candidate identity and result before resetting;
- run `git reset --hard HEAD~1` in the dedicated subject worktree;
- confirm the worktree is back at the last kept commit;
- record `discard` or the evaluator failure status in `results.tsv`.

Do not rewrite earlier kept commits. The successful branch history is the primary
research record. The TSV is a lightweight overnight ledger, not a replacement for
Git.

## Failure policy

Expected candidate failures include build errors, correctness failures, illegal
instructions, crashes, benchmark errors, malformed output, and timeouts.

- If a build failure is an obvious transcription error, make at most two focused
  fixes, amend the candidate commit, and rerun it.
- If the hypothesis itself is broken, log it and reject immediately.
- Correctness failures, benchmark crashes, illegal instructions, malformed
  benchmark output, and candidate timeouts are rejects.
- The evaluator retries transfer and SSH infrastructure failures once.
- An infrastructure failure is not a performance result. Do not reset a candidate
  merely because the target is unreachable.
- After several consecutive infrastructure failures, stop and leave the candidate,
  results ledger, and logs intact for the engineer.
- After any candidate rejection, recover to the last kept commit and continue.
  Do not stop merely because an experiment failed.

## Research quality

Prefer changes whose performance gain justifies their complexity. Preserve
reasonable readability and maintainability. Equal performance from substantially
simpler code can be worth reporting, but do not call it a throughput keep unless
`task.md` explicitly permits that objective.

Write experiment descriptions that state the hypothesis, not merely the edited
symbol. Use the target measurements to update your beliefs and choose the next
experiment.
