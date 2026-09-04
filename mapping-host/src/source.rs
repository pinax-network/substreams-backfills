//! Where blocks come from: committed fixtures, or a live Firehose stream.
//!
//! The fixture reader is what `mapping-host` has always used — four sampled
//! mainnet blocks committed as release assets. Four sampled points cannot
//! exercise `handleSwap`, `handleBurn`, `handleFlash` or a successful
//! `handleCollect`, because the pools those events touch were created in blocks
//! the sample skips, and they leave the store and the PoI chain discontinuous.
//! A contiguous range is ~1.2 GB of blocks for the parity window alone, which is
//! far too much to commit, so the live source streams them at run time instead
//! and CI stays hermetic on the fixtures.
//!
//! ## No new dependency
//!
//! `graph` already builds the `sf.firehose.v2` protos and ships a client:
//! [`graph::firehose::FirehoseEndpoint`] wraps a lazily connected tonic channel
//! with a bearer-token interceptor, and `stream_blocks` opens
//! `sf.firehose.v2.Stream/Blocks`. So there is no build script here, no second
//! copy of the Firehose protos, and nothing added to `Cargo.lock`. The tonic
//! stream is mapped to `anyhow::Error` and boxed at construction; the one tonic
//! type this module names is `Status`, and only to read its code when deciding
//! whether a failure is worth reconnecting after.
//!
//! ## Fail closed
//!
//! A replay whose blocks are wrong is worse than one that stops. Every source is
//! wrapped in a [`CheckedSource`], which refuses a duplicate, a decrease, a gap
//! (in contiguous mode), a block outside the requested range, and a stream that
//! ends early. The live source additionally refuses a response that is not
//! `STEP_FINAL`, carries no block, carries something other than an
//! `sf.ethereum.type.v2.Block`, decodes as more than one message, or whose block
//! number is not the one that position in the range calls for.
//!
//! The two-message check is [`crate::block::split_messages`], the same detector
//! that guards the committed fixtures: prost merges concatenated messages rather
//! than rejecting them, which is how release `block-fixtures-v1` shipped blocks
//! that claimed to be `N+1` while carrying `N`'s logs.
//!
//! ## Surviving a stream that dies
//!
//! A twenty-hour range does not arrive over one TCP connection. Measured against
//! a production endpoint, `mapping-host` managed 6,317 blocks in 19m53s before
//! the stream failed with `error reading a body from connection` / `stream error
//! received: unspecific protocol error detected`. That is a transport failure,
//! not a statement about the blocks, so [`ReconnectingSource`] re-opens the
//! stream from the next block it still needs and carries on.
//!
//! Reconnection is deliberately *inside* [`CheckedSource`], not outside it: a
//! reconnect that came back one block short, one block ahead, or on a different
//! fork is refused by exactly the same checks that guard an unbroken stream, and
//! the parent-hash chain is checked straight across the seam. There is no code
//! path in which a reconnect is trusted.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use async_trait::async_trait;
use graph::blockchain::Block as _;
use graph::components::metrics::MetricsRegistry;
use graph::endpoint::EndpointMetrics;
use graph::firehose::{self, ConnectionHeaders, FirehoseEndpoint, ForkStep, SubgraphLimit};
use graph::futures03::stream::{BoxStream, StreamExt as _, TryStreamExt as _};
use graph::prelude::prost::Message as _;
use graph::prelude::{o, slog, tonic, Logger};
use graph_chain_ethereum::chain::BlockFinality;
use graph_chain_ethereum::codec;

use crate::block;

/// The protobuf full name every Firehose response on an Ethereum chain must
/// carry. `Any.type_url` is conventionally `type.googleapis.com/<full name>`,
/// but only the suffix is meaningful.
pub const ETHEREUM_BLOCK_TYPE: &str = "sf.ethereum.type.v2.Block";

/// The environment variable naming the Firehose endpoint, as `host:port`.
pub const ENDPOINT_VAR: &str = "FIREHOSE_ENDPOINT";

/// Bearer token variables, in the order they are consulted.
pub const TOKEN_VARS: &[&str] = &["FIREHOSE_API_TOKEN", "SUBSTREAMS_API_TOKEN"];

/// A stream of blocks in ascending order.
#[async_trait]
pub trait BlockSource: Send {
    /// The next block, or `None` once the source is exhausted.
    async fn next_block(&mut self) -> Result<Option<BlockFinality>>;

    /// A short description for error messages and the run header.
    fn describe(&self) -> String;
}

