use aerodrome_extractor_audit::{call_retval, checks, compare, request, Retval};
use aerodrome_extractor_core::config::{Config, CONTRACT, PARAMS};
use aerodrome_extractor_pb::v1 as p;
use serde_json::json;
mod support;

#[test]
fn existing_receipt_directory_is_never_overwritten() {
    use prost::Message;
    let temp = tempfile::tempdir().unwrap();
    let input = temp.path().join("input.pb");
    std::fs::write(&input, block(Default::default()).encode_to_vec()).unwrap();
    let output = temp.path().join("existing");
    std::fs::create_dir(&output).unwrap();
    std::fs::write(output.join("sentinel"), b"preserve").unwrap();
    let result = std::process::Command::new(env!("CARGO_BIN_EXE_aerodrome-extractor-audit"))
        .args([
            "--input",
            input.to_str().unwrap(),
            "--output",
            output.to_str().unwrap(),
        ])
        .env("BASE_ARCHIVE_RPC_URL", "https://invalid.invalid")
        .output()
        .unwrap();
    assert_eq!(result.status.code(), Some(4));
    assert!(String::from_utf8_lossy(&result.stderr).contains("output must be a new directory"));
    assert_eq!(std::fs::read(output.join("sentinel")).unwrap(), b"preserve");
    assert_eq!(std::fs::read_dir(output).unwrap().count(), 1);
}

#[test]
fn first_pool_storage_pipeline_and_raw_metadata_match_twelve_retained_calls() {
    let block = support::first_pool();
    let cfg = Config::parse(PARAMS).unwrap();
    let checks = checks(&block, &cfg, false).unwrap();
    assert_eq!(checks.len(), 12);
    let oracle = support::oracle();
    for check in checks {
        let entries = oracle["entries"].as_array().unwrap();
        let entry = entries
            .iter()
            .find(|e| {
                e["address"] == format!("0x{}", hex::encode(check.address))
                    && e["calldata"] == format!("0x{}", hex::encode(&check.calldata))
            })
            .unwrap();
        assert_eq!(
            entry["block_hash"],
            format!("0x{}", hex::encode(&block.hash))
        );
        let actual = Retval::Value {
            data: entry["retval"]["data"]
                .as_str()
                .unwrap()
                .strip_prefix("0x")
                .unwrap()
                .into(),
        };
        compare(&check, &actual).unwrap();
    }
}

