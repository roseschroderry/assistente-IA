import os
import requests
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from .app_paths import db_path

load_dotenv()

class HybridDatabase:
    def __init__(self):
        # Configuração Cloud (Supabase)
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_KEY")
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        # Configuração Local (SQLite)
        self.db_path = db_path()
        self._init_local_db()

    def _init_local_db(self):
        """Inicializa o banco de dados local se não existir."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user_message TEXT,
                assistant_message TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT,
                deadline TEXT,
                status TEXT DEFAULT 'pendente'
            )
        ''')
        conn.commit()
        conn.close()

    def save_chat(self, user_msg, assistant_msg):
        """Salva a conversa localmente e tenta na nuvem."""
        timestamp = datetime.now().isoformat()
        
        # Salva Local
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO chats (timestamp, user_message, assistant_message) VALUES (?, ?, ?)',
                           (timestamp, user_msg, assistant_msg))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Erro ao salvar local: {e}")

        # Salva Cloud (se configurado)
        if not self.url or not self.key: return "Salvo localmente."
        
        endpoint = f"{self.url}/rest/v1/chats"
        data = {
            "user_message": user_msg,
            "assistant_message": assistant_msg
        }
        try:
            response = requests.post(endpoint, headers=self.headers, json=data)
            return "Salvo local e na nuvem." if response.status_code in [200, 201] else f"Salvo local (Erro Cloud: {response.status_code})"
        except:
            return "Salvo localmente (Cloud offline)."

    def get_history(self, limit=10):
        """Recupera o histórico recente do banco local."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT user_message, assistant_message FROM chats ORDER BY id DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            conn.close()
            history = []
            for user_message, assistant_message in reversed(rows):
                history.append({"role": "user", "content": user_message})
                history.append({"role": "assistant", "content": assistant_message})
            return history
        except:
            return []

    def learn_fact(self, key, value):
        """Armazena um fato aprendido sobre o usuário."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO knowledge (key, value) VALUES (?, ?)', (key, value))
            conn.commit()
            conn.close()
            return f"Aprendi que seu {key} é {value}."
        except Exception as e:
            return f"Erro ao aprender: {e}"

    def recall_facts(self):
        """Recupera todos os fatos aprendidos."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM knowledge')
            rows = cursor.fetchall()
            conn.close()
            return "\n".join([f"{r[0]}: {r[1]}" for r in rows])
        except:
            return ""

    def add_task(self, task, deadline=None):
        """Adiciona uma tarefa à agenda."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO tasks (task, deadline) VALUES (?, ?)', (task, deadline))
            conn.commit()
            conn.close()
            return f"Tarefa '{task}' adicionada para {deadline or 'hoje'}."
        except Exception as e:
            return f"Erro ao adicionar tarefa: {e}"

    def get_tasks(self):
        """Lista todas as tarefas pendentes."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, task, deadline FROM tasks WHERE status = 'pendente'")
            rows = cursor.fetchall()
            conn.close()
            if not rows: return "Você não tem tarefas pendentes."
            return "\n".join([f"[{r[0]}] {r[1]} - Prazo: {r[2]}" for r in rows])
        except Exception as e:
            return f"Erro ao listar tarefas: {e}"

    def complete_task(self, task_id):
        """Marca uma tarefa como concluída."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET status = 'concluída' WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()
            return f"Tarefa {task_id} marcada como concluída!"
        except Exception as e:
            return f"Erro ao concluir tarefa: {e}"

# Singleton
db = HybridDatabase()
