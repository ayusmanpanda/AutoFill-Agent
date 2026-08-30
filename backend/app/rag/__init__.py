"""Phase 4 — RAG field mapping.

Match the fields perceived on a page to entries in the user's profile:
  - flatten.py   turn the nested Profile into flat, retrievable facts
  - resolver.py  deterministic field -> fact matching (autocomplete + labels), no LLM
  - mapper.py    LLM fallback that matches leftover fields to profile KEYS only
  - plan.py      orchestrator that builds a per-field fill plan
  - router.py    POST /fill/plan

Privacy invariants (enforced structurally):
  * SECRET fields are never resolved, never sent to the model, never given a value.
  * The LLM matcher receives field labels + profile KEYS only — never profile values.
  * Resolved values are returned only to the local extension (loopback), never to the cloud.
"""
