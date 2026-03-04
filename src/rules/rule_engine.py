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

Missing fields and the silent-skip rule
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
If an event type does not carry the field a condition references (e.g.
``ROUND_START`` has ``round_num`` but no ``target``), accessing
``event.target`` raises ``AttributeError``.  The engine catches *all*
exceptions from condition evaluation and silently skips the rule for that
event.  This is intentional: a rule such as
``"condition": "event.target.has_concentration"`` should simply not fire
for ``ROUND_START``, not crash the combat.
"""

from types import SimpleNamespace
from typing import Callable, Dict, List, Optional

from src.combat.event_bus import CombatEvent, EventBus
from src.combat.events import EventType
from .effects import BUILTIN_EFFECTS
from .rule import Rule
from .rule_loader import RuleLoader


_SAFE_BUILTINS: Dict = {
    "max": max, "min": min, "abs": abs, "int": int,
    "round": round, "bool": bool, "len": len, "hasattr": hasattr,
}

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
                 entities_getter: Optional[Callable[[], list]] = None) -> None:
        self.event_bus = event_bus
        self._entities_getter = entities_getter
        self._rules: List[Rule] = []
        self._effect_registry: Dict[str, EffectHandler] = dict(BUILTIN_EFFECTS)
        if entities_getter is not None:
            for event_type in EventType:
                event_bus.subscribe(event_type, self._handle_entity_effects)

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
        self._rules.append(rule)
        # Capture rule in closure so each subscription references its own Rule.
        self.event_bus.subscribe(rule.trigger, lambda e, r=rule: self._dispatch(r, e))

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

    def apply_effect(self, entity, rule: Rule) -> None:
        """Attach a rule as an entity-scoped effect."""
        entity.add_effect(rule.trigger.value, rule)

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
        - ``_event``: the raw ``CombatEvent`` object (for handlers that need
          to mutate ``event.cancelled``; condition expressions should use
          ``event.*`` instead).
        - All entries from ``_SAFE_BUILTINS``: ``max``, ``min``, ``abs``,
          ``int``, ``round``, ``bool``, ``len``, ``hasattr``.
        """
        event_ns = SimpleNamespace(**event.data)
        return {**_SAFE_BUILTINS, "event": event_ns, "_event": event}

    def _eval(self, expr: str, ctx: dict):
        return eval(expr, {"__builtins__": {}}, ctx)

    def _dispatch(self, rule: Rule, event: CombatEvent, entity=None) -> None:
        if not rule.enabled:
            return

        ctx = self._make_context(event)
        if entity is not None:
            ctx["entity"] = entity

        if rule.condition:
            try:
                if not self._eval(rule.condition, ctx):
                    return
            except Exception:
                # Condition couldn't be evaluated (e.g. missing attribute on
                # this event type) — silently skip rather than crashing.
                return

        for effect in rule.effects:
            action = effect.get("action")
            handler = self._effect_registry.get(action)
            if handler is None:
                raise ValueError(
                    f"Rule '{rule.name}': unknown effect action '{action}'. "
                    f"Registered actions: {list(self._effect_registry)}"
                )
            handler(effect, ctx, event, self.event_bus)
            # Stop processing further effects if the event was cancelled.
            if event.cancelled:
                break

    def _handle_entity_effects(self, event: CombatEvent) -> None:
        """Iterate all entities and dispatch their effects for this trigger."""
        trigger_str = event.event_type.value
        for entity in self._entities_getter():
            for effect_rule in list(entity.get_effects_for_trigger(trigger_str)):
                self._dispatch(effect_rule, event, entity=entity)
        if event.event_type == EventType.TURN_END:
            self._tick_durations(event.data.get("entity"))

    def _tick_durations(self, entity) -> None:
        """Decrement duration_rounds for entity's effects; remove expired ones."""
        if entity is None:
            return
        for trigger_str, bucket in list(entity.active_effects.items()):
            bucket[:] = [e for e in bucket if not self._tick_one(e)]

    @staticmethod
    def _tick_one(rule: Rule) -> bool:
        """Decrement and return True if expired."""
        if rule.duration_rounds is None:
            return False
        rule.duration_rounds -= 1
        return rule.duration_rounds <= 0
