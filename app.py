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

# Dimensões e Tiles
IMG_W, IMG_H = 160, 120
TILE_W, TILE_H = 16, 16
TILES_X = IMG_W // TILE_W 

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

# Canvas Global (Fundo escuro inicial)
current_frame = np.full((IMG_H, IMG_W), 30, dtype=np.uint8)

def save_frame():
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    
    # Salva a imagem para o front-end ou para ser consumida pela IA
    cv2.imwrite(filepath, current_frame)
    latest_image_name = filename
    print(f" [IO] Imagem renderizada e salva: {filename}")

# --- DESCOMPRESSÃO POR DICIONÁRIO ---
def decompress_dict(compressed_payload, max_out=256):
    """ Descomprime o payload baseado em dicionário (4 bits por pixel) """
    if len(compressed_payload) < 17:
        print(" [ERRO] Payload pequeno demais para conter a paleta.")
        return None 

    palette_size = compressed_payload[0]
    palette = compressed_payload[1 : 1 + palette_size]
    compressed_data = compressed_payload[1 + palette_size :]
    
    output = bytearray()
    
    for packed in compressed_data:
        # Primeiro pixel (nibble alto)
        idx1 = (packed >> 4) & 0x0F
        if len(output) < max_out:
            output.append(palette[idx1] if idx1 < palette_size else 0)
            
        # Segundo pixel (nibble baixo)
        idx2 = packed & 0x0F
        if len(output) < max_out:
            output.append(palette[idx2] if idx2 < palette_size else 0)
            
    return bytes(output)

# --- RECEPTOR TCP ROBUSTO ---
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
    print(f" [TCP] Ouvindo conexões de gateway na porta {PORT_TCP}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST_IP, PORT_TCP))
    server_socket.listen(5)

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [TCP] Pacote chegando de: {addr}")
            
            # 1. Lê exatamente os 2 bytes do cabeçalho injetado pelo ESP
            header = recvall(client, 2)
            if not header:
                client.close()
                continue
                
            packet_len = int.from_bytes(header, 'big')
            
            # 2. Lê todo o payload original do protocolo Cosmic
            packet_data = recvall(client, packet_len)
            client.close() # Pode fechar logo após receber tudo

            if not packet_data: continue

            # 3. Decodifica o protocolo Cosmic
            if len(packet_data) >= 4:
                net_id = packet_data[0]
                tile_index = packet_data[1] # DevID usado como índice de tile
                pkg_type = packet_data[2]
                mode = packet_data[3]
                
                # Pula os 4 bytes de cabeçalho do Cosmic para pegar a imagem
                image_payload = packet_data[4:]
                
                print(f" >> [Processando] Tile {tile_index} | Payload Comprimido: {len(image_payload)} bytes")

                col = tile_index % TILES_X
                row = tile_index // TILES_X
                px_x = col * TILE_W
                px_y = row * TILE_H

                if px_y < IMG_H and px_x < IMG_W:
                    try:
                        # Descomprime os dados usando o dicionário
                        final_pixel_data = decompress_dict(image_payload, TILE_W * TILE_H)

                        if final_pixel_data and len(final_pixel_data) == (TILE_W * TILE_H):
                            # Transforma os bytes puros de volta numa matriz 2D (16x16)
                            tile = np.frombuffer(final_pixel_data, dtype=np.uint8).reshape((TILE_H, TILE_W))
                            current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile
                            print(f" >> Tile {tile_index} alocado no Canvas com sucesso.")
                        else:
                            print(f" [ERRO] Descompressão inválida para o Tile {tile_index}")
                    except Exception as e:
                        print(f" [ERRO IMG] Falha ao processar matriz: {e}")

                    # Atualiza a imagem no disco assim que o tile for processado
                    save_frame()

        except Exception as e:
            print(f" [ERRO FATAL NO LOOP TCP] {e}")
            time.sleep(1)

# --- ROTAS DO FLASK ---
@app.route('/')
def index(): 
    return render_template('index.html', image_file=latest_image_name)

@app.route('/status')
def status(): 
    return jsonify({'latest_image': latest_image_name})

if __name__ == '__main__':
    # Salva uma imagem preta inicial para o app não quebrar ao abrir
    save_frame()
    
    # Inicia a Thread do servidor TCP em background
    t = threading.Thread(target=tcp_receiver_thread, daemon=True)
    t.start()
    
    # Roda a interface web
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
