# Latency Evaluation

This project is an interactive itinerary planner: the user enters a natural-language request, the backend performs LLM intent parsing plus planning/tool calls, and the frontend updates the route on the map.

## Latency Target

For classroom demo use, the target was:

- `/plan` API response: under 10 seconds for typical queries
- Frontend route rendering after API response: under 2 seconds
- User-visible planning state shown immediately while waiting

## Measurement Method

Latency was evaluated manually during local runs:

1. Start backend with `python run_api.py`.
2. Start frontend with `npm run dev`.
3. Submit representative itinerary queries from the UI.
4. Observe browser Network timing for `/plan` and visible map update time.

Representative queries:

| ID | Query |
| --- | --- |
| Q1 | Find a restaurant rated over 4 nearby, eat for 30 minutes, then go to a park for 1 hour, then return |
| Q2 | Find a coffee shop nearby for 20 minutes, then go to a museum for 1 hour |
| Q3 | Find a park nearby, then a bookstore, then return |

## Results Summary

| Component | Target | Observed behavior | Evidence |
| --- | ---: | --- | --- |
| Loading state | Immediate | Frontend shows `Planning...` while the API request is pending | `frontend/src/App.jsx` loading state and spinner |
| `/plan` backend request | < 10s typical demo target | Interactive response during local demo runs; depends on Google Maps and LLM availability | `src/itinerary_agent/api_server.py` `/plan` handler |
| Map route rendering | < 2s after response | Mapbox route is fetched and animated after plan response | `frontend/src/App.jsx` `fetchMapboxRoute()` and animated route logic |

## Code Pointers

- API endpoint: `src/itinerary_agent/api_server.py`
- LLM intent parsing call: `src/itinerary_agent/llm/intent_parser.py`
- Agent planning loop: `src/itinerary_agent/agent_loop.py`
- Frontend loading state: `frontend/src/App.jsx`
- Mapbox Directions route fetch: `frontend/src/App.jsx`
- Animated route rendering: `frontend/src/App.jsx`

## Notes

Latency depends on local machine performance, Google Maps API response time, Mapbox Directions API response time, and whether the local LLM server is available. The system includes fallback parsing so the demo does not block indefinitely when the local LLM is unavailable.
