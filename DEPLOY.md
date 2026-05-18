# Deploy com dominio

Objetivo: publicar o Assistente Elite em um dominio HTTPS para mobile e PC sem depender da rede local.

## Recomendacao

Use dois subdominios:

- `api.seu-dominio.com`: backend FastAPI do Assistente.
- `app.seu-dominio.com`: painel web/desktop se voce quiser uma versao web publica.

O app mobile deve apontar para `https://api.seu-dominio.com`. As chaves de IA ficam no servidor, nunca no APK/IPA.

## Opcoes de hospedagem

### Producao simples

VPS com Docker:

- Hetzner, DigitalOcean, Vultr, Hostinger VPS ou similar.
- Rode `docker compose -f docker-compose.prod.yml up -d`.
- Coloque Nginx/Caddy/Traefik na frente para HTTPS.

### Producao sem gerenciar servidor

Plataformas como Render, Railway ou Fly.io aceitam Docker e variaveis de ambiente. Suba este repositorio com o `Dockerfile` e configure as variaveis de `.env.production.example`.

### Teste rapido pelo seu PC

Cloudflare Tunnel pode publicar seu servidor local em `api.seu-dominio.com` sem abrir portas no roteador. Funciona fora da rede local, mas depende do seu PC ficar ligado.

## Passo a passo VPS

1. Comprar dominio, por exemplo `assistenteelite.com.br` ou `assistenteelite.app`.
2. Criar DNS:
   - `api` apontando para o IP do servidor.
   - `app` apontando para o mesmo servidor, se houver painel web.
3. Copiar o projeto para o servidor.
4. Criar `.env.production` a partir de `.env.production.example`.
5. Garantir que estes valores estejam seguros:

```env
MOBILE_PUBLIC_API_BASE_URL=https://api.seu-dominio.com
MOBILE_CLIENT_TOKEN=gere_um_token_longo
PUBLIC_ALLOWED_ORIGINS=https://api.seu-dominio.com,https://app.seu-dominio.com
ELITE_ENABLE_DANGEROUS_TOOLS=0
ELITE_ENABLE_OPERATOR_MODE=0
ELITE_FULL_ACCESS=0
```

6. Subir o backend:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

7. Testar:

```text
https://api.seu-dominio.com/health
https://api.seu-dominio.com/mobile/status
```

## Gerar APK apontando para o dominio

Na pasta `mobile`, defina:

```env
EXPO_PUBLIC_ASSISTENTE_API_URL=https://api.seu-dominio.com
EXPO_PUBLIC_ASSISTENTE_CLIENT_TOKEN=o_mesmo_mobile_client_token
EXPO_PUBLIC_ASSISTENTE_CHANNEL=production
```

Depois rode:

```powershell
npm.cmd install
npx.cmd expo prebuild --platform android
cd android
.\gradlew.bat assembleRelease
```

O APK sai em:

```text
mobile/android/app/build/outputs/apk/release/app-release.apk
```

## Importante sobre ferramentas do PC

No servidor publico, deixe ferramentas perigosas desligadas. Um backend publico nao deve abrir apps, ler arquivos pessoais ou executar comandos da maquina de alguem.

Para uma versao futura em que o app mobile controla o PC do usuario, o modelo correto e:

- backend cloud em `api.seu-dominio.com`;
- agente local instalado no PC do usuario;
- agente local abre uma conexao de saida segura com o cloud;
- acoes sensiveis exigem aprovacao.

