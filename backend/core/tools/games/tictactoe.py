"""Tic-Tac-Toe — 3x3 grid game against the computer."""
from typing import Any


def _print_board(board: list[str]) -> str:
    return "\n".join([
        f" {board[0]} | {board[1]} | {board[2]} ",
        "---+---+---",
        f" {board[3]} | {board[4]} | {board[5]} ",
        "---+---+---",
        f" {board[6]} | {board[7]} | {board[8]} ",
    ])


def _check_winner(board: list[str]) -> str | None:
    lines = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8],
        [0, 3, 6], [1, 4, 7], [2, 5, 8],
        [0, 4, 8], [2, 4, 6],
    ]
    for a, b, c in lines:
        if board[a] == board[b] == board[c] and board[a] != " ":
            return board[a]
    if " " not in board:
        return "tie"
    return None


def _computer_move(board: list[str]) -> int:
    for i in range(9):
        if board[i] == " ":
            board[i] = "O"
            if _check_winner(board) == "O":
                board[i] = " "
                return i
            board[i] = " "
    for i in range(9):
        if board[i] == " ":
            board[i] = "X"
            if _check_winner(board) == "X":
                board[i] = " "
                return i
            board[i] = " "
    for i in (4, 0, 2, 6, 8, 1, 3, 5, 7):
        if board[i] == " ":
            return i
    return -1


def play_tictactoe(action: str, position: int = 0) -> dict[str, Any]:
    """Play Tic-Tac-Toe. action: 'start', 'move'. position: 1-9 for cell."""
    from backend.core.tools.games import _state

    state = _state.setdefault("tictactoe", {})
    if action == "start" or "board" not in state:
        state["board"] = [" "] * 9

    board = state["board"]

    if action == "move":
        idx = position - 1
        if idx < 0 or idx > 8 or board[idx] != " ":
            return {
                "board": _print_board(board),
                "message": "Invalid position. Pick an empty cell (1-9).",
                "status": "error",
            }
        board[idx] = "X"
        winner = _check_winner(board)
        if winner:
            state["board"] = [" "] * 9
            if winner == "X":
                return {"board": _print_board(board), "message": "You win!", "status": "won"}
            if winner == "tie":
                return {"board": _print_board(board), "message": "It's a tie!", "status": "tie"}
            return {"board": _print_board(board), "message": f"{winner} wins!", "status": "won"}

        comp = _computer_move(board)
        if comp >= 0:
            board[comp] = "O"
            winner = _check_winner(board)
            if winner:
                state["board"] = [" "] * 9
                if winner == "O":
                    return {"board": _print_board(board), "message": "Computer wins!", "status": "lost"}
                if winner == "tie":
                    return {"board": _print_board(board), "message": "It's a tie!", "status": "tie"}
                return {"board": _print_board(board), "message": f"{winner} wins!", "status": "lost"}

        return {
            "board": _print_board(board),
            "message": "Your turn. Pick a position (1-9):",
            "status": "playing",
        }

    return {
        "board": _print_board(board),
        "message": "Your turn (X). Pick a position (1-9):",
        "status": "playing",
    }
