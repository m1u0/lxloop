# Experiment in an external dedicated worktree

lxloop remains independent from `llama.cpp` and operates on a dedicated, initially clean experiment worktree rather than an engineer's normal checkout. Candidate commits may change only `ggml/src/ggml-cpu/`, and the fixed evaluator rejects any broader diff before measurement; this keeps rollback and successful history in ordinary Git while providing mechanical protection against accidental scope violations without claiming to be an adversarial sandbox.
