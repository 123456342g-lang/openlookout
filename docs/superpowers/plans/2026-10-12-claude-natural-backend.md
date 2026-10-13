# Claude natural backend (controlled host bridge)

## Goal

Restore the VISTA Claude Code backend as the primary model transport so the
model can naturally choose quiet, conversation, offers, or background work
without scene/task allowlists. VISTA remains the owner of visual history,
WORKING/GUIDE, Agenda, result verification, and lifecycle.

## Safety contract

* Claude Code runs in the Docker player by default (`mode=container`).
* Host capabilities are exposed only through the authenticated MCP bridge and
  the runtime's registered tool interface. Unknown tool names are rejected;
  no unrestricted shell is added.
* `host_mode=True` is a legacy escape hatch and is disabled unless an operator
  explicitly sets `OPENLOOKOUT_ALLOW_UNSAFE_HOST_MODE=1` for an isolated test.
  It must never be used by the resident brain or treated as a sandbox.
* If Docker/preflight cannot start, the direct Anthropic-compatible path is an
  explicit `direct-fallback` mode (no sandbox, no claim of host isolation).

## Implementation steps

1. Remove the unreachable early return in `brain.build()` and attempt the
   Docker Claude backend first.
2. Keep the direct backend only as a clearly labelled availability fallback.
3. Route all host actions through MCP/tool registration and Agenda claim/record
   paths; preserve undo journals and independent verification.
4. Add regression tests for backend selection, tool allowlisting, output modes,
   background `next_step`, fallback labelling, and host-mode gating.
5. Run focused desktop tests, then the complete desktop/proactive suite.

## Verification evidence required

* Synthetic traces cover repeated work, error, and blockage while a normal
  trace remains quiet; no scene branch is introduced.
* Tool calls cannot execute an unregistered name; mutating calls have a journal
  entry and a verification result before completion is reported.
* Logs/UI expose `container` versus `direct-fallback`; no mode is silently
  presented as sandboxed.