/// What ordering a [`CheckedSource`] enforces.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ordering {
    /// Strictly increasing; gaps are allowed. This is what the four sampled
    /// fixtures need, and it is deliberately *not* what a live range gets.
    Sampled,
    /// Strictly increasing by exactly one, from `start` up to but excluding
    /// `stop`. A gap, a repeat, a regression or an early end is an error.
    Contiguous { start: i32, stop: i32 },
}

/// Enforces block ordering over any [`BlockSource`].
///
/// This is where "fail closed on a gap, a fork, or a duplicate" actually lives,
/// which is why it is generic: the fake source in the tests exercises exactly
/// the code path the live source runs behind.
pub struct CheckedSource<S> {
    inner: S,
    ordering: Ordering,
    previous: Option<i32>,
    /// The previous block's own hash, `0x`-prefixed. Only meaningful in
    /// contiguous mode, where the next block must name it as its parent.
    previous_hash: Option<String>,
    finished: bool,
}

impl<S: BlockSource> CheckedSource<S> {
    pub fn new(inner: S, ordering: Ordering) -> Self {
        CheckedSource {
            inner,
            ordering,
            previous: None,
            previous_hash: None,
            finished: false,
        }
    }

    fn check(&mut self, block: &BlockFinality) -> Result<()> {
        let identity = crate::block::identify(block);
        let number = identity.number;
        if let Some(previous) = self.previous {
            if number == previous {
                bail!("block {number} was produced twice; a source must not repeat a block");
            }
            if number < previous {
                bail!(
                    "block {number} follows block {previous}; a source must produce blocks in \
                     strictly ascending order"
                );
            }
        }

        if let Ordering::Contiguous { start, stop } = self.ordering {
            if number < start || number >= stop {
                bail!(
                    "block {number} is outside the requested range [{start}, {stop}); the source \
                     produced a block that was not asked for"
                );
            }
            let expected = self.previous.map_or(start, |previous| previous + 1);
            if number != expected {
                bail!(
                    "gap in the block stream: expected block {expected}, got {number}. A \
                     contiguous replay cannot skip a block, because the store and the PoI chain \
                     would silently diverge"
                );
            }
            // The block numbers alone cannot see a fork: two chains have the
            // same heights. In a contiguous range every block is its
            // predecessor's child, so the chain is checked link by link — which
            // is what makes a reconnect safe, because the first block after a
            // reconnect is checked by exactly this line.
            if let (Some(previous_hash), Some(parent)) = (
                self.previous_hash.as_deref(),
                identity.parent_hash.as_deref(),
            ) {
                if !parent.eq_ignore_ascii_case(previous_hash) {
                    bail!(
                        "block {number} names parent {parent}, but block {} in this same stream \
                         has hash {previous_hash}: the stream changed chains mid-range, and \
                         folding two histories into one store would corrupt it silently",
                        number - 1
                    );
                }
            }
        }

        self.previous = Some(number);
        self.previous_hash = Some(identity.hash);
        Ok(())
    }

    fn check_end(&self) -> Result<()> {
        let Ordering::Contiguous { start, stop } = self.ordering else {
            return Ok(());
        };
        match self.previous {
            Some(previous) if previous == stop - 1 => Ok(()),
            Some(previous) => bail!(
                "the block stream ended at block {previous}, but the requested range \
                 [{start}, {stop}) needs block {} last",
                stop - 1
            ),
            None => bail!(
                "the block stream produced no blocks at all for the requested range \
                 [{start}, {stop})"
            ),
        }
    }
}

#[async_trait]
impl<S: BlockSource> BlockSource for CheckedSource<S> {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        if self.finished {
            return Ok(None);
        }
        match self.inner.next_block().await? {
            Some(block) => {
                self.check(&block)?;
                Ok(Some(block))
            }
            None => {
                self.finished = true;
                self.check_end()?;
                Ok(None)
            }
        }
    }

    fn describe(&self) -> String {
        self.inner.describe()
    }
}

/// The committed `.pb` fixtures, replayed in ascending block order.
///
/// Blocks are decoded up front, because the block number is only knowable after
/// decoding and the ordering has to be established before the first one is
/// replayed. That is exactly what this crate has always done; a fixture set is
/// a handful of files.
pub struct FixtureSource {
    /// Ascending by block number; drained from the front.
    blocks: std::collections::VecDeque<(i32, PathBuf, BlockFinality)>,
    described: String,
}

