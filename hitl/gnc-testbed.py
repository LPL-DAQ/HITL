# HITL
    
# run: uv --project hitl run hitl/gnc_testbed.py --csv [file].csv

import argparse
import csv
import socket
import struct
import threading
import time
import sys
import os

# Protobuf
try:
    import clover_pb2
except ImportError:
    print("ERROR: clover_pb2 not found.")
    print("Run: protoc --python_out=. api/clover.proto --proto_path=api")
    sys.exit(1)

# smbus2 -- should be installed when running 'uv'
DAC_AVAILABLE = False
try:
    import smbus2
    DAC_AVAILABLE = True
    print("DAC support enabled (smbus2 found)")
except ImportError:
    print("WARNING: smbus2 not found — DAC outputs disabled. Install with: pip3 install smbus2") # install if not


# Network
LISTEN_IP       = "0.0.0.0"
COMMAND_PORT    = 5000
DATA_PORT       = 5001
BROADCAST_ADDR  = "169.254.99.255"

# I2C config
I2C_BUS         = 1
DAC_ADDR_1      = 0x4C   # default address
DAC_ADDR_2      = 0x4A   # AD0 jumper bridged

# DAC channel mapping - 4 sensors connected to each DAC (use all 8 channels)

DAC_CHANNEL_MAP = [
    # (dac_addr, channel, csv_column,   sensor_min, sensor_max)
    (DAC_ADDR_1, 0, "pt102",   0.0, 300.0),
    (DAC_ADDR_1, 1, "pt103",   0.0, 300.0),
    (DAC_ADDR_1, 2, "pt202",   0.0, 300.0),
    (DAC_ADDR_1, 3, "pt203",   0.0, 300.0),
    (DAC_ADDR_2, 0, "pto401",  0.0, 300.0),
    (DAC_ADDR_2, 1, "ptf401",  0.0, 300.0),
    (DAC_ADDR_2, 2, "ptc401",  0.0, 100.0),
    (DAC_ADDR_2, 3, "ptc402",  0.0, 100.0),
]

DAC_RESOLUTION  = 1023          # 10-bit DAC (DAC6578)
DAC_VREF        = 3.3           # volts

# ── Simulator state ───────────────────────────────────────────────────────────
class SimState:
    def __init__(self):
        self.lock           = threading.Lock()
        self.system_state   = clover_pb2.STATE_IDLE
        self.sequence_number = 0
        self.start_time_ns  = time.time_ns()
        self.subscribers    = set()   # set of (ip, port) tuples for UDP data stream

        # Valve state
        self.fuel_target    = 0.0
        self.fuel_encoder   = 0.0
        self.lox_target     = 0.0
        self.lox_encoder    = 0.0
        self.fuel_on        = False
        self.lox_on         = False

        # Sensor values (to update)
        self.sensors = {
            "pt102": 0.0, "pt103": 0.0,
            "pt202": 0.0, "pt203": 0.0,
            "ptf401": 0.0, "pto401": 0.0,
            "ptc401": 0.0, "ptc402": 0.0,
        }

        # Sequence control
        self.sequence_loaded  = False
        self.sequence_running = False
        self.sequence_thread  = None
        self.csv_rows         = []
        self.abort_flag       = threading.Event()

state = SimState()

# DAC
_i2c_bus = None

def get_i2c():
    global _i2c_bus
    if _i2c_bus is None and DAC_AVAILABLE:
        _i2c_bus = smbus2.SMBus(I2C_BUS)
    return _i2c_bus

def dac_write(bus, addr, channel, value_10bit):
    """Write a 10-bit value to the specified DAC channel."""
    cmd = 0x40 | (channel << 1)
    val = (value_10bit & 0x3FF) << 6
    hi  = (val >> 8) & 0xFF
    lo  = val & 0xFF
    bus.write_i2c_block_data(addr, cmd, [hi, lo])

def update_dac_outputs(sensors: dict):
    """Push current sensor values out to DAC channels."""
    if not DAC_AVAILABLE:
        return
    bus = get_i2c()
    if bus is None:
        return
    for (dac_addr, channel, csv_col, s_min, s_max) in DAC_CHANNEL_MAP:
        val = sensors.get(csv_col, 0.0)
        # Scale to 10-bit
        val = max(s_min, min(s_max, val))
        dac_val = int((val - s_min) / (s_max - s_min) * DAC_RESOLUTION)
        try:
            dac_write(bus, dac_addr, channel, dac_val)
        except Exception as e:
            print(f"  DAC write error ({dac_addr:#x} ch{channel}): {e}")

