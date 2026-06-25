"""Blackjack game — play against the dealer."""
import random
from typing import Any

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def _card_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def _hand_value(hand: list[str]) -> int:
    total = sum(_card_value(r) for r in hand)
    aces = hand.count("A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _card_str(rank: str, suit: str) -> str:
    return f"{rank}{suit}"


def new_deck() -> list[tuple[str, str]]:
    return [(r, s) for s in SUITS for r in RANKS]


def deal(deck: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    return player, dealer


def hit(hand: list[tuple[str, str]], deck: list[tuple[str, str]]) -> bool:
    hand.append(deck.pop())
    return _hand_value([r for r, _ in hand]) > 21


def format_hand(hand: list[tuple[str, str]], hide_first: bool = False) -> str:
    if hide_first:
        return f"[?] {_card_str(hand[1][0], hand[1][1])}"
    return " ".join(_card_str(r, s) for r, s in hand)


def play_blackjack(action: str, bet: int = 10) -> dict[str, Any]:
    """Play a round of Blackjack. action: 'deal', 'hit', 'stand'."""
    from backend.core.tools.games import _state

    state = _state.setdefault("blackjack", {})
    if action == "deal" or "deck" not in state:
        deck = new_deck()
        player, dealer = deal(deck)
        state["deck"] = deck
        state["player"] = player
        state["dealer"] = dealer
        state["bet"] = bet
        pv = _hand_value([r for r, _ in player])
        return {
            "hand": format_hand(player),
            "dealer_up": format_hand(dealer, hide_first=True),
            "value": pv,
            "message": f"Your hand: {format_hand(player)} (value: {pv}). Hit or stand?",
            "status": "playing",
        }
    if action == "hit":
        player = state["player"]
        deck = state["deck"]
        busted = hit(player, state["deck"])
        pv = _hand_value([r for r, _ in player])
        if busted:
            return {
                "hand": format_hand(player),
                "value": pv,
                "message": f"Bust! {format_hand(player)} = {pv}. You lose {bet}.",
                "status": "bust",
                "result": "lose",
            }
        return {
            "hand": format_hand(player),
            "value": pv,
            "message": f"Your hand: {format_hand(player)} (value: {pv}). Hit or stand?",
            "status": "playing",
        }
    if action == "stand":
        player = state["player"]
        dealer = state["dealer"]
        deck = state["deck"]
        dv = _hand_value([r for r, _ in dealer])
        while dv < 17:
            dealer.append(deck.pop())
            dv = _hand_value([r for r, _ in dealer])
        pv = _hand_value([r for r, _ in player])
        if dv > 21 or pv > dv:
            result = "win"
            msg = f"You win! Dealer: {format_hand(dealer)} ({dv})."
        elif pv == dv:
            result = "push"
            msg = f"Push! Both have {pv}."
        else:
            result = "lose"
            msg = f"Dealer wins! Dealer: {format_hand(dealer)} ({dv})."
        return {
            "hand": format_hand(player),
            "dealer_hand": format_hand(dealer),
            "value": pv,
            "dealer_value": dv,
            "message": msg,
            "status": "done",
            "result": result,
        }
    return {"message": "Unknown action. Try: deal, hit, or stand.", "status": "error"}