impl FixtureSource {
    /// Load every file, optionally keep only the named block numbers, and sort.
    ///
    /// A block number requested through `only` that no file holds is an error,
    /// and so is the same block number appearing in two files.
    pub fn load(paths: &[PathBuf], only: &[i32]) -> Result<Self> {
        let mut blocks: Vec<(i32, PathBuf, BlockFinality)> = Vec::with_capacity(paths.len());
        for path in paths {
            let block = block::load_block(path)?;
            blocks.push((block.number(), path.clone(), block));
        }
        if !only.is_empty() {
            blocks.retain(|(number, _, _)| only.contains(number));
            for wanted in only {
                if !blocks.iter().any(|(number, _, _)| number == wanted) {
                    bail!("block {wanted} was requested with --only but is not in --blocks");
                }
            }
        }
        blocks.sort_by_key(|(number, _, _)| *number);
        for pair in blocks.windows(2) {
            if pair[0].0 == pair[1].0 {
                bail!("block {} appears in more than one fixture", pair[0].0);
            }
        }
        let described = format!("{} block fixture(s)", blocks.len());
        Ok(FixtureSource {
            blocks: blocks.into(),
            described,
        })
    }
}

#[async_trait]
impl BlockSource for FixtureSource {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        Ok(self.blocks.pop_front().map(|(_, _, block)| block))
    }

    fn describe(&self) -> String {
        self.described.clone()
    }
}

/// A validated, credential-free Firehose endpoint.
///
/// The endpoint is a bare `host:port`, or the same with an explicit `https://`.
/// Anything that could smuggle a credential — userinfo, a query string, a
/// fragment — is refused rather than stripped, so a token can only ever arrive
/// through the environment variable that is meant to carry it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FirehoseTarget {
    uri: String,
}

impl FirehoseTarget {
    pub fn parse(raw: &str) -> Result<Self> {
        let raw = raw.trim();
        if raw.is_empty() {
            bail!("{ENDPOINT_VAR} is empty; it must name a Firehose endpoint as `host:port`");
        }
        if raw.chars().any(char::is_whitespace) {
            bail!("the Firehose endpoint contains whitespace");
        }

        let rest = match raw.split_once("://") {
            None => raw,
            Some(("https", rest)) => rest,
            Some((scheme, _)) => bail!(
                "the Firehose endpoint uses scheme `{scheme}`; only `https` (or a bare \
                 `host:port`, which means https) is accepted, because the stream must be \
                 encrypted"
            ),
        };

        if rest.contains('@') {
            bail!(
                "the Firehose endpoint contains userinfo (`@`); credentials must come from \
                 ${} or ${}, never from the endpoint string",
                TOKEN_VARS[0],
                TOKEN_VARS[1]
            );
        }
        if rest.contains('?') || rest.contains('#') {
            bail!(
                "the Firehose endpoint contains a query string or fragment; a Firehose target is \
                 `host:port` and nothing else, and either could carry a token"
            );
        }
        let authority = match rest.split_once('/') {
            None => rest,
            Some((authority, "")) => authority,
            Some((_, path)) => bail!(
                "the Firehose endpoint has a path (`/{path}`); a Firehose target is `host:port` \
                 and nothing else"
            ),
        };

        let (host, port) = authority
            .rsplit_once(':')
            .ok_or_else(|| anyhow!("the Firehose endpoint has no port; use `host:port`"))?;
        if host.is_empty() {
            bail!("the Firehose endpoint has no host");
        }
        port.parse::<u16>()
            .with_context(|| format!("the Firehose endpoint port `{port}` is not a port number"))?;

        Ok(FirehoseTarget {
            uri: format!("https://{authority}"),
        })
    }

    /// Read the endpoint from [`ENDPOINT_VAR`].
    pub fn from_env() -> Result<Self> {
        let raw = std::env::var(ENDPOINT_VAR).map_err(|_| {
            anyhow!(
                "a live run needs ${ENDPOINT_VAR} (for example `eth.firehose.pinax.network:443`); \
                 no endpoint is compiled in"
            )
        })?;
        Self::parse(&raw)
    }

    /// The `https://host:port` a tonic channel is built from.
    pub fn uri(&self) -> &str {
        &self.uri
    }

    /// `host:port`, which is what a log line should show.
    pub fn authority(&self) -> &str {
        self.uri.trim_start_matches("https://")
    }
}

/// Read the bearer token from the environment, if one is set.
///
/// The value is never returned in an error message, printed, or written to any
/// artifact.
pub fn token_from_env() -> Result<Option<String>> {
    for var in TOKEN_VARS {
        let Ok(raw) = std::env::var(var) else {
            continue;
        };
        if let Some(token) = validate_token(var, &raw)? {
            return Ok(Some(token));
        }
    }
    Ok(None)
}