# CSV
def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: float(v) for k, v in row.items()})
    print(f"Loaded {len(rows)} rows from {path}")
    return rows

# build data packet
def build_data_packet(row: dict | None = None) -> clover_pb2.DataPacket:
    with state.lock:
        pkt = clover_pb2.DataPacket()
        pkt.time_ns                 = time.time_ns() - state.start_time_ns
        pkt.state                   = state.system_state
        pkt.data_queue_size         = 0
        pkt.sequence_number         = state.sequence_number
        pkt.controller_tick_time_ns = 1_000_000.0
        pkt.gnc_connected           = len(state.subscribers) > 0
        pkt.gnc_last_pinged_ns      = 0.0
        pkt.daq_connected           = False
        pkt.daq_last_pinged_ns      = 0.0
        state.sequence_number      += 1

# Sensors — use CSV row if provided, else current state
        sensors = state.sensors.copy()
        if row:
            for k in sensors:
                if k in row:
                    sensors[k] = row[k]

        pkt.analog_sensors.pt102          = sensors["pt102"]
        pkt.analog_sensors.pt103          = sensors["pt103"]
        pkt.analog_sensors.pt202          = sensors["pt202"]
        pkt.analog_sensors.pt203          = sensors["pt203"]
        pkt.analog_sensors.ptf401         = sensors["ptf401"]
        pkt.analog_sensors.pto401         = sensors["pto401"]
        pkt.analog_sensors.ptc401         = sensors["ptc401"]
        pkt.analog_sensors.ptc402         = sensors["ptc402"]
        pkt.analog_sensors.tc102          = 0.0
        pkt.analog_sensors.tc102_5        = 0.0
        pkt.analog_sensors.adc_read_time_ns = 100_000.0

        # Valve state — use CSV row if provided, else current state
        fuel_enc = row["fuel_valve_encoder_pos"] if row else state.fuel_encoder
        lox_enc  = row["lox_valve_encoder_pos"]  if row else state.lox_encoder
        fuel_tgt = row["fuel_valve_setpoint"]     if row else state.fuel_target
        lox_tgt  = row["lox_valve_setpoint"]      if row else state.lox_target

        pkt.fuel_valve.target_pos_deg         = fuel_tgt
        pkt.fuel_valve.driver_setpoint_pos_deg= fuel_tgt
        pkt.fuel_valve.encoder_pos_deg        = fuel_enc
        pkt.fuel_valve.is_on                  = state.fuel_on

        pkt.lox_valve.target_pos_deg          = lox_tgt
        pkt.lox_valve.driver_setpoint_pos_deg = lox_tgt
        pkt.lox_valve.encoder_pos_deg         = lox_enc
        pkt.lox_valve.is_on                   = state.lox_on

        # State data
        if state.system_state in (
            clover_pb2.STATE_IDLE,
            clover_pb2.STATE_VALVE_PRIMED,
            clover_pb2.STATE_THRUST_PRIMED,
        ):
            pkt.idle_data.SetInParent()
        elif state.system_state == clover_pb2.STATE_ABORT:
            pkt.abort_data.SetInParent()
        elif state.system_state == clover_pb2.STATE_VALVE_SEQ:
            pkt.valve_sequence_data.SetInParent()
        elif state.system_state == clover_pb2.STATE_THRUST_SEQ:
            pkt.thrust_sequence_data.SetInParent()
        elif state.system_state == clover_pb2.STATE_CALIBRATE_VALVE:
            pkt.valve_calibration_data.fuel_found_hardstop = False
            pkt.valve_calibration_data.fuel_hardstop_pos   = 0.0
            pkt.valve_calibration_data.lox_found_hardstop  = False
            pkt.valve_calibration_data.lox_hardstop_pos    = 0.0
            pkt.valve_calibration_data.cal_phase           = 0
            pkt.valve_calibration_data.rep_count           = 0
            pkt.valve_calibration_data.fuel_err            = 0.0
            pkt.valve_calibration_data.lox_err             = 0.0

        return pkt

# UDP data packet
def send_data_packet(udp_sock: socket.socket, row: dict | None = None):
    pkt  = build_data_packet(row)
    data = pkt.SerializeToString()
    with state.lock:
        subs = list(state.subscribers)
    for (ip, port) in subs:
        try:
            udp_sock.sendto(data, (ip, port))
        except Exception as e:
            print(f"  UDP send error to {ip}:{port}: {e}")

