"""Rock-Paper-Scissors."""
import random
from typing import Any

_CHOICES = {"rock", "paper", "scissors"}
_RULES = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def play_rps(action: str, choice: str = "") -> dict[str, Any]:
    """Play Rock-Paper-Scissors. action: 'play'. choice: rock, paper, or scissors."""
    if action != "play":
        return {"message": "Say 'play' to throw.", "status": "error"}
    choice = choice.strip().lower()
    if choice not in _CHOICES:
        return {"message": "Choose rock, paper, or scissors.", "status": "error"}
    comp = random.choice(list(_CHOICES))
    if choice == comp:
        result = "tie"
        msg = f"Both {choice}. It's a tie!"
    elif _RULES[choice] == comp:
        result = "win"
        msg = f"{choice} beats {comp}. You win!"
    else:
        result = "lose"
        msg = f"{comp} beats {choice}. You lose!"
    return {"player": choice, "computer": comp, "result": result, "message": msg, "status": "done"}
