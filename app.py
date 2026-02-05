import socket
import threading
import os
import time
import struct
import numpy as np
import cv2 # OpenCV para manipular a imagem
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
HOST_IP = '0.0.0.0'
PORT_TCP = 12345        # Porta que recebe do Heltec
PORT_WEB = 5000         # Porta do site
SAVE_FOLDER = "static/received"

# Configurações da Imagem (Devem bater com o Arduino)
IMG_W = 160
IMG_H = 120
TILE_W = 16
TILE_H = 16
TILES_X = IMG_W // TILE_W # 10 colunas

os.makedirs(SAVE_FOLDER, exist_ok=True)

# Variáveis Globais
latest_image_name = None
# Cria um "Canvas" preto (matriz de zeros) onde vamos colar as peças
# uint8 = 0 a 255 (Escala de cinza)
current_frame = np.zeros((IMG_H, IMG_W), dtype=np.uint8)

def decompress_payload(mode, payload, width, height):
    """
    Tenta descomprimir o payload vindo do Arduino.
    Por enquanto, suporta RAW (sem compressão).
    Se usar Block4 no Arduino, precisaria portar a lógica C para Python aqui.
    """
    try:
        # Modo 0: Sem compressão (RAW)
        if mode == 0:
            # Converte bytes para array numpy
            arr = np.frombuffer(payload, dtype=np.uint8)
            return arr.reshape((height, width))
        
        # Modo 2 ou 3 (Block4/RLE): Implementação simplificada (Fallback)
        # Se você enviar comprimido do Arduino e não tiver o descompressor exato aqui,
        # vai virar ruído. Sugiro usar COMPRESS_NONE no Arduino para testar primeiro.
        else:
            # Retorna um bloco cinza indicando "Compressão não suportada ainda"
            return np.full((height, width), 127, dtype=np.uint8)
            
    except Exception as e:
        print(f"Erro descompressão: {e}")
        return np.zeros((height, width), dtype=np.uint8)

def save_current_frame():
    """Salva o estado atual do canvas como JPG"""
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    
    # Salva usando OpenCV
    cv2.imwrite(filepath, current_frame)
    latest_image_name = filename
    print(f" [IMG] Frame salvo: {filename}")

def tcp_receiver_thread():
    print(f" [TCP] Aguardando conexão na porta {PORT_TCP}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST_IP, PORT_TCP))
    server_socket.listen(1)

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [TCP] Gateway Conectado: {addr}")
            
            while True:
                # 1. Ler o Cabeçalho de Tamanho (2 bytes) que o Gateway manda
                # Isso diz o tamanho total do pacote LoRa que veio a seguir
                size_header = client.recv(2)
                if not size_header: break 
                
                packet_len = int.from_bytes(size_header, 'big')
                
                # 2. Ler o pacote exato
                packet_data = b''
                while len(packet_data) < packet_len:
                    chunk = client.recv(packet_len - len(packet_data))
                    if not chunk: break
                    packet_data += chunk
                
                if len(packet_data) != packet_len:
                    break

                # 3. Decodificar Protocolo COSMIC (Igual ao CLoRa)
                # Header Cosmic: [NetID(1), DevID(1), Type(1), Mode(1)] ... [Payload]
                if len(packet_data) > 4:
                    net_id = packet_data[0]
                    tile_index = packet_data[1] # DevID foi usado como índice do bloco
                    pkg_type = packet_data[2]
                    mode = packet_data[3]
                    payload = packet_data[4:]

                    # Verifica se é pacote de imagem (0x20 = 32 decimal)
                    if pkg_type == 32: # PKG_TYPE_IMAGE
                        
                        # Calcula posição X, Y baseado no índice
                        # Ex: Índice 0 -> x=0, y=0. Índice 10 -> x=0, y=16 (se tiver 10 colunas)
                        col = tile_index % TILES_X
                        row = tile_index // TILES_X
                        
                        px_x = col * TILE_W
                        px_y = row * TILE_H
                        
                        # Descomprime e cola no Canvas Principal
                        if px_y < IMG_H and px_x < IMG_W:
                            tile_img = decompress_payload(mode, payload, TILE_W, TILE_H)
                            
                            # Cola o pedaço na imagem grande
                            try:
                                current_frame[px_y:px_y+TILE_H, px_x:px_x+TILE_W] = tile_img
                            except ValueError:
                                pass # Ignora se vazar a borda

                            print(f"Rx Tile {tile_index} (Modo {mode}) -> Pos {px_x},{px_y}")

                            # Lógica para salvar:
                            # Se recebermos o último tile (aprox. índice 70-74 para 160x120), salvamos
                            # Ou salvamos a cada N tiles para ver o progresso
                            max_tiles = (IMG_W // TILE_W) * (IMG_H // TILE_H)
                            if tile_index >= max_tiles - 1 or tile_index % 10 == 0:
                                save_current_frame()

        except Exception as e:
            print(f" [TCP] Erro na conexão: {e}")
            time.sleep(1)
        finally:
            try:
                client.close()
            except:
                pass

# Inicia thread
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
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
