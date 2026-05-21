#!/usr/bin/env python3
"""
Solax T58 Battery Monitor — passive RS-485 sniffer → MQTT bridge

Passively listens to communication between the inverter (master) and batteries (slave)
on the RS-485 bus via Waveshare ETH-RS485 in transparent TCP mode.
No active queries — only reads what the inverter and batteries communicate.
"""

import json
import logging
import os
import socket
import time
import threading
import argparse
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modbus RTU frame parser
# ---------------------------------------------------------------------------
FRAME_END = bytes([0x0D, 0x0A])
FC_READ_HOLDING = 0x03
FC_SET_BITS = 0x05
MAX_VALID_SLAVE = 8


def _modbus_crc(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _crc_ok(frame: bytes) -> bool:
    """CRC at bytes [-4:-2], followed by 0x0D 0x0A."""
    if len(frame) < 6:
        return False
    payload = frame[:-4]
    stored = frame[-4] | (frame[-3] << 8)
    return _modbus_crc(payload) == stored


# ---------------------------------------------------------------------------
# Register map and parsing
# ---------------------------------------------------------------------------
REG_PACK_VOLTAGE = 1
REG_SOC          = 2
REG_CURRENT      = 3
REG_VOLTAGE_MIN  = 4
REG_VOLTAGE_MAX  = 5
REG_TEMP_MIN     = 6
REG_TEMP_MAX     = 7
REG_CELL_START   = 8    # 18 registers
REG_TEMP_START   = 26   # 8 registers
REG_CAPACITY     = 36
REG_TOTAL        = 37

def _s16(v: int) -> int:
    return v - 65536 if v > 32767 else v


def registers_to_data(regs: list[int]) -> dict | None:
    if len(regs) <= REG_CAPACITY:
        return None
    pack_v = regs[REG_PACK_VOLTAGE] / 500
    if not (30.0 < pack_v < 65.0):
        return None

    data: dict = {}
    data["pack_voltage"] = round(pack_v, 2)
    data["soc"]          = round((regs[REG_SOC] & 0xFF) * 100 / 250)
    data["current"]      = round(_s16(regs[REG_CURRENT]) / 100, 2)
    data["temp_min"]     = round(_s16(regs[REG_TEMP_MIN]) / 100, 1)
    data["temp_max"]     = round(_s16(regs[REG_TEMP_MAX]) / 100, 1)
    data["capacity"]     = round(regs[REG_CAPACITY] / 10, 1)
    data["balancer_mask"] = regs[34] | ((regs[35] & 0xC000) << 2)

    
    # Diagnostický výpis VŠECH surových dat z Modbusu
    data["raw_regs"] = regs

    
    cells = []
    for i in range(18):
        v = round(_s16(regs[REG_CELL_START + i]) / 1000, 3)
        data[f"cell_{i+1:02d}"] = v
        cells.append(v)

    for i in range(8):
        data[f"temp_{i+1:02d}"] = round(_s16(regs[REG_TEMP_START + i]) / 100, 1)

    valid = [c for c in cells if 2.0 < c < 5.0]
    if valid:
        data["cell_min"]   = min(valid)
        data["cell_max"]   = max(valid)
        data["cell_delta"] = round(max(valid) - min(valid), 3)
        data["cell_avg"]   = round(sum(valid) / len(valid), 3)

    return data


# ---------------------------------------------------------------------------
# MQTT Discovery
# ---------------------------------------------------------------------------
# (key, name, unit, device_class, state_class, precision)
_SENSORS = [
    ("pack_voltage", "Pack Voltage",     "V",  "voltage",     "measurement", 1),
    ("soc",          "SOC",              "%",  "battery",     "measurement", 0),
    ("current",      "Current",          "A",  "current",     "measurement", 2),
    ("temp_min",     "Temp Min",         "°C", "temperature", "measurement", 1),
    ("temp_max",     "Temp Max",         "°C", "temperature", "measurement", 1),
    ("capacity",     "Capacity",         "Wh", "energy",      "measurement", 0),
    ("cell_min",     "Cell Min",         "V",  "voltage",     "measurement", 3),
    ("cell_max",     "Cell Max",         "V",  "voltage",     "measurement", 3),
    ("cell_delta",   "Cell Delta",       "V",  "voltage",     "measurement", 3),
    ("cell_avg",     "Cell Average",     "V",  "voltage",     "measurement", 3),
    *[(f"cell_{i:02d}", f"Cell {i:02d}", "V",  "voltage",     "measurement", 3) for i in range(1, 19)],
    *[(f"temp_{i:02d}", f"Temp {i:02d}", "°C", "temperature", "measurement", 1) for i in range(1, 9)],
]


def _state_topic(base: str, slave: int) -> str:
    return f"{base}/{slave}/state"


def publish_discovery(client: mqtt.Client, base_topic: str, discovery_prefix: str,
                      slave: int, modules_per_battery: int):
    battery = (slave - 1) // modules_per_battery + 1
    module  = (slave - 1) % modules_per_battery + 1
    device = {
        "identifiers":  [f"solax_t58_battery_{battery}"],
        "name":         f"Battery {battery}",
        "manufacturer": "Solax",
        "model":        "T58",
    }
    state_topic = _state_topic(base_topic, slave)
    for key, name, unit, device_class, state_class, precision in _SENSORS:
        uid = f"solax_t58_b{battery}_m{module}_{key}"
        payload = {
            "name":                        f"M{module} {name}",
            "unique_id":                   uid,
            "state_topic":                 state_topic,
            "value_template":              f"{{{{ value_json.{key} }}}}",
            "unit_of_measurement":         unit,
            "state_class":                 state_class,
            "suggested_display_precision": precision,
            "device":                      device,
        }
        if device_class:
            payload["device_class"] = device_class
        if device_class in ("voltage", "current"):
            payload["icon"] = "mdi:current-dc"
        client.publish(f"{discovery_prefix}/sensor/{uid}/config", json.dumps(payload), retain=True)
    log.info("Discovery published: slave %d → Battery %d Module %d (%d entities)",
             slave, battery, module, len(_SENSORS))


# ---------------------------------------------------------------------------
# Passive sniffer
# ---------------------------------------------------------------------------
class PassiveSniffer:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._req_addr  = 0
        self._req_start = 0
        self._req_count = 0
        # index 0 unused
        self._registers: dict[int, list[int]] = {i: [0] * REG_TOTAL for i in range(1, MAX_VALID_SLAVE + 1)}
        self._last_received: dict[int, float] = {i: 0.0 for i in range(1, MAX_VALID_SLAVE + 1)}
        self._lock = threading.Lock()

    def connect(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(2.0)
        self._sock.connect((self.host, self.port))
        self._buf.clear()
        log.info("Connected to %s:%d (transparent TCP)", self.host, self.port)

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def receive(self):
        if not self._sock:
            return
        try:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection")
            self._buf.extend(chunk)
        except socket.timeout:
            pass

    def process(self):
        while True:
            idx = self._buf.find(FRAME_END)
            if idx < 0:
                break
            frame = bytes(self._buf[:idx + 2])
            del self._buf[:idx + 2]
            if len(frame) >= 6:
                self._parse_frame(frame)

    def _parse_frame(self, frame: bytes):
        addr = frame[0]
        fc   = frame[1]

        if addr > MAX_VALID_SLAVE:
            return
        if not _crc_ok(frame):
            log.debug("CRC error: %s", frame.hex())
            return

        if fc == FC_READ_HOLDING:
            if len(frame) == 10:
                self._req_addr  = addr
                self._req_start = (frame[2] << 8) | frame[3]
                self._req_count = (frame[4] << 8) | frame[5]
                log.debug("REQ  slave=%d reg=%d n=%d", addr, self._req_start, self._req_count)

            else:
                byte_count = frame[2]
                if byte_count == 0 or len(frame) != 3 + byte_count + 4:
                    return
                reg_count = byte_count // 2
                regs_received = [(frame[3 + i*2] << 8) | frame[4 + i*2] for i in range(reg_count)]

                slave = addr if addr != 0 else self._req_addr
                if slave < 1 or slave > MAX_VALID_SLAVE:
                    return

                start = self._req_start
                log.debug("RESP slave=%d start=%d n=%d", slave, start, reg_count)

                with self._lock:
                    target = self._registers[slave]
                    for i, val in enumerate(regs_received):
                        pos = start + i
                        if pos < len(target):
                            target[pos] = val
                    self._last_received[slave] = time.monotonic()

    def get_registers(self, slave: int) -> list[int]:
        with self._lock:
            return list(self._registers[slave])

    def has_recent_data(self, slave: int, max_age_s: float = 60.0) -> bool:
        return (time.monotonic() - self._last_received[slave]) <= max_age_s


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class Config:
    tcp_host:            str
    tcp_port:            int  = 502
    slave_count:         int  = 4
    modules_per_battery: int  = 2
    publish_interval:    int  = 30
    mqtt_host:        str  = "core-mosquitto"
    mqtt_port:        int  = 1883
    mqtt_user:        str  = ""
    mqtt_password:    str  = ""
    mqtt_base_topic:  str  = "solax/t58"
    discovery_prefix: str  = "homeassistant"


def _load_ha_options() -> Config | None:
    path = "/data/options.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        o = json.load(f)
    return Config(
        tcp_host=o["tcp_host"],
        tcp_port=o.get("tcp_port", 502),
        slave_count=o.get("slave_count", 4),
        modules_per_battery=o.get("modules_per_battery", 2),
        publish_interval=o.get("publish_interval", 30),
        mqtt_host=o.get("mqtt_host", "core-mosquitto"),
        mqtt_port=o.get("mqtt_port", 1883),
        mqtt_user=o.get("mqtt_user", ""),
        mqtt_password=o.get("mqtt_password", ""),
        mqtt_base_topic=o.get("mqtt_base_topic", "solax/t58"),
        discovery_prefix=o.get("discovery_prefix", "homeassistant"),
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run(cfg: Config):
    mc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if cfg.mqtt_user:
        mc.username_pw_set(cfg.mqtt_user, cfg.mqtt_password)
    mc.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=60)
    mc.loop_start()

    for slave in range(1, cfg.slave_count + 1):
        publish_discovery(mc, cfg.mqtt_base_topic, cfg.discovery_prefix, slave, cfg.modules_per_battery)

    sniffer = PassiveSniffer(cfg.tcp_host, cfg.tcp_port)
    last_publish: dict[int, float] = {s: 0.0 for s in range(1, cfg.slave_count + 1)}

    while True:
        if not sniffer.connected:
            try:
                sniffer.connect()
            except OSError as exc:
                log.error("Cannot connect to %s:%d — %s", cfg.tcp_host, cfg.tcp_port, exc)
                time.sleep(10)
                continue

        try:
            sniffer.receive()
            sniffer.process()
        except (OSError, ConnectionError) as exc:
            log.error("Connection error: %s — reconnect in 10 s", exc)
            sniffer.disconnect()
            time.sleep(10)
            continue

        now = time.monotonic()
        for slave in range(1, cfg.slave_count + 1):
            if (now - last_publish[slave]) < cfg.publish_interval:
                continue
            if not sniffer.has_recent_data(slave, max_age_s=cfg.publish_interval * 3):
                continue
            data = registers_to_data(sniffer.get_registers(slave))
            if data is None:
                log.warning("Slave %d: invalid data, skipping", slave)
                continue
            mc.publish(_state_topic(cfg.mqtt_base_topic, slave), json.dumps(data))
            last_publish[slave] = now
            log.info(
                "Slave %d | SOC %3d%% | %.2fV | %.2fA | delta %dmV",
                slave, data["soc"], data["pack_voltage"],
                data["current"], int(data.get("cell_delta", 0) * 1000),
            )

        time.sleep(0.05)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    cfg = _load_ha_options()

    if cfg is None:
        parser = argparse.ArgumentParser(description="Solax T58 passive sniffer → MQTT")
        parser.add_argument("--tcp-host",         required=True, help="Waveshare converter IP address")
        parser.add_argument("--tcp-port",         type=int, default=502, help="TCP port (transparent mode)")
        parser.add_argument("--slaves",               type=int, default=4)
        parser.add_argument("--modules-per-battery",  type=int, default=2)
        parser.add_argument("--publish-interval", type=int, default=30)
        parser.add_argument("--mqtt-host",        default="localhost")
        parser.add_argument("--mqtt-port",        type=int, default=1883)
        parser.add_argument("--mqtt-user",        default="")
        parser.add_argument("--mqtt-password",    default="")
        parser.add_argument("--mqtt-topic",       default="solax/t58")
        parser.add_argument("--discovery-prefix", default="homeassistant")
        parser.add_argument("--debug",            action="store_true")
        args = parser.parse_args()

        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        cfg = Config(
            tcp_host=args.tcp_host,
            tcp_port=args.tcp_port,
            slave_count=args.slaves,
            modules_per_battery=args.modules_per_battery,
            publish_interval=args.publish_interval,
            mqtt_host=args.mqtt_host,
            mqtt_port=args.mqtt_port,
            mqtt_user=args.mqtt_user,
            mqtt_password=args.mqtt_password,
            mqtt_base_topic=args.mqtt_topic,
            discovery_prefix=args.discovery_prefix,
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        log.info("Started as Home Assistant add-on")

    run(cfg)


if __name__ == "__main__":
    main()
