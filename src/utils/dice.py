"""Dice rolling utilities."""

import random
from typing import Tuple, List


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


def parse_dice_formula(formula: str) -> Tuple[int, int, int]:
    """Parse a dice formula like "2d6+3".
    
    Args:
        formula: Dice formula string
        
    Returns:
        Tuple of (num_dice, num_sides, modifier)
        
    Raises:
        ValueError: If formula is invalid
    """
    formula = formula.strip().lower()
    
    # Split by + or -
    parts = formula.replace("+", " +").replace("-", " -").split()
    
    # Parse dice part
    if not parts or "d" not in parts[0]:
        raise ValueError(f"Invalid dice formula: {formula}")
    
    dice_parts = parts[0].split("d")
    num_dice = int(dice_parts[0]) if dice_parts[0] else 1
    num_sides = int(dice_parts[1])
    
    # Parse modifier
    modifier = 0
    for part in parts[1:]:
        modifier += int(part)
    
    return num_dice, num_sides, modifier


def roll_formula(formula: str) -> int:
    """Roll a dice formula.
    
    Args:
        formula: Dice formula like "2d6+3"
        
    Returns:
        Total result
    """
    num_dice, num_sides, modifier = parse_dice_formula(formula)
    return roll_dice(num_dice, num_sides) + modifier


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
