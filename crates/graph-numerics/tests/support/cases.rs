//! Inputs only. Shared with the independent Graph Node generator, never results
//! or normalization/arithmetic code.
use serde::{Deserialize, Serialize};

pub const SWEEP_SEED: u64 = 0x0A3E_0D00_2026_1021;
pub const SWEEP_COUNT: usize = 200_000;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Case {
    pub op: String,
    pub a: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub b: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub c: Option<String>,
}

impl Case {
    pub fn new(op: &str, a: &str, b: Option<&str>) -> Self {
        Self {
            op: op.into(),
            a: a.into(),
            b: b.map(Into::into),
            c: None,
        }
    }
}

pub fn edge_cases() -> Vec<Case> {
    let mut cases = Vec::new();
    for sign in ["", "-"] {
        for op in ["host_long_string", "db_long_string"] {
            cases.push(Case::new(op, "132000", Some(sign)));
        }
    }
    for s in [
        "0",
        "-0",
        "1",
        "-1",
        "2",
        "10",
        "1000000",
        "0.01",
        "1.0001",
        "1.23000",
        "+12.5",
        ".5",
        "123.",
        "-0.33333333333333333333333333333333333",
        "-1958.2627366648723548155211868460794",
        "-85070591730234615865843651857942052863",
        "-83076749736557242056487941267521535",
        "-83076749736557242056487941267521536",
        "-83076749736557242056487941267521536001",
        "-83076749736557242056487941267521536000",
        "-83076749736557242056487941267521535999",
        "99999999999999999999999999999999999",
        "-99999999999999999999999999999999999",
        "1e-6143",
        "1e6144",
        "123e6144",
        "1e-6144",
        "1e6145",
        "0e9999",
        "NaN",
        "1.2.3",
        "",
        "--2",
        "1efoo",
    ] {
        cases.push(Case::new("host_string", s, None));
        cases.push(Case::new("db_string", s, None));
    }
    for s in [
        "0",
        "1",
        "-1",
        "83076749736557242056487941267521535",
        "-83076749736557242056487941267521535",
        "-83076749736557242056487941267521536",
        "-85070591730234615865843651857942052863",
        "-83076749736557242056487941267521536001",
        "-83076749736557242056487941267521536000",
        "-83076749736557242056487941267521535999",
        "6277101735386680763835789423207666416102355444464034512896",
    ] {
        cases.push(Case::new("raw_int", s, None));
        cases.push(Case::new("token", s, Some("0")));
        cases.push(Case::new("token", s, Some("18")));
    }
    for (a, b) in [
        ("1", "3"),
        ("-1", "3"),
        ("1", "-3"),
        ("-1", "-3"),
        ("0", "0"),
        ("1", "0"),
        ("1e6144", "10"),
        ("1e-6143", "0.1"),
        ("1e6144", "1e-6143"),
        (
            "-0.86833597019960473614471136709664557",
            "2255.190161262956454194198227130777",
        ),
        ("9999999999999999999999999999999999", "1"),
        ("1.000000000000000000000000000000001", "1"),
        ("-83076749736557242056487941267521535", "1"),
    ] {
        for op in ["add", "sub", "mul", "div", "cmp"] {
            cases.push(Case::new(op, a, Some(b)));
        }
    }
    cases.push(Case {
        op: "mul_chain".into(),
        a: "-1958.23222".into(),
        b: Some("0.000443428497055167816687599679621575".into()),
        c: Some("2255.190161262956454194198227130777".into()),
    });
    cases.push(Case {
        op: "mul_associated".into(),
        a: "-1958.23222".into(),
        b: Some("0.000443428497055167816687599679621575".into()),
        c: Some("2255.190161262956454194198227130777".into()),
    });
    for (a, b) in [
        ("7", "3"),
        ("-7", "3"),
        ("7", "-3"),
        ("-7", "-3"),
        ("-1", "2"),
        ("1", "0"),
        ("0", "0"),
        (
            "79228162514264337593543950336",
            "79228162514264337593543950336",
        ),
    ] {
        for op in [
            "int_add", "int_sub", "int_mul", "int_div", "int_mod", "int_and", "int_or",
        ] {
            cases.push(Case::new(op, a, Some(b)));
        }
    }
    for a in [
        "0",
        "1",
        "-1",
        "2147483647",
        "2147483648",
        "-2147483648",
        "-2147483649",
        "4294967295",
        "4294967296",
        "-4294967295",
        "-4294967296",
        "-4294967297",
    ] {
        cases.push(Case::new("int_i32", a, None));
        for op in ["int_pow", "int_shl", "int_shr"] {
            cases.push(Case::new(op, a, Some("8")));
        }
    }
    for bits in ["435410", "435411", "435412"] {
        cases.push(Case::new("int_bits", bits, None));
    }
    for d in 0..=255 {
        cases.push(Case::new("pow10", &d.to_string(), None));
    }
    for (s, d0, d1) in [
        ("79228162514264337593543950336", "18", "6"),
        ("0", "18", "18"),
        (
            "1461446703485210103287273052203988822378723970342",
            "6",
            "18",
        ),
    ] {
        cases.push(Case {
            op: "prices".into(),
            a: s.into(),
            b: Some(d0.into()),
            c: Some(d1.into()),
        });
    }
    for s in [
        "1.5",
        "-2",
        "0",
        "1e100",
        "-85070591730234615865843651857942052863",
    ] {
        cases.push(Case::new("decimal_to_int", s, None));
    }
    cases
}

pub struct Sweep(u64);
impl Sweep {
    pub fn new() -> Self {
        Self(SWEEP_SEED)
    }
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn operand(&mut self) -> String {
        let length = 1 + self.next() % 80;
        let mut s = if self.next() & 1 == 0 {
            String::from("-")
        } else {
            String::new()
        };
        s.push((b'1' + (self.next() % 9) as u8) as char);
        for _ in 1..length {
            s.push((b'0' + (self.next() % 10) as u8) as char);
        }
        let exp = (self.next() % 257) as i64 - 128;
        s.push_str(&format!("e{exp}"));
        s
    }
    pub fn case(&mut self) -> Case {
        let op = [
            "add",
            "sub",
            "mul",
            "div",
            "cmp",
            "host_string",
            "db_string",
        ][(self.next() % 7) as usize];
        Case {
            op: op.into(),
            a: self.operand(),
            b: Some(self.operand()),
            c: None,
        }
    }
}
