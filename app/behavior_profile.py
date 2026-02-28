"""Session-level behavioral personality profiles."""

import random
from dataclasses import dataclass


@dataclass
class BehaviorProfile:
    delay_min: int
    delay_max: int
    scroll_fraction_min: float
    scroll_fraction_max: float
    scroll_back_chance: float
    mouse_moves: int
    mouse_step_min: int
    mouse_step_max: int
    initial_pause_min: int
    initial_pause_max: int
    inter_page_min: int
    inter_page_max: int

    @classmethod
    def random(cls) -> "BehaviorProfile":
        style = random.choice(["fast_scanner", "careful_reader", "average"])
        if style == "fast_scanner":
            return cls(
                delay_min=300,
                delay_max=1500,
                scroll_fraction_min=0.7,
                scroll_fraction_max=1.3,
                scroll_back_chance=0.05,
                mouse_moves=random.randint(1, 3),
                mouse_step_min=2,
                mouse_step_max=5,
                initial_pause_min=500,
                initial_pause_max=1500,
                inter_page_min=2000,
                inter_page_max=5000,
            )
        elif style == "careful_reader":
            return cls(
                delay_min=800,
                delay_max=4000,
                scroll_fraction_min=0.4,
                scroll_fraction_max=0.9,
                scroll_back_chance=0.20,
                mouse_moves=random.randint(4, 7),
                mouse_step_min=4,
                mouse_step_max=10,
                initial_pause_min=2000,
                initial_pause_max=5000,
                inter_page_min=5000,
                inter_page_max=12000,
            )
        else:  # average
            return cls(
                delay_min=500,
                delay_max=3000,
                scroll_fraction_min=0.6,
                scroll_fraction_max=1.2,
                scroll_back_chance=0.10,
                mouse_moves=random.randint(2, 5),
                mouse_step_min=3,
                mouse_step_max=8,
                initial_pause_min=1000,
                initial_pause_max=3000,
                inter_page_min=3000,
                inter_page_max=8000,
            )
