//! Authoritative block execution over an atomic EntityBackend. The memory
//! stream adapter retains every frame until EOF and supervisor success;
//! the durable module supplies a separate streaming disk adapter.
use crate::{
    address,
    handlers::SupportedHandler,
    hosts::{HostSet, FACTORY_EXCLUDED_POOL},
    identity::InputBinding,
    input::{BlockInput, InputStream},
    pb, refuse, require,
    state::{BlockStore, EntityBackend, HandlerJournal, HandlerStatus, MemoryBackend, Step},
    Address, Result,
};
use backfill_common::{clock::Frame, state_snapshot::Boundary};
use serde::Serialize;
use std::io::Read;

/// Production qualification requires zero aborts. EmitNonFatal exists for
/// diagnostic parity only; it must also match the descriptor's nonfatal policy.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum AbortMode {
    #[default]
    FailClosed,
    EmitNonFatal,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum CandidateOutcome {
    NotMatched,
    Committed {
        handler_group_order: u64,
    },
    Aborted {
        handler_group_order: u64,
        message: String,
    },
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CandidateReport {
    pub candidate_index: usize,
    pub wave: u32,
    pub source_trigger_order: u32,
    pub handler: Option<String>,
    #[serde(flatten)]
    pub outcome: CandidateOutcome,
}
#[derive(Debug)]
pub struct CommittedBlock {
    frame: Frame,
    candidates: Vec<CandidateReport>,
}
impl CommittedBlock {
    pub fn frame(&self) -> &Frame {
        &self.frame
    }
    pub fn candidates(&self) -> &[CandidateReport] {
        &self.candidates
    }
}

/// Owns state and matching outcomes together. A refused block poisons the
/// runner: the caller cannot ignore its failure and continue at a later block.
pub struct Runner<B: EntityBackend> {
    binding: InputBinding,
    backend: B,
    hosts: HostSet,
    mode: AbortMode,
    failed: bool,
}
pub type MemoryRunner = Runner<MemoryBackend>;
impl<B: EntityBackend> Runner<B> {
    pub fn new(binding: InputBinding, backend: B) -> Result<Self> {
        Self::with_abort_mode(binding, backend, AbortMode::FailClosed)
    }
    pub fn with_abort_mode(binding: InputBinding, backend: B, mode: AbortMode) -> Result<Self> {
        require(
            backend.compatibility_id() == *binding.compatibility().id(),
            "runner state/descriptor mismatch",
        )?;
        require(
            mode != AbortMode::EmitNonFatal || binding.compatibility().deterministic_error_policy()
                == backfill_common::pb::pinax::graph::backfill::v1::DeterministicErrorPolicy::NonFatal,
            "EmitNonFatal requires a nonfatal descriptor",
        )?;
        let hosts = backend.host_set()?;
        Ok(Self {
            binding,
            backend,
            hosts,
            mode,
            failed: false,
        })
    }
    /// Diagnostic state access; neither this nor a committed block proves range
    /// completion. Only run_stream checks the input and producer completion gates.
    pub fn backend(&self) -> &B {
        &self.backend
    }
    pub fn into_backend(self) -> Result<B> {
        require(!self.failed, "runner is poisoned")?;
        Ok(self.backend)
    }
    pub fn process(&mut self, input: &BlockInput) -> Result<CommittedBlock> {
        self.process_with(input, |handler, journal| handler.run(journal))
    }
    pub(crate) fn process_with<F>(
        &mut self,
        input: &BlockInput,
        mut run: F,
    ) -> Result<CommittedBlock>
    where
        F: FnMut(
            &SupportedHandler<'_>,
            &mut HandlerJournal<'_, B>,
        ) -> std::result::Result<Option<Address>, Step>,
    {
        require(!self.failed, "runner is poisoned")?;
        self.failed = true; // also refuses continuation after a caught panic
        let mut hosts = self.hosts.clone();
        let mut store = BlockStore::begin(&self.backend, &self.binding, input)?;
        let mut candidates = Vec::with_capacity(input.block().candidates.len());
        let mut group = 0;
        let mut aborted_sources = Vec::new();
        // validate_block proved ascending (wave, source_trigger_order). No
        // filtering or re-sorting here: even unmatched candidates are reported.
        for (index, candidate) in input.block().candidates.iter().enumerate() {
            let handler = SupportedHandler::match_candidate(input, &hosts, index)?;
            let outcome = if let Some(handler) = handler {
                let mut created = None;
                let status = store.run_handler(handler.source_trigger_order(), |journal| {
                    created = run(&handler, journal)?;
                    Ok(())
                })?;
                let fact = (candidate.source == pb::DataSourceKind::Factory as i32)
                    .then(|| {
                        input
                            .block()
                            .pools_created
                            .iter()
                            .find(|f| f.log_index == candidate.log_index)
                    })
                    .flatten();
                if let Some(pool) = created {
                    require(
                        matches!(status, HandlerStatus::Committed),
                        "aborted creator returned a source",
                    )?;
                    require(
                        fact.is_some_and(|f| f.pool == pool),
                        "handler creation differs from validated fact",
                    )?;
                    hosts.record_creation_outcome(input, pool, true)?;
                }
                let result = match status {
                    HandlerStatus::Committed => {
                        // A nonexcluded new Factory host must be backed by an
                        // actual successful dataSource.create, never its fact.
                        if let Some(fact) = fact {
                            let pool = address(&fact.pool)?;
                            require(
                                hex::encode(pool) == FACTORY_EXCLUDED_POOL || hosts.contains(&pool),
                                "Factory committed without creating its declared host",
                            )?;
                        }
                        CandidateOutcome::Committed {
                            handler_group_order: group,
                        }
                    }
                    HandlerStatus::Aborted(abort) => {
                        if self.mode == AbortMode::FailClosed {
                            return Err(refuse(format!(
                                "MappingAbort at block {} candidate {index}: {}",
                                input.block().number,
                                abort.message
                            )));
                        }
                        if let Some(fact) = fact {
                            let pool = address(&fact.pool)?;
                            if !hosts.contains(&pool) && hex::encode(pool) != FACTORY_EXCLUDED_POOL
                            {
                                hosts.record_creation_outcome(input, pool, false)?;
                                aborted_sources.push(pool);
                            }
                        }
                        CandidateOutcome::Aborted {
                            handler_group_order: group,
                            message: abort.message,
                        }
                    }
                };
                group += 1;
                result
            } else {
                CandidateOutcome::NotMatched
            };
            candidates.push(CandidateReport {
                candidate_index: index,
                wave: candidate.wave,
                source_trigger_order: candidate.source_trigger_order,
                handler: input.decoded()[index].as_ref().map(|e| e.name.clone()),
                outcome,
            });
        }
        let mut sealed = store.seal()?;
        sealed.aborted_sources = aborted_sources;
        require(sealed.committable(), "fatal discarded block cannot commit")?;
        let frame = sealed.frame().clone();
        // The backend atomically installs the entire block. Publishing staged
        // hosts after this atomic commit is infallible; failed outcomes follow
        // the same block boundary, but never become in-band source creations.
        self.backend.commit(sealed)?;
        self.hosts = hosts;
        self.failed = false;
        Ok(CommittedBlock { frame, candidates })
    }
}

/// This is an in-memory receipt, not the durable producer/v1 completion marker.
pub struct CompletedMemoryRun {
    runner: MemoryRunner,
    blocks: Vec<CommittedBlock>,
}
impl CompletedMemoryRun {
    pub fn boundary(&self) -> &Boundary {
        self.runner.backend.boundary()
    }
    pub fn backend(&self) -> &MemoryBackend {
        &self.runner.backend
    }
    pub fn blocks(&self) -> &[CommittedBlock] {
        &self.blocks
    }
    /// Continue without losing failed-creation matching history. Reconstructing
    /// from only entity/source rows is not a checkpoint of that history.
    pub fn into_runner(self) -> MemoryRunner {
        self.runner
    }
}

#[derive(Clone, Copy, Debug)]
pub struct MemoryLimits {
    pub max_blocks: usize,
    pub max_candidates: usize,
    pub max_output_payload_bytes: usize,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputCompletion {
    Complete,
    Refused,
}

/// Retain the complete bounded range in memory. A supervisor must supply a
/// callback which checks its producer's final success (including cancellation).
/// This callback is invoked even on input/execution failure so it can reap the
/// producer. Refused means it must cancel/drain the producer before waiting
/// if unread pipe data could prevent that producer from exiting.
/// No callback or early-return path can produce a CompletedMemoryRun.
pub fn run_stream<R: Read>(
    mut runner: MemoryRunner,
    mut input: InputStream<R>,
    limits: MemoryLimits,
    producer_success: impl FnOnce(InputCompletion) -> Result<()>,
) -> Result<CompletedMemoryRun> {
    let result = (|| {
        require(!runner.failed, "runner is poisoned")?;
        require(
            input.binding().compatibility().id() == runner.binding.compatibility().id(),
            "input/runner descriptor mismatch",
        )?;
        require(
            limits.max_blocks > 0
                && limits.max_candidates > 0
                && limits.max_output_payload_bytes > 0,
            "memory limits must be positive",
        )?;
        let mut blocks = Vec::new();
        let mut candidates = 0_usize;
        let mut payload_bytes = 0_usize;
        while let Some(block) = input.next_block()? {
            require(
                blocks.len() < limits.max_blocks,
                "memory block limit exceeded",
            )?;
            candidates = candidates
                .checked_add(block.block().candidates.len())
                .ok_or_else(|| refuse("candidate count overflow"))?;
            require(
                candidates <= limits.max_candidates,
                "memory candidate limit exceeded",
            )?;
            let block = runner.process(&block)?;
            payload_bytes = payload_bytes
                .checked_add(block.frame().payload.len())
                .ok_or_else(|| refuse("output size overflow"))?;
            require(
                payload_bytes <= limits.max_output_payload_bytes,
                "memory output payload limit exceeded",
            )?;
            blocks.push(block);
        }
        let hash = input.finish()?;
        require(
            hash == runner.backend.boundary().block_hash,
            "completed input/state boundary mismatch",
        )?;
        Ok(blocks)
    })();
    let producer = producer_success(if result.is_ok() {
        InputCompletion::Complete
    } else {
        InputCompletion::Refused
    });
    let blocks = result?;
    producer.map_err(|e| refuse(format!("producer did not complete successfully: {e}")))?;
    Ok(CompletedMemoryRun { runner, blocks })
}

#[cfg(test)]
mod tests;
