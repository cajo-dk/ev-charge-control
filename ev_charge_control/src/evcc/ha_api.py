from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


DEFAULT_TIMEOUT_SECONDS = 10


class HomeAssistantApiError(RuntimeError):
    """Raised when the Home Assistant API call fails."""


@dataclass(slots=True)
class HomeAssistantClient:
    base_url: str
    token: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def get_state(self, entity_id: str) -> dict[str, Any]:
        payload = self._request_json(f"/states/{entity_id}")
        if not isinstance(payload, dict):
            raise HomeAssistantApiError(
                f"Unexpected response for entity '{entity_id}': expected object."
            )
        if "state" not in payload:
            raise HomeAssistantApiError(
                f"Entity '{entity_id}' response did not contain a state field."
            )
        return payload

    def get_entity_value(self, entity_id: str) -> str | float | int | None:
        state_payload = self.get_state(entity_id)
        return state_payload.get("state")

    def set_input_text(self, entity_id: str, value: str) -> None:
        self._request_json(
            "/services/input_text/set_value",
            method="POST",
            payload={"entity_id": entity_id, "value": value},
        )

    def set_input_number(self, entity_id: str, value: float | int) -> None:
        self._request_json(
            "/services/input_number/set_value",
            method="POST",
            payload={"entity_id": entity_id, "value": value},
        )

    def turn_on_switch(self, entity_id: str) -> None:
        self._request_json(
            "/services/switch/turn_on",
            method="POST",
            payload={"entity_id": entity_id},
        )

    def turn_off_switch(self, entity_id: str) -> None:
        self._request_json(
            "/services/switch/turn_off",
            method="POST",
            payload={"entity_id": entity_id},
        )

    def turn_on_input_boolean(self, entity_id: str) -> None:
        self._request_json(
            "/services/input_boolean/turn_on",
            method="POST",
            payload={"entity_id": entity_id},
        )

    def turn_off_input_boolean(self, entity_id: str) -> None:
        self._request_json(
            "/services/input_boolean/turn_off",
            method="POST",
            payload={"entity_id": entity_id},
        )

    def _request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body: bytes | None = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        api_request = request.Request(
            url=f"{self.base_url.rstrip('/')}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(api_request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise HomeAssistantApiError(
                f"Home Assistant API returned HTTP {exc.code} for {method} {path}: {details}"
            ) from exc
        except error.URLError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant API request failed for {method} {path}: {exc.reason}"
            ) from exc

        if not raw_body:
            return None

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant API returned malformed JSON for {method} {path}."
            ) from exc
