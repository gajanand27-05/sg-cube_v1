"""Phase F1: 6 CLI games — registered as @tool functions."""
from backend.core.tools.games.blackjack import play_blackjack
from backend.core.tools.games.connect4 import play_connect4
from backend.core.tools.games.hangman import play_hangman
from backend.core.tools.games.rps import play_rps
from backend.core.tools.games.tictactoe import play_tictactoe
from backend.core.tools.games.wordle import play_wordle
from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_blackjack_tool(action: str, bet: int = 10) -> ToolResult:
    """Play Blackjack. 'deal' to start, 'hit' for a card, 'stand' to hold."""
    result = play_blackjack(action, bet)
    return ToolResult.success(result["message"], data=result)


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_hangman_tool(action: str, letter: str = "") -> ToolResult:
    """Play Hangman. 'start' to begin, 'guess' with a letter to guess."""
    result = play_hangman(action, letter)
    return ToolResult.success(result["message"], data=result)


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_wordle_tool(action: str, guess: str = "") -> ToolResult:
    """Play Wordle. 'start' to begin, 'guess' with a 5-letter word."""
    result = play_wordle(action, guess)
    return ToolResult.success(result["message"], data=result)


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_tictactoe_tool(action: str, position: int = 0) -> ToolResult:
    """Play Tic-Tac-Toe. 'start' to begin, 'move' with a position (1-9)."""
    result = play_tictactoe(action, position)
    return ToolResult.success(result["message"], data=result)


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_connect4_tool(action: str, column: int = 0) -> ToolResult:
    """Play Connect Four. 'start' to begin, 'drop' in a column (1-7)."""
    result = play_connect4(action, column)
    return ToolResult.success(result["message"], data=result)


@tool(security=SecurityLevel.SAFE, tier=CapabilityTier.READONLY)  # tier: in-memory game state only, no external side effects
def play_rps_tool(action: str, choice: str = "") -> ToolResult:
    """Play Rock-Paper-Scissors. 'play' with rock, paper, or scissors."""
    result = play_rps(action, choice)
    return ToolResult.success(result["message"], data=result)
