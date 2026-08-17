# LXLoop

> **Note:** LXLoop is inspired by Andrej Karpathy’s [autoresearch](https://github.com/karpathy/autoresearch).

LXLoop is a small, human-directed research tool for finding CPU inference-performance improvements in `llama.cpp`.

You choose a focused research direction. A shell-capable coding agent then runs a sequence of experiments against a dedicated `llama.cpp` worktree, testing one optimization hypothesis at a time and measuring every candidate on real RISC-V hardware.

## How it works

```text
Human defines a research direction
              ↓
Agent proposes and commits one change
              ↓
LXLoop builds and deploys it
              ↓
Target runs correctness tests and llama-bench
              ↓
Agent keeps or discards the candidate
              ↓
Repeat from the best known baseline
```

The coding agent orchestrates the research loop. Git records candidate state and successful history, while `evaluate.py` provides a fixed path from committed source to target measurements.

Each experiment changes only `ggml/src/ggml-cpu/`. The agent commits the candidate before evaluation, and the evaluator mechanically rejects dirty worktrees or changes outside that boundary. Candidates must pass the configured correctness command before they are benchmarked.

The workstation holds all source and Git state, cross-compiles candidates, deploys them, and stores the results. The RISC-V target only runs the deployed correctness and benchmark commands; it needs no compiler, Python, or internet access.

## Requirements

You need:

- a local `llama.cpp` repository;
- a dedicated linked worktree on an `lxloop/*` branch;
- a working RISC-V cross-toolchain and sysroot;
- SSH and SCP access to the target;
- configured correctness and `llama-bench` commands;
- Python 3;
- a shell-capable coding agent.

`rsync` is optional. The target should be reserved exclusively for the research run so measurements are not affected by other workloads.

## Getting started

### 1. Create a dedicated worktree

Choose a baseline, resolve it to its full commit ID, and create an `lxloop/*` branch in a separate worktree:

```bash
cd /path/to/llama.cpp

git worktree add \
  -b lxloop/my-research-run \
  /path/to/llama.cpp-lxloop \
  <full-baseline-commit-id>
```

Do not use your normal development checkout. The worktree must start clean and descend from the configured baseline.

### 2. Configure LXLoop

Copy the example configuration:

```bash
cp config.example.py config.py
```

Edit `config.py` with:

- the dedicated worktree path and full baseline commit ID;
- the SSH target and remote deployment directory;
- the cross-compilation command and resulting deploy directory;
- a command that identifies the cross-compiler;
- the remote correctness and benchmark commands;
- suitable timeouts for each phase.

The build command must produce one complete deploy directory containing every binary and runtime library needed by the target.

> **Warning:** `REMOTE_DIR` is replaced during deployment. Use a dedicated directory containing no data you need to preserve.

### 3. Define the research direction

Edit `task.md` with the specific problem you want the agent to investigate. Include the primary metric, permitted trade-offs, implementation constraints, and any hardware or environment facts relevant to the work.

Keep the direction bounded. LXLoop is designed to pursue an engineer-chosen question, not to choose its own optimization target.

Both `config.py` and `task.md` remain local and are ignored by Git, so they can contain machine-specific or private run context.

### 4. Start with the untouched baseline

Ask your coding agent to read the permanent research rules in `program.md` and the current direction in `task.md`:

```text
Read program.md and task.md completely. Set up a new research run, run and
record the untouched baseline, then stop so I can review it before continuing.
```

The first evaluation is also an end-to-end smoke test of the worktree, cross-toolchain, deployment payload, target runtime, correctness command, and benchmark command. Review it before allowing the experiment loop to run unattended.

## Evaluation results

The evaluator can be run from the LXLoop repository with:

```bash
python3 evaluate.py
```

A successful evaluation produces a concise summary:

```text
---
status: ok
commit: b4e2f1a
prefill_tps: 142.310 ± 1.850 (n=5)
decode_tps: 9.874 ± 0.041 (n=5)
log: logs/20260817T031412Z_b4e2f1a
```

The configured correctness command is authoritative: a candidate is benchmarked only if that command succeeds. The benchmark reports both prefill and decode throughput, leaving the agent to judge the result according to the research direction in `task.md` and the permanent rules in `program.md`.

A kept candidate becomes the next baseline and remains in the branch’s Git history. A rejected candidate is recorded before the agent returns to the last kept commit.

The agent maintains a compact experiment ledger in `results.tsv`, while complete build, deployment, correctness, and benchmark output is stored under `logs/`. Git remains the authoritative record of successful improvements.
