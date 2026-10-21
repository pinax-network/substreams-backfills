#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("Graph Node gas field exceeds u128")]
pub struct GasOverflow;
fn integer(bytes: Option<&[u8]>) -> Result<u128, GasOverflow> {
    let bytes = bytes.unwrap_or_default();
    let first = bytes.iter().position(|v| *v != 0).unwrap_or(bytes.len());
    let bytes = &bytes[first..];
    if bytes.len() > 16 {
        return Err(GasOverflow);
    }
    let mut out = [0; 16];
    out[16 - bytes.len()..].copy_from_slice(bytes);
    Ok(u128::from_be_bytes(out))
}
/// Graph Node codec + alloy 2.4.1 effective gas price. Unknown types (including OP deposits) use gasPrice.
pub fn graph_node_gas_price(
    tx_type: u32,
    gas_price: Option<&[u8]>,
    max_fee: Option<&[u8]>,
    max_prio: Option<&[u8]>,
    base_fee: Option<u64>,
) -> Result<u128, GasOverflow> {
    let gp = integer(gas_price)?;
    if !matches!(tx_type, 2..=4) {
        return Ok(gp);
    }
    let cap = match max_fee {
        Some(v) => integer(Some(v))?,
        None => gp,
    };
    let priority = integer(max_prio)?;
    Ok(match base_fee {
        None => cap,
        Some(base) => {
            let base = u128::from(base);
            if cap.saturating_sub(base) > priority {
                base + priority
            } else {
                cap
            }
        }
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn known_unknown_and_missing_fees() {
        for kind in [0, 1, 126, 255] {
            assert_eq!(
                graph_node_gas_price(kind, Some(&[7]), Some(&[99]), None, Some(10)),
                Ok(7)
            );
        }
        assert_eq!(graph_node_gas_price(126, None, None, None, Some(10)), Ok(0));
        for kind in 2..=4 {
            assert_eq!(
                graph_node_gas_price(kind, Some(&[7]), Some(&[99]), Some(&[3]), Some(10)),
                Ok(13)
            );
        }
        assert_eq!(
            graph_node_gas_price(2, Some(&[7]), None, None, Some(10)),
            Ok(7)
        );
        assert_eq!(
            graph_node_gas_price(2, None, Some(&[99]), None, None),
            Ok(99)
        );
        assert_eq!(
            graph_node_gas_price(
                2,
                None,
                Some(&296906355u128.to_be_bytes()),
                Some(&903800u128.to_be_bytes()),
                Some(98354726)
            ),
            Ok(99258526)
        );
        assert!(graph_node_gas_price(0, Some(&[1; 17]), None, None, None).is_err());
        assert_eq!(
            graph_node_gas_price(
                2,
                None,
                Some(&u128::MAX.to_be_bytes()),
                Some(&u128::MAX.to_be_bytes()),
                Some(u64::MAX)
            ),
            Ok(u128::MAX)
        );
    }
}
