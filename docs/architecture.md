# lxloop v0 architecture

## Purpose

lxloop is a minimal, standalone research repository inspired by `autoresearch`. An engineer chooses a focused optimization problem inside `llama.cpp`'s `ggml/src/ggml-cpu/`; a coding agent repeatedly proposes one change, measures it on RISC-V hardware, keeps measured improvements, and rejects everything else.

The coding agent is the orchestrator. Git is the state machine. Markdown holds research policy. One fixed Python evaluator closes the workstation-to-target measurement loop. lxloop does not implement an orchestration framework around capabilities already supplied by the agent, Git, SSH, and existing `llama.cpp` tools.

## v0 success

An engineer can point lxloop at a dedicated `llama.cpp` worktree, write a focused research direction, reserve the RISC-V target, and leave an agent running experiments overnight. In the morning, the engineer can inspect the kept Git history, the experiment ledger, and detailed logs.

lxloop is human-directed. It does not choose which part of `ggml-cpu` deserves optimization.

## Repository layout

```text
lxloop/
├── program.md             permanent research rules
├── evaluate.py            fixed local evaluation harness
├── config.example.py      machine-specific configuration template
├── .gitignore
├── CONTEXT.md             project vocabulary
└── docs/
    ├── architecture.md    this design
    └── adr/               durable architectural decisions

# Created locally and not committed:
config.py                  local and target commands/paths
task.md                    research direction for the current run
results.tsv                experiment ledger
logs/                      complete evaluator output

# Separate repository/worktree:
llama.cpp/                 experiment subject
```

Only three files form the runtime research system: `program.md`, `evaluate.py`, and `config.example.py`. Deployment, building, testing, benchmark parsing, and reporting are sequential phases inside `evaluate.py`; separate scripts or frameworks would add indirection without creating an independent responsibility.

## Responsibilities

### `program.md`

`program.md` tells a shell-capable coding agent how to conduct research. It defines:

- setup and baseline measurement;
- the one-hypothesis-per-experiment loop;
- allowed and forbidden edits;
- commit, keep, and reject behavior;
- how to invoke and interpret `evaluate.py`;
- the provisional acceptance policy;
- experiment-ledger fields;
- failure recovery and unattended-operation rules;
- how to consume private per-run hardware and environment context from `task.md`.

It is agent-agnostic. v0 is initially validated with Codex, without an agent-specific launcher or adapter.

### `task.md`

`task.md` contains only the engineer's per-run research direction: the function, file, or area to investigate; prefill or decode priority; permitted metric trade-offs; implementation properties to preserve; and useful hypotheses. It is untracked so an engineer can rewrite it frequently without changing permanent policy.

Keeping the direction on disk allows an agent to reread it after context compaction during an overnight run.

### `evaluate.py`

`evaluate.py` is a fixed, standard-library-only local program. In order, it:

1. checks that the subject checkout is a dedicated, clean experiment worktree on an `lxloop/*` branch;
2. rejects tracked or untracked candidate changes outside `ggml/src/ggml-cpu/`;
3. clears the lxloop-owned deploy directory and runs the configured cross-compilation command on the workstation;
4. verifies that the command produced the configured deploy directory;
5. safely replaces the dedicated remote candidate directory;
6. transfers the deploy directory with `rsync`, or with `scp -r` when `rsync` is unavailable locally or remotely;
7. runs the configured correctness command on the target;
8. runs the configured `llama-bench` command on the target;
9. parses benchmark JSON and emits one small, stable summary while preserving complete phase logs.

The evaluator does not decide what code to write or whether a measured result is worth its maintenance cost. Those judgments remain with the coding agent under `program.md`.

## Machine responsibilities

### Workstation

The workstation owns all research logic and mutable source state. It runs the coding agent, Git, `evaluate.py`, the RISC-V cross-toolchain, the local build, result parsing, and logging. The configured build command must produce a deploy directory containing every target binary and runtime library needed by the configured test and benchmark commands.

The engineer supplies an already-working cross-toolchain and sysroot. lxloop records the build command and compiler version with the baseline logs but does not install, containerize, or manage the toolchain.

### RISC-V target

The target does not compile candidates and needs no Python or Internet access. It only receives the deploy directory and executes correctness and benchmark commands over SSH. Models and other large stable inputs may remain at configured target paths.

The v0 environment contract is deliberately small: SSH/SCP access, a shell sufficient to create and replace the dedicated candidate directory, the model and runtime resources named by configuration, and support for executing the deployed binaries. `rsync` is optional.

The target is reserved exclusively for one research run. Reservation is handled by engineers; lxloop does not implement scheduling.

## Configuration

An engineer copies committed `config.example.py` to gitignored `config.py`. Plain Python assignments avoid a parser, schema, or dependency. Configuration supplies at least:

- subject worktree path and upstream baseline ref;
- SSH target and dedicated remote directory;
- local cross-compilation command and deploy-directory path;
- compiler-version command;
- remote correctness and `llama-bench` commands;
- model and benchmark parameters embedded in those commands;
- per-phase timeouts.

The build command is opaque to lxloop. It must recreate `DEPLOY_DIR`; lxloop marks ownership beside a produced directory and clears that owned directory before the next build, so a failed build cannot leave a stale payload for a later experiment. Ownership metadata is not added to the opaque payload, and an existing unmarked directory is never deleted automatically. Changing compiler flags, toolchain files, native versus containerized invocation, or the exact set of staged artifacts must not change the research loop.

