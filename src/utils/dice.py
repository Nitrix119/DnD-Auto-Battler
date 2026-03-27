"""Dice rolling utilities."""

import re
import random
from typing import List, Tuple


def roll_d20() -> int:
    """Roll a d20.

    Returns:
        Random value from 1-20
    """
    return random.randint(1, 20)


def roll_dice(num_dice: int, num_sides: int) -> int:
    """Roll multiple dice.

    Args:
        num_dice: Number of dice to roll
        num_sides: Sides on each die

    Returns:
        Sum of all dice rolled
    """
    return sum(random.randint(1, num_sides) for _ in range(num_dice))


# Matches tokens like: +2d6, -1d8, +5, -3, 2d6 (leading token, no sign)
_TOKEN_RE = re.compile(r"([+-]?)(\d+)(?:d(\d+))?", re.IGNORECASE)


def parse_dice_formula(formula: str) -> List[Tuple[int, int, int]]:
    """Parse an arbitrary dice formula like "2d6+1d8+5".

    Each token is returned as (sign, num_dice, num_sides) where num_sides=0
    means a flat modifier (num_dice holds the value).

    Args:
        formula: Dice formula string, e.g. "2d6+1d8-3" or "1d20+5"

    Returns:
        List of (signed_count, num_dice, num_sides) tuples.
        For flat modifiers num_sides is 0 and signed_count is the modifier value.

    Raises:
        ValueError: If the formula contains no valid tokens.
    """
    formula = formula.strip().lower().replace(" ", "")
    tokens = _TOKEN_RE.findall(formula)
    if not tokens:
        raise ValueError(f"Invalid dice formula: {formula!r}")

    result = []
    for sign, number, sides in tokens:
        multiplier = -1 if sign == "-" else 1
        if sides:
            result.append((multiplier * int(number), int(sides), True))
        else:
            result.append((multiplier * int(number), 0, False))
    return result


def roll_formula(formula: str) -> int:
    """Roll an arbitrary dice formula.

    Supports formulas like "2d6+1d8+5" or "1d20-2".

    Args:
        formula: Dice formula string

    Returns:
        Total result
    """
    total = 0
    for count_or_val, sides, is_dice in parse_dice_formula(formula):
        if is_dice:
            sign = -1 if count_or_val < 0 else 1
            total += sign * roll_dice(abs(count_or_val), sides)
        else:
            total += count_or_val
    return total


def multiply_formula(formula: str, multiplier: int) -> str:
    """Multiply the dice counts in a formula by a multiplier.

    Args:
        formula: Dice formula string, e.g. "6d8" or "2d6+3"
        multiplier: Factor to multiply dice counts by

    Returns:
        New formula string with dice counts multiplied, e.g. "12d8" or "4d6+3"
    """
    def replace_token(m: re.Match) -> str:
        sign, number, sides = m.group(1), m.group(2), m.group(3)
        if sides:
            return f"{sign}{int(number) * multiplier}d{sides}"
        return f"{sign}{number}"

    return _TOKEN_RE.sub(replace_token, formula.strip().replace(" ", ""))


def roll_with_advantage() -> int:
    """Roll with advantage (roll twice, take highest).
    
    Returns:
        The higher of two d20 rolls
    """
    return max(roll_d20(), roll_d20())


def roll_with_disadvantage() -> int:
    """Roll with disadvantage (roll twice, take lowest).
    
    Returns:
        The lower of two d20 rolls
    """
    return min(roll_d20(), roll_d20())
