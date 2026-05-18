# Assistente Elite Mobile

App mobile compartilhado para Android e iPhone usando Expo/React Native.

## Arquitetura

O app nao guarda chaves de IA no APK/IPA. Ele vem apontado para o gateway do Assistente:

- `EXPO_PUBLIC_ASSISTENTE_API_URL`: URL publica do backend.
- `EXPO_PUBLIC_ASSISTENTE_CLIENT_TOKEN`: token do gateway mobile, se voce habilitar `MOBILE_CLIENT_TOKEN` no backend.
- As chaves Groq/OpenRouter/Deepgram/ElevenLabs continuam no `.env` do servidor.

Assim o cliente recebe o app pronto, sem configurar API manualmente, e as chaves principais continuam protegidas no backend.

## Configuracao do backend

No `.env` do servidor:

```env
MOBILE_APP_NAME=Assistente Elite
MOBILE_APP_ENV=production
MOBILE_PUBLIC_API_BASE_URL=https://api.seu-dominio.com
MOBILE_CLIENT_TOKEN=troque_este_token
```

Para desenvolvimento no computador:

```env
MOBILE_PUBLIC_API_BASE_URL=http://127.0.0.1:8008
```

Para celular fisico na mesma rede, use o IP local do computador:

```env
MOBILE_PUBLIC_API_BASE_URL=http://192.168.0.10:8008
```

## Configuracao do app

Crie um `.env` dentro da pasta `mobile`:

```env
EXPO_PUBLIC_ASSISTENTE_API_URL=https://api.seu-dominio.com
EXPO_PUBLIC_ASSISTENTE_CLIENT_TOKEN=troque_este_token
EXPO_PUBLIC_ASSISTENTE_CHANNEL=production
```

Esse valor entra no build. O usuario final nao precisa digitar nada.

## Instalar dependencias

```powershell
cd mobile
npm.cmd install
```

## Rodar em desenvolvimento

```powershell
npm.cmd run start
```

Depois abra no Expo Go, emulador Android ou simulador iOS.

## Build Android e iPhone

Instale e configure o EAS CLI:

```powershell
npm.cmd install -g eas-cli
eas login
```

Android:

```powershell
npm.cmd run build:android
```

iPhone:

```powershell
npm.cmd run build:ios
```

Para iOS voce precisa de conta Apple Developer e credenciais de assinatura.

## Rotas usadas

- `GET /mobile/bootstrap`
- `GET /mobile/status`
- `POST /mobile/chat`
- `POST /mobile/voice/transcribe`
- `POST /mobile/notifications/send`
- `GET /mobile/brain/status`
- `POST /mobile/brain/scan`
- `GET /mobile/brain/search`
- `POST /mobile/brain/open`
- `GET /mobile/browser/status`
- `GET /mobile/browser/approvals`
- `POST /mobile/browser/approvals/{approval_id}`
