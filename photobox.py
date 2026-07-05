import os
import time
import subprocess
import pygame
import threading
from io import BytesIO
from PIL import Image

# Ordner für die Fotos
SAVE_DIR = "fotos"
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

# Pygame initialisieren
pygame.init()
pygame.mouse.set_visible(False)
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
WIDTH, HEIGHT = screen.get_size()
clock = pygame.time.Clock()

# Farben
WHITE = (255, 255, 255)
RED = (255, 50, 50)
BLACK = (0, 0, 0)

# RIESIGE Schriftarten für den Countdown (Zahlen stark vergrößert)
FONT_COUNTDOWN = pygame.font.SysFont("Arial", 400, bold=True)
FONT_CHEESE = pygame.font.SysFont("Arial", 250, bold=True)
FONT_INFO = pygame.font.SysFont("Arial", 50)
FONT_SUBTITLE = pygame.font.SysFont("Arial", 40, italic=True)

# Globale Variablen für den Stream-Thread
current_frame = None
stream_process = None
stream_thread = None
keep_streaming = False

def stream_worker():
    """Hintergrund-Thread für den flüssigen Kamera-Live-Stream."""
    global current_frame, keep_streaming, stream_process
    
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
                
                try:
                    img = Image.open(BytesIO(jpg_data))
                    mode = img.mode
                    size = img.size
                    data = img.tobytes()
                    surface = pygame.image.fromstring(data, size, mode)
                    current_frame = pygame.transform.smoothscale(surface, (WIDTH, HEIGHT))
                except Exception:
                    pass
    except Exception:
        pass

def start_live_stream():
    """Startet den Live-Stream."""
    global stream_thread, keep_streaming
    if not keep_streaming:
        keep_streaming = True
        stream_thread = threading.Thread(target=stream_worker, daemon=True)
        stream_thread.start()

def stop_live_stream():
    """Stoppt den Stream komplett."""
    global keep_streaming, stream_process, current_frame
    keep_streaming = False
    if stream_process:
        gphoto, ffmpeg = stream_process
        gphoto.kill()
        ffmpeg.kill()
        stream_process = None
    current_frame = None

def capture_photo():
    """Schießt das hochauflösende Foto (Kamera ist bereits bereit)."""
    filename = f"{SAVE_DIR}/foto_{int(time.time())}.jpg"
    cmd = ["gphoto2", "--capture-image-and-download", "--filename", filename]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return filename

def draw_text(text, font, color, y_offset=0):
    """Hilfsfunktion für zentrierten Text."""
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=(WIDTH // 2, (HEIGHT // 2) + y_offset))
    screen.blit(text_surface, text_rect)

# Hauptprogramm-Schleife
running = True
state = "PREVIEW"
countdown_start = 0
photo_path = ""
show_photo_start = 0

# Erster Start des Streams
start_live_stream()

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_SPACE and state == "PREVIEW":
                # JETZT NEU: Direkt beim Tastendruck den Stream kappen,
                # damit die Kamera sofort umschaltet und das Klacken hier passiert.
                stop_live_stream()
                state = "COUNTDOWN"
                countdown_start = time.time()

    if state == "PREVIEW":
        if current_frame:
            screen.blit(current_frame, (0, 0))
            draw_text("Drücke die LEERTASTE für ein Foto!", FONT_INFO, WHITE, y_offset=(HEIGHT // 2) - 50)
        else:
            screen.fill(BLACK)
            draw_text("Bereite Kamera vor...", FONT_INFO, WHITE)

    elif state == "COUNTDOWN":
        elapsed = time.time() - countdown_start
        
        # Ab jetzt bleibt der Hintergrund komplett schwarz
        screen.fill(BLACK)
        
        if elapsed < 1.0:
            draw_text("3", FONT_COUNTDOWN, RED, y_offset=-50)
            draw_text("wird vorbereitet...", FONT_SUBTITLE, WHITE, y_offset=180)
        elif elapsed < 2.0:
            draw_text("2", FONT_COUNTDOWN, RED, y_offset=-50)
        elif elapsed < 3.0:
            draw_text("1", FONT_COUNTDOWN, RED, y_offset=-50)
        elif elapsed < 3.8:
            # 3-2-1 vorbei: Direkt "Cheese!" anzeigen und parallel auslösen!
            draw_text("Cheese!", FONT_CHEESE, WHITE)
            if elapsed < 3.1: # Nur einmal kurz den Blitz-Effekt triggern
                screen.fill(WHITE)
        else:
            # Nach dem "Cheese!"-Moment wechseln wir zum Speicher-Zustand
            state = "FLASH"

    elif state == "FLASH":
        # Da der Stream seit Sekunde 0 aus ist, knackt der Verschluss jetzt verzögerungsfrei
        photo_path = capture_photo()
        state = "SHOW_PHOTO"
        show_photo_start = time.time()

    elif state == "SHOW_PHOTO":
        if os.path.exists(photo_path):
            try:
                img = pygame.image.load(photo_path)
                scaled_img = pygame.transform.smoothscale(img, (WIDTH, HEIGHT))
                screen.blit(scaled_img, (0, 0))
            except Exception:
                screen.fill(BLACK)
        else:
            screen.fill(BLACK)
            draw_text("Verarbeite Foto...", FONT_INFO, WHITE)
        
        # NEU: Erhöht auf 5.0 Sekunden Anzeigezeit
        if time.time() - show_photo_start > 5.0:
            start_live_stream()
            state = "PREVIEW"

    pygame.display.flip()
    clock.tick(30)

# Aufräumen
stop_live_stream()
pygame.quit()