fn block(calls: p::CallAnswers) -> p::ExtractorBlock {
    p::ExtractorBlock {
        number: 13_899_663,
        hash: vec![1; 32],
        parent_hash: vec![2; 32],
        contract: CONTRACT.into(),
        audit: Some(Default::default()),
        calls: Some(calls),
        ..Default::default()
    }
}
fn value(bytes: Vec<u8>) -> Option<p::RawRetval> {
    Some(p::RawRetval {
        kind: Some(p::raw_retval::Kind::Value(bytes)),
    })
}
#[test]
fn archive_errors_cannot_be_misclassified_as_mapping_reverts() {
    assert_eq!(
        call_retval(
            &json!({"jsonrpc":"2.0","id":7,"error":{"code":3,"message":"execution reverted: ID"}}),
            7
        )
        .unwrap(),
        Retval::Reverted
    );
    assert_eq!(
        call_retval(&json!({"jsonrpc":"2.0","id":7,"result":"0x"}), 7).unwrap(),
        Retval::Reverted
    );
    for (code, message) in [
        (3, "execution aborted (timeout)"),
        (-32000, "execution reverted"),
        (-32001, "header not found"),
        (-32005, "rate limit exceeded"),
    ] {
        assert!(call_retval(
            &json!({"jsonrpc":"2.0","id":7,"error":{"code":code,"message":message}}),
            7
        )
        .is_err());
    }
    for response in [
        json!({"jsonrpc":"2.0","id":8,"result":"0x01"}),
        json!({"jsonrpc":"2.0","id":7,"result":"0x0"}),
        json!({"jsonrpc":"2.0","id":7,"result":"0x01","error":{"code":3,"message":"execution reverted"}}),
    ] {
        assert!(call_retval(&response, 7).is_err());
    }
}
#[test]
fn erc20_raw_bytes_masks_and_duplicate_keys_are_checked() {
    let cfg = Config::parse(PARAMS).unwrap();
    let erc = p::Erc20Answer {
        token: vec![3; 20],
        symbol: value(vec![1]),
        name: value(vec![2]),
        total_supply: value(vec![3]),
        decimals: value(vec![4]),
        ..Default::default()
    };
    let mut b = block(p::CallAnswers {
        erc20: vec![erc.clone()],
        ..Default::default()
    });
    let c = checks(&b, &cfg, true).unwrap();
    assert_eq!(c.len(), 4);
    assert!(c.windows(2).all(|w| w[0].calldata < w[1].calldata));
    let expected = match &c[0].expected {
        aerodrome_extractor_audit::Expected::Raw(r) => r.clone(),
        _ => panic!(),
    };
    compare(&c[0], &expected).unwrap();
    assert!(compare(&c[0], &Retval::Reverted).is_err());
    let r = request(&c[0], &b.hash, 9);
    assert_eq!(
        r["params"][1],
        json!({"blockHash":format!("0x{}",hex::encode(&b.hash)),"requireCanonical":true})
    );
    b.calls.as_mut().unwrap().erc20[0].rpc_failed_mask = 1;
    assert!(checks(&b, &cfg, true).is_err());
    b.calls.as_mut().unwrap().erc20[0] = erc.clone();
    b.calls.as_mut().unwrap().erc20.push(erc);
    assert!(checks(&b, &cfg, true).is_err());
    b.calls = None;
    assert!(checks(&b, &cfg, true).is_err());
}
#[test]
fn consumed_tick_fields_are_signed_and_unconsumed_words_do_not_affect_comparison() {
    let cfg = Config::parse(PARAMS).unwrap();
    let b = block(p::CallAnswers {
        ticks: vec![p::TickAnswer {
            pool: vec![3; 20],
            tick: -1,
            staked_liquidity_net: vec![255; 16],
            fee_growth_outside0_x128: vec![5; 32],
            ..Default::default()
        }],
        ..Default::default()
    });
    let c = checks(&b, &cfg, false).unwrap();
    let mut actual = vec![0; 320];
    actual[64..96].fill(255);
    actual[96..128].fill(5);
    let ret = |v: &[u8]| Retval::Value {
        data: hex::encode(v),
    };
    compare(&c[0], &ret(&actual)).unwrap();
    actual[0] = 123;
    compare(&c[0], &ret(&actual)).unwrap();
    actual[64] = 0;
    assert!(compare(&c[0], &ret(&actual)).is_err());
    assert!(compare(&c[0], &ret(&actual[..128])).is_err());
}
#[test]
fn every_position_consumed_field_and_revert_is_checked() {
    let cfg = Config::parse(PARAMS).unwrap();
    let p = p::PositionValue {
        token0: vec![1; 20],
        token1: vec![2; 20],
        tick_spacing: 1,
        tick_lower: -1,
        tick_upper: 1,
        fee_growth_inside0_last_x128: vec![3; 32],
        fee_growth_inside1_last_x128: vec![4; 32],
        ..Default::default()
    };
    let mut b = block(p::CallAnswers {
        positions: vec![p::PositionAnswer {
            token_id: vec![1],
            result: Some(p::position_answer::Result::Value(p)),
        }],
        ..Default::default()
    });
    let c = checks(&b, &cfg, false).unwrap();
    let mut actual = vec![0; 384];
    if let aerodrome_extractor_audit::Expected::Words { consumed, .. } = &c[0].expected {
        for (index, word) in consumed {
            actual[index * 32..(index + 1) * 32].copy_from_slice(word);
        }
        compare(
            &c[0],
            &Retval::Value {
                data: hex::encode(&actual),
            },
        )
        .unwrap();
        for (index, _) in consumed {
            let mut changed = actual.clone();
            changed[index * 32 + 31] ^= 1;
            assert!(compare(
                &c[0],
                &Retval::Value {
                    data: hex::encode(changed)
                }
            )
            .is_err());
        }
    } else {
        panic!()
    }
    b.calls.as_mut().unwrap().positions[0].result =
        Some(p::position_answer::Result::Reverted(Default::default()));
    let c = checks(&b, &cfg, false).unwrap();
    compare(&c[0], &Retval::Reverted).unwrap();
    assert!(compare(
        &c[0],
        &Retval::Value {
            data: hex::encode(actual)
        }
    )
    .is_err());
    b.calls.as_mut().unwrap().positions[0].token_id = vec![0, 1];
    assert!(checks(&b, &cfg, false).is_err());
}
