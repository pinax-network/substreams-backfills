//! GitHub release asset fetcher. The repository is private, so every request
//! carries a token from `GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token`.

use std::io::Write;
use std::process::Command;
use std::time::Duration;

use serde::Deserialize;

use crate::evidence::{Asset, EvidenceError, Fetcher, Lock, Result};

const API: &str = "https://api.github.com";
const USER_AGENT: &str = "substreams-backfills-xtask";

#[derive(Debug, Deserialize)]
struct Release {
    tag_name: String,
    assets: Vec<ReleaseAsset>,
}

#[derive(Debug, Deserialize)]
struct ReleaseAsset {
    id: u64,
    name: String,
    size: u64,
}

pub struct GithubFetcher {
    token: String,
    agent: ureq::Agent,
    release: std::cell::OnceCell<Release>,
}

impl GithubFetcher {
    pub fn from_environment() -> Result<GithubFetcher> {
        let token = resolve_token().ok_or_else(|| EvidenceError::Fetch {
            asset: "(auth)".into(),
            detail: "no GitHub token: set GITHUB_TOKEN or GH_TOKEN, or run `gh auth login`".into(),
        })?;
        let agent = ureq::AgentBuilder::new()
            .timeout_connect(Duration::from_secs(30))
            .timeout_read(Duration::from_secs(600))
            .build();
        Ok(GithubFetcher {
            token,
            agent,
            release: std::cell::OnceCell::new(),
        })
    }

    fn release(&self, lock: &Lock) -> Result<&Release> {
        if let Some(r) = self.release.get() {
            return Ok(r);
        }
        let url = format!(
            "{API}/repos/{}/releases/tags/{}",
            lock.repository, lock.release_tag
        );
        let response = self
            .agent
            .get(&url)
            .set("Accept", "application/vnd.github+json")
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("User-Agent", USER_AGENT)
            .call()
            .map_err(|e| EvidenceError::Release(format!("GET {url}: {e}")))?;
        let release: Release = response
            .into_json()
            .map_err(|e| EvidenceError::Release(format!("decode {url}: {e}")))?;
        if release.tag_name != lock.release_tag {
            return Err(EvidenceError::Release(format!(
                "release tag {} does not match lock {}",
                release.tag_name, lock.release_tag
            )));
        }
        let _ = self.release.set(release);
        Ok(self.release.get().expect("set above"))
    }

    /// `(name, size)` pairs as published, for `audit_release_assets`.
    pub fn published_assets(&self, lock: &Lock) -> Result<Vec<(String, u64)>> {
        Ok(self
            .release(lock)?
            .assets
            .iter()
            .map(|a| (a.name.clone(), a.size))
            .collect())
    }
}

impl Fetcher for GithubFetcher {
    fn fetch(&self, lock: &Lock, asset: &Asset, dest: &mut dyn Write) -> Result<()> {
        let release = self.release(lock)?;
        let published = release
            .assets
            .iter()
            .find(|a| a.name == asset.asset)
            .ok_or_else(|| EvidenceError::Fetch {
                asset: asset.asset.clone(),
                detail: format!("not published on release {}", lock.release_tag),
            })?;
        if published.size != asset.bytes {
            return Err(EvidenceError::Fetch {
                asset: asset.asset.clone(),
                detail: format!(
                    "release reports {} bytes, lock expects {}",
                    published.size, asset.bytes
                ),
            });
        }
        let url = format!(
            "{API}/repos/{}/releases/assets/{}",
            lock.repository, published.id
        );
        let response = self
            .agent
            .get(&url)
            .set("Accept", "application/octet-stream")
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("User-Agent", USER_AGENT)
            .call()
            .map_err(|e| EvidenceError::Fetch {
                asset: asset.asset.clone(),
                detail: format!("GET {url}: {e}"),
            })?;
        let mut reader = response.into_reader();
        std::io::copy(&mut reader, dest).map_err(|e| EvidenceError::Fetch {
            asset: asset.asset.clone(),
            detail: e.to_string(),
        })?;
        Ok(())
    }
}

fn resolve_token() -> Option<String> {
    for key in ["GITHUB_TOKEN", "GH_TOKEN"] {
        if let Ok(value) = std::env::var(key) {
            let trimmed = value.trim().to_string();
            if !trimmed.is_empty() {
                return Some(trimmed);
            }
        }
    }
    let output = Command::new("gh").args(["auth", "token"]).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let token = String::from_utf8(output.stdout).ok()?.trim().to_string();
    (!token.is_empty()).then_some(token)
}
