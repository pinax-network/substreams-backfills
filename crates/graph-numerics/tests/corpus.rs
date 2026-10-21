use graph_numerics::{bigint, mapping, BigInt, GraphDecimal, NumericError, GRAPH_NODE_COMMIT};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{path::PathBuf, sync::OnceLock};

#[path = "support/cases.rs"]
mod cases;
use cases::{Case, Sweep, SWEEP_COUNT, SWEEP_SEED};

fn fixture() -> &'static Value {
    static FIXTURE: OnceLock<Value> = OnceLock::new();
    FIXTURE.get_or_init(|| {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("fixtures/graph-node-v0.44-numerics.json");
        serde_json::from_slice(
            &std::fs::read(path).expect("run the mapping-host numerics corpus generator"),
        )
        .unwrap()
    })
}
fn decimal_result(value: GraphDecimal) -> Value {
    let (coefficient, scale) = value.coefficient_and_scale();
    let wire = value.to_wire_exact();
    assert_eq!(
        GraphDecimal::from_wire_exact(&wire)
            .unwrap()
            .to_wire_exact(),
        wire
    );
    let fixed = value.is_fixed_point();
    assert_eq!(value.to_block_changes_wire().is_ok(), fixed);
    let twice = value.cross().unwrap();
    assert_eq!(
        twice.cross().unwrap().to_wire_exact(),
        twice.to_wire_exact()
    );
    json!({"coefficient":coefficient.to_string(),"scale":scale,
        "wire":hex::encode(wire.coefficient_signed_be),"fixed":fixed,
        "display_sha256":hex::encode(Sha256::digest(value.to_string().as_bytes()))})
}
fn integer_result(value: BigInt) -> Value {
    let wire = bigint::to_wire(&value).unwrap();
    assert_eq!(bigint::from_wire(&wire).unwrap(), value);
    json!({"integer":value.to_string(),"wire":hex::encode(wire.signed_be)})
}
fn evaluate(case: &Case) -> Result<Value, NumericError> {
    let a = case.a.as_str();
    let b = case.b.as_deref().unwrap_or("");
    let c = case.c.as_deref().unwrap_or("");
    let host = GraphDecimal::host_from_string;
    let dec = match case.op.as_str() {
        "host_string" => host(a)?,
        "db_string" => GraphDecimal::from_db_text(a)?,
        "raw_int" => GraphDecimal::from_bigint(&bigint::parse(a)?)?,
        "add" => host(a)?.plus(&host(b)?)?,
        "sub" => host(a)?.minus(&host(b)?)?,
        "mul" => host(a)?.times(&host(b)?)?,
        "div" => host(a)?.divided_by(&host(b)?)?,
        "mul_chain" => host(a)?.times(&host(b)?)?.times(&host(c)?)?,
        "mul_associated" => host(a)?.times(&host(b)?.times(&host(c)?)?)?,
        "cmp" => {
            return Ok(json!({"comparison": match host(a)?.compare(&host(b)?) {
                std::cmp::Ordering::Less => -1, std::cmp::Ordering::Equal => 0, std::cmp::Ordering::Greater => 1,
            }}))
        }
        "token" => mapping::convert_token_to_decimal(&bigint::parse(a)?, &bigint::parse(b)?)?,
        "pow10" => mapping::exponent_to_big_decimal(&bigint::parse(a)?)?,
        "prices" => {
            let (p0, p1) = mapping::sqrt_price_x96_to_token_prices(
                &bigint::parse(a)?,
                &bigint::parse(b)?,
                &bigint::parse(c)?,
            )?;
            return Ok(json!({"prices":[decimal_result(p0),decimal_result(p1)]}));
        }
        "decimal_to_int" => return Ok(integer_result(host(a)?.to_bigint()?)),
        "int_bits" => {
            let value = BigInt::from(1) << a.parse::<usize>().unwrap();
            bigint::check_bits(&value)?;
            return Ok(json!({"bits":value.bits()}));
        }
        op if op.starts_with("int_") => {
            let lhs = bigint::parse(a)?;
            let result = match op {
                "int_add" => bigint::plus(&lhs, &bigint::parse(b)?)?,
                "int_sub" => bigint::minus(&lhs, &bigint::parse(b)?)?,
                "int_mul" => bigint::times(&lhs, &bigint::parse(b)?)?,
                "int_div" => bigint::divided_by(&lhs, &bigint::parse(b)?)?,
                "int_mod" => bigint::modulo(&lhs, &bigint::parse(b)?)?,
                "int_and" => bigint::bit_and(&lhs, &bigint::parse(b)?)?,
                "int_or" => bigint::bit_or(&lhs, &bigint::parse(b)?)?,
                "int_pow" => bigint::pow(&lhs, b.parse().unwrap())?,
                "int_shl" => bigint::left_shift(&lhs, b.parse().unwrap())?,
                "int_shr" => bigint::right_shift(&lhs, b.parse().unwrap())?,
                "int_i32" => return Ok(json!({"i32":bigint::to_i32_checked(&lhs)?})),
                _ => panic!("unknown integer op {op}"),
            };
            return Ok(integer_result(result));
        }
        op => panic!("unknown operation {op}"),
    };
    Ok(decimal_result(dec))
}
fn outcome(case: &Case) -> Value {
    match evaluate(case) {
        Ok(value) => value,
        Err(error) => json!({"error":error.kind()}),
    }
}

