"""Sequential effect pipeline for spell resolution.

Each step in a spell's ``pipeline_effects`` list is processed in order.
Steps may read and write to a shared ephemeral ``context`` dict, allowing
later steps to reference results of earlier ones (e.g. ``context.damage_dealt``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.models.entity import Entity
from src.models.action import SpellAction
from src.models.damage import Damage, DamageType
from src.utils.dice import roll_formula, multiply_formula
from src.utils.saving_throw import roll_saving_throw
from src.rules.expressions import build_context, evaluate, resolve
from .attack_resolver import AttackResolver
from .event_bus import CombatEvent, EventBus
from .event_data import AttackDeclaredData, AttackRolledData, SpellHitData, HealingAppliedData
from .events import EventType

if TYPE_CHECKING:
    from src.rules.rule_engine import RuleEngine
    from .damage_processor import DamageProcessor

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Outcome from running an effect pipeline for one caster/defender pair."""
    hit: bool = True
    damage_dealt: int = 0
    healing_total: int = 0
    healed_entity: Optional[Entity] = None
    save_roll: Optional[int] = None
    save_dc: Optional[int] = None
    save_success: bool = True
    attack_roll: Optional[int] = None
    attack_total: Optional[int] = None
    critical_hit: bool = False
    critical_miss: bool = False


