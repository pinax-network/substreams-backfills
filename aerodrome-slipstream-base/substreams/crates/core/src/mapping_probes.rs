//! Pure call keys from the deployed mapping, shared by extraction and reduction.
use crate::Address;

/// The deployed `addMissingWhitelistedPools` uses USDC as the first argument.
pub const USDC: Address = [
    0x83, 0x35, 0x89, 0xfc, 0xd6, 0xed, 0xb6, 0xe0, 0x8f, 0x4c, 0x7c, 0x32, 0xd4, 0xf7, 0x1b, 0x54,
    0xbd, 0xa0, 0x29, 0x13,
];

/// Exact ordered calls made for a token whose mapping `version` getter is zero.
///
/// Pool.wasm's helper excludes only USDC, then calls all four `getPool` variants
/// before inspecting their results. These literal third arguments are NOT the
/// fee-tier-to-tick-spacing conversion used by the Swap tick walker. The pushes
/// into `whitelistPools` getter copies have no persistent effect, but the host
/// calls still must be answered. Extractors may supply this conservative set
/// without knowing whether the reducer's token version is already nonzero.
pub fn missing_whitelist_pool_probes(token: Address) -> Vec<(Address, Address, i32)> {
    if token == USDC {
        Vec::new()
    } else {
        [100, 500, 3000, 10000]
            .map(|spacing| (USDC, token, spacing))
            .to_vec()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deployed_helper_keys_keep_argument_order_and_literal_tiers() {
        let token = [0x42; 20];
        assert_eq!(
            hex::encode(USDC),
            "833589fcd6edb6e08f4c7c32d4f71b54bda02913"
        );
        assert_eq!(
            missing_whitelist_pool_probes(token),
            vec![
                (USDC, token, 100),
                (USDC, token, 500),
                (USDC, token, 3000),
                (USDC, token, 10000)
            ]
        );
        assert!(missing_whitelist_pool_probes(USDC).is_empty());
    }
}
