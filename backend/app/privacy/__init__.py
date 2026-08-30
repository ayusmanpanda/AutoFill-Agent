"""Privacy subpackage: sensitivity classifier, egress scrub, and the LLM guard.

This is the safety layer that enforces the project's hard rule — secrets are
never stored, never embedded, and never sent to the cloud LLM — and scrubs PII
from anything that does leave the machine.
"""
