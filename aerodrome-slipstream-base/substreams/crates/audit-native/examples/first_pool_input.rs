//! Bounded fixture only: fresh first-pool carry + retained raw ERC20 returns.
//! Not a general seeded-block capture or a live WASM output.
#[path = "../tests/support/mod.rs"]
mod support;
use prost::Message;
use std::{fs::OpenOptions, io::Write};
fn main() {
    let path = std::env::args().nth(1).expect("new output protobuf path");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.write_all(&support::first_pool().encode_to_vec())
        .unwrap();
    file.sync_all().unwrap();
}
