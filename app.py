import socket
import threading
import os
import time
import numpy as np
import cv2 
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
HOST_IP = '0.0.0.0'
PORT_TCP = 12345
PORT_WEB = 5000
SAVE_FOLDER = "static/received"

# A imagem final montada tem 160x120, formada por pacotes de 20x20
IMG_W, IMG_H = 160, 120
TILE_W, TILE_H = 20, 20
TILES_X = IMG_W // TILE_W 

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

# Canvas Global agora suporta a imagem inteira de 160x120
current_frame = np.full((IMG_H, IMG_W), 30, dtype=np.uint8)

def save_frame():
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    
    # --- A MÁGICA DA AMPLIAÇÃO ACONTECE AQUI ---
    # Transforma o 160x120 recebido em um quadro de 640x480 para a Web (Proporção 4:3)
    # INTER_NEAREST garante que os pixels fiquem nítidos
    enlarged_frame = cv2.resize(current_frame, (640, 480), interpolation=cv2.INTER_NEAREST)

    cv2.imwrite(filepath, enlarged_frame)
    latest_image_name = filename

# --- FUNÇÃO DE DESCOMPRESSÃO POR DICIONÁRIO ---
def decompress_dict(compressed_payload, max_out=256):
    if len(compressed_payload) < 17:
        return None 

    palette_size = compressed_payload[0]
    palette = compressed_payload[1 : 1 + palette_size]
    compressed_data = compressed_payload[1 + palette_size :]
    
    output = bytearray()
    
    for packed in compressed_data:
        idx1 = (packed >> 4) & 0x0F
        if len(output) < max_out:
            output.append(palette[idx1] if idx1 < palette_size else 0)
            
        idx2 = packed & 0x0F
        if len(output) < max_out:
            output.append(palette[idx2] if idx2 < palette_size else 0)
            
    return bytes(output)

# --- RECEPTOR TCP ---
def recvall(sock, n):
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet: return None
            data += packet
        except Exception as e:
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
            
            while True:
                header = recvall(client, 2)
                if not header: break
                
                packet_len = int.from_bytes(header, 'big')
                packet_data = recvall(client, packet_len)
                if not packet_data: break

                # Decodifica a estrutura
                if len(packet_data) >= 7:
                    tile_index = packet_data[1]  # O XIAO manda o ID do Tile no DevID (Byte 1)
                    pkg_type = packet_data[2]
                    internal_mode = packet_data[6]

                    if pkg_type == 0x20: # Se for pacote de imagem
                        image_payload = packet_data[7:]
                        
                        try:
                            # Verifica se o modo é o Dicionário (4)
                            if internal_mode == 4:
                                # Tenta descomprimir APENAS os 400 pixels do Tile (20x20)
                                final_pixel_data = decompress_dict(image_payload, TILE_W * TILE_H)
                                
                                if final_pixel_data and len(final_pixel_data) == (TILE_W * TILE_H):
                                    # Transforma os bytes em uma matriz 20x20
                                    tile = np.frombuffer(final_pixel_data, dtype=np.uint8).reshape((TILE_H, TILE_W))
                                    
                                    # Calcula a posição exata desse bloco no Canvas 160x120
                                    col = tile_index % TILES_X
                                    row = tile_index // TILES_X
                                    px_x = col * TILE_W
                                    px_y = row * TILE_H
                                    
                                    # Insere o Tile no Canvas Global se estiver dentro dos limites
                                    if px_y < IMG_H and px_x < IMG_W:
                                        global current_frame
                                        current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                                        print(f" [OK] Tile {tile_index}/47 montado.")
                                        
                                        # Atualiza a página web a cada pedacinho recebido
                                        save_frame()
                                else:
                                    print(f" [ERRO] Tamanho de descompressão inválido no Tile {tile_index}.")
                        except Exception as e:
                            print(f" [ERRO IMG] Falha no processamento: {e}")
                            
        except Exception as e:
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
