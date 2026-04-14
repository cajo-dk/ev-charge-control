from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from paho.mqtt import client as mqtt


DEFAULT_KEEPALIVE_SECONDS = 60

CONTROL_DEFINITIONS = {
    "current_soc": {"component": "number", "name": "Current SoC", "min": 0, "max": 100, "step": 1, "unit": "%", "mode": "box"},
    "target_soc": {"component": "number", "name": "Target SoC", "min": 0, "max": 100, "step": 1, "unit": "%", "mode": "box"},
    "battery_capacity": {"component": "number", "name": "Battery Capacity", "min": 0, "max": 200, "step": 0.1, "unit": "kWh"},
    "charger_speed": {"component": "number", "name": "Charger Speed", "min": 0, "max": 100, "step": 0.1, "unit": "kW"},
    "charge_loss": {"component": "number", "name": "Charge Loss", "min": 0, "max": 100, "step": 1, "unit": "%", "mode": "box"},
    "finish_by": {"component": "text", "name": "Finish By"},
    "nighttime_charging_only": {"component": "switch", "name": "Nighttime Charging Only"},
    "schedule_authorized": {"component": "switch", "name": "Schedule Authorized"},
    "start_stop": {"component": "switch", "name": "Start / Stop"},
    "continuous_power": {"component": "switch", "name": "Continuous Power"},
}

SENSOR_DEFINITIONS = {
    "charger_state": {"component": "sensor", "name": "Charger State"},
    "soc_at_charge_start": {"component": "sensor", "name": "SoC At Charge Start"},
    "calculated_start": {"component": "sensor", "name": "Calculated Start"},
    "calculated_end": {"component": "sensor", "name": "Calculated End"},
    "complete_by": {"component": "sensor", "name": "Complete By"},
    "charge_window_state": {"component": "sensor", "name": "Charge Window State"},
    "status_message": {"component": "sensor", "name": "Status Message"},
    "status_level": {"component": "sensor", "name": "Status Level"},
}


