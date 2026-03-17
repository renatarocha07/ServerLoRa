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

# Dimensões Reais
IMG_W, IMG_H = 48, 36

os.makedirs(SAVE_FOLDER, exist_ok=True)
latest_image_name = "aguardando.jpg"

current_frame = np.full((IMG_H, IMG_W), 30, dtype=np.uint8)

def save_frame():
    global latest_image_name
    timestamp = int(time.time())
    filename = f"imagem_{timestamp}.jpg"
    filepath = os.path.join(SAVE_FOLDER, filename)
    
    # Amplia o 48x36 para 640x480 para exibir grande no site
    enlarged_frame = cv2.resize(current_frame, (640, 480), interpolation=cv2.INTER_NEAREST)

    cv2.imwrite(filepath, enlarged_frame)
    latest_image_name = filename
    print(f" [IO] Imagem salva: {filename}")

# --- DESEMPACOTADOR MANUAL 1-BIT ---
def unpack_1bit_manual(payload, expected_pixels):
    output = bytearray()
    for byte in payload:
        for i in range(8):
            if len(output) < expected_pixels:
                bit = (byte >> (7 - i)) & 1
                output.append(255 if bit else 0)
    return bytes(output)

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

                if len(packet_data) >= 7:
                    pkg_type = packet_data[2]
                    internal_mode = packet_data[6]

                    if pkg_type == 0x20: 
                        image_payload = packet_data[7:]
                        
                        try:
                            # Se for o nosso modo RAW (0) e vier com o tamanho exato da nossa mentira (216 bytes)
                            if internal_mode == 0 and len(image_payload) == 216:
                                final_pixel_data = unpack_1bit_manual(image_payload, IMG_W * IMG_H)
                                
                                if final_pixel_data and len(final_pixel_data) == (IMG_W * IMG_H):
                                    global current_frame
                                    current_frame = np.frombuffer(final_pixel_data, dtype=np.uint8).reshape((IMG_H, IMG_W))
                                    print(" [OK] Frame de 48x36 recebido em UM pacote!")
                                    save_frame()
                        except Exception as e:
                            print(f" [ERRO IMG] Falha no processamento: {e}")
                            
        except Exception as e:
            time.sleep(1)

t = threading.Thread(target=tcp_receiver_thread, daemon=True)
t.start()

@app.route('/')
def index(): return render_template('index.html', image_file=latest_image_name)

@app.route('/status')
def status(): return jsonify({'latest_image': latest_image_name})

if __name__ == '__main__':
    save_frame()
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
