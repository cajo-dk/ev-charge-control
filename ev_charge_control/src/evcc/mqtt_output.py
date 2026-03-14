from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from paho.mqtt import client as mqtt


DEFAULT_KEEPALIVE_SECONDS = 60


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
    sensor_object_id: str = "ev_charge_control"
    sensor_name: str = "EV Charge Control"
    _client: mqtt.Client | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.connect_async(self.host, self.port, DEFAULT_KEEPALIVE_SECONDS)
        client.loop_start()
        self._client = client

    def stop(self) -> None:
        if self._client is None:
            return
        self._publish(self.availability_topic, "offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()
        self._client = None

    def publish_output(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("status", ""))
        attributes = {key: value for key, value in payload.items() if key != "status"}
        self._publish(self.state_topic, state, retain=True)
        self._publish(self.attributes_topic, json.dumps(attributes), retain=True)

    @property
    def discovery_topic(self) -> str:
        return f"{self.discovery_prefix}/sensor/{self.sensor_object_id}/config"

    @property
    def state_topic(self) -> str:
        return f"{self.topic_prefix}/state"

    @property
    def attributes_topic(self) -> str:
        return f"{self.topic_prefix}/attributes"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/availability"

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        self.logger.info("Connected to MQTT broker at %s:%s", self.host, self.port)
        self._publish_discovery()
        self._publish(self.availability_topic, "online", retain=True)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        if getattr(reason_code, "value", 0):
            self.logger.warning("Disconnected from MQTT broker: %s", reason_code)

    def _publish_discovery(self) -> None:
        payload = {
            "name": self.sensor_name,
            "object_id": self.sensor_object_id,
            "unique_id": self.sensor_object_id,
            "state_topic": self.state_topic,
            "json_attributes_topic": self.attributes_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "icon": "mdi:ev-station",
            "device": {
                "identifiers": [self.sensor_object_id],
                "name": self.sensor_name,
                "manufacturer": "EVCC",
            },
        }
        self._publish(self.discovery_topic, json.dumps(payload), retain=True)

    def _publish(self, topic: str, payload: str, *, retain: bool) -> None:
        if self._client is None:
            self.logger.warning("MQTT publisher is not started; dropping payload for topic '%s'.", topic)
            return
        result = self._client.publish(topic, payload, qos=1, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.logger.warning("MQTT publish to '%s' returned rc=%s", topic, result.rc)
