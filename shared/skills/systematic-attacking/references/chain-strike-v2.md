# chain-strike v2 — the Chaining method

Reference doc for **Phase 4 (Chaining)** of the `systematic-attacking` skill. This is the
rewritten successor to the standalone `chain-strike` skill, reconciled per two independent
advisory reviews (Sol / gpt-5.6 and Fable) and the design in
`docs/2026-07-25-systematic-attacking-and-mode-consolidation-spec.md` §B.3.

It is **target-agnostic**. It defines *how* to compose attacker primitives into a proven,
maximum-blast-radius chain; it does **not** carry the domain checklists (those live in the
domain-branch references and existing audit-checklist skills — this doc routes into them,
never copies them).

> **Do not redefine "finding" here.** This doc uses the host skill's one vocabulary:
> **primitive** (a bounded attacker capability or environmental fact — carries *capability,
> not severity*), **lead** ("there may be impact here"), **candidate** (a lead/primitive-path
> whose PoC + negative control pass in a sandbox), **finding** (a candidate reproduced
> end-to-end, negative-controlled, over the impact bar, cross-family reproduced). **Only
> findings carry CVSS and may be submitted.** If any word here seems to conflict with the
> host `SKILL.md`, the host wins.

---

## 0. What this replaces, and what it keeps

The original `chain-strike` was **not sufficient** as the Chaining phase (unanimous across
both advisors). This v2 keeps what worked and rips out the spine that produced duplicate,
severity-laundered submissions.

**Keep (≈60%):**
- The core question — *does A **enable / supply / amplify** B?* — as the driver of composition.
- Pattern tables **as prompts** (hypothesis seeds), never as a severity scoresheet.
- The demand for **end-to-end reproduction** of the whole chain, not per-link hand-waving.
- The anti-pattern instinct (forced chains, theoretical chains, duplicate-root-cause) — now expanded.

**Subtract (the failure spine):**
- Any *independent* definition of "a finding" (the host owns it).
- **Per-item severity** and **severity arithmetic** ("Medium + Low → Critical"). Forbidden. There
  is no severity until one score at the realized terminus.
- The **pairwise N×N matrix** ("is A related to B?"). "Related to" is not an edge.
- A standalone `attack-chains.md` output. Output conforms to the host candidate/finding artifact.

**Add (the new spine):** typed primitives incl. environmental ones · a typed directed
dependency **graph** whose edges are falsifiable proof obligations · impact-first
**bidirectional** search to the *shortest reliable* path · **causal** negative controls at
link and chain level · **chain-level dedup** · bounded chaining · one terminus score.

---

## 1. Inventory primitives — not "findings"

A **primitive** is a typed object describing a bounded attacker capability or an environmental
fact. It carries **capability, not severity.** Build the pool from every source: validated
leads, standalone findings (used here only as *inner links*), known/public/dep-CVE behavior,
config defaults, self-inflicted quirks, and the environment itself.

Each primitive is a record, not a sentence:

| Field | What it holds |
|---|---|
| `id` + `lifecycle` | source ID and status (`lead` / `candidate` / `finding` / `dedup-dead`). A `dedup-dead` primitive is still a legal **inner link**. |
| `capability` | the *raw* capability, phrased as an action — "can mint an unauth session token for any user id", "can read arbitrary S3 object by key", "can bend block timestamp ±N as a validator". **Never a severity.** |
| `required_privilege` | the privilege needed to wield it (prefer *none*). Note if it needs a role a later link must supply. |
| `user_interaction` | none / click / navigate / install — reliability and blast radius depend on this. |
| `target / version / state` | exact component, version, and observed state — a primitive proven against a lab config is not proven against prod (see *assumption laundering*). |
| `scope / trust_boundary` | which tenant / principal / origin / contract / host it operates within, and which boundary it sits against. |
| `preconditions / postconditions` | what must be true to fire it, and the state it leaves behind (this is what a later link consumes). |
| `evidence / confidence` | the observation that proves the capability, and how sure you are. |
| `standalone_disposition` | its own impact verdict in isolation (often "below bar" / "dedup-dead") — kept so the chain's novelty is auditable. |