# Sequence replay thread
def run_sequence(udp_sock: socket.socket):
    """Replay CSV rows in real time, updating sensor state and DAC outputs."""
    rows = state.csv_rows
    if not rows:
        print("  No CSV rows loaded — nothing to replay")
        return

    print(f"  Sequence started: {len(rows)} rows")
    with state.lock:
        state.system_state   = clover_pb2.STATE_VALVE_SEQ
        state.abort_flag.clear()

    t0_real = time.monotonic()
    t0_csv  = rows[0]["time"]

    for row in rows:
        if state.abort_flag.is_set():
            print("  Sequence ABORTED")
            with state.lock:
                state.system_state = clover_pb2.STATE_ABORT
            send_data_packet(udp_sock)
            return

        # Wait until the right real time for this row
        csv_elapsed  = row["time"] - t0_csv
        real_elapsed = time.monotonic() - t0_real
        sleep_time   = csv_elapsed - real_elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

        # Update sensor state
        with state.lock:
            for k in state.sensors:
                if k in row:
                    state.sensors[k] = row[k]
            state.fuel_encoder = row.get("fuel_valve_encoder_pos", state.fuel_encoder)
            state.lox_encoder  = row.get("lox_valve_encoder_pos",  state.lox_encoder)

        # Push to DAC outputs
        update_dac_outputs(state.sensors)

        # Send data packet to all subscribers
        send_data_packet(udp_sock, row)

    # Sequence complete
    print("  Sequence complete — returning to IDLE")
    with state.lock:
        state.system_state    = clover_pb2.STATE_IDLE
        state.sequence_loaded = False

# idle telemetry thread
def idle_telemetry_loop(udp_sock: socket.socket):
    """Send data at 10 Hz when no sequence is running."""
    while True:
        with state.lock:
            running = state.sequence_running
        if not running:
            send_data_packet(udp_sock)
        time.sleep(0.1)

# Command handler
def handle_request(raw: bytes, udp_sock: socket.socket) -> bytes:
    """Parse a Request, update state, return serialized Response."""
    req  = clover_pb2.Request()
    resp = clover_pb2.Response()

    try:
        req.ParseFromString(raw)
    except Exception as e:
        resp.err = f"Failed to parse request: {e}"
        return resp.SerializeToString()

    payload = req.WhichOneof("payload")
    print(f"  → Command: {payload}")

    if payload == "subscribe_data_stream":
        # caller's IP is added in the TCP handler
        pass

    elif payload == "identify_client":
        client = req.identify_client.client
        print(f"    Client identified as: {clover_pb2.ClientType.Name(client)}")

    elif payload == "is_not_aborted_request":
        with state.lock:
            if state.system_state == clover_pb2.STATE_ABORT:
                resp.err = "System is in ABORT state"

    elif payload == "abort":
        state.abort_flag.set()
        with state.lock:
            state.system_state = clover_pb2.STATE_ABORT
        print("    !!! ABORT !!!")

    elif payload == "halt":
        state.abort_flag.set()
        with state.lock:
            state.system_state    = clover_pb2.STATE_IDLE
            state.sequence_loaded = False
        print("    HALT — returning to IDLE")

    elif payload == "unprime":
        with state.lock:
            if state.system_state in (clover_pb2.STATE_VALVE_PRIMED, clover_pb2.STATE_THRUST_PRIMED):
                state.system_state    = clover_pb2.STATE_IDLE
                state.sequence_loaded = False
            else:
                resp.err = f"Cannot unprime from state {clover_pb2.SystemState.Name(state.system_state)}"

    elif payload == "reset_valve_position":
        valve   = req.reset_valve_position.valve
        new_pos = req.reset_valve_position.new_pos_deg
        with state.lock:
            if valve == clover_pb2.FUEL:
                state.fuel_encoder = new_pos
                state.fuel_target  = new_pos
            else:
                state.lox_encoder  = new_pos
                state.lox_target   = new_pos
        print(f"    Valve {clover_pb2.Valve.Name(valve)} reset to {new_pos:.2f}°")

    elif payload == "power_on_valve":
        with state.lock:
            if req.power_on_valve.valve == clover_pb2.FUEL:
                state.fuel_on = True
            else:
                state.lox_on = True

    elif payload == "power_off_valve":
        with state.lock:
            if req.power_off_valve.valve == clover_pb2.FUEL:
                state.fuel_on = False
            else:
                state.lox_on = False

    elif payload == "calibrate_valve":
        with state.lock:
            if state.system_state != clover_pb2.STATE_IDLE:
                resp.err = f"Cannot calibrate from {clover_pb2.SystemState.Name(state.system_state)}"
            else:
                state.system_state = clover_pb2.STATE_CALIBRATE_VALVE

    elif payload == "load_valve_sequence":
        with state.lock:
            if state.system_state != clover_pb2.STATE_IDLE:
                resp.err = f"Cannot load sequence from {clover_pb2.SystemState.Name(state.system_state)}"
            elif not state.csv_rows:
                resp.err = "No CSV loaded — start simulator with --csv"
            else:
                state.system_state    = clover_pb2.STATE_VALVE_PRIMED
                state.sequence_loaded = True
        print("    Valve sequence loaded (will replay CSV)")

    elif payload == "start_valve_sequence":
        with state.lock:
            if state.system_state != clover_pb2.STATE_VALVE_PRIMED:
                resp.err = f"Cannot start from {clover_pb2.SystemState.Name(state.system_state)}"
            else:
                state.sequence_running = True
        if not resp.HasField("err"):
            t = threading.Thread(
                target=_sequence_wrapper,
                args=(udp_sock,),
                daemon=True
            )
            t.start()

    elif payload == "load_thrust_sequence":
        with state.lock:
            if state.system_state != clover_pb2.STATE_IDLE:
                resp.err = f"Cannot load from {clover_pb2.SystemState.Name(state.system_state)}"
            else:
                state.system_state    = clover_pb2.STATE_THRUST_PRIMED
                state.sequence_loaded = True

    elif payload == "start_thrust_sequence":
        with state.lock:
            if state.system_state != clover_pb2.STATE_THRUST_PRIMED:
                resp.err = f"Cannot start from {clover_pb2.SystemState.Name(state.system_state)}"
            else:
                state.sequence_running = True
        if not resp.HasField("err"):
            t = threading.Thread(
                target=_sequence_wrapper,
                args=(udp_sock,),
                daemon=True
            )
            t.start()

    elif payload == "configure_analog_sensors_bias":
        sensor = req.configure_analog_sensors_bias.sensor
        bias   = req.configure_analog_sensors_bias.bias
        print(f"    Bias configured: {clover_pb2.AnalogSensor.Name(sensor)} += {bias}")

    else:
        resp.err = f"Unknown command: {payload}"

    return resp.SerializeToString()


