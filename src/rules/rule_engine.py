"""Rule engine — evaluates JSON-defined rules against combat events.

How expression evaluation works
---------------------------------
Every rule may have a ``condition`` string and every effect field may contain a
Python expression string.  Both are evaluated via ``eval()`` inside a carefully
controlled namespace so that rule authors can write natural D&D expressions
without being able to do anything dangerous.

The namespace is built by ``_make_context`` from the live ``CombatEvent``.
When ``CombatSystem`` (or any other emitter) calls::

    event_bus.emit(EventType.DAMAGE_DEALT, defender=entity, damage_list=[], total=20)

the kwargs become ``event.data = {"target": entity, "damage_list": [], "total": 20}``.
``_make_context`` then does::

    event_ns = SimpleNamespace(**event.data)   # event_ns.target  → entity
                                               # event_ns.total   → 20

and returns a dict with ``"event": event_ns`` as a key.  When the engine
evaluates the string ``"event.target.has_concentration"``, Python sees:

1. ``event``              — the ``SimpleNamespace`` in the namespace dict
2. ``.target``            — attribute access on that namespace → the real Entity
3. ``.has_concentration`` — Python ``@property`` on the Entity → bool

No magic is involved; it is ordinary Python attribute lookup on real objects.

Available names in every expression
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
+-----------------+---------------------------------------------------------+
| Name            | Value                                                   |
+=================+=========================================================+
| ``event``       | ``SimpleNamespace`` wrapping ``event.data``             |
+-----------------+---------------------------------------------------------+
| ``event_type``  | The ``EventType`` enum value for the current event      |
+-----------------+---------------------------------------------------------+
| ``max``         | built-in ``max``                                        |
+-----------------+---------------------------------------------------------+
| ``min``         | built-in ``min``                                        |
+-----------------+---------------------------------------------------------+
| ``abs``         | built-in ``abs``                                        |
+-----------------+---------------------------------------------------------+
| ``int``         | built-in ``int``                                        |
+-----------------+---------------------------------------------------------+
| ``round``       | built-in ``round``                                      |
+-----------------+---------------------------------------------------------+
| ``bool``        | built-in ``bool``                                       |
+-----------------+---------------------------------------------------------+
| ``len``         | built-in ``len``                                        |
+-----------------+---------------------------------------------------------+
| ``hasattr``     | built-in ``hasattr``                                    |
+-----------------+---------------------------------------------------------+

``__builtins__`` is set to ``{}`` — imports, ``open``, ``exec``, and all other
built-ins are unavailable.

Missing fields and the error-handling strategy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
If an event type does not carry the field a condition references (e.g.
``ROUND_START`` has ``round_num`` but no ``target``), accessing
``event.target`` raises ``AttributeError``.  The engine catches
``AttributeError`` specifically and silently skips (DEBUG log).  This is
intentional: a rule such as
``"condition": "event.target.has_concentration"`` should simply not fire
for ``ROUND_START``, not crash the combat.

All *other* exceptions (``NameError``, ``TypeError``, etc.) are logged at
WARNING level, as they likely indicate a bug in the rule condition.  The
rule is still skipped to avoid crashing combat, but the warning helps rule
authors diagnose issues.

Per-effect event gating with ``"on"``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
When a rule has multiple triggers, individual effects can specify which event
type(s) they respond to via the ``"on"`` key::

    {
        "action": "ModifyDamage",
        "multiplier": 0.5,
        "on": "DAMAGE_INCOMING"
    }

``"on"`` accepts either a single event-type string or a list of strings.
If ``"on"`` is absent, the effect fires for all triggers.
"""

import logging
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

from src.combat.event_bus import CombatEvent, EventBus
from src.combat.events import EventType
from .effect_instance import EffectInstance
from .effects import BUILTIN_EFFECTS
from .expressions import SAFE_BUILTINS, build_context, evaluate
from .rule import Rule
from .rule_loader import RuleLoader

EffectHandler = Callable[[dict, dict, CombatEvent, EventBus], None]


