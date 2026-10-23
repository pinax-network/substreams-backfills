//! Sequential HTTPS RPC. No redirects, unbounded body reads or URL diagnostics.
use crate::{Result, Rpc, MAX_RESPONSE};
use serde_json::Value;
use std::{
    io::{self, Read},
    net::ToSocketAddrs,
    sync::mpsc,
    time::{Duration, Instant},
};

pub struct HttpsRpc {
    url: String,
}
impl HttpsRpc {
    pub fn new(url: String) -> Result<Self> {
        if !url.starts_with("https://") || url.contains(['\r', '\n']) {
            return Err("archive RPC requires HTTPS".into());
        }
        Ok(Self { url })
    }
}
impl Rpc for HttpsRpc {
    fn request(&mut self, body: &Value, timeout: Duration) -> Result<Vec<u8>> {
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or("RPC deadline overflow")?;
        // ureq's request deadline bounds connect/TLS/HTTP reads, but its default
        // system DNS call has no timeout. Bound the resolver separately. A DNS
        // timeout aborts the whole CLI; at most one unresolved OS worker can be
        // left until process exit, never one new worker per retry (there are none).
        let agent = ureq::AgentBuilder::new()
            .redirects(0)
            .timeout(timeout)
            .resolver(move |name: &str| {
                let name = name.to_owned();
                let (send, receive) = mpsc::sync_channel(1);
                std::thread::spawn(move || {
                    let result = name.to_socket_addrs().map(|v| v.collect::<Vec<_>>());
                    let _ = send.send(result);
                });
                let left = deadline
                    .checked_duration_since(Instant::now())
                    .ok_or_else(|| io::Error::new(io::ErrorKind::TimedOut, "RPC DNS deadline"))?;
                receive
                    .recv_timeout(left)
                    .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "RPC DNS deadline"))?
            })
            .build();
        let request = crate::bounded_json(body, 4096).map_err(|_| "RPC request exceeds bound")?;
        let response = agent
            .post(&self.url)
            .set("Content-Type", "application/json")
            .send_bytes(&request)
            .map_err(|_| "archive RPC transport/HTTP failure")?;
        if let Some(length) = response.header("Content-Length") {
            let length = length
                .parse::<u64>()
                .map_err(|_| "invalid RPC response length")?;
            if length > MAX_RESPONSE as u64 {
                return Err("RPC response exceeds byte limit".into());
            }
        }
        let mut bytes = Vec::new();
        response
            .into_reader()
            .take(MAX_RESPONSE as u64 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "archive RPC body read failed")?;
        if bytes.len() > MAX_RESPONSE || Instant::now() >= deadline {
            return Err("RPC response exceeds byte/time limit".into());
        }
        Ok(bytes)
    }
}
