//! Checked-in protobuf bindings for shared backfill contracts.

pub mod pinax {
    pub mod graph {
        pub mod backfill {
            pub mod v1 {
                include!("pinax.graph.backfill.v1.rs");
            }
        }
    }
}
