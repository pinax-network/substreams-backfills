use crate::{layout::LAYOUT_ID, Address};
use std::collections::BTreeMap;
pub const DEPLOYMENT: &str = "QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV";
pub const INITIAL_BLOCK: u64 = 13_843_704;
pub const CONTRACT: &str = "pinax.aerodrome.slipstream.base.extractor/v1";
pub const PARAMS: &str = "network=base;deployment=QmasYjypV6nTLp4iNH4Vjf7fksRNxAkAskqDdKf2DCsQkV;factory=0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a;factory_start=13843704;npm=0x827922686190790b37229fd06084350e74485b72;npm_start=13843719;pool_implementation=0xec8e5342b19977b4ef8892e02d8daecfa1315831;storage_layout=slipstream@37eead2c7e5302a204dec78bfa0775bbb8ff48a2;walk_spacing=1:1,50:10,100:10,200:60,*:200";
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    pub factory: Address,
    pub factory_start: u64,
    pub npm: Address,
    pub npm_start: u64,
    pub pool_implementation: Address,
}
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("extractor configuration refused: {0}")]
pub struct ConfigError(pub String);
fn pairs(params: &str) -> Result<BTreeMap<&str, &str>, ConfigError> {
    let mut out = BTreeMap::new();
    for item in params.split(';') {
        let (key, value) = item
            .split_once('=')
            .ok_or_else(|| ConfigError("expected key=value".into()))?;
        if out.insert(key, value).is_some() {
            return Err(ConfigError(format!("duplicate {key}")));
        }
    }
    Ok(out)
}
fn address(s: &str) -> Result<Address, ConfigError> {
    let s = s
        .strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s);
    let mut result = [0; 20];
    hex::decode_to_slice(s, &mut result).map_err(|_| ConfigError("invalid address".into()))?;
    Ok(result)
}
impl Config {
    pub fn parse(params: &str) -> Result<Self, ConfigError> {
        let actual = pairs(params)?;
        let expected = pairs(PARAMS)?;
        if actual.len() != expected.len() {
            return Err(ConfigError("wrong key set".into()));
        }
        for (key, want) in expected {
            let got = actual
                .get(key)
                .ok_or_else(|| ConfigError(format!("missing {key}")))?;
            let equal = if ["factory", "npm", "pool_implementation"].contains(&key) {
                address(got)? == address(want)?
            } else {
                *got == want
            };
            if !equal {
                return Err(ConfigError(format!("wrong {key}")));
            }
        }
        debug_assert_eq!(actual["storage_layout"], LAYOUT_ID);
        Ok(Self {
            factory: address(actual["factory"])?,
            factory_start: INITIAL_BLOCK,
            npm: address(actual["npm"])?,
            npm_start: 13_843_719,
            pool_implementation: address(actual["pool_implementation"])?,
        })
    }
    pub fn walk_spacing(tick_spacing: i32) -> i32 {
        match tick_spacing {
            1 => 1,
            50 | 100 => 10,
            200 => 60,
            _ => 200,
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_keys_and_values() {
        Config::parse(PARAMS).unwrap();
        for part in PARAMS.split(';') {
            let key = part.split('=').next().unwrap();
            assert!(Config::parse(
                &PARAMS
                    .split(';')
                    .filter(|p| *p != part)
                    .collect::<Vec<_>>()
                    .join(";")
            )
            .is_err());
            assert!(Config::parse(&format!("{PARAMS};{part}")).is_err());
            assert!(Config::parse(&PARAMS.replace(part, &format!("{key}=bad"))).is_err());
        }
        assert!(Config::parse(&format!("{PARAMS};extra=x")).is_err());
        Config::parse(&PARAMS.replace(
            "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
            "5E7BB104D84C7CB9B682AAC2F3D509F5F406809A",
        ))
        .unwrap();
    }
}
