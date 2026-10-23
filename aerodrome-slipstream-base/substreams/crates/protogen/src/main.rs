use sha2::{Digest, Sha256};
use std::{error::Error, fs, path::Path};
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.iter().any(|x| x != "--check") {
        return Err("usage: aerodrome-extractor-protogen [--check]".into());
    }
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let temp = tempfile::tempdir()?;
    let proto = root.join("proto");
    prost_build::Config::new()
        .out_dir(temp.path())
        .compile_protos(
            &[
                proto.join("pinax/aerodrome/slipstream/base/v1/extractor.proto"),
                proto.join("pinax/aerodrome/slipstream/base/internal/v1/internal.proto"),
            ],
            &[proto],
        )?;
    for file in [
        "pinax.aerodrome.slipstream.base.v1.rs",
        "pinax.aerodrome.slipstream.base.internal.v1.rs",
    ] {
        let generated = fs::read(temp.path().join(file))?;
        let target = root.join("crates/pb/src").join(file);
        if args.is_empty() {
            fs::write(target, generated)?;
        } else if fs::read(&target)? != generated {
            return Err(format!("generated protobuf drift: {}", target.display()).into());
        }
    }
    let pin: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("crates/pb/ethereum-bindings.json"))?)?;
    let bytes = fs::read(root.join("crates/pb/src/sf.ethereum.type.v2.rs"))?;
    if format!("{:x}", Sha256::digest(bytes))
        != pin["sha256"]
            .as_str()
            .ok_or("missing Ethereum bindings hash")?
    {
        return Err("vendored Ethereum protobuf drift".into());
    }
    println!("public/internal prost bindings and pinned Ethereum bindings verified");
    Ok(())
}
