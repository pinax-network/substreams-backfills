use crate::{config::Config, layout, Address, Word};
pub const ERC20_SELECTORS: [[u8; 4]; 4] = [
    [0x95, 0xd8, 0x9b, 0x41],
    [0x06, 0xfd, 0xde, 0x03],
    [0x18, 0x16, 0x0d, 0xdd],
    [0x31, 0x3c, 0xe5, 0x67],
];
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum CallKey {
    Erc20 { token: Address, selector: [u8; 4] },
    FeeGrowth { pool: Address, which: u8 },
    Ticks { pool: Address, tick: i32 },
    Positions { token_id: Word },
    GetPool { a: Address, b: Address, ts: i32 },
}
impl CallKey {
    pub fn address(&self, cfg: &Config) -> Address {
        match self {
            Self::Erc20 { token, .. } => *token,
            Self::FeeGrowth { pool, .. } | Self::Ticks { pool, .. } => *pool,
            Self::Positions { .. } => cfg.npm,
            Self::GetPool { .. } => cfg.factory,
        }
    }
    pub fn calldata(&self) -> Result<Vec<u8>, &'static str> {
        let (selector, words) = match self {
            Self::Erc20 { selector, .. } => {
                if !ERC20_SELECTORS.contains(selector) {
                    return Err("unsupported ERC20 selector");
                }
                (*selector, vec![])
            }
            Self::FeeGrowth { which: 0, .. } => ([0xf3, 0x05, 0x83, 0x99], vec![]),
            Self::FeeGrowth { which: 1, .. } => ([0x46, 0x14, 0x13, 0x19], vec![]),
            Self::FeeGrowth { .. } => return Err("fee growth index must be 0 or 1"),
            Self::Ticks { tick, .. } => {
                if !(-8388608..=8388607).contains(tick) {
                    return Err("tick exceeds int24");
                }
                ([0xf3, 0x0d, 0xba, 0x93], vec![layout::int_word(*tick)])
            }
            Self::Positions { token_id } => ([0x99, 0xfb, 0xab, 0x88], vec![*token_id]),
            Self::GetPool { a, b, ts } => {
                if !(-8388608..=8388607).contains(ts) {
                    return Err("tick spacing exceeds int24");
                }
                let mut wa = [0; 32];
                wa[12..].copy_from_slice(a);
                let mut wb = [0; 32];
                wb[12..].copy_from_slice(b);
                (
                    [0x28, 0xaf, 0x8d, 0x0b],
                    vec![wa, wb, layout::int_word(*ts)],
                )
            }
        };
        let mut result = selector.to_vec();
        for word in words {
            result.extend(word);
        }
        Ok(result)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_calldata() {
        let c = CallKey::Ticks {
            pool: [1; 20],
            tick: -1,
        }
        .calldata()
        .unwrap();
        assert_eq!(hex::encode(&c[..4]), "f30dba93");
        assert_eq!(&c[4..], &[255; 32]);
        assert!(CallKey::FeeGrowth {
            pool: [0; 20],
            which: 2
        }
        .calldata()
        .is_err());
        let g = CallKey::GetPool {
            a: [1; 20],
            b: [2; 20],
            ts: 100,
        }
        .calldata()
        .unwrap();
        assert_eq!(g.len(), 100);
        assert_eq!(g[99], 100);
    }
}
