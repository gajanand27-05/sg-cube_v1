"""Wordle — guess the 5-letter word in 6 tries."""
import random
from typing import Any

_WORDS = [
    "apple", "crane", "drive", "eagle", "flame", "grape", "house",
    "light", "mango", "noble", "ocean", "piano", "queen", "river",
    "sugar", "table", "ultra", "vivid", "waste", "yacht", "zebra",
    "brave", "chess", "dance", "early", "frost", "ghost", "hello",
    "image", "joker", "knife", "lemon", "magic", "night", "olive",
    "peace", "quiet", "robot", "snake", "tiger", "unity", "voice",
]


def _score_guess(guess: str, target: str) -> str:
    result = []
    target_chars = list(target)
    guess_chars = list(guess)
    for i in range(5):
        if guess_chars[i] == target_chars[i]:
            result.append("🟩")
            target_chars[i] = None
            guess_chars[i] = None
    for i in range(5):
        if guess_chars[i] is None:
            continue
        if guess_chars[i] in target_chars:
            result.append("🟨")
            target_chars[target_chars.index(guess_chars[i])] = None
        else:
            result.append("⬛")
    return " ".join(result)


def play_wordle(action: str, guess: str = "") -> dict[str, Any]:
    """Play Wordle. action: 'start', 'guess'. guess: a 5-letter word."""
    from backend.core.tools.games import _state

    state = _state.setdefault("wordle", {})
    if action == "start" or "target" not in state:
        state["target"] = random.choice(_WORDS)
        state["attempts"] = 0
        state["max_attempts"] = 6
        state["history"] = []

    target = state["target"]
    attempts = state["attempts"]
    max_attempts = state["max_attempts"]
    history = state["history"]

    if action == "guess":
        guess = guess.strip().lower()
        if len(guess) != 5 or not guess.isalpha():
            return {"message": "Guess must be a 5-letter word.", "status": "error"}
        attempts += 1
        state["attempts"] = attempts
        score = _score_guess(guess, target)
        history.append(f"{guess.upper()} {score}")

        if guess == target:
            return {
                "history": history,
                "message": f"You got it in {attempts}! The word was {target.upper()}.",
                "status": "won",
            }

        if attempts >= max_attempts:
            return {
                "history": history,
                "message": f"Game over! The word was {target.upper()}.",
                "status": "lost",
            }

        return {
            "history": history,
            "attempts": attempts,
            "remaining": max_attempts - attempts,
            "message": "\n".join(history),
            "status": "playing",
        }

    return {"message": "Guess a 5-letter word.", "status": "playing", "attempts": 0}
