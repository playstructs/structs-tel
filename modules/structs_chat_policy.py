"""
Synapse module: guild chat policy for every structs-tel homeserver.

Enforces, for users on THIS homeserver only (remote events are never rejected,
so federated room state cannot diverge):

1. No end-to-end encryption. ``m.room.encryption`` is refused, including in
   ``createRoom`` initial_state. Comms has no E2EE, so an encrypted room is a
   room half the guild cannot read.
2. Only room managers (``@guild-bot``) may make a room ``public``. Players can
   still create DMs and invite / knock / restricted rooms. Aliases and directory
   publication are gated separately by ``alias_creation_rules`` and
   ``room_list_publication_rules`` in homeserver.yaml.

Config (homeserver.yaml):

    modules:
      - module: structs_chat_policy.StructsChatPolicy
        config:
          room_managers: ["@guild-bot:matrix.example"]
"""
from __future__ import annotations

from typing import Any

from synapse.events import EventBase
from synapse.module_api import ModuleApi
from synapse.types import StateMap


class StructsChatPolicy:
    def __init__(self, config: dict[str, Any], api: ModuleApi):
        self._api = api
        self._room_managers = frozenset(config.get("room_managers") or [])
        api.register_third_party_rules_callbacks(
            check_event_allowed=self.check_event_allowed,
        )

    @staticmethod
    def parse_config(config: dict[str, Any]) -> dict[str, Any]:
        managers = config.get("room_managers") or []
        if not isinstance(managers, list) or not all(isinstance(m, str) for m in managers):
            raise ValueError("room_managers must be a list of MXIDs")
        return config

    async def check_event_allowed(
        self, event: EventBase, state_events: StateMap[EventBase]
    ) -> tuple[bool, dict | None]:
        if not self._api.is_mine(event.sender):
            return True, None

        if event.type == "m.room.encryption":
            return False, None

        if (
            event.type == "m.room.join_rules"
            and event.content.get("join_rule") == "public"
            and event.sender not in self._room_managers
        ):
            return False, None

        return True, None
