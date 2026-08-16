
## Phase contract — read before acting

Actor action: what this lane is here to do, in one line.
Question: the falsifiable question this lane answers.
Oracle: the observable that settles it either way.
May receive: information classes this lane is entitled to.
Must not receive: information classes withheld from this lane, and why.
Evidence form: what counts as evidence for this target class — an executed
  request and its response, a reproduced state, a captured artifact, a
  measured differential. Reading alone is a hypothesis owing an experiment.
Output state: hypothesis | primitive | lead | candidate | finding | bounded | refuted

Before return: link evidence, name residual surface, disclose deviations from
this contract, and name the next owed owner.

Do not adjudicate payability. Report the mechanism and its honest state; name what it owes.
  Scope, severity, duplication and "would this pay" are decided later, at a dedicated gate, by a role
  holding inputs you do not have. A hunting lane that excludes its own result on those grounds is
  doing another role's job without its evidence -- and the exclusion is invisible downstream, because
  nobody can review a mechanism you declined to report.

  - **An objection is the next thing to build, not a verdict.** When you hit one, name the experiment
    that would settle it, then run it or hand it up as owed work. "I could not close X" is a result.
    "Therefore this is not a finding" is not yours to write.
  - **"By design" is an impact judgment, not a mechanism refutation.** Only a quoted production guard
    refutes a mechanism. Measured: a lane dismissed two one-way value destinations as "design
    behaviour, not attacker"; cross-family review found the mechanisms real, and two sibling lanes
    independently banked them as a candidate.
  - **Do not argue against your own evidence from facts you have not sourced.** Measured: a lane
    reproduced its effect end to end in three independent runs, then discounted it on an assumption
    about the wider system it had never checked -- while the target's own documentation supported
    the claim it was arguing against.

Controls: every control must be **shown to catch** the thing it exists to detect — run it once
  where the effect is present and once where it is removed, and report both results. A control that
  only ever passes has not been tested; it has been assumed. Measured: a lane shipped
  `accounting_control.py` asserting `2e18 - 1e18 - 1e17 == 9e17` on hardcoded literals, never
  invoking its own harness — it proved that subtraction works, not that the instrument could detect
  the effect under test. Name what the control must detect, then show the run where it fails to
  detect it.

A banked primitive names what it was trying to make true — the accepted-impact
class or attack-graph edge it targets — not merely that an action was taken.

If this contract and the packet body disagree, the packet wins and you report
the conflict in your response. Silent precedence institutionalises drift.
