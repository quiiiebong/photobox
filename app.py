import os
import time
import subprocess
import threading
import json
import random
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, Response, jsonify, request, send_from_directory

app = Flask(__name__)

SAVE_DIR = "fotos"
CONFIG_FILE = "config.json"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

DEFAULT_CONFIG = {
    "countdown_time": 3,
    "cheese_text": "Cheese!",
    "pre_trigger_time": 1.0,
    "show_photo_time": 5,
    "diashow_order": "random",
    "diashow_transition": "fade",
    "diashow_duration": 4
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config_data):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)

config = load_config()

stream_process = None
keep_streaming = False
current_frame = b""
last_frame_time = 0
lock = threading.Lock()

overlay_text = ""
overlay_subtitle = ""
show_photo_path = None
is_capturing = False

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
]
FONT_PATH = None
for path in FONT_PATHS:
    if os.path.exists(path):
        FONT_PATH = path
        break

try:
    from gpiozero import Button
    buzzer = Button(17, pull_up=True, bounce_time=0.2)
    def handle_buzzer():
        global is_capturing
        if not is_capturing:
            threading.Thread(target=capture_sequence_worker, daemon=True).start()
    buzzer.when_pressed = handle_buzzer
    print("Hardware-Buzzer an GPIO 17 (Pin 11) erfolgreich initialisiert.")
except Exception as e:
    print(f"Hardware-Buzzer nicht initialisiert (läuft dieses Skript auf einem Raspberry Pi?): {e}")

