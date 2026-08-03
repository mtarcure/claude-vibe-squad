//! Outcome accounting, and the non-vacuity gate.
//!
//! A prior campaign reported 6.2 million "passing" fuzz calls with zero
//! successful calls: the harness was bouncing every input off an auth check and
//! printing that as a clean run. A tool that silently failed to execute and a
//! tool that found nothing print the same empty output, so this ledger refuses
//! to report a run as meaningful unless it can name how many calls SUCCEEDED,
//! and how many distinct instruction kinds were reached.

use std::collections::BTreeMap;

#[derive(Default, Clone, Debug)]
pub struct KindStat {
    pub built: u64,
    pub succeeded: u64,
    pub authorized_built: u64,
    pub authorized_succeeded: u64,
    pub unauthorized_built: u64,
    pub unauthorized_succeeded: u64,
}

#[derive(Default, Clone, Debug)]
pub struct Ledger {
    /// Calls the fuzzer generated.
    pub attempted: u64,
    /// Calls the adapter could render into an instruction.
    pub built: u64,
    /// Calls that returned `Ok` from the program.
    pub succeeded: u64,
    pub per_kind: BTreeMap<String, KindStat>,
    /// Literal error strings, counted.
    pub errors: BTreeMap<String, u64>,
    pub max_compute_units: u64,
    pub total_compute_units: u64,
    /// Invariant violations, with the call index that produced them.
    pub violations: Vec<(u64, String, String)>,
    /// Unauthorized calls that succeeded on a TSS-gated kind. Non-empty is a
    /// lead, not coverage.
    pub auth_bypasses: Vec<(u64, String)>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Vacuity {
    /// Zero successful calls: the run proves nothing.
    Vacuous,
    /// Some kinds reached, others never succeeded.
    Partial,
    /// Every declared instruction kind was reached with a successful call.
    Sound,
}

#[derive(Debug, Clone)]
pub struct NonVacuityReport {
    pub verdict: Vacuity,
    pub successful_calls: u64,
    pub kinds_covered: usize,
    pub kinds_total: usize,
    pub uncovered: Vec<String>,
}

impl Ledger {
    pub fn record_unbuildable(&mut self) {
        self.attempted += 1;
    }

    pub fn record(
        &mut self,
        kind: &str,
        authorized: bool,
        tss_gated: bool,
        ok: bool,
        err: Option<String>,
        compute_units: u64,
        call_index: u64,
    ) {
        self.attempted += 1;
        self.built += 1;
        let e = self.per_kind.entry(kind.to_string()).or_default();
        e.built += 1;
        if authorized {
            e.authorized_built += 1;
        } else {
            e.unauthorized_built += 1;
        }
        if ok {
            self.succeeded += 1;
            e.succeeded += 1;
            if authorized {
                e.authorized_succeeded += 1;
            } else {
                e.unauthorized_succeeded += 1;
                if tss_gated {
                    self.auth_bypasses.push((call_index, kind.to_string()));
                }
            }
        } else if let Some(msg) = err {
            *self.errors.entry(msg).or_insert(0) += 1;
        }
        self.total_compute_units += compute_units;
        self.max_compute_units = self.max_compute_units.max(compute_units);
    }

    pub fn non_vacuity(&self, kinds: &[&str]) -> NonVacuityReport {
        let uncovered: Vec<String> = kinds
            .iter()
            .filter(|k| {
                self.per_kind
                    .get(**k)
                    .map(|s| s.succeeded == 0)
                    .unwrap_or(true)
            })
            .map(|k| k.to_string())
            .collect();
        let kinds_covered = kinds.len() - uncovered.len();
        let verdict = if self.succeeded == 0 {
            Vacuity::Vacuous
        } else if !uncovered.is_empty() {
            Vacuity::Partial
        } else {
            Vacuity::Sound
        };
        NonVacuityReport {
            verdict,
            successful_calls: self.succeeded,
            kinds_covered,
            kinds_total: kinds.len(),
            uncovered,
        }
    }

    pub fn report(&self, kinds: &[&str]) -> String {
        let mut s = String::new();
        let nv = self.non_vacuity(kinds);
        s.push_str(&format!(
            "calls generated      : {}\ncalls built          : {}\ncalls SUCCEEDED      : {}\n",
            self.attempted, self.built, self.succeeded
        ));
        s.push_str(&format!(
            "compute units        : max {} / total {}\n",
            self.max_compute_units, self.total_compute_units
        ));
        s.push_str(&format!(
            "non-vacuity          : {:?}  (reached {} of {} instruction kinds)\n",
            nv.verdict, nv.kinds_covered, nv.kinds_total
        ));
        if !nv.uncovered.is_empty() {
            s.push_str(&format!("  never succeeded    : {}\n", nv.uncovered.join(", ")));
        }
        s.push_str("\nper instruction kind (built / SUCCEEDED, split by signature validity):\n");
        for k in kinds {
            let d = KindStat::default();
            let st = self.per_kind.get(*k).unwrap_or(&d);
            s.push_str(&format!(
                "  {:<38} built {:>5}  ok {:>5}   | authorized {:>5}/{:<5}  unauthorized {:>5}/{:<5}\n",
                k,
                st.built,
                st.succeeded,
                st.authorized_succeeded,
                st.authorized_built,
                st.unauthorized_succeeded,
                st.unauthorized_built
            ));
        }
        s.push_str("\nerror histogram (literal program results):\n");
        let mut errs: Vec<(&String, &u64)> = self.errors.iter().collect();
        errs.sort_by(|a, b| b.1.cmp(a.1));
        for (msg, n) in errs.iter().take(25) {
            s.push_str(&format!("  {:>6}  {}\n", n, msg));
        }
        if !self.auth_bypasses.is_empty() {
            s.push_str("\n!! UNAUTHORIZED CALLS THAT SUCCEEDED ON A TSS-GATED KIND:\n");
            for (i, k) in &self.auth_bypasses {
                s.push_str(&format!("  call #{i}  {k}\n"));
            }
        }
        if !self.violations.is_empty() {
            s.push_str("\n!! INVARIANT VIOLATIONS:\n");
            for (i, name, detail) in &self.violations {
                s.push_str(&format!("  call #{i}  {name}: {detail}\n"));
            }
        }
        s
    }
}
