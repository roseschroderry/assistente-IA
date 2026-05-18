Assistente Elite
================

Aplicativo desktop para Windows com interface PyQt, dashboard web local e backend FastAPI.

Estrutura
---------

- `app.py`: inicia o servidor local em `127.0.0.1:8008` e abre a janela PyQt.
- `backend/`: API, motor de IA, ferramentas, memoria SQLite e voz.
- `frontend/index.html`: dashboard local sem dependencias externas de CDN.
- `mobile/`: app Expo/React Native para Android e iPhone.
- `build_app.py`: build PyInstaller do executavel.
- Dados persistentes do app ficam em `%LOCALAPPDATA%\AssistenteElite` por padrao.

Habilidades Office
------------------

- Excel: cria planilhas `.xlsx` com tabela formatada, filtros, congelamento de cabecalho, leitura de dados em texto e aba `Resumo` com indicadores.
- Word: cria `.docx` com titulo, paragrafos, headings e listas usando `python-docx`, com fallback para Word COM.
- PowerPoint: cria `.pptx` com slides e topicos usando `python-pptx`, com fallback para PowerPoint COM.
- Leitura: analisa PDF, Excel/CSV, Word e PowerPoint em `read_complex_file`.

Navegador Operacional
---------------------

- Modo leitura: `browser_fetch_page` le paginas e extrai texto limpo sem clicar.
- Modo preparacao: `browser_run_instruction` prepara automacoes de site por linguagem natural.
- Aprovacao humana: acoes como enviar, pagar, comprar, publicar, excluir ou operar fora da allowlist entram em fila de aprovacao no dashboard.
- Ponte opcional: `browser_agent_runner.mjs` conecta Browserbase + Stagehand quando os pacotes JS e credenciais estiverem configurados.

Voz com IA
----------

- STT em nuvem: com `DEEPGRAM_API_KEY`, o dashboard grava o microfone no navegador e envia para o Deepgram.
- TTS em nuvem: com `ELEVENLABS_API_KEY`, as respostas viram audio MP3 e tocam no holograma do app.
- Fallbacks: sem chaves, o app continua usando SpeechRecognition do navegador, microfone local do backend e `pyttsx3` quando disponiveis.

Mobile Android/iPhone
---------------------

- O app em `mobile/` usa Expo/React Native para gerar Android e iPhone a partir do mesmo codigo.
- O app fala com o gateway `/mobile/*` do backend e nao leva chaves de IA dentro do APK/IPA.
- Alem de chat e voz, o app consulta o cerebro local, abre resultados no computador servidor e revisa aprovacoes pendentes do navegador operacional.
- A URL da API e o token mobile entram no build via `EXPO_PUBLIC_ASSISTENTE_API_URL` e `EXPO_PUBLIC_ASSISTENTE_CLIENT_TOKEN`.
- Para o cliente final, o app ja abre configurado; a configuracao manual fica no build/servidor.

Configuracao
------------

Crie um `.env` na raiz do projeto com pelo menos uma chave:

```env
GROQ_API_KEY=sua_chave_groq
AI_MODEL=llama-3.1-8b-instant
AI_MAX_TOKENS=768
AI_HISTORY_MESSAGES=6
AI_PROVIDER=groq
OPENROUTER_API_KEY=sua_chave_openrouter
OPENROUTER_MODEL=openai/gpt-4o-mini
MOBILE_PUBLIC_API_BASE_URL=https://api.seu-dominio.com
MOBILE_CLIENT_TOKEN=token_gateway_mobile
```

Ferramentas de terminal, execucao de codigo e auto-modificacao ficam ocultas por padrao. Para habilitar conscientemente:

```env
ELITE_ENABLE_DANGEROUS_TOOLS=1
ELITE_ENABLE_OPERATOR_MODE=1
ELITE_FULL_ACCESS=1
```

Com `ELITE_FULL_ACCESS=1`, o assistente libera ferramentas avancadas, operador local e acesso fora da pasta do projeto quando voce pedir comandos na maquina.

Para mudar a pasta de dados, defina:

```env
ELITE_DATA_DIR=C:\caminho\para\dados
```

Para ativar Browserbase + Stagehand, configure tambem:

```env
BROWSER_ALLOWED_DOMAINS=example.com,seuportal.com
BROWSER_REQUIRE_ALLOWLIST_FOR_ACTIONS=1
BROWSER_AGENT_ENABLE_STAGEHAND=1
BROWSERBASE_API_KEY=sua_chave_browserbase
BROWSERBASE_PROJECT_ID=seu_project_id
STAGEHAND_MODEL=openai/gpt-4o-mini
```

Sem essas credenciais, o app usa o provedor `local-fetch`, que ja permite leitura de paginas, politicas, logs e aprovacoes.

Para ativar Deepgram + ElevenLabs no chat de voz:

```env
DEEPGRAM_API_KEY=sua_chave_deepgram
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=pt-BR
ELEVENLABS_API_KEY=sua_chave_elevenlabs
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
ELEVENLABS_STABILITY=0.45
ELEVENLABS_SIMILARITY=0.75
```

Instalacao
----------

```powershell
pip install -r backend\requirements.txt
```

Execucao
--------

```powershell
python app.py
```

Diagnostico
-----------

Com o servidor ativo, abra:

```text
http://127.0.0.1:8008/diagnostics
http://127.0.0.1:8008/tools/catalog
```

Essas rotas ajudam a conferir dependencias, caminhos do app, ferramentas habilitadas e prontidao para empacotamento.

Build
-----

```powershell
python build_app.py
```
