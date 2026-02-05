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

# Dimensões (Devem ser iguais ao Xiao)
IMG_W, IMG_H = 160, 120
TILE_W, TILE_H = 16, 16
TILES_X = IMG_W // TILE_W 

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

# Canvas Global
current_frame = np.full((IMG_H, IMG_W), 30, dtype=np.uint8)

def save_frame():
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    cv2.imwrite(filepath, current_frame)
    latest_image_name = filename
    print(f" [IO] Imagem salva: {filename}")

# --- A MÁGICA ESTÁ AQUI: recvall ---
# Essa função fica num loop infinito até receber EXATAMENTE 'n' bytes
def recvall(sock, n):
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet: return None
            data += packet
        except Exception as e:
            print(f"Erro recv: {e}")
            return None
    return data

def tcp_receiver_thread():
    print(f" [TCP] Ouvindo na porta {PORT_TCP}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST_IP, PORT_TCP))
    server_socket.listen(1)

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [CONEXÃO] Gateway conectado: {addr}")
            
            while True:
                # 1. Tenta ler EXATAMENTE 2 bytes (Cabeçalho de tamanho)
                header = recvall(client, 2)
                if not header: 
                    print(" [TCP] Conexão perdida (Header).")
                    break
                
                # Converte os 2 bytes para um número inteiro (Tamanho do pacote)
                packet_len = int.from_bytes(header, 'big')
                # print(f" [DEBUG] Esperando pacote de {packet_len} bytes...")

                # 2. Agora obriga o Python a ficar lendo até chegar o pacote TODO
                packet_data = recvall(client, packet_len)
                if not packet_data: 
                    print(" [TCP] Conexão perdida (Payload).")
                    break

                # 3. Se chegou aqui, temos o pacote completo!
                if len(packet_data) >= 4:
                    # Decodifica protocolo Cosmic
                    tile_index = packet_data[1]
                    mode = packet_data[3]
                    pixel_data = packet_data[4:]

                    print(f" >> Tile {tile_index} | Bytes Recebidos: {len(pixel_data)} (Esperado: {TILE_W*TILE_H})")

                    # Monta no Canvas
                    col = tile_index % TILES_X
                    row = tile_index // TILES_X
                    px_x = col * TILE_W
                    px_y = row * TILE_H

                    if px_y < IMG_H and px_x < IMG_W:
                        try:
                            # Se for RAW (Mode 0) ou se o tamanho bater com 256 bytes (16x16)
                            if len(pixel_data) == (TILE_W * TILE_H):
                                tile = np.frombuffer(pixel_data, dtype=np.uint8).reshape((TILE_H, TILE_W))
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                            else:
                                # Se vier comprimido ou tamanho estranho, desenha bloco cinza
                                block = np.full((TILE_H, TILE_W), 128, dtype=np.uint8)
                                cv2.rectangle(block, (0,0), (15,15), 255, 1)
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = block
                        except Exception as e:
                            print(f" [ERRO IMG] Falha ao desenhar: {e}")

                        # Salva a cada 10 blocos para atualizar o site
                        if tile_index % 10 == 0:
                            save_frame()

        except Exception as e:
            print(f" [ERRO FATAL] {e}")
            time.sleep(1)

# Inicia Thread
t = threading.Thread(target=tcp_receiver_thread, daemon=True)
t.start()

# Flask
@app.route('/')
def index(): return render_template('index.html', image_file=latest_image_name)

@app.route('/status')
def status(): return jsonify({'latest_image': latest_image_name})

if __name__ == '__main__':
    save_frame()
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
