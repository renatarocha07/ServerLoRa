import socket
import threading
import os
import time
import struct
import numpy as np
import cv2 
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
HOST_IP = '0.0.0.0'
PORT_TCP = 12345
PORT_WEB = 5000
SAVE_FOLDER = "static/received"

# Dimensões da Imagem (Devem bater com o Xiao)
IMG_W, IMG_H = 160, 120
TILE_W, TILE_H = 16, 16
TILES_X = IMG_W // TILE_W 

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

# Canvas Global
current_frame = np.zeros((IMG_H, IMG_W), dtype=np.uint8)

def save_image_from_buffer():
    """Salva o estado atual do buffer como arquivo"""
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    
    # Salva o frame atual
    cv2.imwrite(filepath, current_frame)
    latest_image_name = filename
    print(f" [IO] Imagem salva com sucesso: {filename}")

def tcp_receiver_thread():
    print(f" [TCP] Servidor ouvindo na porta {PORT_TCP}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST_IP, PORT_TCP))
    server_socket.listen(1)

    # Estado da Montagem
    last_tile_index = -1
    tiles_received_count = 0

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [CONEXÃO] Gateway conectado: {addr}")
            
            while True:
                # 1. Lê tamanho do pacote (2 bytes)
                header = client.recv(2)
                if not header: break
                packet_len = int.from_bytes(header, 'big')

                # 2. Lê payload exato
                data = b''
                while len(data) < packet_len:
                    chunk = client.recv(packet_len - len(data))
                    if not chunk: break
                    data += chunk
                
                if len(data) != packet_len: break

                # 3. Processa Protocolo Cosmic
                if len(data) >= 4:
                    # Header: [NetID, DevID(TileIndex), Type, Mode]
                    tile_index = data[1]
                    mode = data[3]
                    payload = data[4:]

                    # --- LÓGICA INTELIGENTE DE REINÍCIO ---
                    # Se o índice atual for MENOR que o anterior (ex: estava em 69 e veio 0),
                    # significa que o Xiao começou uma nova foto.
                    if tile_index < last_tile_index:
                        print(f" [RESET] Nova sequência detectada (Tile {last_tile_index} -> {tile_index}). Salvando anterior...")
                        if tiles_received_count > 5: # Só salva se tiver recebido algo útil
                            save_image_from_buffer()
                        
                        # Limpa o canvas para a nova foto
                        current_frame.fill(0) 
                        tiles_received_count = 0

                    last_tile_index = tile_index
                    tiles_received_count += 1

                    # --- MONTAGEM DO TILE ---
                    col = tile_index % TILES_X
                    row = tile_index // TILES_X
                    px_x = col * TILE_W
                    px_y = row * TILE_H

                    if px_y < IMG_H and px_x < IMG_W:
                        try:
                            # Se for RAW (Mode 0) ou se você mudou o Xiao para COMPRESS_NONE
                            if mode == 0 or len(payload) == (TILE_W * TILE_H):
                                tile = np.frombuffer(payload, dtype=np.uint8).reshape((TILE_H, TILE_W))
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                            else:
                                # Fallback visual se vier comprimido
                                block = np.full((TILE_H, TILE_W), 255, dtype=np.uint8)
                                cv2.rectangle(block, (0,0), (15,15), 0, 1)
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = block
                        except Exception as e:
                            print(f"Erro ao desenhar tile {tile_index}: {e}")

                    print(f" >> RX Tile {tile_index} (Total: {tiles_received_count})")

        except Exception as e:
            print(f" [ERRO] {e}")
            time.sleep(1)

# Inicia
t = threading.Thread(target=tcp_receiver_thread, daemon=True)
t.start()

# Flask
@app.route('/')
def index(): return render_template('index.html', image_file=latest_image_name)

@app.route('/status')
def status(): return jsonify({'latest_image': latest_image_name})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