class RuleEngine:
    """Evaluates JSON-defined rules against combat events.

    Usage::

        engine = RuleEngine(combat.event_bus)
        engine.load_from_file("rules/concentration.json")

    Custom effects can be registered before loading rules::

        engine.register_effect("MyEffect", my_handler)

    See ``src/rules/effects.py`` for the full handler contract and a worked
    example of writing a new effect.
    """

    def __init__(self, event_bus: EventBus,
                 entities_getter: Optional[Callable[[], list]] = None,
                 damage_processor=None,
                 effect_registry=None) -> None:
        self.event_bus = event_bus
        self._entities_getter = entities_getter
        self._damage_processor = damage_processor
        self.effect_registry = effect_registry
        self._rules: Dict[EventType, List[Rule]] = {}  # {trigger: [Rule, ...]}
        self._effect_registry: Dict[str, EffectHandler] = dict(BUILTIN_EFFECTS)
        # Track which triggers already have a subscription to avoid duplicates.
        self._subscribed_triggers: Set[EventType] = set()
        if entities_getter is not None:
            for event_type in EventType:
                # Priority -10 so entity-scoped effects fire after global rules
                # (e.g. bonus resource effects fire after the refill rule).
                event_bus.subscribe(event_type, self._handle_entity_effects,
                                    priority=-10)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_effect(self, name: str, handler: EffectHandler) -> None:
        """Register a custom effect handler.

        Args:
            name: The action name used in JSON rule files (e.g. "MyEffect").
            handler: Callable with signature
                ``(effect, ctx, event, event_bus) -> None``.
        """
        self._effect_registry[name] = handler

    def load_rule(self, rule: Rule) -> None:
        """Register a Rule and subscribe it to the event bus.

        Args:
            rule: A Rule instance (e.g. from RuleLoader).
        """
        for trigger in rule.triggers:
            if trigger not in self._rules:
                self._rules[trigger] = []
            if trigger not in self._subscribed_triggers:
                self._subscribed_triggers.add(trigger)
                self.event_bus.subscribe(trigger, lambda e, t=trigger: self._dispatch_trigger(t, e))
            self._rules[trigger].append(rule)

    def load_from_file(self, path: str) -> Rule:
        """Load a JSON rule file and register it.

        Args:
            path: Path to the JSON rule file.

        Returns:
            The loaded Rule (for inspection or disabling).
        """
        rule = RuleLoader.load(path)
        self.load_rule(rule)
        return rule

    def apply_effect(self, entity, rule: Rule, instance_fields: dict = None) -> None:
        """Attach a rule as an entity-scoped effect.

        Args:
            entity: The entity to apply the effect to.
            rule: The Rule template to attach.
            instance_fields: Optional dict of per-application data available in
                rule expressions as ``instance_fields.<key>``.  Typical keys:
                ``charmer`` (entity that applied charm), ``caster``, etc.
        """
        instance = EffectInstance(rule=rule, instance_fields=instance_fields or {})
        for trigger in rule.triggers:
            entity.add_effect(trigger.value, instance)

    def remove_effect(self, entity, name: str) -> None:
        """Remove a named effect from an entity."""
        entity.remove_effect(name)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _make_context(self, event: CombatEvent) -> dict:
        """Build the expression evaluation namespace for an event.

        Returns a dict containing:
        - ``event``: a ``SimpleNamespace`` whose attributes are the kwargs that
          were passed to ``event_bus.emit()``.  E.g. for a ``DAMAGE_DEALT``
          event emitted with ``target=entity, total=20``, the namespace has
          ``event.target`` and ``event.total``.
        - ``event_type``: the ``EventType`` enum value for the current event,
          useful in per-effect ``"when"`` expressions when a rule has multiple
          triggers.
        - ``_event``: the raw ``CombatEvent`` object (for handlers that need
          to mutate ``event.cancelled``; condition expressions should use
          ``event.*`` instead).
        - All entries from ``_SAFE_BUILTINS``: ``max``, ``min``, ``abs``,
          ``int``, ``round``, ``bool``, ``len``, ``hasattr``.
        - ``instance_fields``: a ``SimpleNamespace`` of per-application data
          set when ``apply_effect`` was called (e.g. ``instance_fields.charmer``).
          Populated by ``_dispatch``; defaults to an empty namespace.
        """
        extras = {
            "event_type": event.event_type,
            "_event": event,
        }
        if self._damage_processor is not None:
            extras["_damage_processor"] = self._damage_processor
        ctx = build_context(dict(event.data), **extras)
        return ctx

    def _eval(self, expr: str, ctx: dict):
        return evaluate(expr, ctx)

    def _dispatch_trigger(self, trigger: EventType, event: CombatEvent) -> None:
        """Dispatch all global rules registered for *trigger*."""
        for rule in list(self._rules.get(trigger, [])):
            self._dispatch(rule, event)

    def _dispatch(self, rule: Rule, event: CombatEvent, entity=None,
                  instance_fields: dict = None) -> None:
        if not rule.enabled:
            return

        ctx = self._make_context(event)
        if entity is not None:
            ctx["entity"] = entity
        ctx["instance_fields"] = SimpleNamespace(**(instance_fields or {}))

        if rule._compiled_condition is not None:
            try:
                result = self._eval(rule._compiled_condition, ctx)
                logger.debug("Rule '%s' condition evaluated to %s for %s",
                             rule.name, result, event.event_type.value)
                if not result:
                    return
            except AttributeError as exc:
                # Expected: event doesn't carry the fields this condition
                # references (e.g. ROUND_START has no 'defender').
                logger.debug("Rule '%s' condition skipped (missing field: %s) for %s",
                             rule.name, exc, event.event_type.value)
                return
            except Exception as exc:
                # Unexpected: likely a bug in the rule condition expression.
                logger.warning("Rule '%s' condition error (%s: %s) for %s",
                               rule.name, type(exc).__name__, exc,
                               event.event_type.value)
                return

        current_event_type = event.event_type

        for effect in rule.effects:
            # Per-effect event type gate (optional "on" key).
            on_spec = effect.get("on")
            if on_spec is not None:
                if isinstance(on_spec, str):
                    on_spec = [on_spec]
                allowed = {EventType[t.upper()] for t in on_spec}
                if current_event_type not in allowed:
                    continue

            # Per-effect condition gate (optional "when" key)
            when_expr = effect.get("when")
            if when_expr is not None:
                try:
                    if not self._eval(when_expr, ctx):
                        continue
                except AttributeError as exc:
                    logger.debug("Rule '%s' effect 'when' skipped (missing field: %s)",
                                 rule.name, exc)
                    continue
                except Exception as exc:
                    logger.warning("Rule '%s' effect 'when' error (%s: %s)",
                                   rule.name, type(exc).__name__, exc)
                    continue

            action = effect.get("action")
            handler = self._effect_registry.get(action)
            if handler is None:
                raise ValueError(
                    f"Rule '{rule.name}': unknown effect action '{action}'. "
                    f"Registered actions: {list(self._effect_registry)}"
                )
            logger.info("Rule '%s' firing effect '%s' for %s",
                        rule.name, action, event.event_type.value)
            handler(effect, ctx, event, self.event_bus)
            # Stop processing further effects if the event was cancelled.
            if event.cancelled:
                break

    def _handle_entity_effects(self, event: CombatEvent) -> None:
        """Dispatch entity-scoped effects by querying each entity directly."""
        if not self._entities_getter:
            return
        trigger_str = event.event_type.value
        for entity in self._entities_getter():
            for instance in list(entity.get_effects_for_trigger(trigger_str)):
                self._dispatch(instance.rule, event, entity=entity,
                               instance_fields=instance.instance_fields)
        if event.event_type == EventType.TURN_END:
            self._tick_durations(event.data.get("entity"))

    def _tick_durations(self, entity) -> None:
        """Decrement duration_remaining for entity's effect instances; remove expired ones."""
        if entity is None:
            return
        expired_instances: set = set()  # id(instance) of instances that expired this tick
        ticked: set = set()             # id(instance) already ticked (avoid double-decrement
                                        # when the same instance appears in multiple trigger buckets)
        for trigger_str, bucket in list(entity.active_effects.items()):
            surviving = []
            for instance in bucket:
                inst_id = id(instance)
                if inst_id not in ticked:
                    ticked.add(inst_id)
                    if self._tick_one(instance):
                        expired_instances.add(inst_id)
                        continue
                elif inst_id in expired_instances:
                    # Already expired from another trigger bucket
                    continue
                surviving.append(instance)
            bucket[:] = surviving

    @staticmethod
    def _tick_one(instance: EffectInstance) -> bool:
        """Decrement duration_remaining and return True if the instance has expired."""
        if instance.duration_remaining is None:
            return False
        instance.duration_remaining -= 1
        return instance.duration_remaining <= 0
