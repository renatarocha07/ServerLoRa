import socket

HOST = '0.0.0.0'
PORT = 12345

print(f"--- INICIANDO SNIFFER TCP NA PORTA {PORT} ---")

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((HOST, PORT))
s.listen(1)

conn, addr = s.accept()
print(f"Conectado por: {addr}")

try:
    while True:
        # Tenta ler qualquer coisa que chegar
        data = conn.recv(1024)
        if not data:
            break
        
        # Mostra o tamanho e os primeiros bytes em Hexadecimal
        hex_data = data.hex(' ')
        print(f"Recebido {len(data)} bytes: {hex_data[:50]}...")

except KeyboardInterrupt:
    print("Parando...")
finally:
    conn.close()
    s.close()
