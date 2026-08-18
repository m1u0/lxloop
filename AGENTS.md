## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `m1u0/lxloop`. See `docs/agents/issue-tracker.md`.

### Triage labels

The canonical default triage labels are used unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain-doc layout. See `docs/agents/domain.md`.

### README translations

Keep `README.md` and `README.zh.md` structurally aligned. Whenever either README changes, update its counterpart in the same change.

## Cursor Cloud specific instructions

lxloop is a single, zero-dependency **Python 3 (stdlib only)** project. There is no
package manager, lockfile, build step, linter, or CI config. The startup update
script only verifies the interpreter (`python3 --version`); no install step is
needed. The runtime pieces are `evaluate.py` (the fixed evaluation harness),
`program.md` (agent research rules), and `config.example.py`. See
`docs/architecture.md` for the design.

- Tests: `python3 -m unittest test_evaluate -v` from the repo root. The suite spawns
  real subprocesses and exercises timeout/retry paths, so it takes ~90s; that is
  expected, not a hang.
- Static check (no linter is configured): `python3 -m py_compile evaluate.py test_evaluate.py config.example.py`.
- Running the app: `python3 evaluate.py` needs a gitignored `config.py` (copy from
  `config.example.py`). A real run also needs external, engineer-supplied
  infrastructure — a dedicated `llama.cpp` git worktree, a RISC-V cross-toolchain,
  and a live RISC-V SSH target with a model file — none of which exist in a generic
  cloud sandbox, so a real end-to-end run is not possible here.
- Non-obvious `evaluate.py` preconditions (all enforced before any build/deploy):
  `config.py` must sit next to `evaluate.py` (repo root); `LLAMA_DIR` must be a
  *clean, linked* git worktree on an `lxloop/*` branch; `UPSTREAM_REF` must be a full
  immutable commit id that `HEAD` descends from; only changes under
  `ggml/src/ggml-cpu/` are allowed (anything else is a `boundary_violation`).
- Hardware-free smoke test: you can drive the real `evaluate.py` end-to-end by
  faking `ssh`/`rsync`/`scp` and the cross-compiler on `PATH` and pointing `config.py`
  at a local dedicated `lxloop/*` worktree; the fake `ssh` must echo the
  `__LXLOOP_REMOTE_EXIT_<hex>__:<status>` sentinel on stderr and print `llama-bench`
  JSON (prefill + decode rows) for the bench phase. `test_evaluate.py` shows the
  exact fakes to mirror.
