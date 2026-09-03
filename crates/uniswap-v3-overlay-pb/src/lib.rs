//! The protobuf bindings the Uniswap V3 overlay reducers compile against.
//!
//! Nothing here is a new definition. Every module is the exact bytes that
//! `scripts/materialize-uniswap-v3-*.sh` place in a materialized runtime tree:
//! `pb::writer` is extracted from the writer-runtime patch by `build.rs`, and
//! the rest are `include!`d from the overlay directories in place.
//!
//! The module layout is fixed by the generated code, which refers across
//! packages with `super::` paths. `uniswap.npm.source.v1` names
//! `super::writer::WriterEvents`, so it has to sit beside `pb::writer` exactly
//! as `uniswap-v3/npm-source-block/runtime/src/pb/mod.rs` places it, and the
//! `inputs`/`plan` packages name `super::super::<package>::v1::…`, so they have
//! to sit under `uniswap::npm`. This mirrors the overlay test harnesses.
//!
//! Dependents rename this crate to `substreams_uniswap_v3` so the overlay
//! sources keep the paths they resolve to inside a materialized tree. See
//! `crates/README.md`.

pub mod pb {
    /// `uniswap.writer.v1`, from `uniswap-v3/writer-runtime/runtime.patch`.
    pub mod writer {
        include!(concat!(env!("OUT_DIR"), "/uniswap.writer.v1.rs"));
    }

    /// `uniswap.npm.source.v1`, from the npm-source-block runtime overlay.
    pub mod npm_source {
        include!("../../../uniswap-v3/npm-source-block/runtime/src/pb/uniswap.npm.source.v1.rs");
    }
}

pub mod uniswap {
    pub mod npm {
        pub mod source {
            pub mod v1 {
                pub use crate::pb::npm_source::*;
            }
        }

        pub mod inputs {
            /// `uniswap.npm.inputs.v1`, from the npm-resolved-inputs overlay.
            pub mod v1 {
                include!("../../../uniswap-v3/npm-resolved-inputs/src/uniswap.npm.inputs.v1.rs");
            }
        }

        pub mod plan {
            /// `uniswap.npm.plan.v1`, from the npm-observation-plan overlay.
            pub mod v1 {
                include!("../../../uniswap-v3/npm-observation-plan/src/uniswap.npm.plan.v1.rs");
            }
        }
    }
}
