# Gemini outage and quota

1. Confirm admin health diagnostics without inspecting prompts or patient text.
2. Preserve global logical-call rotation; do not reset the Redis counter to force a model.
3. Open circuit breakers independently for the failing allowed model. Fail over only to the other allowlisted ID.
4. If both models fail, keep emergency screening active, disable model-led routing and return deterministic staff handoff.
5. For embedding outage, degrade primary to the text fallback index and then lexical-only retrieval. Never cross vector spaces.
6. After recovery, use half-open probes, verify four exact model capabilities, and review PHI-safe aggregate error metrics.
