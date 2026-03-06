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
    
    # --- REDIMENSIONAMENTO PARA VISUALIZAÇÃO ---
    # Multiplica o tamanho por 4 (vai de 160x120 para 640x480)
    scale_factor = 4
    new_w = IMG_W * scale_factor
    new_h = IMG_H * scale_factor
    
    # cv2.INTER_NEAREST garante que a imagem esticada não fique embaçada (borrada)
    enlarged_frame = cv2.resize(current_frame, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    # Salva a imagem ampliada para a página web
    cv2.imwrite(filepath, enlarged_frame)
    latest_image_name = filename
    print(f" [IO] Imagem ampliada para {new_w}x{new_h} e salva: {filename}")

# --- FUNÇÃO DE DESCOMPRESSÃO POR DICIONÁRIO ---
def decompress_dict(compressed_payload, max_out=256):
    """
    Descomprime o payload baseado na paleta de 16 cores (4 bits por pixel).
    Espera receber a partir do byte de tamanho da paleta (byte 7 do pacote total).
    """
    if len(compressed_payload) < 17:
        print(f" [ERRO] Payload pequeno demais: {len(compressed_payload)} bytes.")
        return None 

    palette_size = compressed_payload[0]
    # Extrai a paleta de cores
    palette = compressed_payload[1 : 1 + palette_size]
    # Extrai os dados agrupados
    compressed_data = compressed_payload[1 + palette_size :]
    
    output = bytearray()
    
    for packed in compressed_data:
        # Extrai o primeiro pixel (nibble alto: bits 4-7)
        idx1 = (packed >> 4) & 0x0F
        if len(output) < max_out:
            output.append(palette[idx1] if idx1 < palette_size else 0)
            
        # Extrai o segundo pixel (nibble baixo: bits 0-3)
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
            # print(f" [CONEXÃO] Gateway conectado: {addr}")
            
            while True:
                # 1. Lê os 2 bytes de tamanho injetados pelo ESP TCP
                header = recvall(client, 2)
                if not header: 
                    break
                
                packet_len = int.from_bytes(header, 'big')

                # 2. Lê todo o pacote LoRa (Cosmic)
                packet_data = recvall(client, packet_len)
                if not packet_data: 
                    break

                # 3. Decodifica a estrutura combinada (Cosmic + img_compress)
                # Precisamos de pelo menos 7 bytes (4 Cosmic + 3 img_compress)
                if len(packet_data) >= 7:
                    # Cabeçalho Cosmic
                    net_id = packet_data[0]
                    tile_index = packet_data[1]  # DevID é usado como Tile
                    pkg_type = packet_data[2]
                    cosmic_mode = packet_data[3]
                    
                    # Cabeçalho img_compress
                    img_width = packet_data[4]
                    img_height = packet_data[5]
                    internal_mode = packet_data[6]

                    # Apenas processa se for imagem (0x20)
                    if pkg_type == 0x20:
                        # Extrai a imagem comprimida ignorando os 7 bytes de cabeçalho
                        image_payload = packet_data[7:]
                        
                        # print(f" >> Tile {tile_index} | Payload Imagem: {len(image_payload)} bytes | Modo: {internal_mode}")

                        # Monta no Canvas
                        col = tile_index % TILES_X
                        row = tile_index // TILES_X
                        px_x = col * TILE_W
                        px_y = row * TILE_H

                        if px_y < IMG_H and px_x < IMG_W:
                            try:
                                final_pixel_data = None
                                
                                # Verifica se o modo é o Dicionário (4)
                                if internal_mode == 4:
                                    final_pixel_data = decompress_dict(image_payload, TILE_W * TILE_H)
                                else:
                                    print(f" [AVISO] Recebido modo {internal_mode} não suportado neste script.")

                                # Se a descompressão retornou exatamente 256 pixels
                                if final_pixel_data and len(final_pixel_data) == (TILE_W * TILE_H):
                                    tile = np.frombuffer(final_pixel_data, dtype=np.uint8).reshape((TILE_H, TILE_W))
                                    current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                                    print(f" [OK] Tile {tile_index} montado com sucesso.")
                                else:
                                    print(f" [ERRO] Falha na descompressão do Tile {tile_index}")
                                    # Desenha bloco de erro
                                    block = np.full((TILE_H, TILE_W), 128, dtype=np.uint8)
                                    cv2.rectangle(block, (0,0), (15,15), 255, 1)
                                    current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = block
                            except Exception as e:
                                print(f" [ERRO IMG] Falha ao desenhar: {e}")

                            # Salva a imagem para o Flask atualizar
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
