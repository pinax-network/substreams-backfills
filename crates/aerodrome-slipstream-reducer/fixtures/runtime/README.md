# Synthetic runtime admission fixture

`synthetic-extractor.spkg` is a 236-byte test package with an empty WebAssembly
module, one map declaration and no executable mapping. It cannot extract blocks.
It is used only for bundle identity and CLI refusal tests. The adjacent identity
was independently encoded with Python's standard SHA-1 and SHA-256 functions;
the unit test compares every byte against the Rust fixture builder.

The module signature algorithm is the map/store subset of upstream Substreams
v1.18.4 `manifest/signature.go`, with ancestor order from `manifest/graph.go`.
The verifier rejects unsupported executable fields, network overrides, missing
inputs and cycles. Go and prost differ in oneof field serialization order;
protobuf field order is accepted without ignoring unknown executable fields.

A separate local check used the actual development extractor captured in M2:
package SHA-256 `7df52603a63b261ed27faf5f27a0b178b2004e156829c6c0edc1b3d605b4ff59`,
module `map_extractor_block`, hash
`5b880ad140246ec1bc3eefdd64c287769deac4f8`. Those pins came from the independently
retained Substreams CLI output; the new Rust verifier matched them. This check
establishes package identity parity, not image, release or production eligibility.
