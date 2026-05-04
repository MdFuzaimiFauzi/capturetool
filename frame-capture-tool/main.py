import cv2
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import time
import datetime
import os
import threading
import shutil
import http.server
import socketserver
import socket
import subprocess
import numpy as np


# ── Colour palette ─────────────────────────────────────────────────────────────
BG         = "#0b0c0e"
PANEL      = "#13151a"
BORDER     = "#1e2029"
ACCENT_GRN = "#00e87a"
ACCENT_RED = "#ff3a3a"
ACCENT_ORG = "#ff8c26"
ACCENT_BLU = "#3d9bff"
TEXT_PRI   = "#e8eaf0"
TEXT_SEC   = "#5a5f72"
TEXT_MNO   = "#8892a4"
BTN_REC_BG = "#00e87a"
BTN_REC_FG = "#0b0c0e"
BTN_POR_BG = "#1e2029"
BTN_POR_FG = "#3d9bff"

FONT_HEAD   = ("Helvetica", 11, "bold")
FONT_MONO   = ("Courier", 10)
FONT_LABEL  = ("Helvetica", 8)
FONT_BTN    = ("Helvetica", 10, "bold")
FONT_STATUS = ("Helvetica", 16, "bold")


# ── Camera backend ─────────────────────────────────────────────────────────────
class RPiCamera:
    def __init__(self, width, height):
        cmd = [
            "rpicam-vid", "-n", "-t", "0", "--codec", "mjpeg",
            "--width", str(width), "--height", str(height),
            "--framerate", "20", "-o", "-",
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.bytes = b""
        self.is_opened = True
        self.latest_frame = None
        self.lock = threading.Lock()
        self.video_writer = None
        self.is_recording = False
        self.thread = threading.Thread(target=self._capture_thread, daemon=True)
        self.thread.start()

    def _capture_thread(self):
        while self.is_opened:
            chunk = self.process.stdout.read(131072)
            if not chunk:
                break
            self.bytes += chunk
            while True:
                a = self.bytes.find(b"\xff\xd8")
                b = self.bytes.find(b"\xff\xd9")
                if a != -1 and b != -1:
                    jpg = self.bytes[a : b + 2]
                    self.bytes = self.bytes[b + 2 :]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        with self.lock:
                            self.latest_frame = frame.copy()
                            if self.is_recording and self.video_writer is not None:
                                self.video_writer.write(frame)
                else:
                    break

    def isOpened(self):
        return self.is_opened

    def read(self):
        with self.lock:
            if self.latest_frame is not None:
                return True, self.latest_frame.copy()
        return False, None

    def start_recording(self, writer):
        with self.lock:
            self.video_writer = writer
            self.is_recording = True

    def stop_recording(self):
        with self.lock:
            self.is_recording = False
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None

    def release(self):
        self.is_opened = False
        self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()


# ── UI helpers ──────────────────────────────────────────────────────────────────
class Divider(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BORDER, height=1, **kw)
        self.pack(fill=tk.X, pady=10)


class SectionLabel(tk.Label):
    def __init__(self, parent, text, **kw):
        super().__init__(parent, text=text, bg=PANEL, fg=TEXT_SEC,
                         font=FONT_LABEL, anchor="w", **kw)
        self.pack(fill=tk.X, padx=16, pady=(4, 2))


class ModernButton(tk.Canvas):
    def __init__(self, parent, text, bg, fg, command=None, width=220, height=38, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=PANEL, highlightthickness=0, **kw)
        self._bg = bg
        self._fg = fg
        self._text = text
        self._command = command
        self.btn_width = width
        self.btn_height = height
        self._disabled = False
        self._draw()
        self.bind("<ButtonRelease-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _shade(self, hexcol, delta):
        try:
            r = max(0, min(255, int(hexcol[1:3], 16) + delta))
            g = max(0, min(255, int(hexcol[3:5], 16) + delta))
            b = max(0, min(255, int(hexcol[5:7], 16) + delta))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hexcol

    def _draw(self, hover=False):
        self.delete("all")
        bg = self._shade(self._bg, 24 if hover else 0) if not self._disabled else self._shade(self._bg, -60)
        fg = self._fg if not self._disabled else TEXT_SEC
        r  = self.btn_height // 2
        for args in [
            (0, 0, self.btn_height, self.btn_height),
            (self.btn_width - self.btn_height, 0, self.btn_width, self.btn_height),
        ]:
            self.create_oval(*args, fill=bg, outline="")
        self.create_rectangle(r, 0, self.btn_width - r, self.btn_height, fill=bg, outline="")
        self.create_text(self.btn_width // 2, self.btn_height // 2, text=self._text, fill=fg, font=FONT_BTN)

    def _on_click(self, _):
        if not self._disabled and self._command:
            self._command()

    def _on_enter(self, _):
        if not self._disabled:
            self._draw(hover=True)

    def _on_leave(self, _):
        self._draw(hover=False)

    def config_text(self, text):
        self._text = text
        self._draw()

    def config_colors(self, bg=None, fg=None):
        if bg:
            self._bg = bg
        if fg:
            self._fg = fg
        self._draw()

    def set_enabled(self, enabled):
        self._disabled = not enabled
        self._draw()


class StatusDot(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, width=12, height=12, bg=PANEL,
                         highlightthickness=0, **kw)
        self._color = TEXT_SEC
        self._pulse = False
        self._on = True
        self._draw()

    def _draw(self):
        self.delete("all")
        color = self._color if (not self._pulse or self._on) else PANEL
        self.create_oval(2, 2, 10, 10, fill=color, outline="")

    def set_color(self, color, pulse=False):
        self._color = color
        self._pulse = pulse
        self._on = True
        self._draw()

    def tick(self):
        if self._pulse:
            self._on = not self._on
            self._draw()


# ── Application ────────────────────────────────────────────────────────────────
class CM5ResearchRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("Capture Tool")
        self.root.geometry("1200x740")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self.cap = None
        self.recording = False
        self._rec_start = 0
        self.save_path = os.path.join(os.path.expanduser("~"), "Videos")
        if not os.path.exists(self.save_path):
            os.makedirs(self.save_path)

        self.server_thread = None
        self.httpd = None

        self.res_var      = tk.StringVar(value="1920x1080")
        self.count_var    = tk.IntVar(value=3)
        self.duration_var = tk.IntVar(value=6)
        self.prev_time    = 0

        self._build_ui()
        self.check_hardware()
        self.update_system_stats()
        self.start_preview_engine()

    # ── Utilities ──────────────────────────────────────────────────────────────

    def get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    def get_cpu_temp(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return f"{int(f.read()) / 1000.0:.1f}C"
        except Exception:
            return "ERR"

    # ── UI build ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, minsize=270)
        self.root.grid_rowconfigure(0, weight=1)

        # ── Video area ────────────────────────────────────────────────────────
        video_wrapper = tk.Frame(self.root, bg=BG)
        video_wrapper.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=14)
        video_wrapper.grid_rowconfigure(0, weight=1)
        video_wrapper.grid_columnconfigure(0, weight=1)

        self._video_border = tk.Frame(video_wrapper, bg=BORDER, padx=2, pady=2)
        self._video_border.grid(row=0, column=0, sticky="nsew")

        # Explicitly center the image inside the video pane to avoid shifting
        self.video_pane = tk.Label(self._video_border, bg="#000000", anchor="center")
        self.video_pane.pack(fill=tk.BOTH, expand=True)

        # Info bar below video
        info_bar = tk.Frame(video_wrapper, bg=PANEL, height=36)
        info_bar.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        info_bar.grid_propagate(False)

        self._fps_lbl  = tk.Label(info_bar, text="FPS  --", bg=PANEL, fg=TEXT_MNO, font=FONT_MONO, padx=12)
        self._fps_lbl.pack(side=tk.LEFT)
        tk.Label(info_bar, text="│", bg=PANEL, fg=BORDER).pack(side=tk.LEFT)
        self._temp_lbl = tk.Label(info_bar, text="TEMP  --", bg=PANEL, fg=TEXT_MNO, font=FONT_MONO, padx=12)
        self._temp_lbl.pack(side=tk.LEFT)
        tk.Label(info_bar, text="│", bg=PANEL, fg=BORDER).pack(side=tk.LEFT)
        self._res_info = tk.Label(info_bar, text="1920 x 1080", bg=PANEL, fg=TEXT_MNO, font=FONT_MONO, padx=12)
        self._res_info.pack(side=tk.LEFT)
        self._tc_lbl   = tk.Label(info_bar, text="--:--:--", bg=PANEL, fg=TEXT_MNO, font=FONT_MONO, padx=12)
        self._tc_lbl.pack(side=tk.RIGHT)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = tk.Frame(self.root, bg=PANEL, width=270)
        sidebar.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=14)
        sidebar.grid_propagate(False)

        # Brand strip
        brand = tk.Frame(sidebar, bg="#0d0e12", height=56)
        brand.pack(fill=tk.X)
        brand.pack_propagate(False)
        tk.Label(brand, text=" CAPTURE", bg="#0d0e12", fg=TEXT_PRI,
                 font=("Courier", 13, "bold"), padx=16).pack(side=tk.LEFT, pady=14)
        tk.Label(brand, text="TOOL", bg="#0d0e12", fg=TEXT_SEC,
                 font=("Courier", 13)).pack(side=tk.LEFT, pady=14)

        # Status row
        status_row = tk.Frame(sidebar, bg=PANEL)
        status_row.pack(fill=tk.X, padx=16, pady=(14, 2))
        self._dot = StatusDot(status_row)
        self._dot.pack(side=tk.LEFT, pady=2)
        self._status_lbl = tk.Label(status_row, text="SEARCHING...", bg=PANEL,
                                    fg=TEXT_SEC, font=FONT_STATUS, anchor="w")
        self._status_lbl.pack(side=tk.LEFT, padx=(8, 0))

        # Disk readout
        disk_row = tk.Frame(sidebar, bg=PANEL)
        disk_row.pack(fill=tk.X, padx=16, pady=(0, 4))
        self._storage_lbl = tk.Label(disk_row, text="DISK  --% FREE", bg=PANEL,
                                     fg=TEXT_MNO, font=FONT_MONO)
        self._storage_lbl.pack(side=tk.LEFT)

        self._disk_canvas = tk.Canvas(sidebar, bg=PANEL, height=4, highlightthickness=0)
        self._disk_canvas.pack(fill=tk.X, padx=16, pady=(0, 4))

        Divider(sidebar)

        # Resolution
        SectionLabel(sidebar, "RESOLUTION")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                         fieldbackground=BG, background=PANEL,
                         foreground=TEXT_PRI, arrowcolor=TEXT_SEC,
                         bordercolor=BORDER, selectbackground=BG,
                         selectforeground=TEXT_PRI, padding=6)
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG)],
                  foreground=[("readonly", TEXT_PRI)])
        self._res_combo = ttk.Combobox(sidebar, textvariable=self.res_var,
                                       values=["640x480", "1280x720", "1920x1080"],
                                       state="readonly", style="Dark.TCombobox")
        self._res_combo.pack(fill=tk.X, padx=16, pady=(0, 10))
        self.res_var.trace("w", lambda *a: self.reinit_camera())

        # Countdown / Duration
        cfg_row = tk.Frame(sidebar, bg=PANEL)
        cfg_row.pack(fill=tk.X, padx=16, pady=(0, 10))
        for col, (label, var) in enumerate([("COUNTDOWN (s)", self.count_var),
                                            ("DURATION (s)",  self.duration_var)]):
            cfg_row.grid_columnconfigure(col, weight=1)
            cell = tk.Frame(cfg_row, bg=PANEL)
            cell.grid(row=0, column=col, sticky="ew", padx=(0, 6 if col == 0 else 0))
            tk.Label(cell, text=label, bg=PANEL, fg=TEXT_SEC,
                     font=FONT_LABEL, anchor="w").pack(fill=tk.X)
            tk.Entry(cell, textvariable=var, bg=BG, fg=TEXT_PRI,
                     insertbackground=TEXT_PRI, font=FONT_MONO,
                     relief="flat", bd=0, highlightthickness=1,
                     highlightbackground=BORDER,
                     highlightcolor=ACCENT_GRN).pack(fill=tk.X, ipady=5)

        Divider(sidebar)

        # Record button
        self._rec_btn = ModernButton(sidebar, text=" START RECORDING",
                                     bg=BTN_REC_BG, fg=BTN_REC_FG,
                                     command=self.trigger_countdown,
                                     width=238, height=44)
        self._rec_btn.pack(padx=16, pady=(0, 4))

        Divider(sidebar)

        # Portal
        SectionLabel(sidebar, "WIRELESS TRANSFER")
        self._portal_lbl = tk.Label(sidebar, text="Offline", bg=PANEL,
                                    fg=TEXT_SEC, font=FONT_MONO,
                                    anchor="w", wraplength=238)
        self._portal_lbl.pack(fill=tk.X, padx=16, pady=(0, 8))
        self._portal_btn = ModernButton(sidebar, text="ENABLE PORTAL",
                                        bg=BTN_POR_BG, fg=BTN_POR_FG,
                                        command=self.toggle_portal,
                                        width=238, height=36)
        self._portal_btn.pack(padx=16)

        # Spacer + save path footer
        tk.Frame(sidebar, bg=PANEL).pack(fill=tk.BOTH, expand=True)
        footer = tk.Frame(sidebar, bg="#0d0e12")
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        
        tk.Label(footer, text="SAVE PATH", bg="#0d0e12", fg=TEXT_SEC,
                 font=FONT_LABEL, anchor="w").pack(fill=tk.X, padx=12, pady=4)
        tk.Label(footer, text=self.save_path, bg="#0d0e12", fg=TEXT_MNO,
                 font=("Courier", 8), anchor="w", wraplength=240).pack(fill=tk.X, padx=12, pady=(0, 8))

    # ── Status helper ──────────────────────────────────────────────────────────

    def _set_status(self, text, color, pulse=False):
        self._status_lbl.config(text=text, fg=color)
        self._dot.set_color(color, pulse=pulse)
        self._video_border.config(bg=color if pulse else BORDER)

    # ── Hardware ───────────────────────────────────────────────────────────────

    def check_hardware(self):
        if self.cap is None or not self.cap.isOpened():
            w, h = map(int, self.res_var.get().split("x"))
            try:
                self.cap = RPiCamera(w, h)
                if self.cap.isOpened():
                    self._set_status("CONNECTED", ACCENT_GRN)
                else:
                    self._set_status("DISCONNECTED", ACCENT_RED)
            except Exception:
                self._set_status("HARDWARE ERR", ACCENT_RED)

    def reinit_camera(self):
        w, h = self.res_var.get().split("x")
        self._res_info.config(text=f"{w} x {h}")
        if self.cap:
            self.cap.release()
        self.cap = None

    # ── System stats ───────────────────────────────────────────────────────────

    def update_system_stats(self):
        total, _, free = shutil.disk_usage("/")
        pct = (free / total) * 100
        self._storage_lbl.config(
            text=f"DISK  {pct:.0f}% FREE",
            fg=ACCENT_RED if pct < 10 else TEXT_MNO,
        )
        self._disk_canvas.update_idletasks()
        w = self._disk_canvas.winfo_width()
        self._disk_canvas.delete("all")
        self._disk_canvas.create_rectangle(0, 0, w, 4, fill=BORDER, outline="")
        self._disk_canvas.create_rectangle(
            0, 0, int(w * pct / 100), 4,
            fill=ACCENT_RED if pct < 10 else ACCENT_GRN, outline="",
        )
        self.root.after(10000, self.update_system_stats)

    # ── Preview loop ───────────────────────────────────────────────────────────

    def start_preview_engine(self):
        self._dot.tick()

        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                now = time.time()
                fps = 1 / (now - self.prev_time) if self.prev_time > 0 else 0
                self.prev_time = now

                self._fps_lbl.config(text=f"FPS  {int(fps):02d}")
                self._temp_lbl.config(text=f"TEMP  {self.get_cpu_temp()}")
                self._tc_lbl.config(text=datetime.datetime.now().strftime("%H:%M:%S"))

                # Resize the frame FIRST to ensure uniform scaling of our UI elements
                small = cv2.resize(frame, (880, 495))

                if self.recording:
                    if int(time.time() * 2) % 2 == 0:
                        # Draw perfectly scaled borders onto the resized frame
                        cv2.rectangle(small, (3, 3), (877, 492), (0, 0, 220), 6)
                        
                    elapsed   = time.monotonic() - self._rec_start
                    remaining = max(0, self.duration_var.get() - int(elapsed))
                    cv2.putText(small, f"REC -{remaining:02d}s",
                                (18, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 220), 2)

                rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                img   = ImageTk.PhotoImage(Image.fromarray(rgb))
                self.video_pane.img_tk = img
                self.video_pane.config(image=img)

        self.root.after(30, self.start_preview_engine)

    # ── Recording ──────────────────────────────────────────────────────────────

    def trigger_countdown(self):
        self._rec_btn.set_enabled(False)
        threading.Thread(target=self.countdown_process, daemon=True).start()

    def countdown_process(self):
        for i in range(self.count_var.get(), 0, -1):
            self.root.after(0, lambda s=i: self._set_status(f"IN {s}s", ACCENT_ORG))
            time.sleep(1)
        self.root.after(0, self.start_rec)

    def start_rec(self):
        w, h = map(int, self.res_var.get().split("x"))
        ts   = datetime.datetime.now().strftime("%d%m%Y_%H-%M-%S")
        path = os.path.join(self.save_path, f"{ts}.avi")
        out  = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (w, h))
        if self.cap:
            self.cap.start_recording(out)
        self.recording  = True
        self._rec_start = time.monotonic()
        self._set_status("RECORDING", ACCENT_RED, pulse=True)
        self._rec_btn.config_text(" RECORDING")
        self._rec_btn.config_colors(bg=ACCENT_RED, fg="#ffffff")
        threading.Timer(self.duration_var.get(), self.stop_rec).start()

    def stop_rec(self):
        self.recording = False
        if self.cap:
            self.cap.stop_recording()
        self.root.after(0, self._stop_rec_gui)

    def _stop_rec_gui(self):
        self._rec_btn.config_text(" START RECORDING")
        self._rec_btn.config_colors(bg=BTN_REC_BG, fg=BTN_REC_FG)
        self._rec_btn.set_enabled(True)
        self._video_border.config(bg=BORDER)
        self._set_status("CONNECTED", ACCENT_GRN)
        self.check_hardware()

    # ── Portal ─────────────────────────────────────────────────────────────────

    def toggle_portal(self):
        if self.server_thread and self.server_thread.is_alive():
            if self.httpd:
                self.httpd.shutdown()
                self.httpd.server_close()
            self._portal_lbl.config(text="Offline", fg=TEXT_SEC)
            self._portal_btn.config_text("ENABLE PORTAL")
            self._portal_btn.config_colors(bg=BTN_POR_BG, fg=BTN_POR_FG)
        else:
            self.server_thread = threading.Thread(target=self.serve_portal, daemon=True)
            self.server_thread.start()

    def serve_portal(self):
        port    = 8000
        handler = http.server.SimpleHTTPRequestHandler
        os.chdir(self.save_path)
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.TCPServer(("", port), handler) as self.httpd:
                ip = self.get_local_ip()
                self.root.after(0, lambda: [
                    self._portal_lbl.config(text=f"http://{ip}:{port}", fg=ACCENT_BLU),
                    self._portal_btn.config_text("DISABLE PORTAL"),
                    self._portal_btn.config_colors(bg=ACCENT_RED, fg="#ffffff"),
                ])
                self.httpd.serve_forever()
        except Exception as e:
            messagebox.showerror("Server Error", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app  = CM5ResearchRecorder(root)
    root.mainloop()
