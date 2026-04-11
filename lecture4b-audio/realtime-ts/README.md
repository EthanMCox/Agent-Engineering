# Realtime TypeScript Demo

This is a minimal browser-based Realtime API demo for students.
It uses Vite and `@openai/agents` to create a voice conversation in the browser via WebRTC.

## Files

- `src/main.ts`: bootstraps the page and starts the realtime session
- `src/style.css`: simple page styling
- `index.html`: Vite entry page
- `package.json`: dependencies and npm scripts

## Setup

1. Run `npm install`
2. Create an ephemeral realtime key on your server or from the command line
3. Paste that key into the prompt when the page loads
4. Run `npm run dev`

## Important

Do not commit ephemeral keys.
The demo prompts for a key at runtime so no secret needs to live in the code.
To get an ephemeral key run this:
 curl -s -X POST https://api.openai.com/v1/realtime/client_secrets -H "Authorization: Bearer $OPENAI_API_KEY" -H "Content-Type: application/json" -d '{"session": {"type": "realtime", "model": "gpt-realtime"}}' | jq .value

