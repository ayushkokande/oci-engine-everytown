"""Score the three benchmark response sets and check the results.

Run:  python3 verify_benchmark.py
Expect three PASS lines and exit status 0.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.scoring import calculate_recommendations
from utils.data_loader import get_domains, get_stage_names, get_stage_weights

# The benchmark files ship beside the sample reports.
CANDIDATES = [
    os.path.join(HERE, "..", "..", "03_Sample_Responses", "benchmark"),
    os.path.join(HERE, "benchmark"),
]


def benchmark_dir():
    for c in CANDIDATES:
        if os.path.isdir(c):
            return c
    sys.exit("benchmark/ not found. Looked in:\n  "
             + "\n  ".join(os.path.normpath(c) for c in CANDIDATES))


def check(sample, bench):
    with open(os.path.join(bench, "sample_%s_answers.json" % sample)) as f:
        answers = json.load(f)["answers"]
    with open(os.path.join(bench, "sample_%s_expected.json" % sample)) as f:
        expected = json.load(f)

    recs, summaries = calculate_recommendations(
        answers, get_domains(), get_stage_weights(), get_stage_names())

    problems = []

    got_domains = {s.domain_id: s for s in summaries}
    for want in expected["domains"]:
        got = got_domains.get(want["domain_id"])
        if got is None:
            problems.append("missing domain %s" % want["domain_id"])
            continue
        for field, actual in (("capacity_pct", got.score_pct),
                              ("estimated_stage", got.estimated_stage),
                              ("gap_count", got.gap_count)):
            if want[field] != actual:
                problems.append("%s %s: expected %r, got %r"
                                % (want["domain_id"], field, want[field],
                                   actual))

    got_gaps = {r.question_id: r for r in recs}
    if len(got_gaps) != len(expected["gaps"]):
        problems.append("gap count: expected %d, got %d"
                        % (len(expected["gaps"]), len(got_gaps)))
    for want in expected["gaps"]:
        got = got_gaps.get(want["question_id"])
        if got is None:
            problems.append("missing gap %s" % want["question_id"])
            continue
        if abs(got.score - want["priority_score"]) > 1e-9:
            problems.append("%s score: expected %s, got %s"
                            % (want["question_id"], want["priority_score"],
                               got.score))
        if got.priority != want["priority"]:
            problems.append("%s band: expected %s, got %s"
                            % (want["question_id"], want["priority"],
                               got.priority))

    org = expected["organization"]
    if problems:
        print("FAIL  sample %s (%s) - %d problem(s)"
              % (sample, org, len(problems)))
        for p in problems[:10]:
            print("        " + p)
        if len(problems) > 10:
            print("        ... and %d more" % (len(problems) - 10))
        return False

    print("PASS  sample %s (%s) - %d domains, %d gaps"
          % (sample, org, len(expected["domains"]), len(expected["gaps"])))
    return True


if __name__ == "__main__":
    bench = benchmark_dir()
    ok = all([check(s, bench) for s in ("A", "B", "C")])
    sys.exit(0 if ok else 1)