/// Trim a token and refuse one a gRPC metadata value cannot carry.
///
/// `FirehoseEndpoint::new` *panics* on a token that is not printable ASCII, so
/// it is checked here first. The error names the variable and never the value.
/// An all-whitespace value is treated as absent, so an exported-but-empty
/// variable falls through to the next one rather than authenticating with "".
pub fn validate_token(var: &str, raw: &str) -> Result<Option<String>> {
    let token = raw.trim();
    if token.is_empty() {
        return Ok(None);
    }
    if !token.is_ascii() || token.chars().any(|c| c.is_ascii_control()) {
        bail!("${var} is not a valid bearer token; it must be printable ASCII");
    }
    Ok(Some(token.to_string()))
}

/// A half-open `[start, stop)` range streamed from a Firehose endpoint.
pub struct FirehoseSource {
    stream: BoxStream<'static, Result<firehose::Response>>,
    /// Kept alive for the life of the stream; the channel lives here.
    _endpoint: Arc<FirehoseEndpoint>,
    start: i32,
    stop: i32,
    /// The number the *next* response must carry.
    expected: i32,
    described: String,
}

impl FirehoseSource {
    /// Open `sf.firehose.v2.Stream/Blocks` for `[start, stop)`.
    ///
    /// `final_blocks_only` is set, so the endpoint only sends `STEP_FINAL`
    /// blocks and there is no undo stream to reconcile. The Firehose
    /// `stop_block_num` is *inclusive*, so it is `stop - 1` here.
    pub async fn connect(
        target: &FirehoseTarget,
        token: Option<String>,
        start: i32,
        stop: i32,
    ) -> Result<Self> {
        if stop <= start {
            bail!("the requested range [{start}, {stop}) is empty");
        }
        if start < 0 {
            bail!("block numbers are non-negative; got {start}");
        }

        // `rustls` 0.23 panics on the first TLS handshake unless a crypto
        // provider is installed, because this dependency graph links both
        // `aws_lc_rs` (through alloy) and `ring` (through object_store and
        // reqwest). graph-node's own binaries call this from `main`; it is
        // called here instead so a hermetic fixture run installs nothing.
        graph::tls::install_default_crypto_provider();

        let logger = Logger::root(slog::Discard, o!());
        let metrics = Arc::new(EndpointMetrics::new(
            logger,
            &[target.authority()],
            Arc::new(MetricsRegistry::mock()),
        ));

        let endpoint = Arc::new(FirehoseEndpoint::new(
            target.authority(),
            target.uri(),
            token,
            std::env::var("FIREHOSE_API_KEY")
                .ok()
                .map(|key| validate_token("FIREHOSE_API_KEY", &key))
                .transpose()?
                .flatten(),
            // No transforms are sent, so filters stay off: we want every log in
            // every block, exactly as `parse_log_triggers` would see it.
            false,
            true,
            SubgraphLimit::Unlimited,
            metrics,
        ));

        let request = firehose::Request {
            start_block_num: i64::from(start),
            cursor: String::new(),
            stop_block_num: u64::try_from(stop - 1).expect("stop > start >= 0"),
            final_blocks_only: true,
            transforms: Vec::new(),
        };

        let stream = endpoint
            .clone()
            .stream_blocks(request, &ConnectionHeaders::new())
            .await
            .map_err(classify)
            .with_context(|| {
                format!(
                    "opening sf.firehose.v2.Stream/Blocks on {} for [{start}, {stop})",
                    target.authority()
                )
            })?;

        // Classified here rather than at the call site, because this is the only
        // place the raw `tonic::Status` still exists: a status that means "the
        // connection broke" is marked retryable, and one that means "the server
        // will not serve this request" is not.
        let stream = stream
            .map_err(|status| classify(anyhow::Error::new(status)))
            .boxed();

        Ok(FirehoseSource {
            stream,
            _endpoint: endpoint,
            start,
            stop,
            expected: start,
            described: format!("Firehose {} blocks [{start}, {stop})", target.authority()),
        })
    }

    /// The half-open range this source was opened for.
    pub fn range(&self) -> (i32, i32) {
        (self.start, self.stop)
    }
}

#[async_trait]
impl BlockSource for FirehoseSource {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        if self.expected >= self.stop {
            return Ok(None);
        }
        let Some(response) =
            self.stream.try_next().await.with_context(|| {
                format!("reading block {} from the Firehose stream", self.expected)
            })?
        else {
            return Ok(None);
        };
        let block = block_from_response(self.expected, &response)?;
        self.expected += 1;
        Ok(Some(block))
    }

    fn describe(&self) -> String {
        self.described.clone()
    }
}

