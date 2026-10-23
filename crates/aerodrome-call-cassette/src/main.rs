use aerodrome_call_cassette::{prepare, read_request, transport::HttpsRpc};
use std::path::Path;
fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 6
        || args[0] != "--request"
        || args[2] != "--request-sha256"
        || args[4] != "--output"
    {
        return Err("usage: aerodrome-call-cassette --request REQUEST.json --request-sha256 SHA256 --output NEW_DIRECTORY; BASE_ARCHIVE_RPC_URL supplies HTTPS credentials privately".into());
    }
    let (request, bytes) = read_request(Path::new(&args[1]), &args[3])?;
    let mut rpc = HttpsRpc::new(
        std::env::var("BASE_ARCHIVE_RPC_URL").map_err(|_| "BASE_ARCHIVE_RPC_URL is required")?,
    )?;
    prepare(&request, &bytes, Path::new(&args[5]), &mut rpc)?;
    println!("independent cassette complete; supplied inventory only, oracle misses remain fatal");
    Ok(())
}
fn main() {
    if let Err(reason) = run() {
        eprintln!("cassette preparation refused: {reason}");
        std::process::exit(4);
    }
}