def stream_worker():
    global current_frame, keep_streaming, stream_process, last_frame_time
    cmd = ["gphoto2", "--capture-movie", "--stdout"]
    ffmpeg_cmd = ["ffmpeg", "-i", "pipe:0", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"]
    try:
        gphoto = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=gphoto.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        stream_process = (gphoto, ffmpeg)
        bytes_data = b""
        while keep_streaming:
            chunk = ffmpeg.stdout.read(4096)
            if not chunk:
                break
            bytes_data += chunk
            a = bytes_data.find(b'\xff\xd8')
            b = bytes_data.find(b'\xff\xd9')
            if a != -1 and b != -1:
                jpg_data = bytes_data[a:b+2]
                bytes_data = bytes_data[b+2:]
                with lock:
                    current_frame = jpg_data
                    last_frame_time = time.time()
    except Exception:
        pass
    finally:
        stop_stream()

def start_stream():
    global keep_streaming, stream_thread
    if not keep_streaming and not is_capturing:
        keep_streaming = True
        stream_thread = threading.Thread(target=stream_worker, daemon=True)
        stream_thread.start()

def stop_stream():
    global keep_streaming, stream_process, current_frame
    keep_streaming = False
    if stream_process:
        gphoto, ffmpeg = stream_process
        try:
            gphoto.kill()
            ffmpeg.kill()
        except Exception:
            pass
        stream_process = None
    with lock:
        current_frame = b""
    time.sleep(0.4)

def wake_up_camera_via_trigger():
    """Führt eine Blind-Auslösung durch, um verklemmte Kamera-Firmware zurückzusetzen."""
    print("[Kamera-Reset] Sende Reset-Trigger an die Kamera...")
    stop_stream()
    subprocess.run(["pkill", "-9", "gphoto2"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "ffmpeg"], stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    cmd_dummy = ["gphoto2", "--capture-image"]
    try:
        subprocess.run(cmd_dummy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        print("[Kamera-Reset] Reset-Trigger erfolgreich gesendet.")
    except Exception as e:
        print(f"[Kamera-Reset] Trigger-Timeout oder Fehler: {e}")
    time.sleep(1.0)

def restart_stream_internal(force_firmware_trigger=False):
    stop_stream()
    if force_firmware_trigger:
        wake_up_camera_via_trigger()
    time.sleep(0.5)
    start_stream()

def watchdog_worker():
    global keep_streaming, is_capturing, last_frame_time
    while True:
        time.sleep(4)
        if keep_streaming and not is_capturing:
            now = time.time()
            if last_frame_time > 0 and (now - last_frame_time > 5.0):
                print("[Watchdog] Stream hängt! Versuch 1: Soft-Restart...")
                restart_stream_internal(force_firmware_trigger=False)
                
                time.sleep(5)
                if keep_streaming and not is_capturing and (time.time() - last_frame_time > 5.0):
                    print("[Watchdog] Stream immer noch tot! Versuch 2: Triggere Kamera-Auslösung zum Reset...")
                    restart_stream_internal(force_firmware_trigger=True)
                    time.sleep(8)

def draw_center_text(draw, img_width, img_height, text, font, fill_color, y_offset=0):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = right - left
    text_height = bottom - top
    x = (img_width - text_width) // 2
    y = (img_height - text_height) // 2 + y_offset
    draw.text((x+4, y+4), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill_color)

def gen_frames():
    global current_frame, overlay_text, overlay_subtitle, show_photo_path
    while True:
        time.sleep(0.04)
        if show_photo_path:
            try:
                with Image.open(show_photo_path) as img:
                    img.thumbnail((1280, 720))
                    output = BytesIO()
                    img.save(output, format="JPEG", quality=80)
                    yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + output.getvalue() + b'\r\n')
                continue
            except Exception:
                pass
        with lock:
            frame_data = current_frame
        if frame_data:
            try:
                img = Image.open(BytesIO(frame_data))
                w, h = img.size
                if overlay_text != "":
                    draw = ImageDraw.Draw(img)
                    if overlay_text in ["3", "2", "1", config["cheese_text"]]:
                        draw.rectangle([(0,0), (w,h)], fill=(0,0,0))
                        if overlay_text == config["cheese_text"]:
                            size_cheese = int(w * 0.14)
                            font = ImageFont.truetype(FONT_PATH, size_cheese) if FONT_PATH else ImageFont.load_default()
                            draw_center_text(draw, w, h, overlay_text, font, (255, 255, 255))
                        else:
                            size_countdown = int(w * 0.22)
                            size_sub = int(w * 0.035)
                            font_num = ImageFont.truetype(FONT_PATH, size_countdown) if FONT_PATH else ImageFont.load_default()
                            font_sub = ImageFont.truetype(FONT_PATH, size_sub) if FONT_PATH else ImageFont.load_default()
                            draw_center_text(draw, w, h, overlay_text, font_num, (255, 50, 50), y_offset=-int(h * 0.05))
                            if overlay_subtitle:
                                draw_center_text(draw, w, h, overlay_subtitle, font_sub, (255, 255, 255), y_offset=int(h * 0.25))
                output = BytesIO()
                img.save(output, format="JPEG", quality=85)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + output.getvalue() + b'\r\n')
            except Exception:
                pass

def capture_sequence_worker():
    global is_capturing, overlay_text, overlay_subtitle, show_photo_path, config, last_frame_time
    is_capturing = True
    show_photo_path = None
    countdown = float(config["countdown_time"])
    pre_trigger = float(config["pre_trigger_time"])
    current_count = int(countdown)
    time_per_step = max(0.1, (countdown - pre_trigger) / max(1, current_count - 1))
    
    while current_count > 1:
        overlay_text = str(current_count)
        if current_count == int(countdown):
            overlay_subtitle = "wird vorbereitet..."
        else:
            overlay_subtitle = ""
        time.sleep(time_per_step)
        current_count -= 1
        
    stop_stream()
    overlay_text = "1"
    time.sleep(pre_trigger)
    overlay_text = config["cheese_text"]
    
    filename = f"foto_{int(time.time())}.jpg"
    filepath = os.path.join(SAVE_DIR, filename)
    cmd = ["gphoto2", "--capture-image-and-download", "--filename", filepath]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    overlay_text = ""
    
    if os.path.exists(filepath):
        show_photo_path = filepath
        time.sleep(float(config["show_photo_time"]))
    
    show_photo_path = None
    is_capturing = False
    
    start_stream()
    
    # Prüfen, ob der Stream nach dem Bild wieder Daten sendet
    time.sleep(2.5)
    if time.time() - last_frame_time > 3.0:
        print("[Capture Worker] Stream nach Foto blockiert. Führe erzwungenen Kamera-Reset aus...")
        restart_stream_internal(force_firmware_trigger=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html', config=config)

@app.route('/diashow')
def diashow():
    return render_template('diashow.html')

@app.route('/galerie')
def galerie():
    return render_template('galerie.html')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/trigger')
def trigger():
    global is_capturing
    if is_capturing:
        return jsonify({"status": "busy"}), 423
    threading.Thread(target=capture_sequence_worker, daemon=True).start()
    return jsonify({"status": "triggered"})

@app.route('/save_settings', methods=['POST'])
def save_settings():
    global config
    for key in DEFAULT_CONFIG.keys():
        if key in request.form:
            if isinstance(DEFAULT_CONFIG[key], int):
                config[key] = int(request.form[key])
            elif isinstance(DEFAULT_CONFIG[key], float):
                config[key] = float(request.form[key])
            else:
                config[key] = request.form[key]
    save_config(config)
    return jsonify({"status": "success"})

@app.route('/api/camera_status')
def camera_status():
    try:
        res = subprocess.run(["gphoto2", "--auto-detect"], capture_output=True, text=True)
        lines = [line.strip() for line in res.stdout.strip().split('\n') if line.strip()]
        connected = len(lines) > 2
        details = lines[-1] if connected else "Keine Kamera erkannt"
        return jsonify({"connected": connected, "details": details})
    except Exception as e:
        return jsonify({"connected": False, "details": str(e)})

@app.route('/api/restart_stream', methods=['POST'])
def api_restart_stream():
    restart_stream_internal(force_firmware_trigger=False)
    return jsonify({"status": "success", "message": "Stream wurde neu gestartet"})

@app.route('/api/restart_gphoto', methods=['POST'])
def api_restart_gphoto():
    threading.Thread(target=restart_stream_internal, kwargs={"force_firmware_trigger": True}, daemon=True).start()
    return jsonify({"status": "success", "message": "Reset-Auslösung gesendet & Stream wird neu gestartet!"})

@app.route('/api/restart_app', methods=['POST'])
def api_restart_app():
    def delayed_exit():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=delayed_exit, daemon=True).start()
    return jsonify({"status": "success", "message": "App wird neu gestartet..."})

@app.route('/get_photo/<filename>')
def get_photo(filename):
    return send_from_directory(SAVE_DIR, filename)

@app.route('/api/fotos')
def api_fotos():
    try:
        files = [f for f in os.listdir(SAVE_DIR) if f.lower().endswith(('.jpg', '.jpeg'))]
        if config["diashow_order"] == "chronological":
            files.sort()
        else:
            random.shuffle(files)
        return jsonify({
            "fotos": files, 
            "transition": config["diashow_transition"], 
            "duration": config["diashow_duration"]
        })
    except Exception:
        return jsonify({"fotos": [], "transition": "fade", "duration": 4})

if __name__ == '__main__':
    start_stream()
    threading.Thread(target=watchdog_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