/// Validate one Firehose response and convert its payload.
///
/// Split out from [`FirehoseSource`] so every refusal is reachable in a
/// hermetic test.
pub fn block_from_response(
    expected_number: i32,
    response: &firehose::Response,
) -> Result<BlockFinality> {
    if response.step != ForkStep::StepFinal as i32 {
        let step = ForkStep::try_from(response.step)
            .map(|s| s.as_str_name().to_string())
            .unwrap_or_else(|_| format!("{}", response.step));
        bail!(
            "the Firehose response for block {expected_number} is {step}, not STEP_FINAL; the \
             request set final_blocks_only, so anything else means the stream is not the one \
             that was asked for"
        );
    }
    let any = response.block.as_ref().ok_or_else(|| {
        anyhow!("the Firehose response for block {expected_number} carries no block payload")
    })?;
    decode_block_payload(expected_number, &any.type_url, &any.value)
}

/// Decode one `Any` payload as exactly one `sf.ethereum.type.v2.Block` with the
/// number that was asked for.
pub fn decode_block_payload(
    expected_number: i32,
    type_url: &str,
    value: &[u8],
) -> Result<BlockFinality> {
    let name = type_url.rsplit('/').next().unwrap_or(type_url);
    if name != ETHEREUM_BLOCK_TYPE {
        bail!(
            "the Firehose response for block {expected_number} carries `{type_url}`, not \
             `{ETHEREUM_BLOCK_TYPE}`"
        );
    }

    let chunks = block::split_messages(value).with_context(|| {
        format!("splitting the payload for block {expected_number} into block messages")
    })?;
    if chunks.len() > 1 {
        let (offset, second) = chunks[1];
        let second_number = codec::Block::decode(second)
            .map(|block| block.number.to_string())
            .unwrap_or_else(|_| "<undecodable>".to_string());
        bail!(
            "the Firehose response for block {expected_number} holds {} concatenated block \
             messages; the second is block {second_number} at offset {offset}. prost would merge \
             them silently, producing a block that claims one number while carrying another \
             block's logs",
            chunks.len()
        );
    }

    let block = codec::Block::decode(value)
        .with_context(|| format!("decoding block {expected_number} as {ETHEREUM_BLOCK_TYPE}"))?;
    if block.number != u64::try_from(expected_number).unwrap_or(u64::MAX) {
        bail!(
            "the Firehose stream produced block {} where block {expected_number} was expected",
            block.number
        );
    }

    (&block)
        .try_into()
        .map_err(|e| anyhow!("converting block {expected_number} to BlockFinality: {e}"))
}

// ---------------------------------------------------------------------------
// Surviving a stream that dies
// ---------------------------------------------------------------------------

/// Marks an error as a failure of the *transport*, not of the blocks.
///
/// Attached with [`anyhow::Context::context`], so the original error and its
/// whole chain survive and `downcast_ref` still finds this marker underneath
/// however many layers of context were added on the way out.
///
/// The distinction is the whole point of the type. A connection that resets, an
/// HTTP/2 protocol error, a stream that stops mid-range: those say nothing about
/// the data, so re-opening the stream and asking again is correct. A response
/// that is not `STEP_FINAL`, a payload that is not an Ethereum block, a block
/// with the wrong number, a server answering `PermissionDenied`: those are
/// statements about *this request*, and retrying one would only turn a clear
/// refusal into a slow one.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TransportFailure;

impl std::fmt::Display for TransportFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("the Firehose stream failed at the transport level")
    }
}

/// Whether an error is a transport failure, and so worth reconnecting after.
pub fn is_transport_failure(error: &anyhow::Error) -> bool {
    error.downcast_ref::<TransportFailure>().is_some()
}

/// gRPC status codes that mean "the connection did not work", as opposed to
/// "the server declines to serve this".
///
/// `Internal` and `Unknown` are on the list because that is where tonic puts a
/// hyper/h2 body error: the failure observed in a twenty-hour replay arrives as
/// `error reading a body from connection: stream error received: unspecific
/// protocol error detected`, which is a broken connection wearing a status code.
fn is_retryable_code(code: tonic::Code) -> bool {
    matches!(
        code,
        tonic::Code::Unavailable
            | tonic::Code::Internal
            | tonic::Code::Unknown
            | tonic::Code::Aborted
            | tonic::Code::Cancelled
            | tonic::Code::DeadlineExceeded
            | tonic::Code::ResourceExhausted
            | tonic::Code::DataLoss
    )
}

