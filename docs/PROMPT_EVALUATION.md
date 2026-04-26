# Prompt Design Evaluation

This document records the prompt-engineering iterations used for the LLM intent parser. The goal was to make the model extract itinerary intent in a format the agent loop could safely consume:

- `tasks`: only place types to visit
- `constraints`: rating, deadline, and duration constraints
- no extra natural-language explanation or unsupported fields

The final implementation is in `src/itinerary_agent/llm/intent_parser.py`, especially `parse_intent()` and the retry/normalization logic.

## Evaluation Queries

The prompt variants were checked against the same representative itinerary requests used by the evaluation harness:

| ID | Query |
| --- | --- |
| Q1 | Find a coffee shop near Duke with rating above 4.5, stay 1 hour, go home before 8pm |
| Q2 | Go to a cafe and supermarket then return before 7pm |
| Q3 | Visit 2 museums in 2 hours before 6pm |
| Q4 | Visit coffee shop, museum, park, and restaurant in 40 minutes |
| Q5 | Museum then library then gym in 25 minutes |
| Q6 | Supermarket, pharmacy, and gym in 18 minutes |
| Q7 | Find 2 stops within 45 minutes |
| Q8 | Coffee shop, bar, restaurant, and home before 5pm in 90 minutes total |

## Prompt Variants

### V1: Loose Intent Extraction

```text
Extract the user's itinerary intent. Return the places to visit and any constraints.
User query: {query}
```

Observed issue: outputs were often prose-like or mixed constraints into the place list, e.g. `"rating above 4.5"` appearing as a task.

### V2: Strict JSON Schema

```text
Extract structured intent from a user query.
Return STRICT JSON:
{ "tasks": [string], "constraints": { "rating": number|null, "deadline": string|null, "duration": number|null } }
- In tasks, include only place types.
- Put rating, deadline, and duration only under constraints.
User query: {query}
```

Observed improvement: outputs were easier to parse and usually separated place types from constraints, but occasional malformed JSON or extra fields still required guards.

### V3: Strict JSON + Retry Feedback + Normalization

```text
Extract structured intent from a user query.
Return STRICT JSON (no extra keys, no markdown, no locations or actions):
{ "tasks": [string], "constraints": { "rating": number|null, "deadline": string|null, "duration": number|null } }
- In 'tasks', INCLUDE ONLY place types mentioned and nothing else.
- Constraints must appear only under 'constraints' and NOT in 'tasks'.
User query: {query}

If the previous output was invalid:
Your previous output was invalid.
Reason: {last_error}
Try again and output ONLY strict JSON matching the schema.
```

This is the version implemented in `src/itinerary_agent/llm/intent_parser.py` lines 233-263, with validation and fallback normalization in lines 274-287 and 290-347.

## Comparison Table

| Prompt design | Schema compliance | Tasks/constraints separation | Robustness strategy | Result used in final system |
| --- | --- | --- | --- | --- |
| V1 Loose extraction | Low | Low | None | Rejected |
| V2 Strict JSON schema | Medium | Medium/High | Parser normalization | Partially used |
| V3 Strict JSON + retry feedback | High | High | Retry prompt, JSON mode, validation, deterministic fallback | Yes |

## Evidence in Code

- Final prompt text: `src/itinerary_agent/llm/intent_parser.py` lines 233-263
- Retry feedback prompt: `src/itinerary_agent/llm/intent_parser.py` lines 243-250
- JSON parsing and validation: `src/itinerary_agent/llm/intent_parser.py` lines 274-287
- Normalization/fallback checks: `src/itinerary_agent/llm/intent_parser.py` lines 290-347
- Downstream use by agent loop: `src/itinerary_agent/agent_loop.py` lines 141-172
