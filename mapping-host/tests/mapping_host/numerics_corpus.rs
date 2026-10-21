//! Independent oracle: uses graph's actual scalar types at its pinned git
//! revision. Does not depend on graph-numerics or its normalization code.
//! Shared code supplies ONLY input vectors and the deterministic input PRNG.
use graph::data::store::scalar::{BigDecimal, BigInt};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{path::PathBuf, str::FromStr};

#[path = "../../../crates/graph-numerics/tests/support/cases.rs"]
mod cases;
use cases::{Case, Sweep, SWEEP_COUNT, SWEEP_SEED};

mod deployed_i32;

type OracleResult<T> = Result<T, &'static str>;

fn range(value: BigDecimal) -> OracleResult<BigDecimal> {
    let exponent = -value.as_bigint_and_exponent().1;
    if (i64::from(BigDecimal::MIN_EXP)..=i64::from(BigDecimal::MAX_EXP)).contains(&exponent) {
        Ok(value)
    } else {
        Err("exponent_out_of_range")
    }
}

fn cross(value: BigDecimal) -> OracleResult<BigDecimal> {
    let (coefficient, scale) = value.as_bigint_and_exponent();
    let coefficient = BigInt::from_signed_bytes_le(&coefficient.to_signed_bytes_le()).unwrap();
    range(BigDecimal::new(coefficient, -scale))
}

fn host(value: &str) -> OracleResult<BigDecimal> {
    cross(BigDecimal::from_str(value).map_err(|_| "invalid_decimal")?)
}
fn integer(value: &str) -> OracleResult<BigInt> {
    BigInt::from_str(value).map_err(|_| "invalid_integer")
}
fn raw(value: &str) -> OracleResult<BigDecimal> {
    range(BigDecimal::new(integer(value)?, 0))
}
fn decimal_result(value: BigDecimal) -> Value {
    let (coefficient, scale) = value.as_bigint_and_exponent();
    let bytes = if coefficient == 0.into() {
        Vec::new()
    } else {
        coefficient.to_signed_bytes_be()
    };
    let fixed = value.normalized().as_bigint_and_exponent() == (coefficient.clone(), scale);
    json!({"coefficient": coefficient.to_string(), "scale": scale,
        "wire": hex::encode(bytes), "fixed": fixed,
        "display_sha256": hex::encode(Sha256::digest(value.to_string().as_bytes()))})
}
fn integer_result(value: BigInt) -> Value {
    let bytes = if value == 0.into() {
        Vec::new()
    } else {
        let mut bytes = value.to_signed_bytes_le();
        bytes.reverse();
        bytes
    };
    json!({"integer": value.to_string(), "wire": hex::encode(bytes)})
}
fn divide(a: BigDecimal, b: BigDecimal) -> OracleResult<BigDecimal> {
    if b == 0.into() {
        Err("decimal_divide_by_zero")
    } else {
        cross(a / b)
    }
}
fn pow10(count: &str) -> OracleResult<BigDecimal> {
    let count: u8 = count.parse().map_err(|_| "token_decimals_out_of_range")?;
    // Deliberately the deployed loop, not the implementation's direct exponent.
    let mut value = host("1")?;
    for _ in 0..count {
        value = cross(value * host("10")?)?;
    }
    Ok(value)
}
fn evaluate(case: &Case) -> OracleResult<Value> {
    let a = case.a.as_str();
    let b = case.b.as_deref().unwrap_or("");
    let c = case.c.as_deref().unwrap_or("");
    let dec = match case.op.as_str() {
        "host_string" => host(a)?,
        "db_string" => range(BigDecimal::from_str(a).map_err(|_| "invalid_decimal")?)?,
        "host_long_string" | "db_long_string" => {
            let count = a.parse::<usize>().unwrap();
            let text = format!("{b}{}e-{}", "1".repeat(count), count - 1);
            if case.op == "host_long_string" {
                host(&text)?
            } else {
                range(BigDecimal::from_str(&text).map_err(|_| "invalid_decimal")?)?
            }
        }
        "raw_int" => raw(a)?,
        "add" => cross(host(a)? + host(b)?)?,
        "sub" => cross(host(a)? - host(b)?)?,
        "mul" => cross(host(a)? * host(b)?)?,
        "div" => divide(host(a)?, host(b)?)?,
        "mul_chain" => cross(cross(host(a)? * host(b)?)? * host(c)?)?,
        "mul_associated" => cross(host(a)? * cross(host(b)? * host(c)?)?)?,
        "cmp" => {
            return Ok(json!({"comparison": match host(a)?.cmp(&host(b)?) {
                std::cmp::Ordering::Less => -1, std::cmp::Ordering::Equal => 0, std::cmp::Ordering::Greater => 1,
            }}))
        }
        "token" => {
            if b == "0" {
                raw(a)?
            } else {
                divide(raw(a)?, pow10(b)?)?
            }
        }
        "pow10" => pow10(a)?,
        "prices" => {
            let squared = integer(a)? * integer(a)?;
            let q192 = BigInt::from(2).pow(192).unwrap();
            let price1 = divide(
                cross(divide(BigDecimal::new(squared, 0), BigDecimal::new(q192, 0))? * pow10(b)?)?,
                pow10(c)?,
            )?;
            let price0 = if price1 == 0.into() {
                BigDecimal::zero()
            } else {
                divide(host("1")?, price1.clone())?
            };
            return Ok(json!({"prices": [decimal_result(price0),decimal_result(price1)]}));
        }
        "decimal_to_int" => {
            return host(a)?
                .to_bigint()
                .map(integer_result)
                .map_err(|_| "non_integer_decimal")
        }
        "int_bits" => {
            let bit: usize = a.parse().unwrap();
            let mut bytes = vec![0u8; bit / 8 + 1];
            bytes[bit / 8] = 1 << (bit % 8);
            return BigInt::from_unsigned_bytes_le(&bytes)
                .map(|n| json!({"bits": n.bits()}))
                .map_err(|_| "integer_too_big");
        }
        op if op.starts_with("int_") => {
            let lhs = integer(a)?;
            let result = match op {
                "int_add" => lhs + integer(b)?,
                "int_sub" => lhs - integer(b)?,
                "int_mul" => lhs * integer(b)?,
                "int_div" => {
                    let rhs = integer(b)?;
                    if rhs == 0.into() {
                        return Err("integer_divide_by_zero");
                    }
                    lhs / rhs
                }
                "int_mod" => {
                    let rhs = integer(b)?;
                    if rhs == 0.into() {
                        return Err("integer_remainder_by_zero");
                    }
                    lhs % rhs
                }
                "int_and" => lhs & integer(b)?,
                "int_or" => lhs | integer(b)?,
                "int_pow" => lhs.pow(b.parse().unwrap()).map_err(|_| "integer_too_big")?,
                "int_shl" => lhs << b.parse::<u8>().unwrap(),
                "int_shr" => lhs >> b.parse::<u8>().unwrap(),
                // Execute the deployed AssemblyScript method. Its sign-byte
                // check differs from a mathematical signed i32 range check.
                "int_i32" => {
                    return deployed_i32::convert(&lhs).map(|n| json!({"i32":n}));
                }
                _ => panic!("unknown integer op {op}"),
            };
            let result = BigInt::from_signed_bytes_le(&result.to_signed_bytes_le())
                .map_err(|_| "integer_too_big")?;
            return Ok(integer_result(result));
        }
        op => panic!("unknown operation {op}"),
    };
    Ok(decimal_result(dec))
}
fn outcome(case: &Case) -> Value {
    match evaluate(case) {
        Ok(value) => value,
        Err(error) => json!({"error":error}),
    }
}

