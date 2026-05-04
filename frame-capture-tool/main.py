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

class RPiCamera:
    def __init__(self, width, height):
        # Reduced framerate to 20 to match Pi's CPU max processing speed for 1080p decode/encode
        cmd = ['rpicam-vid', '-n', '-t', '0', '--codec', 'mjpeg', '--width', str(width), '--height', str(height), '--framerate', '20', '-o', '-']
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.bytes = b''
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
            
            # Process ALL available complete frames in the buffer
            while True:
                a = self.bytes.find(b'\xff\xd8')
                b = self.bytes.find(b'\xff\xd9')
                if a != -1 and b != -1:
                    jpg = self.bytes[a:b+2]
                    self.bytes = self.bytes[b+2:]
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

class CM5ResearchRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title('Capture Tool')
        self.root.geometry('1150x850')

        # App Variables
        self.cap = None
        self.recording = False
        self.out = None
        self.save_path = os.path.join(os.path.expanduser('~'), 'Videos')
        if not os.path.exists(self.save_path): os.makedirs(self.save_path)
        
        self.server_thread = None
        self.httpd = None

        # GUI Tracking
        self.res_var = tk.StringVar(value='1920x1080')
        self.count_var = tk.IntVar(value=3)
        self.duration_var = tk.IntVar(value=6)
        self.prev_time = 0
        self.blink_state = True

        self.setup_ui()
        self.check_hardware()
        self.update_system_stats()
        self.start_preview_engine()

    def get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def get_cpu_temp(self):
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_raw = int(f.read())
            return f'TEMP: {temp_raw / 1000.0:.1f}C'
        except Exception:
            return 'TEMP: ERR'

    def setup_ui(self):
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Video Area
        self.video_pane = tk.Label(self.main_container, bg='black')
        self.video_pane.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

        # Control Panel
        self.ctrl_panel = tk.Frame(self.main_container, width=280)
        self.ctrl_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        # Health Labels
        self.status_lbl = tk.Label(self.ctrl_panel, text='SEARCHING...', font=('Arial', 14, 'bold'))
        self.status_lbl.pack(pady=10)

        self.storage_lbl = tk.Label(self.ctrl_panel, text='Storage: --%', font=('Arial', 10))
        self.storage_lbl.pack()

        tk.Label(self.ctrl_panel, text='--- CONFIGURATION ---').pack(pady=(20, 5))
        
        ttk.Combobox(self.ctrl_panel, textvariable=self.res_var, values=['640x480', '1280x720', '1920x1080']).pack()
        self.res_var.trace('w', lambda *args: self.reinit_camera())

        tk.Label(self.ctrl_panel, text='Countdown (s):').pack(pady=(10, 0))
        tk.Spinbox(self.ctrl_panel, from_=3, to=10, textvariable=self.count_var).pack()

        tk.Label(self.ctrl_panel, text='Duration (s):').pack(pady=(10, 0))
        tk.Spinbox(self.ctrl_panel, from_=1, to=3600, textvariable=self.duration_var).pack()

        self.rec_btn = tk.Button(self.ctrl_panel, text='START RECORDING', bg='#27ae60', fg='white', 
                                 height=2, font=('Arial', 10, 'bold'), command=self.trigger_countdown)
        self.rec_btn.pack(fill=tk.X, pady=20)

        # Portal Section
        tk.Label(self.ctrl_panel, text='--- SECURE PORTAL ---').pack(pady=(15, 0))
        self.portal_info = tk.Label(self.ctrl_panel, text='Portal: Offline', fg='blue', wraplength=200)
        self.portal_info.pack(pady=5)
        
        self.portal_btn = tk.Button(self.ctrl_panel, text='ENABLE WIRELESS TRANSFER', command=self.toggle_portal)
        self.portal_btn.pack(fill=tk.X)

    def toggle_portal(self):
        if self.server_thread and self.server_thread.is_alive():
            if self.httpd: 
                self.httpd.shutdown()
                self.httpd.server_close()
            self.portal_info.config(text='Portal: Offline', fg='black')
            self.portal_btn.config(text='ENABLE WIRELESS TRANSFER', bg='SystemButtonFace', fg='black')
        else:
            self.server_thread = threading.Thread(target=self.serve_portal, daemon=True)
            self.server_thread.start()

    def serve_portal(self):
        port = 8000
        handler = http.server.SimpleHTTPRequestHandler
        os.chdir(self.save_path)
        socketserver.TCPServer.allow_reuse_address = True
        try:
            with socketserver.TCPServer(('', port), handler) as self.httpd:
                self.portal_info.config(text=f'Laptop Browser: http://{self.get_local_ip()}:{port}', fg='#2980b9')
                self.portal_btn.config(text='DISABLE PORTAL', bg='#e67e22', fg='white')
                self.httpd.serve_forever()
        except Exception as e:
            messagebox.showerror('Server Error', str(e))

    def update_system_stats(self):
        total, used, free = shutil.disk_usage('/')
        free_pct = (free / total) * 100
        self.storage_lbl.config(text=f'Available Storage: {free_pct:.1f}%', 
                                fg='red' if free_pct < 10 else 'black')
        self.root.after(10000, self.update_system_stats)

    def check_hardware(self):
         if self.cap is None or not self.cap.isOpened():
             w, h = map(int, self.res_var.get().split('x'))
             try:
                 self.cap = RPiCamera(w, h)
                 if self.cap.isOpened():
                     self.status_lbl.config(text='CONNECTED', fg='#2ecc71')
                 else:
                     self.status_lbl.config(text='DISCONNECTED', fg='#e74c3c')
             except Exception as e:
                 print(f"Camera init error: {e}")
                 self.status_lbl.config(text='DISCONNECTED', fg='#e74c3c')

    def reinit_camera(self):
        if self.cap: self.cap.release()
        self.cap = None
        #self.check_hardware()

    def start_preview_engine(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                # Performance Data
                now = time.time()
                fps = 1 / (now - self.prev_time) if (now - self.prev_time) > 0 else 0
                self.prev_time = now
                
                # NOTE: Video saving is now handled in the background thread for speed!
                if self.recording:
                    if int(time.time() * 2) % 2 == 0:
                        cv2.rectangle(frame, (10, 10), (frame.shape[1]-10, frame.shape[0]-10), (0, 0, 255), 8)

                # Visual Overlays (Applied AFTER recording so they only show on GUI)
                cv2.putText(frame, f'GUI FPS: {int(fps)}', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(frame, self.get_cpu_temp(), (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

                # Rendering - Highly Optimized for Raspberry Pi CPU
                small_frame = cv2.resize(frame, (800, 450))
                cv_img = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(cv_img)
                img_tk = ImageTk.PhotoImage(image=img)
                self.video_pane.img_tk = img_tk
                self.video_pane.config(image=img_tk)

        self.root.after(30, self.start_preview_engine)

    def trigger_countdown(self):
        self.rec_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.countdown_process).start()

    def countdown_process(self):
        for i in range(self.count_var.get(), 0, -1):
            self.root.after(0, lambda sec=i: self.status_lbl.config(text=f'STARTING IN {sec}s', fg='#f39c12'))
            time.sleep(1)
        self.root.after(0, self.start_rec)

    def start_rec(self):
        w, h = map(int, self.res_var.get().split('x'))
        ts = datetime.datetime.now().strftime('%d%m%Y_%H-%M-%S')
        out = cv2.VideoWriter(os.path.join(self.save_path, f'{ts}.avi'), 
                                   cv2.VideoWriter_fourcc(*'MJPG'), 20.0, (w, h))
        if self.cap:
            self.cap.start_recording(out)
        self.recording = True
        self.status_lbl.config(text='RECORDING', fg='#e74c3c')
        threading.Timer(self.duration_var.get(), self.stop_rec).start()

    def stop_rec(self):
        self.recording = False
        if self.cap:
            self.cap.stop_recording()
        self.root.after(0, self._stop_rec_gui)

    def _stop_rec_gui(self):
        self.rec_btn.config(state=tk.NORMAL)
        self.check_hardware()

if __name__ == '__main__':
    root_window = tk.Tk()
    app = CM5ResearchRecorder(root_window)
    root_window.mainloop()
