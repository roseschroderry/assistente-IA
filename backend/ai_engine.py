import json
import os
import re
import shlex
import sys
import time
import ast

from dotenv import load_dotenv
from openai import OpenAI

from .database import db
from .tools import available_tools, recall_user_preferences, tool_map, _resolve_known_path
from .voice_engine import voice
from .app_paths import log_path

load_dotenv()

if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(sys.executable)
    load_dotenv(os.path.join(exe_dir, ".env"))

MAX_HISTORY_MESSAGES = int(os.getenv("AI_HISTORY_MESSAGES", "6"))
MAX_COMPLETION_TOKENS = int(os.getenv("AI_MAX_TOKENS", "768"))
MAX_FACTS_CHARS = 1200
TOOL_SCHEMA_BY_NAME = {tool["function"]["name"]: tool for tool in available_tools}
PLACEHOLDER_KEYS = {
    "sua_chave_aqui",
    "sua_chave_groq_aqui",
    "sua_chave_openai_aqui",
}


def _valid_secret(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value in PLACEHOLDER_KEYS:
        return None
    return value


class AIEngine:
    def __init__(self):
        self.provider = (os.getenv("AI_PROVIDER") or "").strip().lower()
        self.api_key = None
        self.model = None
        self.base_url = None
        self.default_headers = {}
        self.client = None
        self.fallback_provider = None
        self.fallback_client = None
        self.fallback_model = None

        if self.provider not in {"openrouter", "groq", "openai"}:
            if _valid_secret(os.getenv("OPENROUTER_API_KEY")):
                self.provider = "openrouter"
            elif _valid_secret(os.getenv("GROQ_API_KEY")):
                self.provider = "groq"
            elif _valid_secret(os.getenv("OPENAI_API_KEY")):
                self.provider = "openai"

        if self.provider == "openrouter":
            self.api_key = _valid_secret(os.getenv("OPENROUTER_API_KEY"))
            self.model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
            self.base_url = "https://openrouter.ai/api/v1"
            self.default_headers = {
                "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://127.0.0.1:8008"),
                "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_NAME", "Assistente Elite"),
            }
            fallback_key = _valid_secret(os.getenv("GROQ_API_KEY"))
            if fallback_key:
                self.fallback_provider = "groq"
                self.fallback_model = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")
                self.fallback_client = OpenAI(
                    api_key=fallback_key,
                    base_url="https://api.groq.com/openai/v1",
                )
        elif self.provider == "groq":
            self.api_key = _valid_secret(os.getenv("GROQ_API_KEY"))
            self.model = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")
            self.base_url = "https://api.groq.com/openai/v1"
            fallback_key = _valid_secret(os.getenv("OPENROUTER_API_KEY"))
            if fallback_key:
                self.fallback_provider = "openrouter"
                self.fallback_model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
                self.fallback_client = OpenAI(
                    api_key=fallback_key,
                    base_url="https://openrouter.ai/api/v1",
                    default_headers={
                        "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "http://127.0.0.1:8008"),
                        "X-OpenRouter-Title": os.getenv("OPENROUTER_APP_NAME", "Assistente Elite"),
                    },
                )
        elif self.provider == "openai":
            self.api_key = _valid_secret(os.getenv("OPENAI_API_KEY"))
            self.model = os.getenv("OPENAI_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))
            self.base_url = None
        if self.api_key:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    default_headers=self.default_headers or None,
                )
            except Exception as e:
                print(f"Erro ao inicializar cliente I.A: {e}")
        else:
            print("AVISO: chave de API nao configurada ou invalida.")

        self.history = [{"role": "system", "content": self._build_system_prompt()}]

    def _select_client(self, provider: str):
        if provider == self.provider:
            return self.client, self.model
        if provider == self.fallback_provider:
            return self.fallback_client, self.fallback_model
        return None, None

    def _should_fallback(self, api_error: Exception) -> bool:
        status_code = getattr(api_error, "status_code", None)
        message = str(api_error).lower()
        if status_code in {401, 402, 403, 429}:
            return True
        return any(term in message for term in ["insufficient credits", "quota", "billing", "unauthorized", "credits"])

    def _parse_tool_text_value(self, value: str):
        value = value.strip()
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
        if value.startswith(("[", "{", "(", "'", '"')):
            try:
                return ast.literal_eval(value)
            except Exception:
                pass
        return os.path.expandvars(os.path.expanduser(value))

    def _execute_text_tool_commands(self, content: str, allowed_names=None) -> str | None:
        """Executa comandos em texto quando um modelo sem tool-call emite /nome args."""
        if not content:
            return None

        allowed = set(allowed_names or [])
        results = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line.startswith("/"):
                continue

            try:
                parts = shlex.split(line[1:], posix=True)
            except ValueError:
                parts = line[1:].split()

            if not parts:
                continue

            function_name = parts[0]
            if function_name not in tool_map:
                continue
            if allowed and function_name not in allowed:
                continue

            args = {}
            for part in parts[1:]:
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                args[key] = self._parse_tool_text_value(value)

            try:
                result = tool_map[function_name](**args)
            except Exception as e:
                result = f"Erro ao executar {function_name}: {e}"
            results.append(f"{function_name}: {result}")

        return "\n".join(results) if results else None

    def _path_from_message(self, text: str) -> str:
        if any(term in text for term in ["area de trabalho", "área de trabalho", "desktop"]):
            return "desktop"
        if any(term in text for term in ["documentos", "documents"]):
            return "documents"
        if any(term in text for term in ["downloads", "download"]):
            return "downloads"
        if any(term in text for term in ["projeto", "project"]):
            return "projeto"
        if any(term in text for term in ["appdata", "dados do app"]):
            return "appdata"
        if any(term in text for term in ["arquivos do app", "arquivos"]):
            return "arquivos"
        return "."

    def _extract_folder_name(self, message: str) -> str | None:
        patterns = [
            r"pasta\s+(?:chamada|chamado|nomeada|nomeado)?\s*['\"]?([^'\".,!?]+?)(?:\s+(?:no|na|em|dentro|para)\s+|[.,!?]|$)",
            r"(?:crie|criar|faca|faça|nova)\s+(?:uma\s+)?pasta\s+['\"]?([^'\".,!?]+?)(?:\s+(?:no|na|em|dentro|para)\s+|[.,!?]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                name = match.group(1).strip(" '\"")
                name = re.sub(r"^(chamada|chamado|nomeada|nomeado)\s+", "", name, flags=re.IGNORECASE).strip()
                if name:
                    return name
        return None

    def _extract_excel_filename(self, message: str) -> str:
        file_match = re.search(r"['\"]([^'\"]+\.xlsx)['\"]|([^\s'\"\\/:*?<>|]+\.xlsx)", message, flags=re.IGNORECASE)
        if file_match:
            return (file_match.group(1) or file_match.group(2)).strip()
        name_match = re.search(
            r"planilha\s+(?:chamada|chamado|nomeada|nomeado)?\s*['\"]?([^'\".,!?]+?)(?:\s+(?:com|no|na|em|dentro|para)\s+|[.,!?]|$)",
            message,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).strip(" '\"")
            name = re.sub(r"^(chamada|chamado|nomeada|nomeado)\s+", "", name, flags=re.IGNORECASE).strip()
            if name:
                return name if name.lower().endswith(".xlsx") else f"{name}.xlsx"
        return f"planilha_{int(time.time())}.xlsx"

    def _extract_excel_data(self, message: str):
        table_match = re.search(r"(?:dados|tabela|linhas)\s*:?\s*(.+)$", message, flags=re.IGNORECASE | re.DOTALL)
        if table_match:
            raw = table_match.group(1).strip()
            if any(separator in raw for separator in ["|", ";", "\n", "\t"]):
                rows = []
                for line in re.split(r"[\r\n;]+", raw):
                    line = line.strip(" .|")
                    if not line:
                        continue
                    if "|" in line:
                        parts = [part.strip() for part in line.split("|")]
                    elif "\t" in line:
                        parts = [part.strip() for part in line.split("\t")]
                    else:
                        parts = [part.strip() for part in line.split(",")]
                    rows.append([part for part in parts if part])
                if rows:
                    return rows

        headers = ["Item", "Status"]
        columns_match = re.search(r"colunas?\s*:?\s*(.+?)(?:\s+e\s+(?:uma\s+)?linha|\s+com\s+(?:as\s+)?(?:linhas|dados)|[.!?]|$)", message, flags=re.IGNORECASE)
        if columns_match:
            raw_columns = columns_match.group(1)
            parts = re.split(r"\s*,\s*|\s+e\s+", raw_columns)
            cleaned = [part.strip(" :;") for part in parts if part.strip(" :;")]
            if cleaned:
                headers = cleaned[:12]

        rows = []
        rows_match = re.search(r"(?:linhas|dados)\s*:?\s*(.+?)(?:[.!?]|$)", message, flags=re.IGNORECASE | re.DOTALL)
        if rows_match:
            raw_rows = rows_match.group(1)
            for raw_row in re.split(r"\s*;\s*", raw_rows):
                parts = [part.strip(" :;") for part in re.split(r"\s*,\s*|\s+\|\s+", raw_row) if part.strip(" :;")]
                if parts:
                    if len(parts) < len(headers):
                        parts.extend([""] * (len(headers) - len(parts)))
                    rows.append(parts[:len(headers)])

        if not rows:
            rows = [["" for _ in headers]]

        return [headers] + rows[:200]

    def _extract_text_filename(self, message: str) -> str:
        file_match = re.search(
            r"['\"]([^'\"]+\.[a-zA-Z0-9]{1,8})['\"]|([^\s'\"\\/:*?<>|]+\.(?:txt|md|json|csv|log|py|html|css|js))",
            message,
            flags=re.IGNORECASE,
        )
        if file_match:
            return (file_match.group(1) or file_match.group(2)).strip()

        name_match = re.search(
            r"arquivo\s+(?:de\s+texto\s+)?(?:chamado|chamada|nomeado|nomeada)?\s*['\"]?([^'\".,!?]+?)(?:\s+(?:com|no|na|em|dentro|para)\s+|[.,!?]|$)",
            message,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).strip(" '\"")
            name = re.sub(r"^(chamado|chamada|nomeado|nomeada)\s+", "", name, flags=re.IGNORECASE).strip()
            if name:
                return name if os.path.splitext(name)[1] else f"{name}.txt"

        return f"arquivo_{int(time.time())}.txt"

    def _extract_text_content(self, message: str) -> str:
        patterns = [
            r"(?:conteudo|conteúdo)\s*:?\s*['\"]?(.+?)['\"]?$",
            r"(?:texto)\s*:?\s*['\"]?(.+?)['\"]?$",
            r"\bcom\s+(?:o\s+)?(?:conteudo|conteúdo|texto)\s+['\"]?(.+?)['\"]?$",
            r"\bescreva\s+['\"]?(.+?)['\"]?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip(" '\"")
        return ""

    def _extract_office_filename(self, message: str, prefix: str, extension: str) -> str:
        file_match = re.search(
            rf"['\"]([^'\"]+\.{extension.lstrip('.')})['\"]|([^\s'\"\\/:*?<>|]+\.{extension.lstrip('.')})",
            message,
            flags=re.IGNORECASE,
        )
        if file_match:
            return (file_match.group(1) or file_match.group(2)).strip()
        name_match = re.search(
            r"(?:chamad[ao]|nomead[ao])\s*['\"]?([^'\".,!?]+?)(?:\s+(?:com|sobre|no|na|em|dentro|para)\s+|[.,!?]|$)",
            message,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).strip(" '\"")
            if name:
                return name if name.lower().endswith(extension) else f"{name}{extension}"
        return f"{prefix}_{int(time.time())}{extension}"

    def _extract_document_content(self, message: str) -> str:
        content = self._extract_text_content(message)
        if content:
            return content
        topic_match = re.search(r"(?:sobre|de)\s+([^.,!?]+)", message, flags=re.IGNORECASE)
        topic = topic_match.group(1).strip() if topic_match else "relatorio"
        return f"# {topic.title()}\n\nDocumento criado pelo Assistente Elite.\n\n- Objetivo\n- Pontos principais\n- Proximos passos"

    def _extract_slides_content(self, message: str):
        content = self._extract_text_content(message)
        if content:
            return content
        topic_match = re.search(r"(?:sobre|de)\s+([^.,!?]+)", message, flags=re.IGNORECASE)
        topic = topic_match.group(1).strip() if topic_match else "apresentacao"
        return [
            {"title": topic.title(), "body": "Objetivo e contexto"},
            {"title": "Pontos principais", "bullets": ["Resumo executivo", "Dados relevantes", "Impacto esperado"]},
            {"title": "Proximos passos", "bullets": ["Validar informacoes", "Executar plano", "Acompanhar resultados"]},
        ]

    def _extract_search_query(self, message: str) -> str:
        patterns = [
            r"(?:procure|buscar|busque|encontre|pesquise)\s+(?:o\s+)?(?:arquivo\s+)?['\"]?([^'\".,!?]+?)['\"]?(?:\s+(?:no|na|em|dentro)\s+|[.,!?]|$)",
            r"arquivo\s+['\"]?([^'\".,!?]+?)['\"]?(?:\s+(?:no|na|em|dentro)\s+|[.,!?]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                query = match.group(1).strip(" '\"")
                if query:
                    return query
        return ""

    def _extract_open_target(self, message: str) -> str:
        patterns = [
            r"(?:abra|abrir|inicie|iniciar|execute|executar|rode|rodar)\s+(?:o\s+|a\s+|um\s+|uma\s+)?(.+?)(?:\s+em\s+segundo\s+plano|[.!?]|$)",
            r"(?:abrir|executar)\s+por\s+nome\s+(.+?)(?:[.!?]|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                target = match.group(1).strip(" '\"")
                target = re.sub(r"^(aplicativo|app|programa|arquivo|pasta|planilha)\s+", "", target, flags=re.IGNORECASE).strip()
                if target:
                    return target
        return ""

    def _execute_direct_local_intent(self, message: str) -> str | None:
        text = (message or "").lower()
        wants_create = any(term in text for term in ["crie", "criar", "faca", "faça", "nova", "novo"])

        if any(term in text for term in ["analisar maquina", "varrer maquina", "indexar maquina", "mapear pc", "mapear maquina"]):
            return json.dumps(tool_map["scan_machine_index"](reason="chat"), ensure_ascii=False, indent=2)

        if "cerebro" in text or "memoria local" in text or "memória local" in text:
            if any(term in text for term in ["status", "estado", "quantos"]):
                return json.dumps(tool_map["brain_status"](), ensure_ascii=False, indent=2)
            if any(term in text for term in ["procure", "buscar", "busque", "encontre", "pesquise"]):
                query = self._extract_search_query(message) or message
                results = tool_map["search_brain"](query=query, limit=12)
                return json.dumps(results, ensure_ascii=False, indent=2)
            if any(term in text for term in ["lembre", "recorde", "recupere", "buscar memoria"]):
                return tool_map["recall_brain"](query=message, limit=8)

        if any(term in text for term in ["abra", "abrir", "inicie", "iniciar", "execute", "executar", "rode", "rodar"]) and not wants_create:
            target = self._extract_open_target(message)
            if target:
                return tool_map["open_by_name"](
                    query=target,
                    background=any(term in text for term in ["segundo plano", "background", "sem abrir janela"]),
                )

        if wants_create and any(term in text for term in ["planilha", "excel", ".xlsx", "xlsx"]):
            filename = self._extract_excel_filename(message)
            path_key = self._path_from_message(text)
            if path_key != ".":
                filename = os.path.join(_resolve_known_path(path_key), filename)
            return tool_map["create_excel_sheet"](
                filename=filename,
                data=self._extract_excel_data(message),
                sheet_name="Dados",
                include_summary=True,
            )

        if wants_create and any(term in text for term in ["word", "documento", "docx", "relatorio", "relatório"]):
            path_key = self._path_from_message(text)
            return tool_map["create_word_doc"](
                filename=self._extract_office_filename(message, "documento", ".docx"),
                content=self._extract_document_content(message),
                title="Documento",
                path="arquivos" if path_key == "." else path_key,
            )

        if wants_create and any(term in text for term in ["powerpoint", "apresentacao", "apresentação", "ppt", "slides"]):
            path_key = self._path_from_message(text)
            return tool_map["create_powerpoint"](
                filename=self._extract_office_filename(message, "apresentacao", ".pptx"),
                slides_content=self._extract_slides_content(message),
                title="Apresentacao",
                path="arquivos" if path_key == "." else path_key,
            )

        if wants_create and any(term in text for term in ["pasta", "diretorio", "diretório"]):
            folder_name = self._extract_folder_name(message)
            if folder_name:
                return tool_map["create_folder"](folder_name=folder_name, path=self._path_from_message(text))

        if wants_create and any(term in text for term in ["arquivo", ".txt", ".md", ".json", ".csv"]):
            path_key = self._path_from_message(text)
            return tool_map["create_text_file"](
                filename=self._extract_text_filename(message),
                content=self._extract_text_content(message),
                path="arquivos" if path_key == "." else path_key,
            )

        if any(term in text for term in ["diagnostico do app", "diagnostico", "diagnóstico", "diagnostico de app", "prontidao", "prontidão", "build do app"]):
            return json.dumps(tool_map["app_diagnostics"](), ensure_ascii=False, indent=2)

        if any(term in text for term in ["procure", "buscar", "busque", "encontre", "pesquise"]) and any(term in text for term in ["arquivo", "pasta", ".txt", ".xlsx", ".pdf"]):
            results = tool_map["search_files"](
                directory=self._path_from_message(text),
                query=self._extract_search_query(message),
            )
            return "\n".join(results) if isinstance(results, list) else str(results)

        return None

    def _select_tools_for_message(self, message: str):
        text = (message or "").lower()

        keyword_map = {
            "observe_screen": ["observe", "observar", "tela", "screen", "o que estou fazendo", "acompanhar"],
            "get_active_window": ["janela", "window", "janela ativa"],
            "move_mouse": ["mover mouse", "arraste", "coordenada", "mouse para"],
            "click_screen": ["clicar", "clique", "botao", "botão"],
            "drag_mouse": ["arrastar", "drag"],
            "type_text": ["digitar", "escrever", "type text", "texto"],
            "press_hotkey": ["atalho", "hotkey", "tecla", "win+", "ctrl+", "alt+"],
            "scroll_screen": ["rolar", "scroll", "descer", "subir"],
            "capture_screen": ["captura", "print", "screenshot"],
            "list_files": ["listar", "arquivos", "pasta", "diretorio", "diretório"],
            "get_file_info": ["info do arquivo", "metadados", "tamanho do arquivo", "modificado em"],
            "create_text_file": ["criar arquivo", "crie um arquivo", "arquivo de texto", ".txt", ".md", ".json"],
            "append_text_file": ["adicionar texto", "acrescentar texto", "anexar texto"],
            "search_files": ["procurar arquivo", "buscar arquivo", "encontrar arquivo", "pesquisar arquivo"],
            "copy_file": ["copiar arquivo", "duplicar arquivo", "copia do arquivo"],
            "organize_folder": ["organizar", "desktop", "área de trabalho", "area de trabalho"],
            "create_folder": [
                "criar pasta", "crie uma pasta", "crie a pasta", "nova pasta",
                "pasta chamada", "fazer pasta", "faca uma pasta", "faça uma pasta",
                "diretorio novo", "diretório novo", "mkdir"
            ],
            "move_file": ["mover arquivo", "arrastar arquivo", "transferir arquivo"],
            "open_application": ["abrir", "iniciar", "executar", "site", "aplicativo"],
            "get_system_stats": ["status do sistema", "cpu", "ram", "disco"],
            "get_system_info": ["informacoes do sistema", "sistema operacional", "processador"],
            "web_search": ["pesquise", "pesquisar", "internet", "web", "noticias", "notícias"],
            "control_system_volume": ["volume", "som", "mute", "mudo"],
            "manage_tasks": ["tarefa", "agenda", "compromisso"],
            "read_complex_file": ["pdf", "excel", "planilha", "csv", "arquivo complexo"],
            "create_word_doc": ["word", "documento"],
            "create_excel_sheet": ["excel", "planilha", "xlsx", "tabela", "arquivo excel"],
            "create_powerpoint": ["powerpoint", "ppt", "apresentação", "apresentacao"],
            "execute_python_code": ["codigo", "código", "python", "script"],
            "read_complex_file": ["pdf", "excel", "planilha", "csv", "word", "powerpoint", "arquivo complexo"],
            "create_word_doc": ["word", "documento", "docx", "relatorio", "relatório"],
            "create_excel_sheet": ["excel", "planilha", "xlsx", "tabela", "arquivo excel", "orcamento", "orçamento"],
            "create_excel_workbook": ["varias abas", "várias abas", "workbook", "pasta de trabalho"],
            "update_excel_sheet": ["atualizar planilha", "anexar na planilha", "adicionar linha na planilha"],
            "create_powerpoint": ["powerpoint", "ppt", "apresentaÃ§Ã£o", "apresentacao", "slides"],
            "run_command": ["terminal", "comando", "cmd", "powershell"],
            "install_missing_dependency": ["instalar dependencia", "instalar biblioteca", "pip"],
            "read_source_code": ["ler codigo", "ler código", "ver codigo", "ver código", "inspecionar"],
            "apply_code_change": ["aplicar mudança", "aplicar mudança", "alterar codigo", "alterar código", "corrigir no projeto"],
            "modify_assistant_code": ["modificar assistente", "auto modificar", "auto-modificar", "editar assistente"],
            "save_learning_note": ["aprender", "memorizar", "salvar nota", "anotar"],
            "integrate_code_snippet": ["integrar codigo", "integrar código", "snippet", "trecho de codigo", "trecho de código"],
            "scan_machine_index": ["indexar maquina", "mapear maquina", "varrer maquina", "analisar maquina"],
            "brain_status": ["status do cerebro", "estado do cerebro", "memoria local"],
            "search_brain": ["buscar no cerebro", "procure no cerebro", "pesquisar no cerebro"],
            "open_by_name": ["abrir por nome", "abra", "abrir aplicativo", "abrir pasta", "abrir planilha"],
            "execute_by_name": ["executar em segundo plano", "rodar em segundo plano"],
            "remember_brain_note": ["salvar no cerebro", "memorizar no cerebro"],
            "recall_brain": ["lembrar do cerebro", "recuperar memoria"],
            "analyze_and_remember_file": ["analisar arquivo", "analisar planilha", "analisar codigo", "analisar app"],
            "send_notification": ["notificacao", "notifica", "avisar", "telegram", "discord", "slack", "whatsapp", "email"],
            "create_flow": ["criar fluxo", "salvar automacao"],
            "run_flow": ["rodar fluxo", "executar fluxo"],
            "browser_status": ["computer use", "browserbase", "stagehand", "navegador operacional", "navegador autonomo"],
            "browser_start_session": ["abrir sessao de navegador", "nova sessao web", "navegador isolado"],
            "browser_fetch_page": ["ler site", "extrair pagina", "buscar pagina", "fetch"],
            "browser_run_instruction": ["operar site", "entrar no site", "preencher formulario", "baixar pdf", "comparar opcoes", "usar navegador"],
            "browser_pending_approvals": ["aprovacoes do navegador", "aprovações do navegador", "acoes pendentes"],
            "browser_approve_action": ["aprovo acao", "aprovar acao", "rejeitar acao"],
            "app_diagnostics": ["diagnostico", "prontidao", "build do app", "empacotar", "executavel"],
        }

        selected = []
        for tool_name, keywords in keyword_map.items():
            if any(keyword in text for keyword in keywords):
                schema = TOOL_SCHEMA_BY_NAME.get(tool_name)
                if schema:
                    selected.append(schema)

        return selected

    def _create_completion(self, chat_params: dict, provider: str | None = None):
        active_provider = provider or self.provider
        client, model = self._select_client(active_provider)
        if not client:
            raise RuntimeError("Nenhum cliente de IA configurado.")

        request_params = dict(chat_params)
        request_params["model"] = model

        try:
            return client.chat.completions.create(**request_params), active_provider
        except Exception as api_error:
            if active_provider != self.provider or not self.fallback_client or not self._should_fallback(api_error):
                raise

            with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
                f.write(
                    f"Falha no provedor {self.provider}, usando fallback {self.fallback_provider}: {str(api_error)}\n"
                )

            fallback_client, fallback_model = self._select_client(self.fallback_provider)
            if not fallback_client or not fallback_model:
                raise

            fallback_params = dict(chat_params)
            fallback_params["model"] = fallback_model
            return fallback_client.chat.completions.create(**fallback_params), self.fallback_provider

    def _build_system_prompt(self, facts: str = "") -> str:
        facts = (facts or "Ainda nao ha fatos memorizados.")[:MAX_FACTS_CHARS]
        return f"""Voce e o Assistente Elite, um assistente desktop local para Windows.
Prioridades:
1. Quando o usuario pedir uma acao suportada por ferramenta, use a ferramenta apropriada e depois explique o resultado.
2. Seja direto, tecnico e educado. Nao afirme que executou algo se a ferramenta falhou.
3. Use web_search para informacoes atuais.
4. Use ferramentas de arquivos, Office e sistema com cuidado e relate caminhos/erros importantes.
4a. Para Office, prefira criar arquivos reais: Excel com tabelas, filtros, abas e resumo; Word com titulo/estrutura; PowerPoint com slides e topicos. Quando o usuario der dados em texto, converta para tabela organizada.
5. Ferramentas perigosas de codigo, terminal e auto-modificacao so existem se o dono habilitar ELITE_ENABLE_DANGEROUS_TOOLS=1.
6. Em modo operador, use observe_screen antes de controlar mouse/teclado quando precisar entender a tela.
7. Quando o usuario enviar codigo para aprender, use save_learning_note ou integrate_code_snippet; quando pedir uma correcao real no projeto, use read_source_code e apply_code_change se a permissao estiver ativa.
8. Use o cerebro local para buscar, abrir e lembrar: search_brain, open_by_name, remember_brain_note, recall_brain e analyze_and_remember_file.
9. Para automacoes e avisos, use create_flow/run_flow e send_notification; canais externos dependem de variaveis no .env.
10. Para sites e portais, use a camada de navegador operacional: browser_fetch_page para leitura; browser_run_instruction para observar, extrair, preparar formularios e fluxos. Se a ferramenta devolver needs_approval, pare e explique exatamente o que precisa de confirmacao humana.
11. Nunca escreva comandos como /create_folder ou /create_excel_sheet como resposta final. Use chamadas de ferramenta quando uma acao local for necessaria.
Memoria do usuario:
{facts}"""

    def _trim_history(self):
        if len(self.history) > MAX_HISTORY_MESSAGES + 1:
            self.history = [self.history[0]] + self.history[-MAX_HISTORY_MESSAGES:]

    def _safe_speak(self, text: str):
        if not text:
            return
        try:
            voice.speak(text)
        except Exception:
            pass

    def chat(self, message: str):
        facts = recall_user_preferences()
        try:
            brain_facts = tool_map["recall_brain"](query="", limit=3)
            facts = f"{facts}\n\nCerebro local recente:\n{brain_facts}"
        except Exception:
            pass
        self.history[0]["content"] = self._build_system_prompt(facts)
        self._trim_history()

        with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
            f.write(f"Iniciando chat para: {message} as {time.ctime()}\n")

        if not self.client:
            msg = "Chave de API nao encontrada. Configure GROQ_API_KEY ou OPENAI_API_KEY no arquivo .env."
            self._safe_speak(msg)
            return msg

        try:
            self.history.append({"role": "user", "content": message})

            direct_tool_result = self._execute_text_tool_commands(message)
            if not direct_tool_result:
                direct_tool_result = self._execute_direct_local_intent(message)
            if direct_tool_result:
                self.history.append({"role": "assistant", "content": direct_tool_result})
                db.save_chat(message, direct_tool_result)
                self._safe_speak(direct_tool_result)
                self._trim_history()
                return direct_tool_result

            with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
                f.write(f"Chamando API da IA... as {time.ctime()}\n")

            chat_params = {
                "model": self.model,
                "messages": self.history,
                "max_tokens": MAX_COMPLETION_TOKENS,
            }

            selected_tools = self._select_tools_for_message(message)
            selected_tool_names = [tool["function"]["name"] for tool in selected_tools]
            if selected_tools:
                chat_params["tools"] = selected_tools
                chat_params["tool_choice"] = "auto"

            try:
                response, active_provider = self._create_completion(chat_params)
            except Exception as api_error:
                if "tool" not in str(api_error).lower() or "tools" not in chat_params:
                    raise
                with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
                    f.write(f"Falha em tool calling, tentando sem ferramentas: {str(api_error)}\n")
                chat_params.pop("tools", None)
                chat_params.pop("tool_choice", None)
                response, active_provider = self._create_completion(chat_params)

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
                f.write(f"Resposta recebida da IA. Chamadas de ferramenta: {bool(tool_calls)} as {time.ctime()}\n")

            if tool_calls:
                self.history.append(response_message)

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    try:
                        function_args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    except json.JSONDecodeError:
                        function_args = {}

                    if not isinstance(function_args, dict):
                        function_args = {}

                    function_to_call = tool_map.get(function_name)
                    if function_to_call:
                        print(f"Executando ferramenta: {function_name}")
                        result = function_to_call(**function_args)
                    else:
                        result = f"Ferramenta desconhecida: {function_name}"

                    self.history.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": str(result),
                    })

                second_response, _ = self._create_completion(
                    {
                        "messages": self.history,
                    "max_tokens": MAX_COMPLETION_TOKENS,
                    },
                    provider=active_provider,
                )
                final_content = second_response.choices[0].message.content or "Acao concluida."
                self.history.append({"role": "assistant", "content": final_content})
                db.save_chat(message, final_content)
                self._safe_speak(final_content)
                self._trim_history()
                return final_content

            final_content = response_message.content or ""
            text_tool_result = self._execute_text_tool_commands(final_content, selected_tool_names)
            if text_tool_result:
                final_content = text_tool_result
            self.history.append({"role": "assistant", "content": final_content})
            db.save_chat(message, final_content)
            self._safe_speak(final_content)
            self._trim_history()
            return final_content
        except Exception as e:
            import traceback

            with open(log_path("log_ai.txt"), "a", encoding="utf-8") as f:
                f.write(f"ERRO NA IA: {str(e)}\n")
                f.write(traceback.format_exc())
            return f"Erro no nucleo de IA: {str(e)}"

    def clear_history(self):
        self.history = [{"role": "system", "content": self._build_system_prompt()}]
