"""Connect Four — 7x6 grid game against the computer."""
from typing import Any

ROWS, COLS = 6, 7


def _print_board(board: list[list[str]]) -> str:
    rows = [" 1 2 3 4 5 6 7"]
    for r in range(ROWS):
        rows.append(" ".join(f"{board[r][c]}" for c in range(COLS)))
    return "\n".join(rows)


def _drop(board: list[list[str]], col: int, piece: str) -> int | None:
    for r in range(ROWS - 1, -1, -1):
        if board[r][col] == " ":
            board[r][col] = piece
            return r
    return None


def _check_winner(board: list[list[str]], row: int, col: int, piece: str) -> bool:
    for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
        count = 1
        r, c = row + dr, col + dc
        while 0 <= r < ROWS and 0 <= c < COLS and board[r][c] == piece:
            count += 1; r += dr; c += dc
        r, c = row - dr, col - dc
        while 0 <= r < ROWS and 0 <= c < COLS and board[r][c] == piece:
            count += 1; r -= dr; c -= dc
        if count >= 4:
            return True
    return False


def _computer_move(board: list[list[str]]) -> int:
    for col in range(COLS):
        row = _drop(board, col, "O")
        if row is not None:
            board[row][col] = " "
            if _check_winner(board, row, col, "O"):
                return col
    for col in range(COLS):
        row = _drop(board, col, "X")
        if row is not None:
            board[row][col] = " "
            if _check_winner(board, row, col, "X"):
                return col
    for col in [3, 2, 4, 1, 5, 0, 6]:
        if board[0][col] == " ":
            return col
    return -1


def play_connect4(action: str, column: int = 0) -> dict[str, Any]:
    """Play Connect Four. action: 'start', 'drop'. column: 1-7."""
    from backend.core.tools.games import _state

    state = _state.setdefault("connect4", {})
    if action == "start" or "board" not in state:
        state["board"] = [[" "] * COLS for _ in range(ROWS)]

    board = state["board"]
    if action == "drop":
        col = column - 1
        if col < 0 or col >= COLS or board[0][col] != " ":
            return {"message": "Column full or invalid. Pick 1-7.", "status": "error"}
        row = _drop(board, col, "X")
        if _check_winner(board, row, col, "X"):
            state["board"] = [[" "] * COLS for _ in range(ROWS)]
            return {"board": _print_board(board), "message": "You win!", "status": "won"}
        comp = _computer_move(board)
        if comp >= 0:
            row = _drop(board, comp, "O")
            if _check_winner(board, row, comp, "O"):
                state["board"] = [[" "] * COLS for _ in range(ROWS)]
                return {"board": _print_board(board), "message": "Computer wins!", "status": "lost"}
        if all(board[0][c] != " " for c in range(COLS)):
            state["board"] = [[" "] * COLS for _ in range(ROWS)]
            return {"board": _print_board(board), "message": "It's a tie!", "status": "tie"}
        return {"board": _print_board(board), "message": "Your turn. Drop in column (1-7):", "status": "playing"}

    return {"board": _print_board(board), "message": "Your turn (X). Drop in column (1-7):", "status": "playing"}
