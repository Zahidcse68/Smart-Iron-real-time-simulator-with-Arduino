import tkinter as tk
from tkinter import ttk
import math
import threading
import time
import serial
import serial.tools.list_ports

BAUD = 115200
FLAT_THRESHOLD = 14000
SETPOINT = 180
AMBIENT = 25


def blend(c1, c2, t):
    t = max(0, min(1, t))
    a = [int(c1[i:i+2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class IronSim:
    def __init__(self, root):
        self.root = root
        root.title("Smart Iron - Live Serial Simulator")
        root.configure(bg="#14161c")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ---- serial state (shared with reader thread) ----
        self.ser = None
        self.running = False
        self.lock = threading.Lock()
        self.ax = self.ay = 0
        self.az = 16384
        self.touch = False
        self.relay = False
        self.last_rx = 0.0

        # ---- simulation state ----
        self.mains = False
        self.heating = False
        self.temp = AMBIENT
        self.angle = 0.0          # smoothed tilt, degrees
        self.last_state = None

        # ---- top bar: port selection ----
        top = tk.Frame(root, bg="#14161c")
        top.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(top, text="Port:", fg="white", bg="#14161c").pack(side="left")
        self.port_box = ttk.Combobox(top, width=30, state="readonly")
        self.port_box.pack(side="left", padx=5)
        tk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=2)
        self.conn_btn = tk.Button(top, text="Connect", width=12, command=self.toggle_connect)
        self.conn_btn.pack(side="left", padx=8)
        self.status_lbl = tk.Label(top, text="Disconnected", fg="#ef4444", bg="#14161c")
        self.status_lbl.pack(side="left", padx=8)

        self.canvas = tk.Canvas(root, width=640, height=400, bg="#1c1f27", highlightthickness=0)
        self.canvas.pack(padx=10, pady=10)
        self.canvas.bind("<Button-1>", self.on_click)

        self.log = tk.Text(root, height=6, bg="#0d0f14", fg="#9fe39f", font=("Consolas", 10))
        self.log.pack(fill="x", padx=10, pady=(0, 10))

        self.refresh_ports()
        self.tick()

    # ---------- serial handling ----------
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if ports and not self.port_box.get():
            self.port_box.set(ports[0])

    def toggle_connect(self):
        if self.running:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_box.get()
        if not port:
            self.log_msg("No port selected")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=1)
        except Exception as e:
            self.log_msg(f"Could not open {port}: {e}")
            return
        time.sleep(2)  # Arduino resets when the port opens
        self.running = True
        threading.Thread(target=self.reader, daemon=True).start()
        self.conn_btn.config(text="Disconnect")
        self.log_msg(f"Connected to {port} @ {BAUD}")

    def disconnect(self):
        self.running = False
        time.sleep(0.2)
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.conn_btn.config(text="Connect")
        self.log_msg("Disconnected")

    def reader(self):
        while self.running:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                break
            if not line.startswith("DATA,"):
                continue
            parts = line.split(",")
            if len(parts) != 6:
                continue
            try:
                ax, ay, az = int(parts[1]), int(parts[2]), int(parts[3])
                touch, relay = parts[4] == "1", parts[5] == "1"
            except ValueError:
                continue
            with self.lock:
                self.ax, self.ay, self.az = ax, ay, az
                self.touch, self.relay = touch, relay
                self.last_rx = time.time()

    def log_msg(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def on_close(self):
        self.running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.root.destroy()

    # ---------- drawing ----------
    def xf(self, pts, ang):
        ox, oy, s = 260, 350, 1.3
        c, sn = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        out = []
        for x, y in pts:
            xr, yr = x * c - y * sn, x * sn + y * c
            out += [ox + xr * s, oy - yr * s]
        return out

    def draw_iron(self, ang, touched):
        c = self.canvas
        heat = (self.temp - AMBIENT) / (SETPOINT - AMBIENT)
        sole = blend("#9aa0aa", "#ff5a1f", heat)
        body = blend("#3b6fd1", "#d13b3b", heat * 0.5)

        c.create_polygon(self.xf([(0, 0), (190, 0), (232, 18), (190, 35), (0, 35)], ang),
                         fill=sole, outline="#222", width=2)
        c.create_polygon(self.xf([(0, 35), (190, 35), (150, 82), (20, 95), (0, 60)], ang),
                         fill=body, outline="#222", width=2)
        c.create_line(self.xf([(40, 95), (55, 150), (140, 150), (150, 88)], ang),
                      width=12, fill="#2b2e38", joinstyle="round", capstyle="round")
        pad = "#2ee6a6" if touched else "#555b66"
        c.create_polygon(self.xf([(82, 145), (112, 145), (112, 156), (82, 156)], ang),
                         fill=pad, outline="#111")
        if touched:
            pts = [(97 + 34 * math.cos(t / 10 * math.pi), 158 + 20 * math.sin(t / 10 * math.pi))
                   for t in range(20)]
            c.create_polygon(self.xf(pts, ang), fill="#e0b48f", outline="#8a6a4f",
                             width=2, stipple="gray50")
            c.create_text(*self.xf([(97, 185)], ang), text="HAND", fill="#e0b48f")

    def draw_panel(self, state, az, connected):
        c = self.canvas
        # rocker switch (clickable) - mains supply in series with the relay
        c.create_rectangle(540, 20, 620, 90, fill="#2b2e38", outline="#888", width=2)
        c.create_rectangle(548, 28, 612, 82, fill="#22c55e" if self.mains else "#7f1d1d", outline="")
        c.create_text(580, 55, text="I" if self.mains else "O", fill="white", font=("Arial", 24, "bold"))
        c.create_text(580, 105, text="MAINS SWITCH\n(click)", fill="#aaa", font=("Arial", 8))

        # relay LED (from real Arduino data)
        c.create_oval(30, 25, 55, 50, fill="#ff3030" if self.relay else "#3a1515", outline="#888")
        c.create_text(65, 37, anchor="w", fill="white",
                      text="RELAY " + ("ON" if self.relay else "OFF"), font=("Arial", 11, "bold"))
        # heater lamp
        c.create_oval(30, 60, 55, 85, fill="#ffa500" if self.heating else "#3a2a10", outline="#888")
        c.create_text(65, 72, anchor="w", fill="white",
                      text="HEATING" if self.heating else "THERMOSTAT IDLE", font=("Arial", 11))
        # temperature bar
        c.create_rectangle(30, 105, 230, 120, outline="#888")
        w = 200 * min(1, (self.temp - AMBIENT) / (220 - AMBIENT))
        c.create_rectangle(30, 105, 30 + w, 120, fill=blend("#3b82f6", "#ef4444", w / 200), outline="")
        c.create_text(30, 135, anchor="w", fill="white",
                      text=f"Plate temp: {self.temp:.0f} °C  (set {SETPOINT})")
        # live sensor readout
        c.create_text(30, 160, anchor="w", fill="#9ca3af", font=("Consolas", 10),
                      text=f"az = {az}   tilt = {self.angle:.0f}°")

        color = {"IRONING": "#22c55e", "SAFETY CUTOFF": "#ef4444",
                 "NO DATA": "#9ca3af"}.get(state, "#facc15")
        c.create_text(320, 380, fill=color, font=("Arial", 14, "bold"), text=state)

    # ---------- main loop ----------
    def on_click(self, e):
        if 540 <= e.x <= 620 and 20 <= e.y <= 90:
            self.mains = not self.mains

    def tick(self):
        with self.lock:
            ax, ay, az = self.ax, self.ay, self.az
            touched, relay = self.touch, self.relay
            fresh = (time.time() - self.last_rx) < 1.5

        connected = self.running and fresh
        if connected:
            self.relay = relay
            mag = math.sqrt(ax * ax + ay * ay + az * az) or 1
            target = math.degrees(math.acos(min(1, abs(az) / mag)))
            self.angle += (target - self.angle) * 0.35    # smooth movement
            is_flat = abs(az) > FLAT_THRESHOLD

            if not self.mains:
                state = "MAINS SWITCH OFF"
            elif is_flat and touched:
                state = "IRONING"
            elif is_flat and not touched:
                state = "SAFETY CUTOFF"
            else:
                state = "STANDBY (upright)"
        else:
            state = "NO DATA"
            self.relay = False
            touched = False

        # power reaches the plate only if mains is ON and the relay is ON
        powered = self.mains and self.relay
        if powered:
            if self.temp >= SETPOINT:
                self.heating = False
            elif self.temp < SETPOINT - 5:
                self.heating = True
        else:
            self.heating = False
        if self.heating:
            self.temp += 0.6
        self.temp -= 0.15 * (self.temp - AMBIENT) / (SETPOINT - AMBIENT)

        if connected:
            self.status_lbl.config(text="Receiving data", fg="#22c55e")
        else:
            self.status_lbl.config(text="Waiting / disconnected", fg="#ef4444")

        if state != self.last_state:
            self.log_msg(f"az={az:6d} touch={touched} relay={self.relay} -> {state}")
            self.last_state = state

        self.canvas.delete("all")
        self.draw_iron(self.angle, touched)
        self.draw_panel(state, az, connected)
        self.root.after(50, self.tick)


root = tk.Tk()
IronSim(root)
root.mainloop()