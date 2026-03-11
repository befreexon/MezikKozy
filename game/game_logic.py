"""
Pure Python game logic for Mezi Kostkami.
No Django dependencies — easy to test in isolation.
"""
import random


def roll_dice(n=1):
    return [random.randint(1, 6) for _ in range(n)]


def create_game_state(players, starting_money=100, base_bet=10):
    """
    Create initial game state.

    players: list of dicts with keys: name, user_id
    starting_money: initial amount each player receives
    base_bet: minimum bet unit (also used as ante amount)
    """
    state = {
        "players": [
            {
                "name": p["name"],
                "user_id": p["user_id"],
                "money": starting_money,
                "eliminated": False,
            }
            for p in players
        ],
        "current": 0,
        "bank": 0,
        "phase": "new-round",
        "first_roll": None,
        "selected_bet": None,
        "last_result": None,
        "bonus_roll": None,
        "winner_id": None,
        "base_bet": base_bet,
        "log": [],
    }
    _collect_ante(state, "Počáteční vklad do banku")
    _check_eliminations(state)
    return state


def process_action(state, action, data=None):
    """
    Process a player action and mutate state in place.
    Returns True if the action was valid and applied, False otherwise.
    """
    if data is None:
        data = {}

    phase = state["phase"]

    if action == "roll_first" and phase == "new-round":
        return _do_first_roll(state)
    elif action == "select_bet" and phase == "rolled":
        return _select_bet(state, data.get("amount"))
    elif action == "confirm_bet" and phase == "rolled":
        return _confirm_bet(state)
    elif action == "skip" and phase == "rolled":
        return _skip(state)
    elif action == "roll_bonus" and phase == "betting":
        return _do_bonus_roll(state)
    elif action == "next_player" and phase == "result":
        return _advance_to_next_player(state)

    return False


# ── Internal helpers ──────────────────────────────────────────────────────────


def _add_log(state, message, log_type="info"):
    state["log"].insert(0, {"message": message, "type": log_type})
    if len(state["log"]) > 40:
        state["log"] = state["log"][:40]


def _get_active_players(state):
    return [p for p in state["players"] if not p["eliminated"]]


def _collect_ante(state, reason="Nový vklad do banku"):
    active = _get_active_players(state)
    if not active:
        return
    ante = state.get("base_bet", 10)
    total = 0
    for player in active:
        amount = min(ante, player["money"])
        if amount > 0:
            player["money"] -= amount
            state["bank"] += amount
            total += amount
    if total > 0:
        names = ", ".join(p["name"] for p in active)
        _add_log(state, f"{reason}: každý vložil {ante} Kč do banku. ({names})", "system")


def _check_eliminations(state):
    for player in state["players"]:
        if not player["eliminated"] and player["money"] <= 0:
            player["eliminated"] = True
            player["money"] = 0
            _add_log(state, f"{player['name']} nemá žádné peníze a je vyřazen!", "loss")


def _check_game_over(state):
    active = _get_active_players(state)
    if len(active) == 1:
        winner = active[0]
        winner["money"] += state["bank"]
        state["bank"] = 0
        state["phase"] = "game-over"
        state["winner_id"] = winner["user_id"]
        _add_log(state, f"🏆 {winner['name']} vyhrál hru!", "win")
        return True
    return False


def _do_first_roll(state):
    dice = roll_dice(3)
    sorted_dice = sorted(dice)
    lo, mid, hi = sorted_dice

    current_player = state["players"][state["current"]]

    if hi - lo <= 1:
        _add_log(
            state,
            f"{current_player['name']} hodil: {dice[0]}, {dice[1]}, {dice[2]} — Neplatný rozsah, přeskočeno.",
            "info",
        )
        _next_player_internal(state)
        return True

    state["first_roll"] = sorted_dice
    state["bonus_roll"] = None
    state["phase"] = "rolled"
    _add_log(
        state,
        f"{current_player['name']} hodil: {sorted_dice[0]}, {sorted_dice[1]}, {sorted_dice[2]} (rozsah {lo}–{hi})",
        "info",
    )
    return True


def _select_bet(state, amount):
    current_player = state["players"][state["current"]]

    if amount == "all-in":
        amount = current_player["money"]
    else:
        try:
            amount = int(amount)
        except (ValueError, TypeError):
            return False

    if amount <= 0 or amount > current_player["money"]:
        return False

    state["selected_bet"] = amount
    return True


def _confirm_bet(state):
    if state["selected_bet"] is None:
        return False
    state["phase"] = "betting"
    return True


def _skip(state):
    current_player = state["players"][state["current"]]
    _add_log(state, f"{current_player['name']} přeskočil bonusový hod.", "info")
    _next_player_internal(state)
    return True


def _do_bonus_roll(state):
    current_player = state["players"][state["current"]]
    bonus = roll_dice(1)[0]
    state["bonus_roll"] = bonus

    lo, mid, hi = state["first_roll"]
    bet = state["selected_bet"]
    in_between = lo < bonus < hi

    if in_between:
        won = min(bet, state["bank"])
        current_player["money"] += won
        state["bank"] -= won
        state["last_result"] = "win"
        _add_log(
            state,
            f"🏆 {current_player['name']} hodil {bonus} (mezi {lo} a {hi}). Vyhrál {won} Kč!",
            "win",
        )
        if state["bank"] == 0:
            _check_eliminations(state)
            if len(_get_active_players(state)) > 1:
                _add_log(state, "Banka je prázdná!", "system")
                _collect_ante(state, "Nový vklad do banku")
    else:
        lost = min(bet, current_player["money"])
        current_player["money"] -= lost
        state["bank"] += lost
        state["last_result"] = "loss"
        _add_log(
            state,
            f"💸 {current_player['name']} hodil {bonus} (mimo {lo}–{hi}). Prohrál {lost} Kč.",
            "loss",
        )

    state["phase"] = "result"
    _check_eliminations(state)
    _check_game_over(state)
    return True


def _advance_to_next_player(state):
    _check_eliminations(state)
    if _check_game_over(state):
        return True
    _next_player_internal(state)
    return True


def _next_player_internal(state):
    n = len(state["players"])
    current = state["current"]
    for i in range(1, n + 1):
        next_idx = (current + i) % n
        if not state["players"][next_idx]["eliminated"]:
            state["current"] = next_idx
            break

    state["phase"] = "new-round"
    state["first_roll"] = None
    state["selected_bet"] = None
    state["last_result"] = None
    state["bonus_roll"] = None

    if state["bank"] == 0:
        _collect_ante(state)
