import sys
import os
import threading
import uvicorn
import time
import multiprocessing
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtCore import QUrl, QTimer
import requests

# Ajuste de caminho para encontrar o backend
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

if base_path not in sys.path:
    sys.path.insert(0, base_path)

from backend.app_paths import log_path

def run_server():
    """Executa o servidor FastAPI de forma ultra-robusta."""
    try:
        import uvicorn
        import io
        from backend.main import app
        
        # Redireciona stdout e stderr para evitar erro de 'NoneType' no modo windowed
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

        # Log de início
        with open(log_path("log_inicializacao.txt"), "a", encoding="utf-8") as f:
            f.write(f"Iniciando servidor em 127.0.0.1:8008 as {time.ctime()}\n")

        # Configuração ultra-limpa para evitar erro de logging no executável
        uvicorn.run(
            app, 
            host="127.0.0.1", 
            port=8008, 
            log_config=None, # DESATIVA o sistema de log padrão do uvicorn
            access_log=False,
            reload=False
        )
    except Exception as e:
        import traceback
        with open(log_path("erro_servidor.txt"), "w", encoding="utf-8") as f:
            f.write(f"Erro fatal no servidor: {str(e)}\n")
            f.write(traceback.format_exc())

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Assistente Elite v1.0")
        self.setGeometry(100, 100, 1280, 720)

        self.browser = QWebEngineView()
        
        # Configuracoes de seguranca
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, False)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        
        self.setCentralWidget(self.browser)
        
        # Conecta o sinal de falha de carregamento
        self.browser.loadFinished.connect(self.on_load_finished)
        
        # Injeta a porta antes mesmo de carregar (fallback)
        self.browser.page().runJavaScript("window.SERVER_PORT = 8008;")
        
        # Aguarda 3 segundos antes do primeiro carregamento para dar tempo ao servidor
        QTimer.singleShot(3000, self.load_dashboard)

    def load_dashboard(self):
        print("Tentando carregar dashboard...")
        # Usa o endereço 127.0.0.1 em vez de localhost para evitar atrasos de DNS
        self.browser.setUrl(QUrl("http://127.0.0.1:8008/"))

    def on_load_finished(self, ok):
        if not ok:
            # Se não carregou (servidor offline), tenta de novo em 3s
            print("Servidor ainda offline, tentando reconectar em 3s...")
            QTimer.singleShot(3000, self.load_dashboard)
        else:
            print("Dashboard carregado com sucesso!")
            # Injeta a porta correta no JavaScript do navegador
            self.browser.page().runJavaScript("window.SERVER_PORT = 8008;")

if __name__ == "__main__":
    # ESSENCIAL para PyInstaller no Windows
    multiprocessing.freeze_support()

    # Inicia o servidor em uma thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.name = "FastAPIServer"
    server_thread.start()

    # Pequena pausa inicial
    time.sleep(1)

    # Inicia a interface
    qt_app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # Ativa detecção de voz 'Elite' em background
    try:
        from backend.voice_engine import voice
        def wake_word_callback(command):
            # Envia o comando para o próprio servidor
            try:
                requests.post("http://127.0.0.1:8008/chat", json={"message": command})
            except:
                pass
        
        voice.start_wake_word_detection(wake_word_callback)
    except Exception as e:
        print(f"Erro ao iniciar Wake Word: {e}")
    
    sys.exit(qt_app.exec_())
