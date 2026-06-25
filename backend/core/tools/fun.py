"""Phase F2-F3: Random generators, jokes, facts, and mood responses."""
import random
import string
from typing import Any

from backend.core.tools.registry import SecurityLevel, ToolResult, tool

_JOKES: list[str] = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "What do you call a fake noodle? An impasta.",
    "Why did the Python programmer break up with the Java developer? Too much class conflict.",
    "How many programmers does it take to change a light bulb? None — that's a hardware problem.",
    "Why do Java developers wear glasses? Because they can't C#.",
    "What's a computer's favorite snack? Microchips.",
    "Why was the JavaScript developer sad? Because he didn't know how to 'null' his feelings.",
    "What do you call a bear with no teeth? A gummy bear.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
    "I told my computer I needed a break. Now it won't stop sending me Kit-Kats.",
    "Why don't scientists trust atoms? They make up everything.",
    "What do you call a funny mountain? Hill-arious.",
    "Why did the AI break up with the database? Too many relationship issues.",
    "How do you comfort a JavaScript bug? You console it.",
    "Why was the computer cold? It left its Windows open.",
]

_FACTS: list[str] = [
    "Honey never spoils. Archaeologists found 3000-year-old honey in Egyptian tombs that was still edible.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than a year on Venus.",
    "Bananas are berries, but strawberries aren't.",
    "The Eiffel Tower grows 6 inches taller in summer due to thermal expansion.",
    "Humans share about 60% of their DNA with bananas.",
    "A group of flamingos is called a 'flamboyance.'",
    "The shortest war in history lasted 38 minutes between Britain and Zanzibar in 1896.",
    "Wombat poop is cube-shaped so it doesn't roll away.",
    "There are more trees on Earth than stars in the Milky Way.",
    "The average person walks the equivalent of 5 times around the Earth in a lifetime.",
    "A cloud can weigh over a million pounds.",
    "The human nose can remember over 50,000 different scents.",
    "Butterflies taste with their feet.",
    "The Great Wall of China is not visible from space with the naked eye.",
]

_COPING_SUGGESTIONS: list[str] = [
    "Let's play a game! Say 'play blackjack', 'play hangman', 'play wordle', 'play tictactoe', 'play connect4', or 'play rps'.",
    "How about I tell you a joke? Say 'tell me a joke'.",
    "Want a random fact? Say 'tell me a fact'.",
    "Need a password? Say 'generate password'.",
    "Flip a coin! Say 'flip a coin'.",
    "Roll the dice! Say 'roll dice'.",
    "Take a break — maybe open some music or a game?",
]


@tool(security=SecurityLevel.SAFE)
def tell_joke() -> ToolResult:
    """Tell a random joke to lighten the mood."""
    return ToolResult.success(random.choice(_JOKES))


@tool(security=SecurityLevel.SAFE)
def tell_fact() -> ToolResult:
    """Share a random interesting fact."""
    return ToolResult.success(random.choice(_FACTS))


@tool(security=SecurityLevel.SAFE)
def flip_coin() -> ToolResult:
    """Flip a coin — returns heads or tails."""
    result = random.choice(["heads", "tails"])
    return ToolResult.success(f"It's {result}!", data={"result": result})


@tool(security=SecurityLevel.SAFE)
def roll_dice(sides: int = 6) -> ToolResult:
    """Roll a dice with the given number of sides (default 6)."""
    result = random.randint(1, sides)
    return ToolResult.success(f"Rolled a {result}!", data={"result": result, "sides": sides})


@tool(security=SecurityLevel.SAFE)
def generate_password(length: int = 16) -> ToolResult:
    """Generate a random secure password of the given length (default 16)."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    password = "".join(random.choice(chars) for _ in range(length))
    return ToolResult.success(f"Password generated: {password}", data={"password": password})


@tool(security=SecurityLevel.SAFE)
def mood_response(mood: str = "") -> ToolResult:
    """Respond to the user's mood. Say 'bored', 'sad', 'happy', etc."""
    mood = mood.strip().lower()
    if mood in ("bored", "boring", "nothing to do"):
        suggestion = random.choice(_COPING_SUGGESTIONS)
        return ToolResult.success(suggestion, data={"suggestion": suggestion})
    if mood in ("sad", "unhappy", "down", "depressed"):
        joke = random.choice(_JOKES)
        return ToolResult.success(f"Sorry to hear that. Here's a joke: {joke}", data={"type": "joke"})
    if mood in ("happy", "great", "good", "wonderful"):
        fact = random.choice(_FACTS)
        return ToolResult.success(f"That's great! Did you know? {fact}", data={"type": "fact"})
    if mood in ("angry", "mad", "frustrated"):
        return ToolResult.success("Take a deep breath. Want me to play some music or tell a joke?", data={"type": "suggestion"})
    return ToolResult.success(random.choice(_COPING_SUGGESTIONS), data={"type": "suggestion"})
