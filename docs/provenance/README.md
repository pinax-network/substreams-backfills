# Provenance records

This directory holds immutable, machine-readable records for imported source,
deployment targets, and parity inputs. Verifiers consume the JSON files by
their repository-relative paths and fail closed when a recorded file, digest,
or identity no longer matches.

Update a provenance record only as part of a reviewed source or target change.
Do not rewrite a record merely to match unexpected local output.
