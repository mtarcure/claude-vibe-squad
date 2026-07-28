#!/usr/bin/env python3
"""Fail-closed tests for V2 live host admission."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PYTHON_DIR = ROOT / "scripts" / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

import host_admission as admission  # noqa: E402


GIB = 1024**3


def safe_pair(**second_overrides: object) -> tuple[admission.HostSnapshot, admission.HostSnapshot]:
    base = dict(
        captured_at=100.0,
        physical_bytes=16 * GIB,
        resident_bytes=5 * GIB,
        raw_free_bytes=2 * GIB,
        active_bytes=6 * GIB,
        inactive_bytes=3 * GIB,
        wired_bytes=2 * GIB,
        compressed_bytes=1 * GIB,
        purgeable_bytes=1 * GIB,
        supervisor_rss_bytes=64 * 1024**2,
        external_baseline_rss_bytes=5 * GIB - 64 * 1024**2,
        pressure_free_percent=65.0,
        pressure_level="normal",
        swap_total_bytes=12 * GIB,
        swap_free_bytes=8 * GIB,
        swapins=100,
        pageouts=100,
        swapouts=100,
        compressions=100,
        load_average_1m=1.0,
        runnable_processes=2,
        free_disk_bytes=100 * GIB,
        process_count=300,
        pid_limit=4096,
        active_workers=0,
        priority_state_known=True,
        higher_priority_queued=False,
        broker_port_available=True,
        provider_budget_available=True,
    )
    first = admission.HostSnapshot(**base)
    second_values = {**base, "captured_at": 103.0, **second_overrides}
    return first, admission.HostSnapshot(**second_values)


class AdmissionPredicateTests(unittest.TestCase):
    def test_missing_telemetry_queues_instead_of_launching(self) -> None:
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: None,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertEqual(decision.action, "queue")
        self.assertIn(2, decision.failed_clauses)

    def test_invalid_telemetry_schema_queues(self) -> None:
        first, second = safe_pair()
        invalid = replace(second, swap_free_bytes=-1)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: (first, invalid),
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(2, decision.failed_clauses)

    def test_low_free_swap_fails_clause_five(self) -> None:
        snapshots = safe_pair(swap_free_bytes=790 * 1024**2)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(5, decision.failed_clauses)

    def test_safe_calibrated_snapshot_admits(self) -> None:
        snapshots = safe_pair()
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            reserve=512 * 1024**2,
            now=103.0,
        )
        self.assertTrue(decision.admitted, decision.reasons)
        self.assertEqual(decision.failed_clauses, ())

    def test_active_at_hard_max_queues(self) -> None:
        snapshots = safe_pair(active_workers=8)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(1, decision.failed_clauses)

    def test_twelve_is_an_allowed_dynamic_ceiling(self) -> None:
        decision = admission.under_admission(
            hard_max=12,
            requested_workers=2,
            live_snapshot=lambda: safe_pair(active_workers=9),
            workload_class="light-text",
            now=103.0,
        )
        self.assertTrue(decision.admitted, decision.reasons)

    def test_requested_batch_over_live_headroom_queues(self) -> None:
        decision = admission.under_admission(
            hard_max=12,
            requested_workers=3,
            live_snapshot=lambda: safe_pair(active_workers=10),
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(1, decision.failed_clauses)

    def test_ceiling_above_twelve_fails_closed(self) -> None:
        decision = admission.under_admission(
            hard_max=13,
            live_snapshot=lambda: safe_pair(),
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(1, decision.failed_clauses)

    def test_process_projection_scales_with_requested_workers(self) -> None:
        first, second = safe_pair(process_count=3260, pid_limit=4096)
        decision = admission.under_admission(
            hard_max=12,
            requested_workers=2,
            live_snapshot=lambda: (first, second),
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(7, decision.failed_clauses)

    def test_pageout_or_swap_growth_fails_clause_three(self) -> None:
        snapshots = safe_pair(pageouts=101, swapouts=101)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(3, decision.failed_clauses)

    def test_swapin_growth_fails_clause_three(self) -> None:
        snapshots = safe_pair(swapins=101)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertIn(3, decision.failed_clauses)

    def test_unknown_workload_class_fails_closed(self) -> None:
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: safe_pair(),
            workload_class="unknown",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(4, decision.failed_clauses)

    def test_critical_pressure_fails_clause_six(self) -> None:
        snapshots = safe_pair(pressure_level="critical")
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(6, decision.failed_clauses)

    def test_unavailable_broker_port_fails_clause_seven(self) -> None:
        snapshots = safe_pair(broker_port_available=False)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=103.0,
        )
        self.assertFalse(decision.admitted)
        self.assertIn(7, decision.failed_clauses)

    def test_missing_authoritative_capacity_or_priority_state_queues(self) -> None:
        first, second = safe_pair(priority_state_known=False)
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: (replace(first, priority_state_known=False), second),
            workload_class="light-text",
            now=103.0,
        )
        self.assertIn(2, decision.failed_clauses)

    def test_future_dated_telemetry_queues(self) -> None:
        snapshots = safe_pair()
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: snapshots,
            workload_class="light-text",
            now=102.0,
        )
        self.assertIn(2, decision.failed_clauses)

    def test_uncalibrated_security_workload_queues(self) -> None:
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: safe_pair(),
            workload_class="security-untrusted",
            now=103.0,
        )
        self.assertIn(4, decision.failed_clauses)

    def test_provider_budget_unavailable_queues(self) -> None:
        decision = admission.under_admission(
            hard_max=8,
            live_snapshot=lambda: safe_pair(provider_budget_available=False),
            workload_class="light-text",
            now=103.0,
        )
        self.assertIn(7, decision.failed_clauses)


if __name__ == "__main__":
    unittest.main()