/// Substrings that identify a transport failure arriving as something other
/// than a `tonic::Status` — a TLS or connect error on the way to the first
/// response, which tonic surfaces as its own transport error type.
///
/// Only consulted when the error is not a status. Every refusal this module
/// raises itself is a plain `anyhow` message and matches none of these.
const TRANSPORT_MESSAGES: &[&str] = &[
    "error reading a body from connection",
    "connection reset",
    "connection closed",
    "connection refused",
    "broken pipe",
    "unexpected end of file",
    "transport error",
    "protocol error",
    "h2 protocol error",
    "tls handshake",
    "operation timed out",
];

/// Mark `error` retryable when it describes a broken connection.
fn classify(error: anyhow::Error) -> anyhow::Error {
    if let Some(status) = error.downcast_ref::<tonic::Status>() {
        return if is_retryable_code(status.code()) {
            error.context(TransportFailure)
        } else {
            error
        };
    }
    if let Some(io) = error.downcast_ref::<std::io::Error>() {
        use std::io::ErrorKind::*;
        return if matches!(
            io.kind(),
            ConnectionReset
                | ConnectionAborted
                | BrokenPipe
                | UnexpectedEof
                | TimedOut
                | NotConnected
        ) {
            error.context(TransportFailure)
        } else {
            error
        };
    }
    let rendered = format!("{error:#}").to_ascii_lowercase();
    if TRANSPORT_MESSAGES
        .iter()
        .any(|needle| rendered.contains(needle))
    {
        return error.context(TransportFailure);
    }
    error
}

/// How hard a broken stream is retried.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RetryPolicy {
    /// Consecutive failed attempts allowed *without a block arriving*. The
    /// counter resets on every delivered block, so a twenty-hour run may
    /// reconnect any number of times as long as it keeps making progress; what
    /// this bounds is a stream that is simply not working.
    pub retries: u32,
    /// The first delay. Each further consecutive attempt doubles it.
    pub backoff: Duration,
    /// The ceiling the doubling stops at.
    pub backoff_max: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        RetryPolicy {
            retries: 10,
            backoff: Duration::from_secs(1),
            backoff_max: Duration::from_secs(60),
        }
    }
}

impl RetryPolicy {
    /// The delay before consecutive attempt `attempt`, counting from 1.
    ///
    /// Doubling is done on the millisecond count with a saturating shift, so a
    /// large `retries` cannot overflow its way back down to a short delay.
    pub fn delay(&self, attempt: u32) -> Duration {
        if attempt <= 1 {
            return self.backoff.min(self.backoff_max);
        }
        let shift = (attempt - 1).min(32);
        let millis = (self.backoff.as_millis() as u64).saturating_mul(1u64 << shift);
        Duration::from_millis(millis).min(self.backoff_max)
    }
}

/// Opens one stream over a sub-range, so a broken stream can be replaced.
///
/// Separate from [`BlockSource`] because reconnecting needs the ability to ask
/// for `[next, stop)` again, which a source that is already draining cannot do.
#[async_trait]
pub trait StreamConnector: Send {
    /// Open a stream for the half-open range `[from, stop)`.
    async fn connect(&mut self, from: i32, stop: i32) -> Result<Box<dyn BlockSource>>;

    /// A description of the *whole* run, stable across reconnects, because it is
    /// recorded in the run header and in every checkpoint boundary.
    fn describe(&self, from: i32, stop: i32) -> String;
}

/// Opens `sf.firehose.v2.Stream/Blocks` on demand.
pub struct FirehoseConnector {
    target: FirehoseTarget,
    token: Option<String>,
}

impl FirehoseConnector {
    pub fn new(target: FirehoseTarget, token: Option<String>) -> Self {
        FirehoseConnector { target, token }
    }
}

#[async_trait]
impl StreamConnector for FirehoseConnector {
    async fn connect(&mut self, from: i32, stop: i32) -> Result<Box<dyn BlockSource>> {
        let source = FirehoseSource::connect(&self.target, self.token.clone(), from, stop).await?;
        Ok(Box::new(source))
    }

    fn describe(&self, from: i32, stop: i32) -> String {
        format!(
            "Firehose {} blocks [{from}, {stop})",
            self.target.authority()
        )
    }
}

