# Improvement Iterations

This document records two project iterations driven by evaluation results. The evaluation compares a baseline LLM parser, an agent without solver enforcement, and the full agent with constraint solving.

## Final Evaluation Result

| Method | Success Rate | Strict Valid Rate | Avg Retries |
| --- | ---: | ---: | ---: |
| Baseline LLM | 8/8 (100%) | 0/8 (0%) | 0.00 |
| Agent without solver | 8/8 (100%) | 8/8 (100%) | 0.00 |
| Agent with solver | 5/8 (62%) | 5/8 (62%) | 0.00 |

## Iteration 1: Prompt Structure and Intent Parsing

| Field | Description |
| --- | --- |
| What I tried | Started with loose intent extraction, then moved to a strict JSON prompt for `tasks` and `constraints`. |
| What I measured | Whether parsed outputs contained usable tasks, separated constraints from tasks, and passed schema validation. |
| What I changed | Added strict JSON prompting, retry feedback, JSON parsing, normalization, and fallback extraction. |
| Result | The baseline LLM parser achieved 8/8 lenient success on the evaluation set, showing that the parser could extract tasks, but 0/8 strict validity because parsing alone did not produce validated mapped itineraries. |

Evidence:

- Prompt comparison: `docs/PROMPT_EVALUATION.md`
- Final prompt and retry prompt: `src/itinerary_agent/llm/intent_parser.py` lines 233-263
- Parsing, validation, and fallback: `src/itinerary_agent/llm/intent_parser.py` lines 274-347
- Baseline evaluation wrapper: `src/evaluation.py` lines 221-248

## Iteration 2: Agent Pipeline and Constraint Solver

| Field | Description |
| --- | --- |
| What I tried | Compared baseline parsing against an agent pipeline, then compared the agent with and without solver enforcement. |
| What I measured | Success rate, strict valid rate, average retries, total time, stop count, and failure buckets. |
| What I changed | Added an agent loop that maps parsed tasks to places, computes solver-compatible step durations, validates plans with a constraint solver, and records failure reasons. |
| Result | The agent without solver reached 8/8 strict-valid rows under the lenient no-solver evaluation setting. The full solver-enforced agent reached 5/8 strict-valid rows, correctly rejecting infeasible or constraint-violating cases rather than reporting them as successful. |

Evidence:

- Agent loop and solver feedback: `src/itinerary_agent/agent_loop.py` lines 138-228
- Task-to-place execution and travel notes: `src/itinerary_agent/agent_loop.py` lines 230-310
- Solver/no-solver comparison functions: `src/evaluation.py` lines 251-335
- Summary metrics and ablation comparison: `src/evaluation.py` lines 351-399
- Failure bucket/error analysis: `src/evaluation.py` lines 400-469

## Interpretation

The main improvement was not simply increasing reported success rate. The baseline and no-solver variants can appear successful while skipping important validation. The solver-enforced agent is stricter: it reduces false positives by rejecting time-infeasible or otherwise invalid plans, which is why its strict success rate is lower but more meaningful for the itinerary-planning task.
