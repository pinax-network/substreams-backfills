fn main() {
    if let Err(failure) =
        aerodrome_slipstream_reducer::producer_cli::run(std::env::args().skip(1).collect())
    {
        eprintln!("producer: {}", failure.message);
        std::process::exit(i32::from(failure.exit_code));
    }
}
