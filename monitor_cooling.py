"""Monitor cooling-related registers on ebusd every 5 minutes for 1 hour."""
import datetime
import socket
import time

HOST = "192.168.1.135"
PORT = 8888
INTERVAL = 300  # 5 minutes
SAMPLES = 12  # 1 hour

REGISTERS = [
    ("ctlv2", "Z1OpMode"),
    ("ctlv2", "Z1CoolingTemp"),
    ("ctlv2", "Hc1MinCoolingTempDesired"),
    ("ctlv2", "Hc1FlowTemp"),
    ("ctlv2", "Hc1Status"),
    ("ctlv2", "Hc1PumpStatus"),
    ("ctlv2", "Z1RoomTemp"),
    ("ctlv2", "Z1ActualRoomTempDesired"),
    ("ctlv2", "Hc1SummerTempLimit"),
    ("hmu", "RunDataStatuscode"),
    ("hmu", "RunDataBuildingCPumpPower"),
    ("hmu", "RunDataCurrentYieldPower"),
]


def read_reg(s, circuit, name):
    try:
        s.sendall(f"read -c {circuit} {name}\r\n".encode())
        s.settimeout(3)
        data = s.recv(4096).decode().strip()
        return data.split("\n")[0] if data else "-"
    except Exception as e:
        return f"ERR:{e}"


def snapshot(s):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    vals = [read_reg(s, c, n) for c, n in REGISTERS]
    line = f"[{ts}] " + " | ".join(
        f"{n}={v}" for (_, n), v in zip(REGISTERS, vals)
    )
    return line


def main():
    s = socket.create_connection((HOST, PORT), timeout=5)
    try:
        header = "# Cooling monitor - snapshots every 5 min\n"
        header += f"# Started: {datetime.datetime.now().isoformat()}\n"
        header += "# Registers: " + ", ".join(f"{c}.{n}" for c, n in REGISTERS) + "\n"
        print(header, flush=True)

        for i in range(SAMPLES):
            line = snapshot(s)
            print(line, flush=True)
            if i < SAMPLES - 1:
                time.sleep(INTERVAL)
    finally:
        s.close()
    footer = f"# Done: {datetime.datetime.now().isoformat()}"
    print(footer, flush=True)


if __name__ == "__main__":
    main()
