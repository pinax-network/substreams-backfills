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
//! stream is mapped to `anyhow::Error` and boxed at construction, so this module
//! never has to name a tonic type either.
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

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use async_trait::async_trait;
use graph::blockchain::Block as _;
use graph::components::metrics::MetricsRegistry;
use graph::endpoint::EndpointMetrics;
use graph::firehose::{self, ConnectionHeaders, FirehoseEndpoint, ForkStep, SubgraphLimit};
use graph::futures03::stream::{BoxStream, StreamExt as _, TryStreamExt as _};
use graph::prelude::prost::Message as _;
use graph::prelude::{o, slog, Logger};
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
    finished: bool,
}

impl<S: BlockSource> CheckedSource<S> {
    pub fn new(inner: S, ordering: Ordering) -> Self {
        CheckedSource {
            inner,
            ordering,
            previous: None,
            finished: false,
        }
    }

    fn check(&mut self, number: i32) -> Result<()> {
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
        }

        self.previous = Some(number);
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
                self.check(block.number())?;
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
            None,
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
            .with_context(|| {
                format!(
                    "opening sf.firehose.v2.Stream/Blocks on {} for [{start}, {stop})",
                    target.authority()
                )
            })?;

        let stream = stream.map_err(anyhow::Error::from).boxed();

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
