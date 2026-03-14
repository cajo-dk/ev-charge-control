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
        self.on_connect = None
        self.on_disconnect = None
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
    discovery = next(item for item in fake_client.published if item[0] == "homeassistant/sensor/ev_charge_control/config")
    payload = json.loads(discovery[1])
    assert payload["state_topic"] == "evcc/state"
    assert payload["json_attributes_topic"] == "evcc/attributes"


def test_publisher_publishes_state_and_attributes(monkeypatch) -> None:
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
    publisher.publish_output(
        {
            "status": "ok",
            "start": "00:15",
            "end": "05:00",
            "current_soc": 20,
        }
    )

    assert ("evcc/state", "ok", 1, True) in fake_client.published
    attributes_publish = next(item for item in fake_client.published if item[0] == "evcc/attributes")
    attributes = json.loads(attributes_publish[1])
    assert "status" not in attributes
    assert attributes["start"] == "00:15"
    assert attributes["current_soc"] == 20
