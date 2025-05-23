# WaRAG  🚀 🤖📱  
*A WhatsApp bot that ingests chat messages, PDFs, DOCX, and other files, builds a Retrieval‑Augmented Generation (RAG) knowledge base, and answers your questions with cited context.*

![Node.js](https://img.shields.io/badge/node-%3E%3D20.x-green?logo=node.js)
![License](https://img.shields.io/badge/license-MIT-blue)

---

## ✨ Features
- **Chat with your documents** – ask questions in WhatsApp, get answers with citations.
- **End‑to‑end RAG pipeline** – embeds queries, searches ChromaDB, feeds context to an LLM.
- **Twilio WhatsApp integration** – deploy using the Twilio sandbox or a verified number.
- **Local REPL client** – debug without WhatsApp.
- **One‑shot session reset** – `reset-whatsapp.sh` wipes session data for a fresh QR code.

---

## 📂 Project layout
```
.
├── rag-system/           # Core RAG engine (embeddings, retrieval, generation)
├── twilio-whatsapp.js    # Express webhook target for Twilio
├── whatsapp-client.js    # Local CLI client
├── reset-whatsapp.sh     # Convenience script to clear sessions
├── crypto-polyfill.js    # WebCrypto polyfill for Node
├── .env-asal             # Example environment file (copy to .env)
├── package.json          # NPM scripts & dependencies
└── .gitignore            # Keeps node_modules, sessions, secrets out of Git
```

---

## 🚀 Quick start

> **Prerequisites**
> - Node 20 +  
> - Running **ChromaDB** instance  
> - **OpenAI API key** (or any model you wire in)  
> - **Twilio** account with WhatsApp sandbox or approved sender  
> - Public URL for webhooks (ngrok, Cloudflare Tunnel, etc.)

```bash
# Clone
git clone https://github.com/matnet/WaRAG.git
cd WaRAG

# Secrets
cp .env-asal .env           # then edit .env

# Install deps
npm install

# Run locally
npm run dev                 # or: node twilio-whatsapp.js
```

Point Twilio’s **“When a message comes in”** URL to:

```
https://<your-domain-or-ngrok>/whatsapp/webhook
```

Scan the sandbox QR code and say **hi** – WaRAG responds!

---

## 🛠️ Environment variables  

| Variable | Purpose |
| -------- | ------- |
| `OPENAI_API_KEY`            | Key for embeddings & completions |
| `CHROMA_URL` + `..._COLLECTION` | Vector store location |
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | Twilio credentials |
| `TWILIO_WHATSAPP_NUMBER`    | `whatsapp:+1415…` sender |
| `PORT`                      | Express port (`3000` default) |
| `SESSION_DIR`               | Where WhatsApp session JSON lives |

---

## 🤖 Flow

1. **Receive** message → webhook.
2. **Embed** query → vector.
3. **Retrieve** top‑k chunks from ChromaDB.
4. **Generate** answer with context via LLM.
5. **Reply** via Twilio.

---

## 📦 NPM scripts

| Script            | Action                         |
| ----------------- | ------------------------------ |
| `npm run dev`     | Start bot with auto‑reload     |
| `npm run embed`   | Vectorise new documents        |
| `npm run lint`    | ESLint check                  |
| `npm test`        | Unit tests placeholder         |

---

## 🐳 Docker (optional)

```bash
docker build -t warag .
docker run -d --env-file .env -p 80:3000 --name warag warag
```

Update Twilio webhook to your server’s public URL.

---

## 🗺️ Roadmap

- ✅ Basic RAG over WhatsApp  
- 🔄 Streaming responses  
- 🔒 Encrypted session storage  
- 📚 Admin dashboard  
- 🌐 Multi‑language (Bahasa Melayu first!)

---

## 🤝 Contributing

1. Fork & create a feature branch.  
2. `npm test && npm run lint` before PR.  
3. Open a pull request describing **why** and **what**.

---

## 📜 License

[MIT](LICENSE)

> Crafted with ☕ & 📡 by **Matnet**
