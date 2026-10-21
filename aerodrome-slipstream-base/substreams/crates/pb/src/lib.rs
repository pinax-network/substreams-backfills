//! Shared wire types. No Substreams runtime dependency.
#[allow(clippy::all)]
pub mod pinax {
    pub mod aerodrome {
        pub mod slipstream {
            pub mod base {
                pub mod v1 {
                    include!("pinax.aerodrome.slipstream.base.v1.rs");
                }
                pub mod internal {
                    pub mod v1 {
                        include!("pinax.aerodrome.slipstream.base.internal.v1.rs");
                    }
                }
            }
        }
    }
}
#[allow(clippy::all)]
pub mod eth {
    include!("sf.ethereum.type.v2.rs");
}
pub use pinax::aerodrome::slipstream::base::{internal::v1 as internal, v1};
