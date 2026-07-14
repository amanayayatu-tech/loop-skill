# Upstream Codex App process-reaping report

## Symptom

An interrupted strict-stdin tool command can leave a fixed-byte reader and its
Python child waiting indefinitely. When those processes remain children of the
Codex app-server, task reads, automation controls, or cleanup can become
unresponsive until the App is restarted.

## Reproduction shape

1. Start a tool command that feeds a declared byte count into a child runtime.
2. Deliver only a prefix and leave the stdin/session open.
3. Interrupt or lose the producer before the declared count is reached.
4. Observe that the child command remains and control-plane calls may time out.

Do not attach raw user payloads, rollout databases, tokens, generated Packs, or
canonical project state to an upstream report. A synthetic partial JSON frame
is sufficient.

## Recommended app-server changes

- Start every tool command in its own process group.
- Propagate cancellation to the group: `TERM`, bounded wait, then `KILL`,
  followed by `waitpid`/equivalent reaping.
- Close producer stdin on interruption and make session ownership explicit.
- Add a watchdog for commands whose tool session outlives its request.
- Provide automation emergency-pause through a control channel that does not
  depend on the task-execution queue being healthy.

## Repository boundary

loop-skill v3.2.1 bounds its own stdin reader and removes fixed-byte/pipeline
instructions from newly generated Packs. That reduces the trigger and makes the
runtime fail closed. It does not change Codex app-server cancellation, process
groups, child reaping, or automation control-plane architecture.
