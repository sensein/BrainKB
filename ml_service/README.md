# 🧠 ML Service

The **ML Service** provides API endpoints and WebSocket interfaces to interact with our **multi-agent system**, [**StructSense**](https://arxiv.org/abs/2507.03674).  
Currently, it enables the following intelligent operations such as:
- 🏷️ **Named Entity Recognition (NER)** term extraction  
- 📄 **PDF-to-ReproSchema** conversion  
- 🔍 **Resource and metadata extraction**

---

## 🚀 Getting Started

### 1. Environment Setup
Copy the example environment file and update it with your configuration:
```bash
mv env.copy .env
```
Then open `.env` and set all required environment variables (API keys, model paths, etc.).

## Set Up

Update the env variables with correct configuration.
Then run docker compose up, i.e., `docker compose -f docker-compose-prod.yml up`

Note: We expect you to have ollama installed and pulled `nomic-embed-text:v1.5` embedding model. If you want to use different model you can pull accordingly and update the `.env` file. 

### License
[MIT](https://github.com/git/git-scm.com/blob/main/MIT-LICENSE.txt)