/// A live count of how often a [`ReconnectingSource`] re-opened its stream.
///
/// Handed out before the source is boxed, so an operator's progress line can
/// report reconnections without the loop having to know what kind of source it
/// is draining.
#[derive(Clone, Debug)]
pub struct ReconnectCounter(Arc<std::sync::atomic::AtomicU64>);

impl ReconnectCounter {
    pub fn get(&self) -> u64 {
        self.0
            .load(std::sync::atomic::Ordering::Relaxed)
            .saturating_sub(1)
    }
}

/// A `[start, stop)` range that outlives the connections it is delivered over.
///
/// It tracks one number: the block the range still needs next. A reconnect asks
/// for `[next, stop)`, so nothing is skipped and nothing is replayed — and
/// because this sits *inside* a [`CheckedSource`], that claim is not taken on
/// trust: a reconnect that came back at the wrong height, repeated a block, or
/// landed on a different fork is refused by the same checks an unbroken stream
/// passes, the parent-hash link across the seam included.
pub struct ReconnectingSource<C> {
    connector: C,
    stop: i32,
    /// The number the next block must carry.
    next: i32,
    current: Option<Box<dyn BlockSource>>,
    policy: RetryPolicy,
    /// Consecutive failures since the last delivered block.
    attempts: u32,
    /// Streams opened, the first one included. Shared so a progress line can
    /// still read it once the source is boxed behind `dyn BlockSource`.
    connects: Arc<std::sync::atomic::AtomicU64>,
    /// Whether a reconnection prints a line to stderr.
    notify: bool,
    described: String,
}

impl<C: StreamConnector> ReconnectingSource<C> {
    /// Open the first stream. A failure here is retried on the same policy, so
    /// an endpoint that is briefly unreachable does not lose a whole run.
    pub async fn connect(connector: C, start: i32, stop: i32, policy: RetryPolicy) -> Result<Self> {
        if stop <= start {
            bail!("the requested range [{start}, {stop}) is empty");
        }
        let described = connector.describe(start, stop);
        let mut source = ReconnectingSource {
            connector,
            stop,
            next: start,
            current: None,
            policy,
            attempts: 0,
            connects: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            notify: true,
            described,
        };
        source.open().await?;
        Ok(source)
    }

    /// Silence the reconnection notices. Used by the tests, which drive many
    /// simulated failures.
    pub fn quiet(mut self) -> Self {
        self.notify = false;
        self
    }

    /// How many times the stream was re-opened after a failure.
    pub fn reconnects(&self) -> u64 {
        self.connects
            .load(std::sync::atomic::Ordering::Relaxed)
            .saturating_sub(1)
    }

    /// A handle on the reconnect count that outlives boxing this source behind
    /// `dyn BlockSource`, so a progress line can report it.
    pub fn reconnect_counter(&self) -> ReconnectCounter {
        ReconnectCounter(Arc::clone(&self.connects))
    }

    /// The block the range still needs next.
    pub fn next_expected(&self) -> i32 {
        self.next
    }

    /// Open a stream for `[next, stop)`, retrying a transport failure.
    async fn open(&mut self) -> Result<()> {
        loop {
            match self.connector.connect(self.next, self.stop).await {
                Ok(source) => {
                    self.current = Some(source);
                    self.connects
                        .fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                    return Ok(());
                }
                Err(error) => self.wait_or_give_up(error, "opening").await?,
            }
        }
    }

    /// Decide whether `error` may be retried, and if so sleep for the backoff.
    ///
    /// Returning `Ok(())` means "try again"; every other outcome is the error,
    /// with the reason it was not retried spelled out.
    async fn wait_or_give_up(&mut self, error: anyhow::Error, what: &str) -> Result<()> {
        let at = self.next;
        if !is_transport_failure(&error) {
            return Err(error.context(format!(
                "{what} the Firehose stream at block {at}: this is not a transport failure, so \
                 reconnecting could not fix it and would only hide it"
            )));
        }
        self.attempts += 1;
        if self.attempts > self.policy.retries {
            return Err(error.context(format!(
                "{what} the Firehose stream at block {at}: giving up after {} consecutive \
                 transport failures with no block delivered (--stream-retries {})",
                self.attempts - 1,
                self.policy.retries
            )));
        }
        let delay = self.policy.delay(self.attempts);
        if self.notify {
            eprintln!(
                "firehose: {what} the stream failed at block {at} ({}); reconnecting in {:.1}s \
                 (attempt {}/{})",
                error,
                delay.as_secs_f64(),
                self.attempts,
                self.policy.retries
            );
        }
        self.current = None;
        tokio::time::sleep(delay).await;
        Ok(())
    }
}

