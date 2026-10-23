use crate::Address;
use std::{collections::BTreeSet, ops::RangeInclusive};
/// Conservative superset of the mapping's signed-remainder loop, not a corrected Uniswap algorithm.
pub fn walk_window(old: i32, new: i32, spacing: i32) -> (Option<RangeInclusive<i64>>, i32) {
    assert!(spacing > 0);
    let (o, n, s) = (i64::from(old), i64::from(new), i64::from(spacing));
    (
        ((o - n).abs() / s <= 100).then(|| o.min(n)..=o.max(n) + s - 1),
        new,
    )
}
pub fn walk_candidates(
    pool: &Address,
    old: i32,
    new: i32,
    tick_spacing: i32,
    spacing: i32,
    marker: &impl Fn(&Address, i32) -> bool,
) -> (Vec<i32>, u32) {
    assert!(tick_spacing > 0);
    let (window, endpoint) = walk_window(old, new, spacing);
    let mut probes = BTreeSet::new();
    let ts = i64::from(tick_spacing);
    if let Some(w) = window {
        let first = *w.start() + (-*w.start()).rem_euclid(ts);
        let mut t = first;
        while t <= *w.end() {
            if let Ok(t) = i32::try_from(t) {
                probes.insert(t);
            }
            t += ts;
        }
    }
    if endpoint % tick_spacing == 0 {
        probes.insert(endpoint);
    }
    let count = probes.len() as u32;
    (
        probes.into_iter().filter(|t| marker(pool, *t)).collect(),
        count,
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    fn literal(old: i32, new: i32, s: i32) -> Vec<i32> {
        let mut out = vec![];
        let m = new % s;
        if m == 0 {
            out.push(new);
        }
        if (old - new).abs() / s <= 100 {
            if new > old {
                let mut i = old + (s - m);
                while i <= new {
                    out.push(i);
                    i += s;
                }
            } else if new < old {
                let mut i = old - m;
                while i >= new {
                    out.push(i);
                    i -= s;
                }
            }
        }
        out
    }
    #[test]
    fn covers_mapping_signed_loop() {
        for s in [1, 10, 60, 200] {
            for old in [-22001, -601, -1, 0, 1, 601, 22001] {
                for n in [-101, -100, -99, -1, 0, 1, 99, 100, 101] {
                    let new = old + n * s - 1;
                    let (window, end) = walk_window(old, new, s);
                    for t in literal(old, new, s) {
                        assert!(
                            t == end || window.as_ref().is_some_and(|w| w.contains(&i64::from(t)))
                        );
                    }
                }
            }
        }
    }
    #[test]
    fn probes_only_real_ticks() {
        let (v, n) = walk_candidates(&[0; 20], -51, -101, 50, 10, &|_, _| true);
        assert_eq!(v, vec![-100, -50]);
        assert_eq!(n, 2);
    }
}
