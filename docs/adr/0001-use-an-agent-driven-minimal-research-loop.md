# Use an agent-driven minimal research loop

lxloop uses a shell-capable coding agent as the orchestrator, Git as the experiment state machine, Markdown as research policy, and one fixed Python evaluator as the measurement boundary. We deliberately reject a workflow engine, database, service architecture, and separate build/deploy/test scripts because these duplicate capabilities already provided by the agent, Git, SSH, and command-line tools; the trade-off is that lxloop is a human-directed research tool rather than a general autonomous performance-engineering platform.