class EffectPipeline:
    """Processes a sequential list of effect steps, maintaining an ephemeral context dict.

    The pipeline handles both attack-roll spells and saving-throw spells through
    explicit ``attack_roll`` / ``saving_throw`` step types. Later steps such as
    ``damage`` and ``healing`` can reference results via ``context.<key>`` in
    their condition and amount expressions.
    """

    def __init__(
        self,
        event_bus: EventBus,
        damage_processor: DamageProcessor,
        rule_engine: Optional[RuleEngine] = None,
    ) -> None:
        self._event_bus = event_bus
        self._damage_processor = damage_processor
        self._rule_engine = rule_engine

    def run(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        seed_damages: Optional[Dict[int, int]] = None,
    ) -> PipelineResult:
        """Execute all pipeline_effects steps sequentially.

        Args:
            caster: Entity casting the spell.
            defender: Target of this pipeline run.
            action: SpellAction whose ``pipeline_effects`` are processed.
            seed_damages: Pre-rolled damage amounts keyed by step index.
                          Used for ``roll_once: true`` damage steps so that
                          all targets of an AoE spell take the same damage.

        Returns:
            PipelineResult summarising damage, healing, hit, and save outcomes.
        """
        # Initialise context with sensible defaults so expression evaluation
        # never raises AttributeError for uninitialised keys.
        context: Dict[str, Any] = {
            "hit": True,
            "critical_hit": False,
            "critical_miss": False,
            "save_success": True,
            "save_roll": None,
            "attack_roll": None,
            "save_dc": None,
            "attack_total": None,
            "damage_dealt": 0,
            "damage_rolled": 0,
            "healing_amount": 0,
            "temp_hp_granted": 0,
        }
        if seed_damages:
            for idx, amount in seed_damages.items():
                context[f"_pre_rolled_{idx}"] = amount

        healing_total = 0
        healed_entity: Optional[Entity] = None
        spell_hit_emitted = False

        for i, step in enumerate(action.pipeline_effects):
            step_type = step.get("type", "")

            # Emit SPELL_HIT before the first effect/damage step, so that entity
            # effects subscribed to SPELL_HIT fire at the correct moment.
            if step_type not in ("attack_roll", "saving_throw") and not spell_hit_emitted:
                self._emit_spell_hit(caster, defender, action, context)
                spell_hit_emitted = True

            if step_type == "attack_roll":
                self._handle_attack_roll(step, caster, defender, action, context)

            elif step_type == "saving_throw":
                self._handle_saving_throw(step, caster, defender, context)

            elif step_type == "damage":
                dealt = self._handle_damage(step, i, caster, defender, action, context)
                context["damage_dealt"] = context["damage_dealt"] + dealt

            elif step_type == "healing":
                amt, entity = self._handle_healing(step, caster, defender, context)
                if amt > 0 and entity is not None:
                    healing_total += amt
                    healed_entity = entity
                    context["healing_amount"] = amt

            elif step_type == "add_entity_effect":
                self._handle_add_entity_effect(step, caster, defender, action, context)

            elif step_type == "grant_temporary_hp":
                self._handle_grant_temporary_hp(step, caster, defender, context)

            elif step_type == "apply_condition":
                self._handle_apply_condition(step, caster, defender, action, context)

            elif step_type == "add_modifier":
                self._handle_add_modifier(step, caster, defender, context)

            else:
                logger.warning("EffectPipeline: unknown step type %r (skipping)", step_type)

        if not spell_hit_emitted:
            self._emit_spell_hit(caster, defender, action, context)

        return PipelineResult(
            hit=context["hit"],
            damage_dealt=context["damage_dealt"],
            healing_total=healing_total,
            healed_entity=healed_entity,
            save_roll=context["save_roll"],
            save_dc=context["save_dc"],
            save_success=context["save_success"],
            attack_roll=context["attack_roll"],
            attack_total=context["attack_total"],
            critical_hit=context["critical_hit"],
            critical_miss=context["critical_miss"],
        )

    # ------------------------------------------------------------------
    # Step handlers
    # ------------------------------------------------------------------

    def _handle_attack_roll(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        context: dict,
    ) -> None:
        """Emit ATTACK_DECLARED, roll the attack, write hit/attack_roll/attack_total."""
        spell_declared = self._event_bus.emit(
            EventType.ATTACK_DECLARED,
            AttackDeclaredData(attacker=caster, defender=defender, action=action),
        )
        if spell_declared.cancelled:
            context["hit"] = False
            context["attack_roll"] = 0
            context["attack_total"] = 0
            return

        bonus_spec = step.get("attack_bonus", 0)
        if bonus_spec == "use_caster_bonus":
            effective_bonus = caster.spell_attack_bonus
        else:
            effective_bonus = int(bonus_spec)

        roll = AttackResolver._resolve_attack_roll(spell_declared)
        total = roll + effective_bonus

        context["attack_roll"] = roll
        context["attack_total"] = total

        spell_rolled = self._event_bus.emit(
            EventType.ATTACK_ROLLED,
            AttackRolledData(attacker=caster, defender=defender, action=action, roll=roll, total=total),
        )
        
        # Check if ATTACK_ROLLED event has returned a critical hit or miss being noted
        # Handling is done this way for more flexibility (like an effect to let fighters crit on 19)
        critical_hit = spell_rolled.data.get("critical_hit", False)
        critical_miss = spell_rolled.data.get("critical_miss", False)
        context["critical_hit"] = critical_hit
        context["critical_miss"] = critical_miss

        hit = (
            True if critical_hit else 
            False if critical_miss else 
            total >= defender.ac
        )
        context["hit"] = hit

        roll_mode = AttackResolver._roll_mode_label(spell_declared)
        logger.debug(
            "attack_roll step: %s%s roll=%d+%d=%d vs AC %d → %s",
            action.name, roll_mode, roll, effective_bonus, total, defender.ac,
            "hit" if hit else "miss",
        )

    def _handle_saving_throw(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        context: dict,
    ) -> None:
        """Roll a saving throw and write save_roll/save_success to context."""
        attribute = step.get("attribute", "")
        dc_spec = step.get("dc", 0)
        if dc_spec == "use_caster_dc":
            effective_dc = caster.spell_save_dc
        else:
            effective_dc = int(dc_spec)

        if effective_dc > 0 and attribute:
            save_roll, save_success = roll_saving_throw(defender, attribute, effective_dc)
        else:
            save_roll, save_success = None, True

        context["save_roll"] = save_roll
        context["save_dc"] = effective_dc
        context["save_success"] = save_success
        logger.debug(
            "saving_throw step: %s DC %d → roll=%s success=%s",
            attribute, effective_dc, save_roll, save_success,
        )

    def _handle_damage(
        self,
        step: dict,
        step_idx: int,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        context: dict,
    ) -> int:
        """Apply damage to the defender, respecting hit/save conditions.

        Returns the amount of damage actually dealt (after resistances etc.).
        """
        # Gate on requires_hit: skip entirely on a miss
        if step.get("requires_hit") and not context["hit"]:
            return 0

        if not self._check_condition(step, caster, defender, action, context, label="damage"):
            return 0

        # Determine damage amount — use pre-rolled seed if available (roll_once)
        pre_rolled_key = f"_pre_rolled_{step_idx}"
        if pre_rolled_key in context:
            amount = context[pre_rolled_key]
        else:
            formula = step.get("formula", "")
            if context["critical_hit"] and formula:
                formula = multiply_formula(formula, 2)
            amount = roll_formula(formula) if formula else 0

        context["damage_rolled"] = context.get("damage_rolled", 0) + amount

        # Apply save_result modifications
        save_result = step.get("save_result", {})
        if save_result and context["save_roll"] is not None and context["save_success"]:
            on_success = save_result.get("on_success")
            if on_success == "half_damage":
                amount = amount // 2
            elif on_success == "no_damage":
                amount = 0

        if amount <= 0:
            return 0

        damage_type = DamageType[step.get("damage_type", "GENERIC").upper()]
        dealt = self._damage_processor.apply_damage(
            defender, [Damage(damage_type, amount)], source=caster, action_name=action.name,
        )
        logger.debug(
            "damage step: %s %d %s → dealt %d to %s",
            action.name, amount, damage_type.name, dealt, defender.name,
        )
        return dealt

    def _handle_healing(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        context: dict,
    ) -> tuple:
        """Heal a target. Returns (amount_healed, healed_entity)."""
        if not self._check_condition(step, caster, defender, None, context, label="healing"):
            return 0, None

        target = self._resolve_target(step, caster, defender)
        ctx = self._make_eval_ctx(caster, defender, None, context)

        amount_expr = step.get("amount")
        formula = step.get("formula")
        bonus_spec = step.get("bonus", 0)

        if amount_expr is not None:
            try:
                amount = int(resolve(amount_expr, ctx))
            except Exception as exc:
                logger.debug("healing amount eval failed (%s: %s)", type(exc).__name__, exc)
                return 0, None
        elif formula:
            amount = roll_formula(formula)
            try:
                bonus = int(resolve(bonus_spec, ctx)) if isinstance(bonus_spec, str) else int(bonus_spec)
            except Exception:
                bonus = 0
            amount += bonus
        else:
            return 0, None

        if amount <= 0:
            return 0, None

        target.heal(amount)
        self._event_bus.emit(
            EventType.HEALING_APPLIED,
            HealingAppliedData(target=target, amount=amount),
        )
        logger.debug("healing step: healed %s for %d", target.name, amount)
        return amount, target

    def _handle_add_entity_effect(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        context: dict,
    ) -> None:
        """Apply a named entity effect (from the rule_engine registry)."""
        if self._rule_engine is None:
            logger.warning("add_entity_effect: no rule_engine available")
            return

        if not self._check_condition(step, caster, defender, action, context, label="add_entity_effect"):
            return

        effect_name = step.get("entity_effect_name", "")
        rule = self._rule_engine.effect_registry.get(effect_name)
        if rule is None:
            logger.warning("add_entity_effect: unknown effect %r", effect_name)
            return

        on_caster = step.get("on_caster", False)
        effect_entity = caster if on_caster else defender

        ctx = self._make_eval_ctx(caster, defender, action, context)

        # Evaluate instance_fields expressions
        instance_fields: Dict[str, Any] = {}
        for field_name, expr in step.get("instance_fields", {}).items():
            try:
                instance_fields[field_name] = resolve(expr, ctx)
            except Exception as exc:
                logger.debug(
                    "add_entity_effect instance_field %r failed (%s: %s)",
                    field_name, type(exc).__name__, exc,
                )

        # Drop old concentration effect BEFORE applying the new one to avoid
        # the new effect being immediately removed by the old effect's teardown.
        if step.get("concentration"):
            if caster.concentrating_on and caster.concentration_target:
                caster.concentration_target.remove_effect(caster.concentrating_on)

        self._rule_engine.apply_effect(effect_entity, rule, instance_fields=instance_fields)
        logger.info("add_entity_effect: applied %r to %s", effect_name, effect_entity.name)

        # Track concentration linkage so concentration checks know which entity
        # holds the effect and can remove it on a failed save.
        if step.get("concentration"):
            caster.concentrating_on = effect_name
            caster.concentration_target = effect_entity

        # Execute on_apply sub-actions using the existing built-in handler registry
        stub_event = self._make_stub_event(caster, defender, action, context)
        for on_apply_effect in step.get("on_apply", []):
            action_name = on_apply_effect.get("action")
            handler = self._rule_engine._effect_registry.get(action_name)
            if handler is None:
                logger.warning("add_entity_effect on_apply: unknown action %r", action_name)
                continue
            handler(on_apply_effect, ctx, stub_event, self._event_bus)

    def _handle_grant_temporary_hp(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        context: dict,
    ) -> None:
        """Grant temporary hit points to a target."""
        target = self._resolve_target(step, caster, defender)

        ctx = self._make_eval_ctx(caster, defender, None, context)
        try:
            amount = int(resolve(step.get("amount", 0), ctx))
        except Exception:
            amount = 0

        if amount > 0:
            target.gain_temporary_hp(amount)
            context["temp_hp_granted"] = amount
            logger.debug("grant_temporary_hp: %s gains %d temp HP", target.name, amount)

    def _handle_apply_condition(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        context: dict,
    ) -> None:
        """Apply a status condition to a target (delegates to the rule engine)."""
        if self._rule_engine is None:
            return

        if not self._check_condition(step, caster, defender, action, context, label="apply_condition"):
            return

        # Build a synthetic on_apply dict that matches the ApplyCondition handler format
        on_apply_spec = {
            "action": "ApplyCondition",
            "target": "event.defender" if step.get("target", "defender") == "defender" else "event.caster",
            "condition_type": step.get("condition_type", ""),
            "duration": step.get("duration"),
            "source": step.get("source", ""),
        }
        if step.get("instance_fields"):
            on_apply_spec["instance_fields"] = step["instance_fields"]

        handler = self._rule_engine._effect_registry.get("ApplyCondition")
        if handler is None:
            logger.warning("apply_condition: ApplyCondition handler not found in rule engine")
            return

        ctx = self._make_eval_ctx(caster, defender, action, context)
        handler(on_apply_spec, ctx, self._make_stub_event(caster, defender, action, context), self._event_bus)

    def _handle_add_modifier(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        context: dict,
    ) -> None:
        """Add a stat modifier to a target (delegates to the rule engine)."""
        if self._rule_engine is None:
            return

        target_spec = step.get("target", "defender")

        on_apply_spec = {
            "action": "AddModifier",
            "target": "event.caster" if target_spec == "caster" else "event.defender",
            "stat": step.get("stat", ""),
            "value": step.get("value", 0),
            "source": step.get("source", ""),
            "effect_name": step.get("effect_name", ""),
        }

        handler = self._rule_engine._effect_registry.get("AddModifier")
        if handler is None:
            logger.warning("add_modifier: AddModifier handler not found in rule engine")
            return

        ctx = self._make_eval_ctx(caster, defender, None, context)
        stub_event = CombatEvent(
            event_type=EventType.SPELL_HIT,
            data=SpellHitData(
                caster=caster, defender=defender, action=None,
                roll=None, save_success=True, save_roll=None,
            ),
        )
        handler(on_apply_spec, ctx, stub_event, self._event_bus)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_condition(
        self,
        step: dict,
        caster: Entity,
        defender: Entity,
        action: Optional[SpellAction],
        context: dict,
        *,
        label: str = "",
    ) -> bool:
        """Return False if the step's ``condition`` expression evaluates falsy.

        Returns True when no condition is present (i.e. step always runs).
        Logs a debug message and returns False on evaluation errors.
        """
        condition = step.get("condition")
        if not condition:
            return True
        ctx = self._make_eval_ctx(caster, defender, action, context)
        try:
            return bool(evaluate(condition, ctx))
        except Exception as exc:
            logger.debug("%s condition eval failed (%s: %s)", label, type(exc).__name__, exc)
            return False

    def _resolve_target(self, step: dict, caster: Entity, defender: Entity) -> Entity:
        """Return caster or defender based on the step's ``target`` field."""
        return caster if step.get("target", "defender") == "caster" else defender

    def _make_stub_event(
        self,
        caster: Entity,
        defender: Entity,
        action: Optional[SpellAction],
        context: dict,
    ) -> CombatEvent:
        """Build a synthetic SPELL_HIT CombatEvent for on_apply handler dispatch."""
        return CombatEvent(
            event_type=EventType.SPELL_HIT,
            data=SpellHitData(
                caster=caster, defender=defender, action=action,
                roll=context["attack_total"],
                save_success=context["save_success"],
                save_roll=context["save_roll"],
            ),
        )

    def _emit_spell_hit(
        self,
        caster: Entity,
        defender: Entity,
        action: SpellAction,
        context: dict,
    ) -> None:
        """Emit the SPELL_HIT event with current context state."""
        self._event_bus.emit(
            EventType.SPELL_HIT,
            SpellHitData(
                caster=caster, defender=defender, action=action,
                roll=context["attack_total"],
                save_success=context["save_success"],
                save_roll=context["save_roll"],
            ),
        )

    def _make_eval_ctx(
        self,
        caster: Entity,
        defender: Entity,
        action: Optional[SpellAction],
        pipeline_context: dict,
    ) -> dict:
        """Build an expression evaluation namespace that includes a ``context`` SimpleNamespace.

        The ``context`` object exposes all pipeline context keys so that
        effect conditions and amounts can reference e.g. ``context.damage_dealt``.
        Private keys (prefixed with ``_``) are excluded to avoid leaking
        internal seed values.
        """
        public_ctx = {k: v for k, v in pipeline_context.items() if not k.startswith("_")}
        event_data: dict = {"caster": caster, "defender": defender}
        if action is not None:
            event_data["action"] = action
        return build_context(
            event_data,
            save_success=pipeline_context["save_success"],
            save_roll=pipeline_context["save_roll"],
            context=SimpleNamespace(**public_ctx),
        )
