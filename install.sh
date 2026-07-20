#!/bin/bash
echo "=== 1. Aktualisiere Paketquellen ==="
sudo apt update

echo -e "\n=== 2. Installiere System-Pakete ==="
sudo apt install -y gphoto2 ffmpeg python3-pip python3-dev python3-venv fonts-dejavu swig liblgpio-dev

echo -e "\n=== 3. Erstelle virtuelle Python-Umgebung (venv) ==="
python3 -m venv venv

echo -e "\n=== 4. Installiere Python-Pakete im venv ==="
./venv/bin/pip install --upgrade pip
./venv/bin/pip install Flask Pillow gpiozero rpi-lgpio

echo -e "\n=== 5. Erstelle komfortables Start-Skript ==="
cat << 'INNER_EOF' > start_fotobox.sh
#!/bin/bash
cd "$(dirname "$0")" || exit
echo "Starte Fotobox in der virtuellen Umgebung..."
source venv/bin/activate
python app.py
INNER_EOF
chmod +x start_fotobox.sh

mkdir -p templates fotos

echo -e "\n=== 6. Autostart (systemd) einrichten ==="
read -p "Soll die Fotobox als automatischer Service beim Systemstart eingerichtet werden? (j/n): " setup_service
if [[ "$setup_service" =~ ^[jJ] ]]; then
    CURRENT_DIR="$(pwd)"
    CURRENT_USER="$(whoami)"
    SERVICE_FILE="/tmp/fotobox.service"
    
    cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Fotobox Backend Service
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/start_fotobox.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    sudo mv "$SERVICE_FILE" /etc/systemd/system/fotobox.service
    sudo systemctl daemon-reload
    sudo systemctl enable fotobox.service
    sudo systemctl start fotobox.service
    echo "Autostart-Service erfolgreich eingerichtet und gestartet!"
else
    echo "Autostart-Einrichtung übersprungen."
fi

echo -e "\n=== FERTIG! ==="
echo "Die Installation ist abgeschlossen."
echo "Du kannst die Fotobox manuell mit './start_fotobox.sh' starten."