@dataclass(slots=True)
class MQTTOutputPublisher:
    host: str
    port: int
    username: str | None
    password: str | None
    discovery_prefix: str
    topic_prefix: str
    logger: logging.Logger
    client_id: str = "ev_charge_control"
    device_object_id: str = "ev_charge_control"
    device_name: str = "EV Charge Control"
    _client: mqtt.Client | None = field(default=None, init=False, repr=False)
    _message_handler: Callable[[str, str, str], None] | None = field(default=None, init=False, repr=False)
    _connected: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def set_message_handler(self, handler: Callable[[str, str, str], None]) -> None:
        self._message_handler = handler

    def start(self) -> None:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(self.host, self.port, DEFAULT_KEEPALIVE_SECONDS)
        client.loop_start()
        self._client = client

    def wait_until_connected(self, timeout: float) -> bool:
        return self._connected.wait(timeout)

    def stop(self) -> None:
        if self._client is None:
            return
        self._publish(self.availability_topic, "offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()
        self._connected.clear()
        self._client = None

    def publish_control_state(self, key: str, value: Any) -> None:
        if key not in CONTROL_DEFINITIONS:
            raise ValueError(f"Unknown control '{key}'")
        if value in {None, ""}:
            return
        self._publish(self.control_state_topic(key), self._serialize_value(key, value), retain=True)

    def publish_runtime_state(self, *, snapshot: Any, payload: dict[str, Any]) -> None:
        for key in CONTROL_DEFINITIONS:
            self.publish_control_state(key, getattr(snapshot, key))

        sensor_values = {
            "charger_state": getattr(snapshot, "charger_state", ""),
            "soc_at_charge_start": payload.get("soc_at_charge_start", ""),
            "calculated_start": payload.get("start", ""),
            "calculated_end": payload.get("end", ""),
            "complete_by": payload.get("complete_by", ""),
            "charge_window_state": payload.get("charge_window_state", ""),
            "status_message": payload.get("status_message", ""),
            "status_level": payload.get("status_level", 0),
        }
        for key, value in sensor_values.items():
            self._publish(self.sensor_state_topic(key), self._serialize_value(key, value), retain=True)

        self._publish(self.state_topic, str(payload.get("status", "")), retain=True)
        attributes = {key: value for key, value in payload.items() if key != "status"}
        self._publish(self.attributes_topic, json.dumps(attributes), retain=True)

    @property
    def discovery_topic(self) -> str:
        return f"{self.discovery_prefix}/sensor/{self.device_object_id}/config"

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/state"

    @property
    def attributes_topic(self) -> str:
        return f"{self.topic_prefix}/attributes"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/availability"

    def control_state_topic(self, key: str) -> str:
        return f"{self.topic_prefix}/controls/{key}/state"

    def control_command_topic(self, key: str) -> str:
        return f"{self.topic_prefix}/controls/{key}/set"

    def sensor_state_topic(self, key: str) -> str:
        return f"{self.topic_prefix}/sensors/{key}/state"

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        self.logger.info("Connected to MQTT broker at %s:%s", self.host, self.port)
        self._connected.set()
        self._publish_discovery()
        self._subscribe_runtime_topics(client)
        self._publish(self.availability_topic, "online", retain=True)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        self._connected.clear()
        if getattr(reason_code, "value", 0):
            self.logger.warning("Disconnected from MQTT broker: %s", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        if self._message_handler is None:
            return
        topic = message.topic
        payload = message.payload.decode("utf-8")
        try:
            for key in CONTROL_DEFINITIONS:
                if topic == self.control_command_topic(key):
                    self._message_handler("control", key, payload)
                    return
                if topic == self.control_state_topic(key):
                    self._message_handler("control_state", key, payload)
                    return
        except Exception as exc:
            self.logger.warning("Failed to process MQTT message on '%s': %s", topic, exc)

    def _publish_discovery(self) -> None:
        aggregate_payload = {
            "name": self.device_name,
            "object_id": self.device_object_id,
            "unique_id": self.device_object_id,
            "state_topic": self.state_topic,
            "json_attributes_topic": self.attributes_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": "mdi:ev-station",
            "device": self._device_descriptor(),
        }
        self._publish(self.discovery_topic, json.dumps(aggregate_payload), retain=True)

        for key, definition in CONTROL_DEFINITIONS.items():
            self._publish(
                self._entity_discovery_topic(definition["component"], key),
                json.dumps(self._build_control_discovery(key, definition)),
                retain=True,
            )

        for key, definition in SENSOR_DEFINITIONS.items():
            self._publish(
                self._entity_discovery_topic(definition["component"], key),
                json.dumps(self._build_sensor_discovery(key, definition)),
                retain=True,
            )

    def _subscribe_runtime_topics(self, client: mqtt.Client) -> None:
        topics: list[tuple[str, int]] = []
        topics.extend((self.control_command_topic(key), 1) for key in CONTROL_DEFINITIONS)
        topics.extend((self.control_state_topic(key), 1) for key in CONTROL_DEFINITIONS)
        for topic, qos in topics:
            client.subscribe(topic, qos=qos)

    def _build_control_discovery(self, key: str, definition: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "name": definition["name"],
            "object_id": f"{self.device_object_id}_{key}",
            "unique_id": f"{self.device_object_id}_{key}",
            "state_topic": self.control_state_topic(key),
            "command_topic": self.control_command_topic(key),
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self._device_descriptor(),
        }
        if definition["component"] == "switch":
            payload.update({"payload_on": "ON", "payload_off": "OFF", "state_on": "ON", "state_off": "OFF"})
        if "min" in definition:
            payload.update({"min": definition["min"], "max": definition["max"], "step": definition["step"]})
        if "unit" in definition:
            payload["unit_of_measurement"] = definition["unit"]
        if "mode" in definition:
            payload["mode"] = definition["mode"]
        return payload

    def _build_sensor_discovery(self, key: str, definition: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "name": definition["name"],
            "object_id": f"{self.device_object_id}_{key}",
            "unique_id": f"{self.device_object_id}_{key}",
            "state_topic": self.sensor_state_topic(key),
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self._device_descriptor(),
        }
        if definition["component"] == "binary_sensor":
            payload.update({"payload_on": "ON", "payload_off": "OFF"})
        return payload

    def _entity_discovery_topic(self, component: str, key: str) -> str:
        return f"{self.discovery_prefix}/{component}/{self.device_object_id}_{key}/config"

    def _device_descriptor(self) -> dict[str, Any]:
        return {
            "identifiers": [self.device_object_id],
            "name": self.device_name,
            "manufacturer": "EVCC",
        }

    def _serialize_value(self, key: str, value: Any) -> str:
        if key in {"nighttime_charging_only", "schedule_authorized", "start_stop", "continuous_power"}:
            return "ON" if bool(value) else "OFF"
        if value is None:
            return ""
        return str(value)

    def _publish(self, topic: str, payload: str, *, retain: bool) -> None:
        if self._client is None:
            self.logger.warning("MQTT publisher is not started; dropping payload for topic '%s'.", topic)
            return
        result = self._client.publish(topic, payload, qos=1, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.logger.warning("MQTT publish to '%s' returned rc=%s", topic, result.rc)
