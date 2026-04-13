import json
import logging

from evcc.mqtt_output import MQTTOutputPublisher


class FakePublishResult:
    def __init__(self, rc: int = 0) -> None:
        self.rc = rc


class FakeMqttClient:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.username = None
        self.password = None
        self.connected = None
        self.published: list[tuple[str, str, int, bool]] = []
        self.subscriptions: list[tuple[str, int]] = []
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False

    def username_pw_set(self, username, password) -> None:
        self.username = username
        self.password = password

    def connect_async(self, host, port, keepalive) -> None:
        self.connected = (host, port, keepalive)

    def loop_start(self) -> None:
        self.loop_started = True

    def loop_stop(self) -> None:
        self.loop_stopped = True

    def disconnect(self) -> None:
        self.disconnected = True

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return FakePublishResult()

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        return (0, 1)


class Snapshot:
    current_soc = "20"
    target_soc = "80"
    battery_capacity = "77"
    charger_speed = "11"
    charge_loss = "10"
    finish_by = "06:30"
    nighttime_charging_only = False
    schedule_authorized = True
    charger_state = "connected_requesting_charge"
    pricing_information = "{\"raw_today\":[],\"raw_tomorrow\":null,\"forecast\":null}"


def test_publisher_starts_and_publishes_discovery(monkeypatch) -> None:
    fake_client = FakeMqttClient()
    monkeypatch.setattr("evcc.mqtt_output.mqtt.Client", lambda *args, **kwargs: fake_client)

    publisher = MQTTOutputPublisher(
        host="mqtt.local",
        port=1883,
        username="user",
        password="pass",
        discovery_prefix="homeassistant",
        topic_prefix="evcc",
        logger=logging.getLogger("test"),
    )

    publisher.start()
    fake_client.on_connect(fake_client, None, None, type("RC", (), {"value": 0})(), None)

    assert fake_client.username == "user"
    assert fake_client.password == "pass"
    assert fake_client.connected == ("mqtt.local", 1883, 60)
    assert fake_client.loop_started is True
    aggregate = next(item for item in fake_client.published if item[0] == "homeassistant/sensor/ev_charge_control/config")
    aggregate_payload = json.loads(aggregate[1])
    assert aggregate_payload["state_topic"] == "evcc/state"
    assert aggregate_payload["json_attributes_topic"] == "evcc/attributes"
    assert ("evcc/controls/current_soc/set", 1) in fake_client.subscriptions
    assert ("evcc/actions/start/press", 1) in fake_client.subscriptions
    current_soc_discovery = next(item for item in fake_client.published if item[0] == "homeassistant/number/ev_charge_control_current_soc/config")
    current_soc_payload = json.loads(current_soc_discovery[1])
    assert current_soc_payload["mode"] == "box"


def test_publisher_publishes_runtime_controls_and_attributes(monkeypatch) -> None:
    fake_client = FakeMqttClient()
    monkeypatch.setattr("evcc.mqtt_output.mqtt.Client", lambda *args, **kwargs: fake_client)

    publisher = MQTTOutputPublisher(
        host="mqtt.local",
        port=1883,
        username=None,
        password=None,
        discovery_prefix="homeassistant",
        topic_prefix="evcc",
        logger=logging.getLogger("test"),
    )
    publisher.start()
    publisher.publish_runtime_state(
        snapshot=Snapshot(),
        payload={
            "status": "OK",
            "start": "00:15",
            "end": "05:00",
            "complete_by": "06:30",
            "soc_at_charge_start": 20,
            "charge_window_state": "Not Reached",
            "status_message": "Ready",
            "status_level": 0,
            "charger_state": "connected_requesting_charge",
            "pricing_information": {"raw_today": []},
        },
    )

    assert ("evcc/controls/current_soc/state", "20", 1, True) in fake_client.published
    assert ("evcc/sensors/charger_state/state", "connected_requesting_charge", 1, True) in fake_client.published
    assert ("evcc/sensors/status_message/state", "Ready", 1, True) in fake_client.published
    assert ("evcc/state", "OK", 1, True) in fake_client.published
    attributes_publish = next(item for item in fake_client.published if item[0] == "evcc/attributes")
    attributes = json.loads(attributes_publish[1])
    assert attributes["start"] == "00:15"
    assert attributes["status_message"] == "Ready"


def test_publisher_routes_control_and_button_messages(monkeypatch) -> None:
    fake_client = FakeMqttClient()
    monkeypatch.setattr("evcc.mqtt_output.mqtt.Client", lambda *args, **kwargs: fake_client)
    received: list[tuple[str, str, str]] = []

    publisher = MQTTOutputPublisher(
        host="mqtt.local",
        port=1883,
        username=None,
        password=None,
        discovery_prefix="homeassistant",
        topic_prefix="evcc",
        logger=logging.getLogger("test"),
    )
    publisher.set_message_handler(lambda message_type, key, payload: received.append((message_type, key, payload)))
    publisher.start()

    class Message:
        def __init__(self, topic: str, payload: str) -> None:
            self.topic = topic
            self.payload = payload.encode("utf-8")

    fake_client.on_message(fake_client, None, Message("evcc/controls/current_soc/set", "42"))
    fake_client.on_message(fake_client, None, Message("evcc/actions/start/press", "PRESS"))
    assert ("control", "current_soc", "42") in received
    assert ("button", "start", "PRESS") in received