def _sequence_wrapper(udp_sock):
    run_sequence(udp_sock)
    with state.lock:
        state.sequence_running = False


# TCP command
def handle_client(conn: socket.socket, addr, udp_sock: socket.socket):
    print(f"  Client connected: {addr}")
    # Auto-subscribe this client to the data stream
    with state.lock:
        state.subscribers.add((addr[0], DATA_PORT))
    try:
        while True:
            # Read all available data
            conn.settimeout(1.0)
            try:
                raw = conn.recv(4096)
            except socket.timeout:
                continue
            if not raw:
                break
            resp_bytes = handle_request(raw, udp_sock)
            conn.sendall(resp_bytes)
    except Exception as e:
        print(f"  Client {addr} error: {e}")
    finally:
        print(f"  Client disconnected: {addr}")
        # remove stale UDP subscriber
        with state.lock:
            state.subscribers.discard(sub)

        conn.close()


def tcp_server(udp_sock: socket.socket):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((LISTEN_IP, COMMAND_PORT))
        srv.listen(5)
        print(f"TCP command server listening on {LISTEN_IP}:{COMMAND_PORT}")
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=handle_client,
                args=(conn, addr, udp_sock),
                daemon=True
            )
            t.start()

def main():
    parser = argparse.ArgumentParser(description="GNC HIL Simulator")
    parser.add_argument("--csv", required=False, help="Path to CSV sequence file")
    args = parser.parse_args()

    if args.csv:
        state.csv_rows = load_csv(args.csv)
    else:
        print("WARNING: No CSV file provided. Use --csv to load a sequence.")
        print("         Commands will still work but sequence replay will fail.")

    # UDP socket for outgoing data stream
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # Start telemetry in background
    t_telem = threading.Thread(target=idle_telemetry_loop, args=(udp_sock,), daemon=True)
    t_telem.start()

    # Start TCP command server
    print("GNC HIL Simulator starting...")
    print(f"  Command port : {COMMAND_PORT} (TCP)")
    print(f"  Data port    : {DATA_PORT} (UDP)")
    print(f"  DAC support  : {'enabled' if DAC_AVAILABLE else 'disabled'}")
    print(f"  CSV rows     : {len(state.csv_rows)}")
    print()
    tcp_server(udp_sock)


if __name__ == "__main__":
    main()