#[async_trait]
impl<C: StreamConnector> BlockSource for ReconnectingSource<C> {
    async fn next_block(&mut self) -> Result<Option<BlockFinality>> {
        loop {
            if self.next >= self.stop {
                return Ok(None);
            }
            if self.current.is_none() {
                self.open().await?;
            }
            let outcome = self
                .current
                .as_mut()
                .expect("a stream was just opened")
                .next_block()
                .await;
            match outcome {
                Ok(Some(block)) => {
                    // Progress: the retry budget is about a stream that is not
                    // working, and this one just did.
                    self.attempts = 0;
                    self.next = block.number().saturating_add(1);
                    return Ok(Some(block));
                }
                // The range was satisfied. This is the only clean end.
                Ok(None) if self.next >= self.stop => return Ok(None),
                // A stream that closes before the range it was asked for is a
                // truncated stream, which is the EOF-mid-range case: retried,
                // and then caught by the contiguity checks if the retry lies.
                Ok(None) => {
                    let error = anyhow!(
                        "the Firehose stream closed after block {} without reaching block {}, \
                         which the requested range needs",
                        self.next - 1,
                        self.stop - 1
                    )
                    .context(TransportFailure);
                    self.wait_or_give_up(error, "reading").await?;
                }
                Err(error) => self.wait_or_give_up(error, "reading").await?,
            }
        }
    }

    fn describe(&self) -> String {
        self.described.clone()
    }
}

#[cfg(test)]
mod retry_tests {
    use super::*;

    fn policy() -> RetryPolicy {
        RetryPolicy {
            retries: 10,
            backoff: Duration::from_millis(500),
            backoff_max: Duration::from_secs(8),
        }
    }

    #[test]
    fn the_backoff_doubles_and_then_stops_at_the_cap() {
        let policy = policy();
        assert_eq!(policy.delay(1), Duration::from_millis(500));
        assert_eq!(policy.delay(2), Duration::from_secs(1));
        assert_eq!(policy.delay(3), Duration::from_secs(2));
        assert_eq!(policy.delay(4), Duration::from_secs(4));
        assert_eq!(policy.delay(5), Duration::from_secs(8));
        // Capped, and still capped far past the point where doubling would
        // otherwise overflow.
        assert_eq!(policy.delay(6), Duration::from_secs(8));
        assert_eq!(policy.delay(64), Duration::from_secs(8));
        assert_eq!(policy.delay(u32::MAX), Duration::from_secs(8));
    }

    #[test]
    fn a_backoff_larger_than_the_cap_is_the_cap() {
        let policy = RetryPolicy {
            retries: 3,
            backoff: Duration::from_secs(30),
            backoff_max: Duration::from_secs(5),
        };
        assert_eq!(policy.delay(1), Duration::from_secs(5));
        assert_eq!(policy.delay(2), Duration::from_secs(5));
    }

    #[test]
    fn a_broken_connection_is_a_transport_failure_and_a_refusal_is_not() {
        let broken = classify(anyhow!(
            "error reading a body from connection: stream error received: unspecific protocol \
             error detected"
        ));
        assert!(is_transport_failure(&broken), "{broken:#}");
        // Still a transport failure under however much context the call stack
        // wraps it in, which is what the reconnecting source actually sees.
        let wrapped = broken.context("reading block 12764397 from the Firehose stream");
        assert!(is_transport_failure(&wrapped), "{wrapped:#}");

        let refusal = classify(anyhow!(
            "the Firehose stream produced block 42 where block 41 was expected"
        ));
        assert!(!is_transport_failure(&refusal), "{refusal:#}");
    }

    #[test]
    fn a_status_is_classified_by_its_code() {
        let unavailable = classify(anyhow::Error::new(tonic::Status::unavailable("no route")));
        assert!(is_transport_failure(&unavailable));

        let internal = classify(anyhow::Error::new(tonic::Status::internal(
            "stream error received",
        )));
        assert!(is_transport_failure(&internal));

        // A server refusing the request is not retried, however long the run is.
        for status in [
            tonic::Status::unauthenticated("bad token"),
            tonic::Status::permission_denied("not your chain"),
            tonic::Status::invalid_argument("no such range"),
            tonic::Status::not_found("no such chain"),
            tonic::Status::failed_precondition("blocks pruned"),
            tonic::Status::unimplemented("no firehose here"),
        ] {
            let code = status.code();
            let error = classify(anyhow::Error::new(status));
            assert!(
                !is_transport_failure(&error),
                "{code:?} must not be retried: {error:#}"
            );
        }
    }
}
