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

# Dimensões (Devem bater com o Arduino)
IMG_W, IMG_H = 160, 120
TILE_W, TILE_H = 16, 16
TILES_X = IMG_W // TILE_W 

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

# Canvas inicial (Cinza escuro)
current_frame = np.full((IMG_H, IMG_W), 30, dtype=np.uint8)

def save_current_frame():
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    cv2.imwrite(filepath, current_frame)
    latest_image_name = filename
    print(f" [SAVE] Imagem salva: {filename}")

def tcp_receiver_thread():
    print(f" [TCP] Servidor ouvindo na porta {PORT_TCP}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST_IP, PORT_TCP))
    server_socket.listen(1)

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [CONEXÃO] Gateway conectado: {addr}")
            
            while True:
                # 1. Ler Cabeçalho de Tamanho (2 bytes)
                try:
                    header_bytes = client.recv(2)
                    if not header_bytes: 
                        print(" [TCP] Conexão fechada pelo gateway.")
                        break
                    
                    packet_len = int.from_bytes(header_bytes, 'big')
                except Exception as e:
                    print(f" [ERRO] Falha ao ler header: {e}")
                    break

                # 2. Ler Payload Completo
                packet_data = b''
                while len(packet_data) < packet_len:
                    chunk = client.recv(packet_len - len(packet_data))
                    if not chunk: break
                    packet_data += chunk
                
                # 3. Processar Pacote
                if len(packet_data) >= 4:
                    # Cosmic Header: [NetID, DevID(TileID), Type, Mode]
                    tile_index = packet_data[1]
                    mode = packet_data[3]
                    payload = packet_data[4:]
                    
                    print(f" >> Tile: {tile_index} | Mode: {mode} | Bytes: {len(payload)}")

                    # Calcula Posição
                    col = tile_index % TILES_X
                    row = tile_index // TILES_X
                    px_x = col * TILE_W
                    px_y = row * TILE_H

                    if px_y < IMG_H and px_x < IMG_W:
                        # Lógica de Descompressão
                        try:
                            if mode == 0: # RAW
                                tile = np.frombuffer(payload, dtype=np.uint8).reshape((TILE_H, TILE_W))
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                            else:
                                # Se for comprimido (Mode 1, 2, 3...), desenha um bloco BRANCO
                                # Isso confirma que o dado chegou, mesmo sem decodificar pixels
                                white_block = np.full((TILE_H, TILE_W), 200, dtype=np.uint8)
                                # Desenha borda para ver o grid
                                cv2.rectangle(white_block, (0,0), (15,15), 50, 1)
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = white_block
                        except Exception as e:
                            print(f" [ERRO PROC] Falha ao desenhar tile: {e}")

                        # Salva a imagem a cada 5 tiles recebidos para atualizar o site rápido
                        if tile_index % 5 == 0:
                            save_current_frame()
                else:
                    print(f" [LIXO] Pacote muito pequeno: {len(packet_data)}")

        except Exception as e:
            print(f" [CRITICO] Erro no loop TCP: {e}")
            time.sleep(1)

# Inicia Thread
t = threading.Thread(target=tcp_receiver_thread, daemon=True)
t.start()

# --- FLASK ---
@app.route('/')
def index():
    return render_template('index.html', image_file=latest_image_name)

@app.route('/status')
def status():
    return jsonify({'latest_image': latest_image_name})

if __name__ == '__main__':
    # Salva uma imagem inicial preta para o site não ficar vazio
    save_current_frame() 
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
