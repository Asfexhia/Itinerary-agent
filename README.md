# Itinerary Agent

## Overview

Planning a feasible multi-stop itinerary in real-world environments is a non-trivial task for users, as it requires simultaneously satisfying multiple competing constraints, including identifying relevant and high-quality points of interest, estimating realistic travel time between locations, and ensuring that the overall plan fits within limited temporal budgets. Traditional approaches, such as manual search through mapping applications, are both time-consuming and cognitively demanding because users must repeatedly switch between searching for places, evaluating their quality, and mentally reasoning about route feasibility.

This project investigates whether an LLM-powered agentic system, combined with external geographic APIs and constraint-based validation, can automate the process of generating feasible and realistic itineraries from natural language queries. The core research question is:

Can a structured LLM-based agent reliably transform natural language travel requests into time-feasible, high-quality multi-stop itineraries while respecting real-world constraints such as travel time, location quality, and route feasibility?

More specifically, the project explores whether integrating intent parsing, real-world place retrieval, and explicit constraint checking can improve the reliability of generated plans compared to a purely generative LLM approach that lacks external validation.

## What It Does

The system takes user queries expressed in natural language and produces executable travel plans. It first extracts tasks and constraints from the query using an LLM-based parser. These tasks are then grounded to real-world locations through map APIs. A planning module constructs candidate itineraries, which are subsequently validated by a constraint solver that enforces feasibility conditions such as time limits and ordering constraints. The final plan is returned as a structured sequence of stops with estimated travel times and is visualized on a map using route data rather than straight-line connections.

## System Components

The system consists of the following components:

· Intent parser: extracts tasks and constraints from natural language input
· Agent loop: iteratively generates and refines candidate plans
· Constraint solver: validates plans with respect to time and feasibility constraints
· Maps integration: resolves real locations and travel times using external APIs
· Frontend visualization: displays routes and stops using map-based rendering

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

## Environment Variables

Create the required `.env` files before running with real APIs:

- Project root `.env`: `GOOGLE_MAPS_API_KEY=your_google_maps_key`
- frontend/ `.env`: `VITE_MAPBOX_ACCESS_TOKEN=your_mapbox_token`

## Video Links

- Demo video: `(https://youtu.be/qMtVvO0OEj4)`
- Code walkthrough: `(https://youtu.be/hpVo8ezWyY8)`

## Evaluation

The system is evaluated by comparing three configurations:

1. Baseline LLM: parses tasks without enforcing constraints
2. Agent without solver: generates structured plans without constraint validation
3. Agent with solver: enforces time and feasibility constraints
   
## Result
| Method | Success Rate | Strict Valid Rate | Avg Retries |
| --- | ---: | ---: | --- |
| Baseline LLM |8/8 (100%) | 0/8 (0%) | 0.00 |
| Agent without solver | 8/8 (100%) | 8/8 (100%) | 0.00 |
| Agent with solver | 5/8 (62%) | 5/8 (62%) | 0.00 |

## Analysis

The baseline LLM achieves a high success rate because it only verifies whether tasks are parsed, without checking feasibility. As a result, its outputs are often not executable in practice.

The agent without constraint solving produces structured plans but does not enforce time constraints. While all outputs are considered successful, some plans are infeasible when evaluated against real-world constraints.

The agent with constraint solving achieves a lower success rate, but all successful outputs satisfy the defined constraints. The reduction in success rate is due to the rejection of infeasible plans rather than system errors.

## Error analysis

All observed failures fall into a single category:

· time_constraint_violation (3 cases)

These failures occur when the requested number of stops or travel requirements exceed the available time. The constraint solver correctly identifies and rejects such plans, indicating that the system is functioning as intended.

## Visualization

The frontend visualizes itineraries using map-based rendering. Routes are generated using a directions API to follow actual roads rather than straight-line interpolation between stops. This improves realism and provides a more accurate representation of travel paths.

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

## Attribution

Cursor was used as a coding assistant to support implementation, including generating boilerplate code, assisting with debugging, and creating test scripts. All core system design, algorithmic logic, and evaluation methodology were developed independently.
