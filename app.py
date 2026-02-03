from flask import Flask, render_template, jsonify
import socket
import threading
import os
import time

app = Flask(__name__)

# --- CONFIGURAÇÕES ---
HOST_IP = '0.0.0.0'
PORT_TCP_LORA = 12345   # Porta onde o ESP32 conecta
PORT_WEB_SITE = 5000    # Porta onde VOCÊ conecta (Navegador)
SAVE_DIR = "static/received"

# Garante que a pasta existe
os.makedirs(SAVE_DIR, exist_ok=True)

# Variável global para saber qual é a foto mais recente
latest_image_file = None

# --- FUNÇÃO 1: RECEBEDOR LORA (Roda em segundo plano) ---
def lora_receiver_thread():
    global latest_image_file
    
    # Cria o Socket TCP
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST_IP, PORT_TCP_LORA))
        server_socket.listen(1)
        print(f" [TCP] Aguardando ESP32 na porta {PORT_TCP_LORA}...")
    except Exception as e:
        print(f" Erro ao abrir porta TCP: {e}")
        return

    while True:
        try:
            client_socket, addr = server_socket.accept()
            print(f" [TCP] Conexão recebida de: {addr}")

            # Define o nome do arquivo (temporário, pois ainda é bruto)
            timestamp = int(time.time())
            filename_bin = f"img_{timestamp}.bin"     # Arquivo bruto (com cabeçalhos)
            filename_jpg = f"img_{timestamp}.jpg"     # Arquivo final (imagem)
            filepath_bin = os.path.join(SAVE_DIR, filename_bin)
            filepath_jpg = os.path.join(SAVE_DIR, filename_jpg)

            # Timeout: Se o ESP32 parar de mandar dados por 4s, fecha o arquivo
            client_socket.settimeout(4.0)

            # 1. Recebe os dados e salva no arquivo .bin
            with open(filepath_bin, 'wb') as f:
                print(" Recebendo dados...")
                while True:
                    try:
                        data = client_socket.recv(4096)
                        if not data: break
                        f.write(data)
                    except socket.timeout:
                        print(" Fim da transmissão (Timeout).")
                        break
                    except Exception as e:
                        print(f"Erro na conexão: {e}")
                        break
            
            client_socket.close()
            print(f" Arquivo salvo: {filename_bin}")

            # --- AQUI ENTRA A SUA LÓGICA DE DESCOMPRESSÃO ---
            # Como você disse que a descompressão é no servidor:
            # Você precisa pegar o 'filepath_bin', tirar o cabeçalho Cosmic
            # e salvar como 'filepath_jpg'.
            
            # POR ENQUANTO (Gambiarra para teste):
            # Vamos assumir que o arquivo JÁ É um JPG válido (se não tiver cabeçalho complexo)
            # Apenas renomeamos para o site conseguir ler.
            if os.path.exists(filepath_bin):
                os.rename(filepath_bin, filepath_jpg)
                latest_image_file = filename_jpg # Atualiza o site
                print(f" Imagem disponível para visualização: {filename_jpg}")

        except Exception as e:
            print(f"Erro no loop do servidor: {e}")
            time.sleep(1)

# --- FUNÇÃO 2: O SITE (FLASK) ---

# Inicia o recebedor TCP em uma thread separada (paralela)
thread = threading.Thread(target=lora_receiver_thread, daemon=True)
thread.start()

@app.route('/')
def index():
    # Mostra a página com a última imagem
    return render_template('index.html', image_file=latest_image_file)

@app.route('/status')
def status():
    # O JavaScript chama isso a cada 2s para ver se mudou a foto
    return jsonify({'latest_image': latest_image_file})

if __name__ == '__main__':
    print(f"[WEB] Site rodando em http://{HOST_IP}:{PORT_WEB_SITE}")
    app.run(host=HOST_IP, port=PORT_WEB_SITE, debug=False)
