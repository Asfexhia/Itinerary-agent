import os
from unittest.mock import MagicMock

import pytest


def test_google_maps_client_find_place_filters_min_rating(monkeypatch):
    # Import inside test so monkeypatching env works reliably.
    from itinerary_agent.api.maps import GoogleMapsClient

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake")

    # Patch the googlemaps module used by GoogleMapsClient.__post_init__
    fake_googlemaps = MagicMock()
    fake_client = MagicMock()
    fake_googlemaps.Client.return_value = fake_client

    # Two candidates, only one meets min_rating
    fake_client.find_place.return_value = {
        "candidates": [
            {
                "name": "Low Rated Place",
                "place_id": "p1",
                "rating": 3.9,
                "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
            },
            {
                "name": "Good Place",
                "place_id": "p2",
                "rating": 4.6,
                "geometry": {"location": {"lat": 3.0, "lng": 4.0}},
            },
        ]
    }

    monkeypatch.setitem(__import__("sys").modules, "googlemaps", fake_googlemaps)

    g = GoogleMapsClient()
    out = g.find_place("coffee", min_rating=4.5)

    assert out is not None
    assert out["name"] == "Good Place"
    assert out["place_id"] == "p2"
    assert out["rating"] == pytest.approx(4.6)
    assert out["lat"] == 3.0
    assert out["lng"] == 4.0


def test_google_maps_client_get_travel_info_ok(monkeypatch):
    from itinerary_agent.api.maps import GoogleMapsClient

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake")

    fake_googlemaps = MagicMock()
    fake_client = MagicMock()
    fake_googlemaps.Client.return_value = fake_client

    fake_client.distance_matrix.return_value = {
        "rows": [
            {
                "elements": [
                    {
                        "status": "OK",
                        "distance": {"value": 1234},
                        "duration": {"value": 567},
                    }
                ]
            }
        ]
    }

    monkeypatch.setitem(__import__("sys").modules, "googlemaps", fake_googlemaps)

    g = GoogleMapsClient()
    out = g.get_travel_info("A", "B")

    assert out == {"distance": 1234, "duration": 567}


def test_safe_json_extraction_handles_fences():
    from itinerary_agent.llm.intent_parser import _safe_json_from_text

    text = """```json
    {"tasks":["x"],"constraints":{"rating":4.5,"deadline":null,"duration":60}}
    ```"""
    out = _safe_json_from_text(text)
    assert out["tasks"] == ["x"]
    assert out["constraints"]["duration"] == 60


def test_parse_intent_recovers_from_wrapped_text(monkeypatch):
    # Patch requests.post so we don't need Ollama running.
    import itinerary_agent.llm.intent_parser as ip

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": "Here you go:\n```json\n"
                + '{"tasks":["Find coffee"],"constraints":{"rating":"4.5","deadline":"","duration":"60"}}'
                + "\n```"
            }

    monkeypatch.setattr(ip.requests, "post", lambda *args, **kwargs: FakeResp())

    out = ip.parse_intent("find coffee 4.5 for 1 hour", model="deepseek", host="http://localhost:11434")
    # Tasks are normalized to place-type vocabulary (e.g. coffee), not raw LLM strings.
    assert out["tasks"] == ["coffee"]
    assert out["constraints"]["rating"] == pytest.approx(4.5)
    assert out["constraints"]["deadline"] is None
    assert out["constraints"]["duration"] == 60


def test_parse_intent_normalizes_deadline_hhmm_and_duration_minutes(monkeypatch):
    import itinerary_agent.llm.intent_parser as ip

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": '{"tasks":["x"],"constraints":{"rating":null,"deadline":"5:00 PM","duration":"1.5 hours"}}'
            }

    monkeypatch.setattr(ip.requests, "post", lambda *args, **kwargs: FakeResp())

    out = ip.parse_intent("x", model="deepseek", host="http://localhost:11434")
    assert out["constraints"]["deadline"] == "17:00"
    assert out["constraints"]["duration"] == 90


def test_parse_intent_fallback_when_model_not_json(monkeypatch):
    import itinerary_agent.llm.intent_parser as ip

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            # Not JSON at all
            return {"response": "sure, I'd do that. rating above 4.5 before 6pm for 1.5 hours"}

    monkeypatch.setattr(ip.requests, "post", lambda *args, **kwargs: FakeResp())

    out = ip.parse_intent("Find coffee rating above 4.5 before 6pm for 1.5 hours", model="deepseek", host="http://localhost:11434", max_attempts=2)
    assert isinstance(out, dict)
    assert set(out.keys()) == {"tasks", "constraints"}
    assert set(out["constraints"].keys()) == {"rating", "deadline", "duration"}
    assert out["constraints"]["rating"] == pytest.approx(4.5)
    assert out["constraints"]["deadline"] == "18:00"
    assert out["constraints"]["duration"] == 90


def test_agent_loop_smoke_runs(monkeypatch):
    """
    Validate agent_loop end-to-end without Ollama/real Google APIs by mocking:
    - itinerary_agent.agent_loop.parse_intent
    - googlemaps.Client
    """
    from itinerary_agent.agent_loop import Agent, AgentDeps
    from itinerary_agent.agent.constraint_solver import ConstraintSolver

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "fake")

    # Mock googlemaps.Client behavior used inside GoogleMapsClient
    fake_googlemaps = MagicMock()
    fake_client = MagicMock()
    fake_googlemaps.Client.return_value = fake_client

    fake_client.find_place.return_value = {
        "candidates": [
            {
                "name": "Good Place",
                "place_id": "p2",
                "rating": 4.8,
                "geometry": {"location": {"lat": 3.0, "lng": 4.0}},
            }
        ]
    }
    fake_client.distance_matrix.return_value = {
        "rows": [
            {
                "elements": [
                    {
                        "status": "OK",
                        "distance": {"value": 111},
                        "duration": {"value": 222},
                    }
                ]
            }
        ]
    }
    monkeypatch.setitem(__import__("sys").modules, "googlemaps", fake_googlemaps)

    # Mock parse_intent used by agent_loop to avoid Ollama
    import itinerary_agent.agent_loop as al

    monkeypatch.setattr(
        al,
        "parse_intent",
        lambda q: {
            "tasks": ["Find a coffee shop", "Find a museum"],
            # Budget must cover solver model: 2 * (60min + 10min travel) = 140 min
            "constraints": {"rating": 4.5, "deadline": None, "duration": 180},
        },
    )

    from itinerary_agent.api.maps import GoogleMapsClient

    def solver_factory(steps, deadline):
        return ConstraintSolver(steps, deadline)

    agent = Agent(AgentDeps(maps=GoogleMapsClient(), solver=solver_factory, max_iters=3))
    out = agent.run_once("plan things")

    assert out["ok"] is True
    assert out["iterations"] == 1
    assert "itinerary" in out
    assert len(out["itinerary"]["items"]) >= 1

