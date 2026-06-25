"""Hangman word-guessing game."""
import random
from typing import Any

_WORDS = [
    "python", "hangman", "computer", "science", "algorithm",
    "function", "variable", "network", "database", "keyboard",
    "monitor", "software", "hardware", "internet", "program",
    "console", "terminal", "library", "package", "module",
]

_STAGES = [
    "  +---+\n  |   |\n      |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n      |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n  |   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|   |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n      |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n /    |\n      |\n=========",
    "  +---+\n  |   |\n  O   |\n /|\\  |\n / \\  |\n      |\n=========",
]


def play_hangman(action: str, letter: str = "") -> dict[str, Any]:
    """Play Hangman. action: 'start', 'guess'. letter: the letter to guess."""
    from backend.core.tools.games import _state

    state = _state.setdefault("hangman", {})
    if action == "start" or "word" not in state:
        state["word"] = random.choice(_WORDS)
        state["guessed"] = set()
        state["wrong"] = 0
        state["max_wrong"] = len(_STAGES) - 1

    word = state["word"]
    guessed = state["guessed"]
    wrong = state["wrong"]
    max_wrong = state["max_wrong"]

    if action == "guess":
        letter = letter.strip().lower()
        if not letter or len(letter) != 1 or not letter.isalpha():
            return {"message": "Guess one letter at a time.", "status": "error"}
        if letter in guessed:
            return {"message": f"You already guessed '{letter}'.", "status": "repeat"}
        guessed.add(letter)
        if letter not in word:
            wrong += 1
            state["wrong"] = wrong

    display = " ".join(c if c in guessed else "_" for c in word)
    stage = _STAGES[wrong] if wrong < len(_STAGES) else _STAGES[-1]

    if all(c in guessed for c in word):
        return {
            "display": display,
            "word": word,
            "message": f"You won! The word was {word}.",
            "status": "won",
            "stage": stage,
        }
    if wrong >= max_wrong:
        return {
            "display": display,
            "word": word,
            "message": f"Game over! The word was {word}.",
            "status": "lost",
            "stage": stage,
        }

    return {
        "display": display,
        "guessed": ", ".join(sorted(guessed)),
        "wrong": wrong,
        "remaining": max_wrong - wrong,
        "message": f"{display}\nWrong: {wrong}/{max_wrong}",
        "status": "playing",
        "stage": stage,
    }
