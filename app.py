import socket
import threading
import os
import cv2
import time
from datetime import datetime
from flask import Flask, render_template, jsonify
from ultralytics import YOLO

# --- CONFIGURAÇÕES ---
# Detecta o caminho absoluto da pasta atual (para funcionar no Desktop da Orange Pi)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Caminhos
RAW_FOLDER = os.path.join(BASE_DIR, 'raw_data')
ANNOTATED_FOLDER = os.path.join(BASE_DIR, 'static', 'images')
MODEL_PATH = os.path.join(BASE_DIR, 'models', 'best.pt')

# Rede
TCP_IP = '0.0.0.0' # Ouve em todas as interfaces
TCP_PORT = 12345
WEB_PORT = 5000

# Garante que as pastas existem
os.makedirs(RAW_FOLDER, exist_ok=True)
os.makedirs(ANNOTATED_FOLDER, exist_ok=True)

app = Flask(__name__)

# Variável global para armazenar logs recentes
system_logs = []

# --- CARREGAR MODELO ---
print(" Carregando modelo Anhangá IA...")
try:
    model = YOLO(MODEL_PATH)
    print(" Modelo carregado!")
except Exception as e:
    print(f" Erro: Modelo não encontrado em {MODEL_PATH}. Copie o best.pt para a pasta models!")
    model = None

# --- FUNÇÃO DE IA ---
def process_image(raw_path, filename):
    if model is None: return

    print(f" Processando: {filename}")
    # Inferência
    results = model.predict(raw_path, conf=0.5, save=False)
    
    # Desenhar caixas e salvar na pasta estática (pública para web)
    annotated_frame = results[0].plot()
    save_path = os.path.join(ANNOTATED_FOLDER, filename)
    cv2.imwrite(save_path, annotated_frame)
    
    # Log
    timestamp = datetime.now().strftime("%H:%M:%S")
    detection_count = len(results[0].boxes)
    log = f"[{timestamp}] {filename}: {detection_count} objetos detectados."
    system_logs.insert(0, log) # Adiciona no topo
    print(f" Salvo em: {save_path}")

# --- SERVIDOR TCP (RECEBEDOR) ---
def tcp_server_thread():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind((TCP_IP, TCP_PORT))
        server.listen(5)
        print(f" TCP Receiver ouvindo na porta {TCP_PORT}")
    except Exception as e:
        print(f" Erro ao abrir porta TCP: {e}")
        return

    while True:
        client, addr = server.accept()
        print(f" Conexão de {addr}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{timestamp}.jpg"
        filepath = os.path.join(RAW_FOLDER, filename)
        
        try:
            with open(filepath, "wb") as f:
                while True:
                    data = client.recv(4096)
                    if not data: break
                    f.write(data)
            
            client.close()
            # Assim que salvar, manda para a IA
            process_image(filepath, filename)
            
        except Exception as e:
            print(f"Erro ao receber imagem: {e}")

# --- SERVIDOR WEB (FLASK) ---
@app.route('/')
def index():
    # Lista as imagens processadas (mais recentes primeiro)
    images = sorted(os.listdir(ANNOTATED_FOLDER), reverse=True)
    return render_template('index.html', images=images, logs=system_logs)

@app.route('/api/status')
def status():
    # Rota para atualização automática via AJAX (opcional, mas bom ter)
    return jsonify(logs=system_logs)

if __name__ == '__main__':
    # Inicia o TCP em background
    t = threading.Thread(target=tcp_server_thread)
    t.daemon = True
    t.start()
    
    # Inicia o Site
    print(f" Servidor Web rodando. Acesse: http://192.168.0.1:{WEB_PORT}")
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)