#[test]
fn graph_node_numerics_corpus() {
    let mut vectors = cases::edge_cases();
    let mut random = Sweep::new();
    for _ in 0..2048 {
        vectors.push(random.case());
    }
    let rows: Vec<_> = vectors
        .into_iter()
        .map(|case| {
            let result = outcome(&case);
            json!({"case":case,"result":result})
        })
        .collect();
    // Commit every result of the large sweep without a multi-megabyte fixture.
    // The portable crate repeats the exact input stream and checks this digest.
    let mut sweep = Sweep::new();
    let mut digest = Sha256::new();
    for _ in 0..SWEEP_COUNT {
        let case = sweep.case();
        digest.update(serde_json::to_vec(&json!({"case":case,"result":outcome(&case)})).unwrap());
        digest.update(b"\n");
    }
    let mut ticks = Vec::new();
    let base = host("1.0001").unwrap();
    let mut value = host("1").unwrap();
    for power in 0..=887_272 {
        if power > 0 {
            value = cross(value * base.clone()).unwrap();
        }
        if power <= 64 || power % 1024 == 0 || power >= 887_271 {
            ticks.push(json!({"power":power,"result":decimal_result(value.clone()),
                "reciprocal":decimal_result(divide(host("1").unwrap(),value.clone()).unwrap())}));
        }
    }
    let fixture = json!({
        "schema":"pinax.graph-numerics.corpus/v1",
        "graph_node_commit":"77823b5a7adc4eac4abf03202c8dd7cb00dea31d",
        "bigdecimal":"0.1.2", "num_bigint":"0.2.6",
        "vectors":rows,
        "sweep":{"seed":format!("{SWEEP_SEED:016x}"),"count":SWEEP_COUNT,"sha256":hex::encode(digest.finalize())},
        "ticks":ticks,
        "wasm_boundary": {"api_version":"0.0.7","conversion":"FromAscObj<AscBigDecimal>","rows":wasm_boundary::rows()},
        "mapping_i32": {"wasm_sha256":deployed_i32::POOL_SHA256,"function":deployed_i32::METHOD,
            "method":"execute the original function body with one additional export; only error diagnostic imports are mocked"},
    });
    let bytes = format!("{}\n", serde_json::to_string_pretty(&fixture).unwrap());
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../crates/graph-numerics/fixtures/graph-node-v0.44-numerics.json");
    if std::env::var_os("UPDATE_NUMERICS_CORPUS").as_deref() == Some(std::ffi::OsStr::new("1")) {
        std::fs::write(&path, &bytes).unwrap();
    }
    assert_eq!(
        std::fs::read_to_string(path).unwrap(),
        bytes,
        "real Graph Node corpus changed; investigate before regenerating"
    );
}