### Environmental primitives are first-class free edges

The most common missing links are not bugs — they are **facts about the environment** that any
attacker gets for free. Inventory them as primitives with `required_privilege: none`:

- **flash loans** — unbounded, atomic, uncollateralized capital for one transaction.
- **permissionless deploy** — attacker can publish and call arbitrary contracts / functions.
- **public mempool** — pending transactions are observable and front/back-runnable.
- **open self-signup** — attacker can mint arbitrary authenticated identities/tenants at will.
- **public buckets / registries / package indexes** — readable or writable shared storage.
- **unauth deeplinks / exported components** — reachable entry points that skip the front door.

These do not need a "vulnerability" to exist; they are supplied by the platform. Treat them as
nodes that **supply** capability into the graph so you don't mistake "attacker needs capital /
an identity / observability" for a dead end.

---

## 2. Build a typed dependency GRAPH — not a pairwise matrix

Model the attack as a **directed graph**. The pairwise "is A related to B?" matrix is gone: a
vague relation is not composable and invites padding. Every connection must be a **typed edge
carrying a falsifiable proof obligation** — a claim you could design an experiment to *refute*.

### Node types
- **primitive** — an inventoried capability/environmental fact (§1).
- **asset** — the thing worth taking or breaking: funds, secrets, user/PII data, availability.
- **identity** — a principal / role / tenant / session the attack acquires or acts as.
- **trust-boundary** — an authz check, tenant isolation, origin/SOP, privilege ring, network segment, contract boundary.
- **terminus** — a terminal-impact state (see [Terminal impact](#terminal-impact)): funds moved, RCE, cross-tenant compromise at scale, control-plane takeover, permanent freeze.

### Edge types (each = a proof obligation)

| Edge | Meaning | Falsifiable obligation you must discharge |
|---|---|---|
| `REQUIRES` | target node needs precondition P | Prove P actually holds here — produced by an upstream link or an environmental primitive, **not assumed**. |
| `SUPPLIES` | A produces capability/state C that satisfies B's precondition | Show A's *output instance* IS B's *required input* — same object, same scope, same tenant. Not "a token" but "*this* token, valid for *that* check". |
| `CROSSES_BOUNDARY` | the step moves across a named trust boundary | Name the boundary; show the crossing is real **and in scope (Law 1)**. An out-of-scope hop is not a legal edge. |
| `CHANGES_STATE` | the step mutates persistent state a later link reads | Show the mutation persists past the step and is the exact state the next link consumes. |
| `AMPLIFIES` | the step multiplies blast radius (scale / repeatability / reach) | Quantify it — from 1 victim to all tenants, from once to unbounded, from testnet to mainnet. |
| `INVALIDATES_GUARD` | the step defeats or forces-open a defense that would block the next link | Show the guard was **active** and is now bypassed — not that it happened to be off. |
| `REACHES_TERMINUS` | the step realizes intrinsic impact | Show the terminus definition is met at the required (ideally no-) privilege. |

**"Related to" is not an edge.** If you cannot name the edge type and state the obligation you'd
run an experiment to break, the link does not exist yet — it is a hypothesis that must re-enter
the host lead→candidate workflow before it can appear in the graph.

---

## 3. Impact-first bidirectional search — the shortest *reliable* path

Do not enumerate every path and score them. Search **from both ends toward the middle**:

1. **Backward from an authorized HIGH/CRITICAL terminus.** Start at a program-recognized
   terminal-impact state that is *in scope*. Ask, per the host's goal-first stance: *what would
   have to be true for this terminus to be realized?* Expand its immediate preconditions, then
   theirs — a shrinking frontier of "what must supply this".
2. **Forward from observed primitives.** From each inventoried primitive (incl. environmental),
   expand what it `SUPPLIES` / `CHANGES_STATE` / `INVALIDATES_GUARD` next — the depth discipline
   of [Terminal impact](#terminal-impact).
3. **Intersect.** The chain is where the backward frontier meets the forward frontier. Take the
   **shortest reliable** intersection — *not* the path with the most links. Fewer links = higher
   reproducibility, lower dup risk, lower scope/safety risk.

### HIGH/CRIT eligibility is a search *constraint*, not a score

Impact-bar eligibility **prunes the search before any PoC**. A backward frontier rooted only at
in-scope HIGH/CRIT termini never expands toward a below-bar or out-of-scope endpoint, so you
never spend effort building a chain that cannot pay out. This is the opposite of scoring paths
after the fact.

**No CVSS anywhere in this phase.** Severity is not summed, averaged, or assigned per link.
Scoring happens once, later, from the realized terminus, after the full chain reproduces
(§ [Terminal impact](#terminal-impact) and host Phase 6). Any severity number inside the search
is a bug in the method.

---

## 4. Causal negative controls — at link *and* chain level

A chain is a **causal claim**: "this specific composition, and nothing shorter or incidental,
produces the terminus." Prove it the way you'd prove causation — by breaking it.

### Per essential link, prove all five:
1. **Upstream produced the state.** The incoming state consumed by this link was *produced by the
   preceding link*, not pre-seeded or left over from setup.
2. **Transition succeeds from that state.** The next transition actually fires from exactly that
   produced state.
3. **Remove the prerequisite → endpoint fails.** Patch/remove the upstream primitive or precondition
   and show the terminus is **no longer reachable** through this path. This is the load-bearing
   control; a link that survives its own removal was padding.
4. **Benign control input → no endpoint.** A well-formed, non-malicious input at the same point does
   *not* trigger the endpoint (rules out "it was going to happen anyway" / expected behavior).
5. **No shorter route under the documented search.** The terminus is not reachable by a shorter
   path you didn't claim — *within the coverage you actually searched*. **Record that search /
   coverage**; universal non-reachability cannot be proven, so the claim is bounded to "no shorter
   route under this documented search", never "no shorter route exists". A shorter route found here
   makes your extra links padding, and possibly a different/duplicate finding.

### Chain-level control — paired end-to-end trials from identical clean snapshots
A chain-level control is only *causal* if the negative trials are run **end-to-end from the same
clean snapshot** as the positive one — not inferred from the per-link results. Reset to an
**identical** snapshot before each trial and run this matched set:

- **Positive — full chain.** Start to terminus, nothing withheld. The terminus **must** be realized.
- **Benign / baseline.** The same end-to-end run with well-formed, non-malicious inputs. The
  terminus **must NOT** appear (rules out "it was going to happen anyway" / expected behavior).
- **One negative per essential link.** Re-run the whole chain with *that* link's prerequisite
  **patched, withheld, or replaced** by an in-scope benign equivalent — everything else identical.
  The terminus **must be absent in every one** of these trials. A link whose removal still yields
  the terminus was padding (or the real cause lies elsewhere) — the chain is not causal.

Record **success rate**, **timing/order** dependence, and the **privilege at each hop** across the
trials. A chain that only works once, or only in a specific race window, is an *unreliable/race-only*
chain and must be labeled as such with its measured probability — not asserted as deterministic.

### `[new discovery] N/A` is forbidden
You may **not** paper over a missing link with a speculative placeholder such as
`[new discovery] N/A`, "assume attacker can…", or "there is likely a bug that…". Every link is
either (a) an inventoried primitive with evidence, or (b) a *new hypothesis* that re-enters the
host lead→candidate→finding workflow and earns its own PoC + negative control before it may sit
in the graph. A chain with an unproven link is not a candidate; it is an honest **broken chain** —
record *exactly which link breaks and why* (a cited broken chain is a valid, honest result).

---

## 5. Chain-level dedup — the duplicate fix

Per-bug dedup is not enough. The characteristic false-submit is a **known composite dressed up
as novel** because its individual bugs look new (or are individually dedup-dead).

Before a chain is promoted to candidate/finding, run the **whole composite + its terminus on that
asset** through the host Phase-1 prior-art path (disclosed bugs, program history, known-issue/CVE
DBs, and **our own vault**):

- A **known / reported / patched composite** — even one assembled from links that look novel in
  isolation — **is a duplicate.** Kill it or record it dedup-dead.
- Conversely, a chain built entirely from **individually dedup-dead** primitives can still be
  novel — **the novelty lives in the composition and the terminus**, not the parts. Dedup the
  *composite*, not just the links.
- Refresh this dedup **immediately before submission** (state changes; someone may have reported
  it while you built the PoC).

### The composite-dedup identity key

Match composites by a **normalized semantic key**, not by surface text — a renamed, wrapped, or
independently-reordered version of a known chain is the **same** composite. Normalize and store a
key of:

- **target / component** — the asset the chain runs against.
- **affected version / state** — the version or state in which it reproduces (a patched-away
  version is a *different* key — see the historically-patched caveat below).
- **terminus asset + realized effect** — *what* is taken or broken and the concrete effect
  (drained vault X, cross-tenant read of Y's records, RCE on host Z).
- **ordered causal capability / state transitions** — the sequence of *capabilities and state
  changes*, not tool names or step wording. Steps whose order is **not** causally load-bearing are
  normalized to a canonical order before the key is formed, so a reordered-but-equivalent chain
  collides with the original.
- **pivotal boundaries crossed** — the trust boundaries the chain defeats (its `CROSSES_BOUNDARY` /
  `INVALIDATES_GUARD` edges), which two chains with different padding still share.

Two chains with the same key are duplicates **even if** their prose, tooling, or the order of
causally-independent steps differs; renamed / wrapped / reordered-independent steps are treated as
equivalent.

**Do not auto-kill a historically-patched match.** A prior-art hit whose `affected version / state`
differs from the target's current state may be a **live regression** or a fresh instance rather than
a true duplicate. Before killing it, confirm the affected version/state actually **overlaps** the
target's, *and* check the program's **regression / duplicate policy**. Kill (or record dedup-dead)
only when the key matches on a live-affected version/state **and** the program's policy treats that
as a duplicate; otherwise it stays a live candidate.

---

## 6. Bounded chaining — stop at the first realized HIGH/CRIT

More links is not better. Extra hops reduce reproducibility and add dedup/scope/safety risk.

**Stop once the shortest path realizes a program-recognized HIGH/CRIT terminus.** Continue only
when an added link proves **materially greater *realized* blast radius** at acceptable scope,
safety, and reliability — e.g. the same primitive turns a single-tenant compromise into an
all-tenant one, or a bounded loss into an unbounded drain. "It also technically enables X" that
you have not reproduced is not a reason to keep chaining; it is padding.

The judgment is **realized blast radius**, measured, not theoretical reach. If the extra link
lowers the success rate or reaches out of scope, it makes the submission *weaker*, not stronger.

---

<a id="terminal-impact"></a>
## 7. Terminal impact — score once, from the terminus (depth discipline)

*(This section folds in the `chain-impact-rescore` skill as content. Existing references may
retarget the `#terminal-impact` anchor. The standalone `chain-impact-rescore.md` file is left
untouched — its method is absorbed here.)*

The depth axis of chaining: **every primitive is a link, never a terminus.** A defense that kills
a primitive *in isolation* routinely falls when a separate primitive forces its precondition —
isolation-review misses chains by construction. So for each primitive — **including criticals** —
keep asking *what does this enable next?* until you hit real terminal impact.

**Forward-chain prompts by primitive shape:**
- **Halt / DoS** → what window does stopping these node(s) open? shift a quorum / attestation?
  freeze a time-sensitive path (oracle staleness, liquidation, governance timeout, unbonding)?
  crash *which* nodes to change *who* decides?
- **Time / ordering bend** → which check trusts it (expiry, staleness, timeout, sequencing)? does
  bending it replay, evict, reorder, or bypass?
- **Fail-open / missing check** → what *forces* the precondition (a state, a race, resource
  exhaustion, a config default, an environmental primitive)?
- **Info leak / read** → what does knowing it unlock (a key, a nonce, a target, a guard bypass)?
- **A forged / privileged action** → what is the *next* link? one forged signature → drain which
  vaults, across which chains, up to what cap? Push past "critical" to **maximal realized damage**.

**Score once, at the end.** The chain's severity **is its realized terminus** — never the sum,
average, or max of its links. State the terminal impact concretely: *whose* funds, *how much*,
*how repeatably*, at *what privilege*. Scoring happens once, in host Phase 6, from that terminus
(never summed). This is the depth analogue of the impact bar and feeds impact-validator G1.

**Terminal-impact gate:** a chain is submittable only when it **ends** in funds-moved /
secret-read / user-data-accessed / code-executed / cross-tenant compromise at scale /
control-plane takeover / permanent-freeze — at the required (ideally no-) privilege. If it ends
in "could / halt / leak / reachable", it is **not done**: find the next link, or record which link
breaks and why. **Reachability, disclosure, "could-lead-to" are not termini.**

---

<a id="coverage-map"></a>
## 8. Coverage map — breadth over the terminus set

*(This section folds in the `attack-coverage-map` skill as content, re-anchored from detection
coverage to **offensive** coverage. Existing references may retarget the `#coverage-map` anchor.
The standalone `attack-coverage-map.md` file is left untouched — its method is absorbed here.)*

Depth (§7) chases one primitive down. **Breadth** asks: across the *whole* authorized
HIGH/CRIT terminus set, which termini do we already have a path to, and where are the gaps worth
the next unit of effort? This keeps the campaign from over-investing one path while a shorter one
sits unexplored.

**Method (adapted from the coverage-map skill):**
1. **Choose the reference set** — the in-scope HIGH/CRIT termini (from host Phase 2's pre-registered
   impact bar), optionally cross-referenced to a TTP matrix (ATT&CK / the program's technique set)
   so the breadth is systematic, not ad-hoc.
2. **Map each existing chain-candidate / primitive path** to the terminus (or termini) it reaches.
3. **Mark every terminus `reached` / `partial` / `gap`.** `partial` = a backward frontier exists but
   the forward frontier hasn't met it — you know what it would take, not that you have it.
4. **For each gap, name the specific missing primitive or edge** it needs — "needs a primitive that
   `SUPPLIES` a valid cross-tenant identity", "needs an `INVALIDATES_GUARD` on the withdrawal
   allow-list". This is the shopping list that directs Phase 3 hypothesis generation.
5. **Prioritize gaps by (realized impact × feasibility).** Hand genuinely-blocked, out-of-reach
   termini up as a `needs_human` decision rather than forcing an out-of-scope or unsafe link.

**Acceptance for the map:** every candidate path maps to at least one terminus; every in-scope
terminus has a coverage status; every gap names its missing primitive/edge; priorities are
justified by realized impact and feasibility (never by raw count of primitives).

---

<a id="proof-safety-invariant"></a>
## Safety invariant — read before every proof prompt below

> **Proof happens in a sandbox by default — never against the live target.** Every composition
> prompt in the pattern library (§9), every cross-domain pivot (§10), and every "make the link
> real" obligation is validated in a **sandbox, synthetic replica, or read-only fork** — never by
> acting on the production target. The moment a proof would require **any** of the following, you
> **STOP and gate to the operator** (host Phase 5) — you never self-authorize:
>
> - use of a **live credential / token / session** of the real target or its users;
> - a **privileged or mutating API call** against the live system;
> - **execution inside a shipped / production pipeline** (CI/CD, deploy, release);
> - **real fund movement** (mainnet value, a real account balance);
> - **persistence** (planting state, a backdoor, a webhook, a poisoned artifact);
> - any other **mutating / live / irreversible** action.
>
> This invariant governs *every* pattern that follows, in *every* domain (Law 1). A pattern is a
> hypothesis to prove **safely**, not a licence to act on the target. The `unsafe proof`
> anti-pattern (§12) is its enforcement.
>
> **Verb binding (mandatory reading of the tables below).** In every "Proof obligation" cell,
> read *retrieve / show / reach / claim / exfiltrate / execute / authorize / intercept / extract /
> inject* as **"demonstrate in a sandbox / production-faithful replica / read-only fork, and
> evidence the replica's production-faithfulness"** — NEVER as a licence to perform that action
> against the live target, its real users, or a third party. Examples: "retrieve usable role
> creds" = obtain them in the replica and show the replica's IAM *would* grant them; "a build the
> pipeline actually ships" = a faithful pipeline replica, not the production pipeline; "claim a
> dangling subdomain" = prove claimability without seizing a real trusted origin; "exfiltrate via
> a tool" = show the agent *would* in an isolated harness. Any obligation that can only be shown by
> a live/mutating/irreversible action is a **STOP** pending the operator gate — surface it; never
> self-authorize. A genuine refusal is terminal (never re-shopped to a more permissive lane).

---

## 9. Pattern library — proof-gated prompts (no severity)

These are **hypothesis seeds**, not a scoresheet. There are **no severity columns** — each entry
is a composition prompt plus the **proof obligation** that must pass before the link is real. Use
them to expand the forward/backward frontiers in §3; route into the domain-branch references for
the target's specifics.

### Web / SaaS
| Composition prompt | Proof obligation to make the link real |
|---|---|
| SAML/OIDC `alg=none` / audience confusion → assume another tenant | Forge/replay a token the *real* verifier accepts; show it authorizes cross-tenant action. |
| Multi-tenant isolation break (IDOR on tenant key / missing scope check) | Show object of tenant B read/written while authenticated as tenant A, at scale. |
| Request smuggling (FE/BE desync) → route poisoning / auth bypass | Demonstrate a desynced request reaching a privileged backend path. |
| Cache poisoning → mass ATO / response hijack | Poison a shared cache key served to *other* users; show the malicious response is served. |
| Host-header / reset-token capture → account takeover | Show a password-reset link minted to attacker-controlled host and consumed. |
| File upload + path traversal → RCE | Land an executable/interpreted file at a served path and execute it. |
| Prototype pollution → gadget → RCE/authz bypass | Pollute a real object path and reach a *present* sink gadget. |

### Smart-contract / DeFi
| Composition prompt | Proof obligation to make the link real |
|---|---|
| Bridge message forgery / replay → drain | Forge or replay a cross-chain message the *destination* verifier accepts. |
| Signature replay (missing nonce / domain separator / permit reuse) | Replay a signed op the contract still honors; show state change. |
| First-depositor share inflation via direct `transfer` | Inflate share price by donating; show a later depositor loses funds. |
| Oracle staleness + no circuit breaker → mispriced action | Show a stale/again-usable price is consumed by a live path (fork against the *real* oracle, not a mock). |
| `delegatecall` → `selfdestruct` / unauthorized upgrade | Reach a `delegatecall` sink that lets attacker code alter storage/upgrade. |
| Cross-contract read-only reentrancy | Show a view read mid-callback returns inconsistent state a second contract trusts. |
| Flash loan (env primitive) `SUPPLIES` capital → amplify any of the above | Show the atomic capital makes an otherwise-uneconomic step profitable/possible. |

### Infra / cloud
| Composition prompt | Proof obligation to make the link real |
|---|---|
| SSRF → IMDS → IAM creds → account takeover | Reach `169.254.169.254` (or metadata endpoint) and retrieve usable role creds; show a privileged API call. |
| Leaked cloud key → over-broad IAM → privilege escalation | Enumerate the key's actual grants; show a control-plane action it should not have. |
| CI/CD pipeline poisoning → artifact / supply-chain compromise | Inject into a build the pipeline actually ships; show downstream execution. |
| Exposed control plane (kubelet / etcd / dashboard) → cluster takeover | Reach an unauth control-plane API; show workload/secret control. |
| Subdomain takeover → OAuth callback / cookie scope → ATO | Claim a dangling subdomain that is a trusted origin/redirect target; show session capture. |

### Mobile
| Composition prompt | Proof obligation to make the link real |
|---|---|
| Exported activity / insecure deeplink → auth bypass | Invoke the component from an unprivileged app/link and reach a gated screen/action. |
| Deeplink → WebView JS-bridge → in-app RCE | Drive a JS bridge from attacker-controlled content to a native capability. |
| Custom-scheme hijack → OAuth code interception → ATO | Register/claim the scheme; intercept an auth code and exchange it. |
| `allowBackup` / weak keychain → local secret → server-side ATO | Extract a token/secret from backup/keystore; show it authorizes a server action. |

### LLM / AI
| Composition prompt | Proof obligation to make the link real |
|---|---|
| Indirect injection → agent tool call → self-exfil | Plant instructions in retrieved content; show the agent exfiltrates data via a tool. |
| Injection → code-interpreter / MCP-shell → host RCE | Show injected text causes code/command execution on the host. |
| Injection → over-broad MCP scope → cloud/SaaS action | Show the agent performs a privileged external action it was steered into. |
| Persistent RAG poisoning (multi-tenant) | Plant content that later serves *other* tenants' sessions and steers them. |

> **Test the injection, not the leak.** A "system-prompt-leak → bypass" link must be reproduced
> *without* relying on the leaked text as the exploit — otherwise the leak is laundering the real
> (or absent) impact.

---

## 10. Cross-domain pivots — where the shortest path to critical usually lives

The highest-value chains cross a domain boundary that single-domain reviews never look across.
Treat each pivot as one edge with an explicit `CROSSES_BOUNDARY` obligation.

- **Web SSRF → cloud IMDS → IAM → account takeover.** Obligation: the web-tier SSRF actually
  reaches the metadata service and returns creds usable against the account's control plane.
- **LLM agent injection → MCP tool → cloud / SaaS action.** Obligation: injected content drives a
  connected MCP/tool to perform a privileged out-of-band action, crossing from the model context
  into real infrastructure.
- **Mobile deeplink → web OAuth → ATO.** Obligation: a mobile custom-scheme / deeplink intercepts
  or redirects a web OAuth flow to capture a code/token that takes over the web account.

The lesson: inventory primitives from *every* domain the target touches, then look explicitly for
edges that leave the domain a primitive was found in. Single-domain framing is the reason these
chains are underreported.

---

## 11. Hazardous default examples — do NOT ship these unproven

The original pattern set shipped example chains that are frequently **padding or expected
behavior**. They are *not* forbidden, but each must clear a specific, concrete obligation before
it counts. Default to skepticism:

- **XSS → CSRF** — usually **padding**: a same-origin script already acts with the victim's
  authority directly, so wrapping a CSRF around it adds no capability. Only real if CSRF reaches a
  distinct principal/action the XSS cannot.
- **GraphQL introspection** — **discovery, not a primitive.** Knowing the schema grants no
  capability; it must lead to an actual authz/logic break to be a link.
- **Open-redirect → OAuth** — only real with a **concrete `state` / nonce / PKCE failure** that lets
  the redirect capture a usable code/token. Absent that, it is a low-value redirect.
- **System-prompt-leak → bypass** — must be tested **without** the leak (see §9). If the bypass works
  without the leaked text, the leak is not the primitive.
- **Missing-slippage → sandwich** — may be **expected market behavior**, not a vuln. Only a link if it
  causes loss beyond normal market exposure (e.g. forced execution, no user opt-out).
- **Info-disclosure → cred-reuse** — silently **launders an external credential problem** into the
  target. Only a link if the disclosed material is itself the target's secret realizing impact here.

---

## 12. Anti-patterns (expanded)

Kill any chain exhibiting these. The first three are inherited from `chain-strike` v1; the rest are
the v2 additions that block the characteristic false-submit.

**Inherited:**
- **Forced chain** — links assembled to reach a conclusion rather than because A actually supplies B.
- **Theoretical chain** — never reproduced end-to-end; asserted, not demonstrated.
- **Duplicate-root-cause** — multiple "links" are the same underlying bug counted more than once.

**Added:**
- **Severity laundering** — naming a pile of lows/mediums and calling the bundle a high. Severity is
  the realized terminus, never a sum.
- **Chain padding** — the endpoint occurs *without* the extra link; it was added to inflate, not to
  cause. (Caught by negative control #3 and #5.)
- **Privilege laundering** — a hidden admin/root/victim capability is assumed somewhere in the chain
  without a link that *supplies* it.
- **Scope laundering** — an out-of-scope hop bridges the path. Illegal under Law 1 and legally
  hazardous; an out-of-scope edge does not exist.
- **Assumption laundering** — a lab/dev config (feature flag off, guard disabled, test key) is
  presented as the real target's state.
- **Same-effect double-counting** — two links produce the same effect and both are credited toward
  blast radius.
- **Circular dependency** — A requires B and B requires A with no external primitive breaking the
  loop; the chain never actually starts.
- **Unreliable / race-only chain** — only fires in a narrow race/timing window, with the probability
  ignored or asserted as deterministic.
- **Model mismatch** — the harness omits a production guard / oracle / identity / OS behavior, so the
  chain works in the lab but not in prod.
- **Duplicate composition** — the *composite* is known/reported/patched even though the links look
  novel (see §5).
- **Downstream-known chain** — the terminus or the pivotal link is already publicly known/reported for
  this asset.
- **Unsafe proof** — validating the chain would exceed scope, harm bystanders, move real funds,
  persist, or destroy production. Stop and gate to the operator (host Phase 5); never self-authorize.

---

## 13. Output contract

The chaining phase does **not** emit a standalone `attack-chains.md`. Its output **is** the host
skill's candidate/finding artifact, populated so downstream gates can consume it:

- The **typed graph** (nodes + typed edges with their discharged obligations) as the chain's evidence.
- Per essential link: the **five causal negative-control results** + the chain-level clean-snapshot
  run (success rate, timing/order, per-hop privilege).
- The **chain-level dedup** result (composite + terminus checked, with prior-art references).
- The **realized terminus** stated concretely — but **no CVSS here.** Scoring is one operation in
  host Phase 6, from the terminus.
- For a broken chain: the exact link that breaks and why (a valid, honest result — not a failure).

`sequential-thinking` is an optional convenience for walking the graph; if it is unavailable, keep a
written **state-transition table** (state → link → next state → obligation → control result) as the
fallback. The method does not depend on the tool.

---

## 14. Quick checklist

- [ ] Primitives inventoried as typed records (capability, not severity); environmental primitives included.
- [ ] Graph is typed and directed; every edge names a type + a falsifiable obligation. No "related to".
- [ ] Search is bidirectional; HIGH/CRIT eligibility pruned the frontier *before* any PoC.
- [ ] Chosen path is the **shortest reliable** intersection, not the longest.
- [ ] No CVSS / severity anywhere in the search; **no severity arithmetic** at all.
- [ ] Each essential link passes all five causal negative controls; chain runs from a clean snapshot.
- [ ] No `[new discovery] N/A` / speculative links — every link is evidenced or re-entered the lead workflow.
- [ ] Whole composite + terminus dedup'd against prior art; refreshed pre-submit.
- [ ] Stopped at the first realized HIGH/CRIT unless a link proved *materially greater realized* blast radius.
- [ ] Terminus stated concretely; scored **once**, later, from the terminus.
- [ ] Coverage map marks every in-scope terminus reached/partial/gap; gaps name their missing primitive/edge.
- [ ] Output is the host candidate/finding artifact — no standalone `attack-chains.md`.
