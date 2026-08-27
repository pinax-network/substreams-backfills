pub mod pb {
    pub use substreams_uniswap_v3::pb::*;
}

pub use substreams_uniswap_v3::pb::uniswap;
pub use substreams_uniswap_v3::utils;

#[allow(dead_code, unused_imports)]
#[path = "../../source/src/db.rs"]
mod imported_db;

#[cfg(test)]
mod tests {
    use super::imported_db;
    use std::collections::HashMap;
    use substreams::pb::substreams::{store_delta::Operation, StoreDelta};
    use substreams::store::{DeltaBigInt, Deltas};
    use substreams_entity_change::pb::entity::{value::Typed, EntityChange};
    use substreams_entity_change::tables::Tables;

    fn delta(operation: Operation, key: &str, new_value: &str) -> StoreDelta {
        StoreDelta {
            operation: operation as i32,
            ordinal: 1,
            key: key.to_owned(),
            old_value: b"0".to_vec(),
            new_value: new_value.as_bytes().to_vec(),
        }
    }

    fn one_change(tables: Tables) -> EntityChange {
        let mut changes = tables.to_entity_changes().entity_changes;
        assert_eq!(changes.len(), 1);
        changes.pop().unwrap()
    }

    fn fields(change: &EntityChange) -> HashMap<&str, &Typed> {
        change
            .fields
            .iter()
            .map(|field| {
                (
                    field.name.as_str(),
                    field
                        .new_value
                        .as_ref()
                        .and_then(|value| value.typed.as_ref())
                        .expect("typed new value"),
                )
            })
            .collect()
    }

    #[test]
    fn creates_tick_day_data_with_exact_identity_and_defaults() {
        let deltas = Deltas::<DeltaBigInt>::new(vec![delta(
            Operation::Create,
            "TickDayData:20000:abcdef:120:liquidityGross",
            "45",
        )]);
        let mut tables = Tables::new();
        imported_db::tick_windows_create(&mut tables, &deltas);

        let change = one_change(tables);
        assert_eq!(change.entity, "TickDayData");
        assert_eq!(change.id, "0xabcdef#120-20000");
        let fields = fields(&change);
        assert_eq!(fields["pool"], &Typed::String("0xabcdef".into()));
        assert_eq!(fields["tick"], &Typed::String("0xabcdef#120".into()));
        assert_eq!(fields["date"], &Typed::Int32(1_728_000_000));
        for field in [
            "liquidityGross",
            "liquidityNet",
            "feeGrowthOutside0X128",
            "feeGrowthOutside1X128",
        ] {
            assert_eq!(fields[field], &Typed::Bigint("0".into()), "{field}");
        }
        for field in ["volumeToken0", "volumeToken1", "volumeUSD", "feesUSD"] {
            assert_eq!(fields[field], &Typed::Bigdecimal("0".into()), "{field}");
        }
    }

    #[test]
    fn creates_tick_hour_data_with_exact_identity_and_defaults() {
        let deltas = Deltas::<DeltaBigInt>::new(vec![delta(
            Operation::Create,
            "TickHourData:400000:deadbeef:-30:liquidityNet",
            "-9",
        )]);
        let mut tables = Tables::new();
        imported_db::tick_windows_create(&mut tables, &deltas);

        let change = one_change(tables);
        assert_eq!(change.entity, "TickHourData");
        assert_eq!(change.id, "0xdeadbeef#-30-400000");
        let fields = fields(&change);
        assert_eq!(fields["pool"], &Typed::String("0xdeadbeef".into()));
        assert_eq!(fields["tick"], &Typed::String("0xdeadbeef#-30".into()));
        assert_eq!(fields["periodStartUnix"], &Typed::Int32(1_440_000_000));
        assert!(!fields.contains_key("date"));
        assert!(!fields.contains_key("feeGrowthOutside0X128"));
        assert!(!fields.contains_key("feeGrowthOutside1X128"));
    }

    #[test]
    fn updates_tick_day_liquidity_from_the_store_delta() {
        let deltas = Deltas::<DeltaBigInt>::new(vec![delta(
            Operation::Update,
            "TickDayData:20000:abcdef:-120:liquidityGross",
            "45",
        )]);
        let mut tables = Tables::new();
        imported_db::liquidities_tick_windows(&mut tables, &deltas);

        let change = one_change(tables);
        assert_eq!(change.entity, "TickDayData");
        assert_eq!(change.id, "0xabcdef#-120-20000");
        assert_eq!(
            fields(&change)["liquidityGross"],
            &Typed::Bigint("45".into())
        );
    }

    #[test]
    fn updates_tick_hour_liquidity_and_ignores_deletes() {
        let deltas = Deltas::<DeltaBigInt>::new(vec![
            delta(
                Operation::Update,
                "TickHourData:400000:deadbeef:30:liquidityNet",
                "-7",
            ),
            delta(
                Operation::Delete,
                "TickHourData:399999:deadbeef:30:liquidityNet",
                "0",
            ),
        ]);
        let mut tables = Tables::new();
        imported_db::liquidities_tick_windows(&mut tables, &deltas);

        let change = one_change(tables);
        assert_eq!(change.entity, "TickHourData");
        assert_eq!(change.id, "0xdeadbeef#30-400000");
        assert_eq!(fields(&change)["liquidityNet"], &Typed::Bigint("-7".into()));
    }
}