/// A byte heap is enough to exercise Graph Node's actual API 0.0.7 decoder.
/// Only allocation/storage is mocked; Asc headers, arrays, pointers and the
/// FromAscObj implementation are Graph Node's production code.
mod wasm_boundary {
    use super::*;
    use graph::runtime::{
        asc_new, gas::GasCounter, AscHeap, DeterministicHostError, FromAscObj, HostExportError,
        IndexForAscTypeId,
    };
    use graph_runtime_wasm::asc_abi::class::AscBigDecimal;
    use std::mem::MaybeUninit;

    struct Heap {
        bytes: Vec<u8>,
        version: graph::semver::Version,
    }
    #[async_trait::async_trait]
    impl AscHeap for Heap {
        async fn raw_new(
            &mut self,
            bytes: &[u8],
            _: &GasCounter,
        ) -> Result<u32, DeterministicHostError> {
            let pointer = u32::try_from(self.bytes.len()).unwrap();
            self.bytes.extend_from_slice(bytes);
            Ok(pointer)
        }
        fn read<'a>(
            &self,
            offset: u32,
            buffer: &'a mut [MaybeUninit<u8>],
            _: &GasCounter,
        ) -> Result<&'a mut [u8], DeterministicHostError> {
            let bytes = self
                .bytes
                .get(offset as usize..offset as usize + buffer.len())
                .ok_or_else(|| {
                    DeterministicHostError::from(graph::anyhow::anyhow!("test heap bounds"))
                })?;
            for (destination, byte) in buffer.iter_mut().zip(bytes) {
                destination.write(*byte);
            }
            // SAFETY: Every element of this exact buffer was initialized above;
            // MaybeUninit<u8> has the same layout and alignment as u8.
            Ok(unsafe {
                std::slice::from_raw_parts_mut(buffer.as_mut_ptr().cast::<u8>(), buffer.len())
            })
        }
        fn read_u32(&self, offset: u32, _: &GasCounter) -> Result<u32, DeterministicHostError> {
            let bytes = self
                .bytes
                .get(offset as usize..offset as usize + 4)
                .ok_or_else(|| {
                    DeterministicHostError::from(graph::anyhow::anyhow!("test heap bounds"))
                })?;
            Ok(u32::from_le_bytes(bytes.try_into().unwrap()))
        }
        fn api_version(&self) -> &graph::semver::Version {
            &self.version
        }
        async fn asc_type_id(&mut self, index: IndexForAscTypeId) -> Result<u32, HostExportError> {
            Ok(index as u32)
        }
    }

    pub fn rows() -> Vec<Value> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .build()
            .unwrap();
        runtime.block_on(async {
            let gas = GasCounter::new(graph::components::metrics::gas::GasMetrics::mock());
            let mut heap = Heap {
                bytes: vec![0; 16],
                version: graph::semver::Version::new(0, 0, 7),
            };
            let mut rows = Vec::new();
            for text in [
                "-83076749736557242056487941267521535999",
                "-83076749736557242056487941267521536000",
                "-83076749736557242056487941267521536001",
                "-85070591730234615865843651857942052863",
            ] {
                let value = AscBigDecimal {
                    digits: asc_new(&mut heap, &integer(text).unwrap(), &gas)
                        .await
                        .unwrap(),
                    exp: asc_new(&mut heap, &BigInt::from(0), &gas).await.unwrap(),
                };
                let decoded = BigDecimal::from_asc_obj(value, &heap, &gas, 0).unwrap();
                assert_eq!(
                    decimal_result(decoded.clone()),
                    decimal_result(raw(text).unwrap())
                );
                rows.push(json!({"raw_integer":text,"result":decimal_result(decoded)}));
            }
            rows
        })
    }
}
