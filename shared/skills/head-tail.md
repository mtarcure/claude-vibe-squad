---
name: head-tail
status: authored
description: Use when a file is too large to read whole — logs, build output, generated artifacts, dumps — and you need its shape from the first and last N lines instead of loading it into context. Not for source files, which should be read in one operation.
---

# Head-Tail

Sample a file that is too large to read whole by taking a bounded slice from each end. Logs and build
output are usually structured this way on purpose: the beginning carries the invocation, configuration,
and version banner, and the end carries the outcome, the error, and the exit status.

## When this is the right tool — and when it is the wrong one
This technique is **narrow**, and applying it to the wrong file is a measured, expensive mistake.

- **Right:** log files, CI/build output, test-runner transcripts, generated artifacts, data dumps, and
  anything whose middle is repetitive by construction.
- **Wrong: source files, briefs, packets, and configuration.** Read those **whole, in one operation**.
  Paging a source file in small windows costs roughly eight times the round-trips on a large file, and
  because chunked shell output scrolls out of context, it is precisely the lanes that chunked a file that
  end up re-reading it three and four times. If a file is small enough to read whole, reading it whole is
  both cheaper and better.

The deciding question is not "is this file long?" but **"is this file's middle repetitive?"** A 3,000-line
source file is long and dense; a 3,000-line test log is long and repetitive. Only the second is a
head-tail candidate.

## Steps
1. **Size it first.** Check the byte size and line count before reading anything. This is one cheap call
   and it decides the entire approach — a file you assumed was huge is often small enough to read whole.
2. **Choose the slice deliberately.** Twenty lines from each end is a reasonable default for a log. Take
   more from the tail when you are chasing a failure, more from the head when you are checking how a run
   was invoked or configured.
3. **Read both ends in one round-trip.** Combine the head and tail reads into a single command rather than
   two calls; independent operations belong in the same round-trip.
4. **Bound the line length.** A single line in a log can be megabytes — a serialized payload, a base64
   blob, a minified bundle. Truncate over-long lines and mark them truncated, so one pathological line
   cannot displace everything else you read.
5. **State the gap explicitly.** Report the sampled range and what was skipped: "lines 1–20 and
   14,981–15,000 of 15,000; the middle 14,960 lines were not read." A reader who does not know a gap
   exists will treat your sample as the whole file.
6. **Search the middle rather than paging it.** When the ends do not answer the question, do **not** walk
   the file in windows. Search it — grep for the error, the failing test name, the exception class — and
   read the matches with a little surrounding context. One targeted search beats twenty sequential pages.
7. **Exclude generated content at the tool level.** When sampling across many files, filter with globs
   rather than by intention. A prose instruction to ignore generated code does not filter a search; a
   glob does.

## Failure modes
- **Sampling a source file.** The middle of a source file is the part that matters. Read it whole.
- **The truncated conclusion.** Reading the tail of a log, finding no error, and reporting success — when
  the failure was logged mid-run and execution continued. Absence of an error in a *sample* is not
  evidence of absence in the file.
- **The masked exit status.** A piped command returns the status of its *last* stage, so
  `some-build | tail` reports the status of `tail`, not of the build. Reading the tail of a build log is
  not the same as reading the build's exit code — capture the status separately.
- **Unreported gaps.** Presenting a sample as though it were the file.
- **Paging the middle.** Substituting many sequential window reads for one search.

## Acceptance
- The file was sized before it was read, and the whole-file read was ruled out on evidence, not assumption.
- The sample's range and its unread gap are stated wherever the content is used or quoted.
- Over-long lines are bounded and marked, so one line cannot swamp the sample.
- No conclusion about the file as a whole rests on the sample alone; questions about the middle were
  answered by searching, not by paging.
- Where an exit status matters, it was captured directly rather than inferred from tail output.
