import json
import os
import random
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(BASE_DIR, "state.json")

class StateManager:
    def __init__(self):
        self.state = {}
        self.last_logical_day = self.get_logical_day()

    def get_logical_day(self):
        now = datetime.now()
        if now.hour < 4:
            return (now.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        return now.strftime("%Y-%m-%d")

    def load_or_init_daily_state(self, expected_target, fluct):
        logical_day = self.get_logical_day()
        state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                pass
            
        if state.get("date_str") != logical_day:
            # Add nonlinear perturbation to the daily target calculation
            perturbation = random.uniform(0.9, 1.1) ** random.uniform(1.2, 1.8)
            base_target = random.randint(max(1, expected_target - fluct), expected_target + fluct)
            target = int(base_target * perturbation)
            # Make sure it's at least 1
            target = max(1, target)
            
            state = {
                "date": logical_day, # Keep for compatibility if needed
                "date_str": logical_day,
                "completed": 0,
                "target_count": target,
                "next_wake_up": 0.0
            }
            self.save_daily_state(state)
        self.state = state
        self.last_logical_day = logical_day
        return state

    def save_daily_state(self, state=None):
        if state is None:
            state = self.state
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def reset_daily_state(self):
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except Exception:
                pass
        self.state = {}

    def update_completed(self, count):
        self.state["completed"] = count
        self.save_daily_state()

    def update_next_wake_up(self, ts):
        self.state["next_wake_up"] = ts
        self.save_daily_state()
