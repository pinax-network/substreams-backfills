use aerodrome_decimal_audit::saved::{classify_text, scan, Request, SqlPage};
use sha2::{Digest, Sha256};
fn page() -> SqlPage {
    SqlPage {
        format: "pinax.aerodrome.qn2-sql-page/v1".into(),
        schema: "sgd2".into(),
        min_vid: -1,
        max_vid: 100,
        from_block: 13843704,
        to_block: 13843705,
        max_rows: 10,
    }
}
fn request(input: &[u8]) -> Request {
    Request {
        format: "pinax.aerodrome.qn2-saved-request/v1".into(),
        page: page(),
        input: "/unused/synthetic.jsonl".into(),
        input_sha256: hex::encode(Sha256::digest(input)),
        input_bytes: input.len() as u64,
    }
}
fn row(vid: i64, amount: &str) -> Vec<u8> {
    let mut bytes=serde_json::to_vec(&serde_json::json!({"vid":vid,"id":"swap-1","block_start":13843704,"amount0":amount,"amount1":"1.00000"})).unwrap();
    bytes.push(b'\n');
    bytes
}
#[test]
fn saved_numeric_is_never_renormalized_before_classification() {
    let value = "-85070591730234615865843651857942052000.000";
    let tuple = classify_text(value).unwrap();
    assert_eq!(tuple.coefficient, "-85070591730234615865843651857942052");
    assert_eq!(tuple.scale, -3);
    assert!(!tuple.accepted_by_block_changes_v1 && !tuple.fixed_point);
    for value in [
        "0",
        "-0.000",
        "1.00",
        "-0.33333333333333333333333333333333333",
        "-1000000000000000000000000000000000000000000",
    ] {
        assert!(classify_text(value).unwrap().fixed_point, "{value}")
    }
    for value in [
        "NaN",
        "Infinity",
        "-Infinity",
        "1e3",
        "+1",
        "01",
        " 1",
        "1.",
        ".1",
        "1.2.3",
    ] {
        assert!(classify_text(value).is_err(), "{value}")
    }
    let input = row(-1, value);
    let report = scan(input.as_slice(), request(&input)).unwrap();
    assert_eq!(report.saved_non_fixed_points, 1);
    assert_eq!(report.witnesses[0].vid, -1);
    assert!(
        !report.query_execution_verified
            && !report.source_database_identity_verified
            && !report.full_range_qn2_closed
    );
}
#[test]
fn sql_is_read_only_bounded_and_rejects_identifiers_or_saturation() {
    let sql = page().sql().unwrap();
    for expected in [
        "BEGIN READ ONLY;",
        "statement_timeout = '5s'",
        "lock_timeout = '1s'",
        "FROM \"sgd2\".\"swap\"",
        "s.vid BETWEEN -1 AND 100",
        "lower(s.block_range) BETWEEN 13843704 AND 13843705",
        "ORDER BY s.vid\nLIMIT 11;\nROLLBACK;",
    ] {
        assert!(sql.contains(expected), "{sql}")
    }
    for schema in ["public", "sgd2;DELETE", "sgd2\"", "sgd", "sgd../../2"] {
        let mut p = page();
        p.schema = schema.into();
        assert!(p.sql().is_err())
    }
    let mut p = page();
    p.max_vid = i64::MAX;
    assert!(p.sql().is_err());
    let input = [row(0, "0"), row(1, "0")].concat();
    let mut r = request(&input);
    r.page.max_rows = 1;
    assert!(scan(input.as_slice(), r).unwrap_err().contains("saturated"));
    for input in [
        [row(1, "0"), row(0, "0")].concat(),
        row(101, "0"),
        b"{}".to_vec(),
        row(1, "NaN"),
    ] {
        assert!(scan(input.as_slice(), request(&input)).is_err())
    }
    let input = row(1, "0");
    let mut r = request(&input);
    r.input_sha256 = "00".repeat(32);
    assert!(scan(input.as_slice(), r).is_err());
}

#[test]
fn query_uses_the_retained_graph_node_physical_mapping_and_ddl() {
    let ddl = include_bytes!("../fixtures/graph-node-swap.sql");
    assert_eq!(
        hex::encode(Sha256::digest(ddl)),
        "ca02db9439114eb9b02892e2e8f7247cfb39c6e171f1f7c96b3bcbdb3a726d02"
    );
    let provenance: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../fixtures/graph-node-swap.provenance.json"
    ))
    .unwrap();
    assert_eq!(
        provenance["graph_node_commit"],
        graph_numerics::GRAPH_NODE_COMMIT
    );
    assert_eq!(
        provenance["schema_sha256"],
        hex::encode(Sha256::digest(include_bytes!(
            "../../../aerodrome-slipstream-base/reference/schema.graphql"
        )))
    );
    let fields = provenance["table"]["fields"].as_array().unwrap();
    let sql = page().sql().unwrap();
    for logical in ["amount0", "amount1"] {
        let physical = fields
            .iter()
            .find(|f| f["graphql_field"] == logical)
            .unwrap()["physical_column"]
            .as_str()
            .unwrap();
        assert_ne!(physical, logical);
        assert!(std::str::from_utf8(ddl)
            .unwrap()
            .contains(&format!("\"{physical}\"")));
        assert!(
            sql.contains(&format!("'{logical}', s.\"{physical}\"::text")),
            "{sql}"
        );
    }
}
