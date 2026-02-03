import socket
import threading
import os
import time
from flask import Flask, render_template, jsonify, url_for

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
HOST_IP = '0.0.0.0'
PORT_TCP = 12345        # Porta de escuta do ESP32
PORT_WEB = 5000         # Porta do site
SAVE_FOLDER = "static/received"

# Garante que a pasta existe
os.makedirs(SAVE_FOLDER, exist_ok=True)

# Variável global para armazenar o nome da última imagem válida
latest_image = None

def tcp_receiver_thread():
    """
    Função que roda em paralelo (background) para receber os dados do ESP32.
    Ela reconstrói a imagem juntando os pacotes.
    """
    global latest_image
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST_IP, PORT_TCP))
        server_socket.listen(1)
        print(f" [TCP] Aguardando imagens na porta {PORT_TCP}...")
    except Exception as e:
        print(f" Erro ao abrir socket: {e}")
        return

    while True:
        try:
            client, addr = server_socket.accept()
            print(f" [RX] Conectado: {addr}")
            
            # Gera nome do arquivo baseado na hora
            timestamp = int(time.time())
            filename_temp = f"temp_{timestamp}.bin"
            filepath_temp = os.path.join(SAVE_FOLDER, filename_temp)
            
            # Timeout: Se ficar 4 segundos sem chegar dados, considera que a foto acabou
            client.settimeout(4.0)
            
            total_bytes = 0
            
            # --- FASE 1: RECONSTRUÇÃO (Juntar os pedaços) ---
            with open(filepath_temp, 'wb') as f:
                while True:
                    try:
                        # Recebe pacotes de até 4KB por vez
                        data = client.recv(4096)
                        if not data:
                            break # Conexão fechada pelo cliente
                        f.write(data)
                        total_bytes += len(data)
                    except socket.timeout:
                        print(" Fim da transmissão (Timeout). Imagem completa.")
                        break
                    except Exception as e:
                        print(f" Erro durante recebimento: {e}")
                        break
            
            client.close()
            
            # --- FASE 2: FINALIZAÇÃO ---
            if total_bytes > 0:
                # Renomeia de .bin para .jpg para o navegador entender
                filename_final = f"imagem_{timestamp}.jpg"
                filepath_final = os.path.join(SAVE_FOLDER, filename_final)
                
                # Se o arquivo anterior existir, remove o temporário
                if os.path.exists(filepath_temp):
                    os.rename(filepath_temp, filepath_final)
                
                print(f" Imagem salva: {filename_final} ({total_bytes} bytes)")
                
                # Atualiza a variável para o site mostrar a nova foto
                latest_image = filename_final
            else:
                print(" Arquivo vazio recebido. Descartando.")
                if os.path.exists(filepath_temp):
                    os.remove(filepath_temp)

        except Exception as e:
            print(f" Erro no loop principal: {e}")
            time.sleep(1)

# Inicia a thread do receptor TCP
thread = threading.Thread(target=tcp_receiver_thread, daemon=True)
thread.start()

# --- ROTAS DO SITE ---

@app.route('/')
def index():
    # Passa o nome da imagem para o HTML
    return render_template('index.html', image_file=latest_image)

@app.route('/status')
def check_status():
    # Rota usada pelo JavaScript para verificar se chegou imagem nova
    return jsonify({'latest_image': latest_image})

if __name__ == '__main__':
    print(" Servidor Web Iniciado!")
    app.run(host='0.0.0.0', port=PORT_WEB, debug=False)
