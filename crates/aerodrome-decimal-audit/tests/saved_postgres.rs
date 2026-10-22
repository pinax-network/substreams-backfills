//! Explicit owned-cluster test; no ambient database routing or credentials.
use aerodrome_decimal_audit::saved::{scan, Request, SqlPage};
use sha2::{Digest, Sha256};
use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};
struct Pg {
    root: tempfile::TempDir,
    bin: PathBuf,
}
impl Pg {
    fn cmd(&self, name: &str) -> Command {
        let mut c = Command::new(self.bin.join(name));
        c.env_clear().env("LC_ALL", "C");
        c
    }
    fn sql(&self, sql: &str) -> std::process::Output {
        let mut child = self
            .cmd("psql")
            .args([
                "-X",
                "-q",
                "-t",
                "-A",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                self.root.path().to_str().unwrap(),
                "-U",
                "audit",
                "-d",
                "postgres",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(sql.as_bytes())
            .unwrap();
        child.wait_with_output().unwrap()
    }
}
impl Drop for Pg {
    fn drop(&mut self) {
        let _ = self
            .cmd("pg_ctl")
            .args([
                "-D",
                self.root.path().join("data").to_str().unwrap(),
                "-m",
                "immediate",
                "-w",
                "stop",
            ])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}
#[test]
#[ignore = "requires explicit PG16_BIN; creates only its own local Unix-socket cluster"]
fn actual_postgres_numeric_text_preserves_the_non_fixed_point_and_page_bounds() {
    let bin = PathBuf::from(std::env::var_os("PG16_BIN").expect("PG16_BIN required"));
    assert!(bin.is_absolute());
    let pg = Pg {
        root: tempfile::Builder::new()
            .prefix("qn2-pg-")
            .tempdir_in(Path::new("/tmp"))
            .unwrap(),
        bin,
    };
    let version = pg.cmd("postgres").arg("--version").output().unwrap();
    assert!(String::from_utf8_lossy(&version.stdout).contains(" 16."));
    let init = pg
        .cmd("initdb")
        .args([
            "-D",
            pg.root.path().join("data").to_str().unwrap(),
            "-U",
            "audit",
            "--auth=trust",
            "--no-locale",
            "--encoding=UTF8",
        ])
        .output()
        .unwrap();
    assert!(
        init.status.success(),
        "{}",
        String::from_utf8_lossy(&init.stderr)
    );
    let options = format!("-F -h '' -k {}", pg.root.path().display());
    let start = pg
        .cmd("pg_ctl")
        .args([
            "-D",
            pg.root.path().join("data").to_str().unwrap(),
            "-l",
            pg.root.path().join("server.log").to_str().unwrap(),
            "-o",
            &options,
            "-w",
            "start",
        ])
        .output()
        .unwrap();
    assert!(
        start.status.success(),
        "{}",
        String::from_utf8_lossy(&start.stderr)
    );
    let ddl = include_str!("../fixtures/graph-node-swap.sql").replace("\"sgd0\"", "\"sgd2\"");
    let seed = "INSERT INTO sgd2.swap (vid,block_range,id,\"transaction\",timestamp,pool,token_0,token_1,sender,recipient,origin,amount_0,amount_1,amount_usd,sqrt_price_x96,tick,log_index) SELECT v.vid,v.rng::int4range,v.id,'tx',1,'pool','token0','token1',decode('','hex'),decode('','hex'),decode('','hex'),v.amount::numeric,1,0,0,0,NULL FROM (VALUES (-1,'swap-a','[13843704,)','-85070591730234615865843651857942052000.000'),(2,'swap-b','[13843704,13843705)','-1'),(3,'later','[13843706,)','-85070591730234615865843651857942052000')) AS v(vid,id,rng,amount);";
    let init = pg.sql(&format!("CREATE SCHEMA sgd2;\n{ddl}\n{seed}"));
    assert!(
        init.status.success(),
        "{}",
        String::from_utf8_lossy(&init.stderr)
    );
    let page = SqlPage {
        format: "pinax.aerodrome.qn2-sql-page/v1".into(),
        schema: "sgd2".into(),
        min_vid: -1,
        max_vid: 3,
        from_block: 13843704,
        to_block: 13843705,
        max_rows: 10,
    };
    let output = pg.sql(&page.sql().unwrap());
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let request = Request {
        format: "pinax.aerodrome.qn2-saved-request/v1".into(),
        page: page.clone(),
        input: pg.root.path().join("observed.jsonl"),
        input_sha256: hex::encode(Sha256::digest(&output.stdout)),
        input_bytes: output.stdout.len() as u64,
    };
    let report = scan(output.stdout.as_slice(), request).unwrap();
    assert_eq!(report.rows, 2);
    assert_eq!(report.saved_non_fixed_points, 1);
    assert_eq!(report.witnesses[0].saved_tuple.scale, -3);
    let denied = pg.sql(
        &page
            .sql()
            .unwrap()
            .replace("ROLLBACK;", "DELETE FROM sgd2.swap; ROLLBACK;"),
    );
    assert!(!denied.status.success());
    assert!(String::from_utf8_lossy(&denied.stderr).contains("read-only"));
}
