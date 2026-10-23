//! Local development CLI; the staged producer has a separately gated entry.
fn main() {
    if let Err(e) =
        aerodrome_slipstream_reducer::cli::run_development(std::env::args().skip(1).collect())
    {
        eprintln!("aerodrome-durable-fixture refused: {e}");
        std::process::exit(4);
    }
}
