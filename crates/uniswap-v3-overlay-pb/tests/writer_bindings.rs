//! Pins the extracted `uniswap.writer.v1` bindings to the writer contract.
//!
//! `build.rs` reconstructs the bindings from the added lines of
//! `uniswap-v3/writer-runtime/runtime.patch`. The writer runtime contract
//! already records the SHA-256 of that file as it appears in a materialized
//! tree, so comparing against it proves the reconstruction is the same artifact
//! the verifiers and materialize scripts pin, with no second copy to drift.

use std::fs;
use std::path::PathBuf;

use sha2::{Digest, Sha256};

const CONTRACT: &str = "../../uniswap-v3/writer-runtime/contract-v1.json";
const ARTIFACT: &str = "src/pb/uniswap.writer.v1.rs";

#[test]
fn extracted_bindings_match_the_pinned_materialized_artifact() {
    let contract = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(CONTRACT);
    let contract: serde_json::Value =
        serde_json::from_slice(&fs::read(&contract).expect("the writer contract is readable"))
            .expect("the writer contract is JSON");
    let expected = contract["materialized_runtime_artifacts"][ARTIFACT]
        .as_str()
        .expect("the writer contract pins the bindings digest");

    let extracted = fs::read(PathBuf::from(env!("OUT_DIR")).join("uniswap.writer.v1.rs"))
        .expect("build.rs wrote the extracted bindings");

    assert_eq!(
        hex(&Sha256::digest(&extracted)),
        expected,
        "extracted {ARTIFACT} drifted"
    );
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
