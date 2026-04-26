# Itinerary Agent

Itinerary Agent is an LLM-assisted itinerary planning project that turns natural-language travel requests into multi-stop plans. The system parses user intent, searches for real places, checks constraints such as time and ratings, and visualizes the resulting route on an interactive Mapbox frontend with animated road-following paths.

## What It Does

The project combines LLM-based intent parsing with an agent loop and a constraint solver. Users can request plans such as nearby restaurants, parks, museums, or other points of interest from a chosen start location. The backend resolves places with Google Maps APIs and returns structured stops, travel estimates, and feasibility status. The frontend displays the plan on a Mapbox map using Directions API routes rather than straight-line connections.

## Quick Start

```bash
# Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
pip install -r requirements.txt
pip install -e .
python run_api.py

# Frontend
cd frontend
npm install
npm run dev
```

Create the required `.env` files before running with real APIs:

- Project root `.env`: `GOOGLE_MAPS_API_KEY=your_google_maps_key`
- `frontend/.env`: `VITE_MAPBOX_ACCESS_TOKEN=your_mapbox_token`

## Video Links

- Demo video: `[placeholder]`
- Code walkthrough: `[placeholder]`

## Evaluation

The evaluation compares a baseline LLM-only planner against the agent pipeline with and without constraint solving. Metrics include success rate, retry behavior, and failure type analysis.

| Method | Success Rate | Avg. Retries | Main Failure Modes |
| --- | ---: | ---: | --- |
| Baseline LLM | TBD | TBD | Invalid plans, missing constraints |
| Agent without solver | TBD | TBD | Time-infeasible plans, weak validation |
| Agent with solver | TBD | TBD | API lookup failures, unsatisfiable constraints |

Final numeric results should be filled in after running the evaluation script on the selected test set.

## Individual Contributions

This is a solo academic project. All core design decisions, implementation work, experiments, evaluation setup, and final repository preparation were completed individually.

## Repository Structure

```text
.
├── frontend/                 # React + Vite + Tailwind + Mapbox UI
├── src/itinerary_agent/      # Backend agent, maps integration, solver, parser
├── tests/                    # Unit tests
├── run_api.py                # Backend API entrypoint
├── requirements.txt          # Python dependencies
├── SETUP.md                  # Detailed setup instructions
└── ATTRIBUTION.md            # Tooling and assistance disclosure
```