Before deleting remote contents for an SCP deployment, `evaluate.py` validates that the configured path is an absolute, non-root, dedicated candidate directory. It removes only that exact path. `rsync` uses deletion semantics so removed local artifacts cannot survive remotely; the SCP fallback recreates the directory before its full upload for the same reason.

## Experiment loop

```text
engineer writes task.md
        |
agent reads rules, task, and scoped code
        |
agent forms one hypothesis
        |
agent edits only ggml-cpu and commits candidate
        |
evaluate.py checks boundary and cross-compiles locally
        |
deploy directory transfers to target
        |
correctness command passes?
     no |             | yes
   reject          llama-bench
                       |
              meaningful improvement?
                  no |       | yes
                reject       keep
                  |            |
             reset commit   new baseline
                  \            /
                   next experiment
```

The first evaluation is always the untouched baseline. It also serves as the end-to-end smoke test for the cross-toolchain, deployment, target runtime, correctness suite, and benchmark command.

## Correctness and benchmarking

Correctness is entirely delegated to the configured remote test command:

```text
exit 0     candidate is valid
non-zero   candidate is rejected
```

lxloop does not interpret numerical tolerances or redefine the test suite's correctness policy.

`llama-bench` is the v0 performance evaluator. The benchmark command requests JSON output and includes both prompt-processing/prefill and text-generation/decode cases. The evaluator records their mean throughput, standard deviation, and available raw samples.

The default acceptance policy is provisional:

- decode is the primary metric unless `task.md` says otherwise;
- the primary mean must improve by more than both approximately 1% and approximately twice reported benchmark noise;
- the secondary metric may not regress by more than approximately 1% unless `task.md` explicitly permits that trade;
- after a keep, the candidate measurement becomes the next baseline.

This policy prevents tiny fluctuations from advancing the branch without pretending that v0 knows the target's final noise model. Repetition count, thresholds, comparison method, primary metric, model, quantization, prompt and generation lengths, thread count, and batch size remain easy to change.

## Git workflow and edit boundary

Each research run uses a dedicated clean worktree and an `lxloop/<tag>` branch created from the configured upstream baseline. The evaluator refuses a dirty starting state. It compares the branch and working-tree state against the run base and permits changes only under:

```text
ggml/src/ggml-cpu/
```

Every meaningful candidate is committed before evaluation. A keep leaves the branch advanced. A reject resets the candidate commit, returning the worktree to the last kept baseline. The resulting branch is the successful research history; reflog and the ledger provide recovery and references for discarded attempts.

This is mechanical protection against accidental or malformed scope violations, not an adversarial security boundary. A deliberately malicious agent with permission to rewrite the evaluator is outside the v0 threat model.

## Experiment records

The agent appends one untracked row per experiment to `results.tsv`:

```text
commit<TAB>prefill_tps<TAB>decode_tps<TAB>status<TAB>description
```

Statuses distinguish `keep`, `discard`, boundary violations, build failures, correctness failures, benchmark failures, transfer failures, crashes, malformed output, and timeouts. The description contains the short hypothesis or failure reason. Full stdout and stderr are stored under `logs/` with timestamp, commit identity, and phase in their names.

The ledger is for overnight inspection, not authoritative state. Git remains authoritative for the current baseline and successful history.

## Failure recovery

- Boundary violations stop before build or deployment.
- Obvious compile mistakes may be fixed and rerun a small number of times; fundamentally broken ideas are logged and rejected.
- Correctness failures, illegal instructions, crashes, malformed benchmark output, and timeouts reject the candidate.
- Transfer or SSH failures are infrastructure failures rather than performance results. The evaluator retries once; repeated failures stop the unattended loop instead of manufacturing decisions against an unavailable target.
- Rejection returns the subject worktree to the last kept commit with Git.

This is intentionally not a general distributed fault-tolerance system.

## Starting an overnight run

1. Reserve the RISC-V target exclusively.
2. Create or select a dedicated clean `llama.cpp` worktree.
3. Copy `config.example.py` to `config.py` and set the paths and commands.
4. Write the focused research direction in `task.md`.
5. Start a shell-capable coding agent with permission to run the configured Git, build, SSH, and transfer commands.
6. Ask it to read `program.md` and `task.md` and set up a new research run.
7. Review and confirm the initial baseline smoke test before leaving the loop unattended.

## Explicit v0 non-goals

v0 does not include multiple agents, board scheduling, a database, dashboard, service, daemon, queue, deployment framework, toolchain manager, benchmark framework, experiment DSL, plugin system, hardware-counter analysis, autonomous target selection, or advanced statistical inference.

The exact compiler and flags, thermal and DVFS behavior, benchmark noise model, correctness suite, model, quantization, benchmark parameters, and target-specific capabilities remain environment knowledge rather than new infrastructure. Identifying hardware and organization details belong only in the gitignored `task.md`, never in tracked lxloop files.

Future changes should land in one of three existing seams:

- policy or agent behavior in `program.md`;
- machine-specific commands and paths in `config.py`;
- fixed evaluation mechanics behind `evaluate.py`'s stable command and summary contract.

A new file, service, or abstraction is justified only when it gains a genuinely independent responsibility that cannot fit cleanly in one of those seams.
