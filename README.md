# Svitlo School Administration Bot (`svitlo-admin-bot`)

An asynchronous Telegram bot designed to automate operational workflows, manage IT infrastructure, and handle user authorization for **Svitlo School** (an educational organization focused on youth integration, leadership development, and European policy).

The project is architected as a highly scalable, stateless application running on serverless infrastructure.

---

## 🛠 Tech Stack & Architecture

- **Language & Runtime:** Python 3.11 (`asyncio` / asynchronous execution)
- **Framework:** `aiogram` v3.x (configured strictly in **Webhook** mode)
- **Database & Backend:** Google Cloud Firestore integrated via **Rowy CMS**
- **Cloud Infrastructure:** Google Cloud Platform (GCP)
- **Compute Service:** Cloud Run functions (Gen 2)
- **Deployment Region:** `europe-west3` (Frankfurt)
- **Hardware Configuration:** 512MiB Memory Allocation (Dynamic CPU scaling)

---

## 🚀 Key Features

- **Role-Based Access Control (RBAC):** Secure authorization and differentiation of roles (Admins, Teachers, Students).
- **IT Infrastructure Automation:** Streamlined administration of external services (managing Zoom cloud recordings, synchronizing Notion databases).
- **Workflow Automation:** Internal request tracking, schedule coordination, and seamless team admin-panel integration.

---

## ⚡ Serverless Deployment Constraints (Critical)

Since the application runs on **GCP Cloud Run functions (Gen 2)**, the following architectural principles must be strictly followed during development:

1. **Complete Statelessness:** The service is completely stateless. No data can be stored in-memory between Telegram requests. Global variables, local lists, or standard in-memory FSM (Finite State Machine) storages are strictly prohibited. All user states and caches must be read/written from Firestore in real-time.
2. **Webhook Timeout Limits:** GCF and Telegram Webhooks require an immediate response (`HTTP 200 OK`). For heavy or long-running tasks (e.g., Rowy/Notion API integrations), use non-blocking background tasks (`asyncio.create_task`) to prevent `HTTP 504/408` timeouts and duplicate request looping from Telegram.
3. **Secret Management:** Sensitive credentials (like `BOT_TOKEN`) must never be hardcoded. They are injected as environment variables via GCP/GitHub Secrets.

---

## 🔄 CI/CD Pipeline

The project utilizes native **GitHub Actions** for continuous deployment. Any push to the `main` branch automatically triggers the `.github/workflows/deploy.yml` pipeline.

The pipeline authenticates via a secure Google Cloud Service Account (`github-deployer`) and executes the native deployment command:

```bash
gcloud functions deploy school-bot-function \
  --gen2 \
  --runtime=python311 \
  --region=europe-west3 \
  --source=. \
  --entry-point=telegram_webhook \
  --trigger-http \
  --allow-unauthenticated \
  --memory=512MiB
```

---

## Local Development Setup

1. Clone the repository:

```bash
git clone [https://github.com/passshokk/svitlo-admin-bot.git](https://github.com/passshokk/svitlo-admin-bot.git)
cd svitlo-admin-bot
```

2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a .env file for local testing (never commit this file):

```bash
BOT_TOKEN=your_telegram_bot_token
```

Maintained by the Svitlo School IT Department.

---

### How to send a file to Git:

Run the standard commands in the VS Code terminal:

```bash
git add README.md
git commit -m "Added high-standard README.md!"
git push
```
