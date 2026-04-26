from datetime import datetime, timedelta

class ConstraintSolver:
    def __init__(self, steps, deadline_str):
        """
        steps: list of dicts with keys
            - name: str
            - location: (lat, lng) tuple or list
            - duration: int (minutes)
            - travel_time: int (seconds)
        deadline_str: "HH:MM" string interpreted as maximum total itinerary duration
            (hours=HH, minutes=MM), compared against sum of step durations + travel times.
            If exceeded, validate() returns (False, "time_constraint_violation").
        """
        self.steps = steps
        self.deadline_str = deadline_str

    def validate(self):
        # Parse deadline into total allowed minutes
        try:
            deadline_time = datetime.strptime(self.deadline_str, "%H:%M")
            deadline_limit = timedelta(hours=deadline_time.hour, minutes=deadline_time.minute)
        except Exception:
            return (False, "invalid_plan")

        total_time = timedelta()
        for idx, step in enumerate(self.steps):
            # Check each step has valid location
            if "location" not in step:
                return (False, "invalid_plan")
            loc = step["location"]
            if (
                isinstance(loc, (list, tuple))
                and len(loc) == 2
                and all(isinstance(x, (int, float)) for x in loc)
            ):
                if not (-90 <= loc[0] <= 90) or not (-180 <= loc[1] <= 180):
                    return (False, "invalid_plan")
            else:
                return (False, "invalid_plan")

            # Add travel time
            travel_time = step.get("travel_time", 0)
            if not isinstance(travel_time, int) or travel_time < 0:
                return (False, "invalid_plan")
            total_time += timedelta(seconds=travel_time)

            # Add activity duration
            duration = step.get("duration", 0)
            if not isinstance(duration, int) or duration < 0:
                return (False, "invalid_plan")
            total_time += timedelta(minutes=duration)

        if total_time > deadline_limit:
            return (False, "time_constraint_violation")

        return (True, f"Valid itinerary. Total time: {str(total_time)} (deadline {self.deadline_str})")


# --- Example test ---

if __name__ == "__main__":
    steps = [
        {
            "name": "Museum",
            "location": (37.7701, -122.4687),
            "duration": 90,        # 90 minutes
            "travel_time": 600,    # 10 minutes
        },
        {
            "name": "Park Picnic",
            "location": (37.7694, -122.4862),
            "duration": 120,       # 2 hours
            "travel_time": 900,    # 15 minutes
        },
        {
            "name": "Aquarium",
            "location": (37.8087, -122.4098),
            "duration": 60,
            "travel_time": 1200,   # 20 minutes
        }
    ]

    solver = ConstraintSolver(steps, "05:00")  # 5 hour total limit
    valid, message = solver.validate()
    print(f"Valid: {valid}\nMessage: {message}")

    # Try exceeding time
    solver2 = ConstraintSolver(steps, "03:00")
    valid2, message2 = solver2.validate()
    print(f"Valid: {valid2}\nMessage: {message2}")

    # Try invalid location
    steps_invalid_loc = steps.copy()
    steps_invalid_loc[1] = dict(steps_invalid_loc[1])
    steps_invalid_loc[1]["location"] = (111.1, 220.2)
    solver3 = ConstraintSolver(steps_invalid_loc, "05:00")
    valid3, message3 = solver3.validate()
    print(f"Valid: {valid3}\nMessage: {message3}")