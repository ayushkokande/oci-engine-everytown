# OCI Scoring — Reference Implementation

The scoring engine, copied byte-for-byte from the live application. This is
the same code that produced the sample reports in `03_Sample_Responses/`,
so an implementation that matches this will match the benchmark.

Accompanies `../OCI_Scoring_Logic_Specification.docx`, which explains *why*
the model works the way it does. Read the spec if you need the reasoning;
read the code if you just need the behaviour.

## What's here

| Path | What it does |
|---|---|
| `engine/scoring.py` | The whole scoring model. `calculate_recommendations()` is 87 lines and is the only thing you need to reproduce. |
| `engine/recommendations.py` | Reshapes engine output for display. Computes nothing. |
| `utils/data_loader.py` | Loads `data/questions.json`. |
| `data/questions.json` | The question bank: 143 statements, 8 domains, plus the stage and domain weights. |
| `verify_benchmark.py` | Scores the three benchmark response sets and checks them against the expected results. |

**No third-party dependencies.** Python 3.8+, standard library only.

## Run it

```
python3 verify_benchmark.py
```

Expected output is three PASS lines. If you have reimplemented the scorer,
point `verify_benchmark.py` at your own function and the same check applies.

## Scoring in one screen

For each statement, `answer == trigger_on` means a capacity gap.

```
gap_density_bonus = 1 + (gaps in domain / statements in domain)   # 1.0 .. 2.0
priority_score    = stage_weight * domain_weight * gap_density_bonus
```

`stage_weight` is 5 for Seeding down to 1 for Transformational.
`domain_weight` is 0.7 to 1.0, per domain, from `questions.json`.

Then, across every gap in the submission, sorted by score descending:

```
pct = index / total_gaps      # 0-based index
pct < 0.33  -> High     pct < 0.66 -> Medium     otherwise -> Low
```

Per domain:

```
capacity_pct    = favourable / total * 100
estimated_stage = highest stage 1..5 where EVERY statement is favourable,
                  walking upward and stopping at the first stage that is not
```

## Three things that will cost you an hour if you miss them

1. **Priority bands are relative, not absolute.** They are percentile thirds
   of whatever gaps are in *this* submission. Score only four domains instead
   of eight and the same gap lands in a different band. Capacity percentages
   and estimated stages do not have this property — those are per domain and
   are stable.

2. **An unanswered statement is not a gap.** The engine does
   `answers.get(id, "")` and compares to `trigger_on`; an empty string matches
   neither `"yes"` nor `"no"`, so a missing answer silently counts as
   favourable and inflates the score. Validate for completeness before you
   score.

3. **One statement is reverse-coded.** `PL1` has `trigger_on: "yes"` — for
   that one, answering Yes is the gap. Every other statement is
   `trigger_on: "no"`. Read the field; don't assume the polarity.
