# Eligibility

The resolved-input adapter is eligible only for host-side diagnostic testing.
It deterministically validates a complete `NpmSourceBlock`, resolved
observations, exact call scope, and joint-reducer delegation for mainnet and
Base starting at blocks 12,369,651 and 1,371,713.

It is not eligible for a backfill or production checkpoint. No integrated host
engine supplies observations, later Graph execution after a fatal projection
is not modeled, required-observation completeness is not certified, and
continuity/physical/PoI parity remain open.
