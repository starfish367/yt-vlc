#!/usr/bin/env python3
"""
run_e2e_tests.py - Headless Test Runner for yt-vlc E2E Test Suite.
Executes test cases across Tiers 1-4, producing structured tier breakdowns and summary metrics.
"""
import os
import sys
import time
import argparse
import unittest

# Ensure headless GTK & python paths
os.environ["NO_AT_BRIDGE"] = "1"
os.environ["GDK_BACKEND"] = os.environ.get("GDK_BACKEND", "x11")

PROJECT_DIR = "/mnt/yt-vlc"
TESTS_DIR = os.path.join(PROJECT_DIR, "tests")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)


class TierTestResult(unittest.TestResult):
    def __init__(self, stream=None, descriptions=None, verbosity=None):
        super().__init__(stream, descriptions, verbosity)
        self.success_count = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.success_count += 1


def run_tier(tier_name, module_name, verbosity=1):
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception as e:
        print(f"Error loading {module_name}: {e}")
        return {
            "tier": tier_name,
            "module": module_name,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "duration": 0.0,
            "error_msg": str(e)
        }

    total_tests = suite.countTestCases()
    result = TierTestResult()
    start_time = time.time()
    suite.run(result)
    duration = time.time() - start_time

    return {
        "tier": tier_name,
        "module": module_name,
        "total": total_tests,
        "passed": result.success_count,
        "failed": len(result.failures),
        "errors": len(result.errors),
        "duration": duration,
        "failures": result.failures,
        "errors_list": result.errors,
    }


def main():
    parser = argparse.ArgumentParser(description="yt-vlc Headless E2E Test Runner")
    parser.add_argument("--tier", type=str, choices=["1", "2", "3", "4", "all"], default="all",
                        help="Select tier to run (1, 2, 3, 4, or all)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose failure output")
    args = parser.parse_args()

    tiers_config = [
        ("Tier 1: Feature Coverage (F1-F15)", "tests.test_tier1_features"),
        ("Tier 2: Boundary & Corner Cases (F1-F15)", "tests.test_tier2_boundaries"),
        ("Tier 3: Pairwise Combinations", "tests.test_tier3_pairwise"),
        ("Tier 4: Real-World Scenarios", "tests.test_tier4_scenarios"),
    ]

    if args.tier != "all":
        tier_idx = int(args.tier) - 1
        tiers_config = [tiers_config[tier_idx]]

    print("=" * 80)
    print("yt-vlc Headless Automated E2E Test Suite Runner")
    print(f"Target: /mnt/yt-vlc/yt_vlc.py | Working Dir: {os.getcwd()}")
    print("=" * 80)

    tier_results = []
    total_run = 0
    total_passed = 0
    total_failed = 0
    total_errors = 0
    total_duration = 0.0

    for tier_name, mod_name in tiers_config:
        print(f"\n[Running] {tier_name} ({mod_name})...")
        res = run_tier(tier_name, mod_name, verbosity=2 if args.verbose else 1)
        tier_results.append(res)
        total_run += res["total"]
        total_passed += res["passed"]
        total_failed += res["failed"]
        total_errors += res["errors"]
        total_duration += res["duration"]

        status_str = "PASS" if (res["failed"] == 0 and res["errors"] == 0) else "FAIL"
        print(f"  -> {status_str}: {res['passed']}/{res['total']} passed, "
              f"{res['failed']} failed, {res['errors']} errors ({res['duration']:.2f}s)")

        if args.verbose and (res["failed"] > 0 or res["errors"] > 0):
            for test, err in res.get("failures", []):
                print(f"     [FAIL] {test.id()}:")
                for line in err.strip().splitlines()[-2:]:
                    print(f"            {line}")
            for test, err in res.get("errors_list", []):
                print(f"     [ERROR] {test.id()}:")
                for line in err.strip().splitlines()[-2:]:
                    print(f"            {line}")

    # Print Summary Table
    print("\n" + "=" * 80)
    print("E2E TEST EXECUTION SUMMARY REPORT")
    print("=" * 80)
    header = f"{'Tier':<42} | {'Total':<6} | {'Pass':<6} | {'Fail':<6} | {'Err':<6} | {'Time':<6}"
    print(header)
    print("-" * 80)
    for r in tier_results:
        row = f"{r['tier']:<42} | {r['total']:<6} | {r['passed']:<6} | {r['failed']:<6} | {r['errors']:<6} | {r['duration']:>5.2f}s"
        print(row)
    print("-" * 80)
    total_row = f"{'TOTAL SUITE METRICS':<42} | {total_run:<6} | {total_passed:<6} | {total_failed:<6} | {total_errors:<6} | {total_duration:>5.2f}s"
    print(total_row)
    print("=" * 80)

    pass_rate = (total_passed / total_run * 100) if total_run > 0 else 0.0
    print(f"Overall Pass Rate: {pass_rate:.1f}% ({total_passed}/{total_run})")
    print(f"Coverage Target (>= 170 tests): {'MET' if total_run >= 170 else 'NOT MET'} ({total_run} tests)")

    if total_failed == 0 and total_errors == 0:
        print("\nAll tests passed successfully! [EXIT 0]")
        sys.exit(0)
    else:
        print(f"\n{total_failed + total_errors} test(s) require implementation / failed. [EXIT 1]")
        sys.exit(1)


if __name__ == "__main__":
    main()