#[test]
fn every_committed_vector_matches_the_real_graph_node() {
    let fixture = fixture();
    assert_eq!(fixture["graph_node_commit"], GRAPH_NODE_COMMIT);
    assert_eq!(fixture["bigdecimal"], "0.1.2");
    assert_eq!(fixture["num_bigint"], "0.2.6");
    let rows = fixture["vectors"].as_array().unwrap();
    assert_eq!(rows.len(), cases::edge_cases().len() + 2048);
    for (index, row) in rows.iter().enumerate() {
        let case: Case = serde_json::from_value(row["case"].clone()).unwrap();
        assert_eq!(outcome(&case), row["result"], "vector {index}: {case:?}");
    }
    assert_eq!(fixture["wasm_boundary"]["api_version"], "0.0.7");
    for row in fixture["wasm_boundary"]["rows"].as_array().unwrap() {
        let raw = bigint::parse(row["raw_integer"].as_str().unwrap()).unwrap();
        assert_eq!(
            decimal_result(GraphDecimal::from_bigint(&raw).unwrap()),
            row["result"]
        );
    }
}

#[test]
fn two_hundred_thousand_results_match_graph_nodes_committed_digest() {
    let fixture = fixture();
    assert_eq!(fixture["sweep"]["seed"], format!("{SWEEP_SEED:016x}"));
    assert_eq!(fixture["sweep"]["count"], SWEEP_COUNT);
    let mut sweep = Sweep::new();
    let mut digest = Sha256::new();
    for _ in 0..SWEEP_COUNT {
        let case = sweep.case();
        digest.update(serde_json::to_vec(&json!({"case":case,"result":outcome(&case)})).unwrap());
        digest.update(b"\n");
    }
    assert_eq!(hex::encode(digest.finalize()), fixture["sweep"]["sha256"]);
}

#[test]
fn iterative_tick_prices_match_graph_node_through_both_extremes() {
    let mut table = mapping::TickPowTable::default();
    for row in fixture()["ticks"].as_array().unwrap() {
        let power = row["power"].as_i64().unwrap() as i32;
        assert_eq!(
            decimal_result(table.price(power).unwrap()),
            row["result"],
            "tick {power}"
        );
        assert_eq!(
            decimal_result(table.price(-power).unwrap()),
            row["reciprocal"],
            "tick -{power}"
        );
    }
}
