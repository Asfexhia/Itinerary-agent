import pytest
from itinerary_agent.agent.constraint_solver import ConstraintSolver

def test_constraint_solver_valid_plan():
    steps = [
        {
            "name": "Stop 1",
            "location": (37.7, -122.4),
            "duration": 60,        # 1 hour
            "travel_time": 600,    # 10 minutes
        },
        {
            "name": "Stop 2",
            "location": (37.8, -122.5),
            "duration": 30,        # 30 minutes
            "travel_time": 600,    # 10 minutes
        }
    ]
    solver = ConstraintSolver(steps, "02:00")  # 2 hours
    valid, message = solver.validate()
    assert valid is True
    assert "Valid itinerary" in message

def test_constraint_solver_exceeds_deadline():
    steps = [
        {
            "name": "Stop 1",
            "location": (37.7, -122.4),
            "duration": 90,        # 1.5 hours
            "travel_time": 1200,   # 20 minutes
        },
        {
            "name": "Stop 2",
            "location": (37.8, -122.5),
            "duration": 60,        # 1 hour
            "travel_time": 600,    # 10 minutes
        }
    ]
    solver = ConstraintSolver(steps, "02:00")  # 2 hours
    valid, message = solver.validate()
    assert not valid
    assert message == "time_constraint_violation"


def test_constraint_solver_invalid_deadline_format():
    steps = [
        {
            "name": "Stop 1",
            "location": (37.7, -122.4),
            "duration": 30,
            "travel_time": 0,
        }
    ]
    solver = ConstraintSolver(steps, "not-a-time")
    valid, message = solver.validate()
    assert valid is False
    assert message == "invalid_plan"


def test_constraint_solver_invalid_location():
    steps = [
        {
            "name": "Stop 1",
            "location": (999.0, -122.4),
            "duration": 30,
            "travel_time": 0,
        }
    ]
    solver = ConstraintSolver(steps, "02:00")
    valid, message = solver.validate()
    assert valid is False
    assert message == "invalid_plan"