
# Forex Compass: A Hybrid AI Agent for Forex Education

**Forex Compass** is a sophisticated, AI-powered mentor designed to guide beginner forex traders. Built with Python and Django, this agent features a dual-architecture system that provides safe, educational answers through a self-updating knowledge base or direct LLM interaction.

This project was developed for the **HNG Internship Stage 3 Backend Task**, showcasing a production-ready, resilient, and intelligent AI agent fully integrated with the [Telex.im](http://telex.im/) platform.

### Live Project Links
*   **Interact with the Agent:** [**Forex Compass on Telex.im**](https://telex.im/stage3backendagents/home/colleagues/019a6b8b-4bd3-76bf-97ec-a3e459f352c2/019a6b8b-12e6-76ba-a6af-7096de959566)
*   **Technical Blog Post:** [**From Django to Dialogue: Building a Resilient, Self-Updating AI Agent**](https://medium.com/@zichdan1999/5b4eef0160c9?source=friends_link&sk=a9fec55fbc3e3761725f91bafe625a78)
*   **Live API Endpoint:** [**https://hng-stage-3-agent-production.up.railway.app**](https://hng-stage-3-agent-production.up.railway.app)

---

## Key Features

-   **Hybrid Agent Architecture:** The system features two distinct conversational modes for optimal performance and flexibility.
-   ✅ **RAG Agent (Knowledge Base Search):** For high-accuracy answers, this agent uses Retrieval-Augmented Generation. It performs a semantic vector search on a curated PostgreSQL database (`pgvector`) to find verified information before synthesizing a response.
-   ✅ **Direct Agent (Normal Search):** For general conversation and speed, this agent bypasses the database and communicates directly with the Google Gemini LLM via a high-performance `httpx` service.
-   **Automated Knowledge Base:** A background Celery worker perpetually fetches forex news and scrapes educational articles, processes them with AI for clarity, generates vector embeddings, and populates the database. This ensures the agent's knowledge is always growing.
-   **Decoupled & Resilient Data Pipeline:** Data ingestion is fully decoupled from AI processing. A staging table queues fetched content, and a separate, timed Celery task processes one item at a time, making the system immune to API rate-limiting errors and resilient to failures.
-   **Production-Ready Telex.im Integration:** The agent exposes fully compliant Agent-to-Agent (A2A) protocol endpoints, designed for fast, synchronous ("blocking") interaction on the Telex.im platform.

---

## System Architecture

The project is architected into two primary components: a **Real-Time Interaction Flow (The Brain)** and a **Background Data Pipeline (The Heartbeat)**. This decoupled design ensures that the user experience is always fast and responsive, while the slow, heavy data processing happens independently in the background.

```mermaid
graph TD
    subgraph "Real-Time User Interaction (Synchronous Flow)"
        direction LR
        User([User on Telex.im]) -->|A2A Request| API[Django/Daphne View]
        
        subgraph "Agent Routing"
            API -- "/a2a/" --> RAGLogic{RAG Agent}
            API -- "/direct/" --> DirectLogic{Direct Agent}
        end

        RAGLogic --> VectorDB[(Knowledge Base)]
        VectorDB -- "Context" --> RAGLogic
        RAGLogic -- "Synthesize" --> Gemini1[Gemini LLM]
        Gemini1 --> FinalResponse[Format Final Answer]

        DirectLogic -- "Direct Query" --> Gemini2[Gemini LLM]
        Gemini2 --> FinalResponse
        
        FinalResponse --> API
        API -->|A2A Response| User
    end

    subgraph "Background Data Pipeline (Asynchronous Tasks)"
        direction TB
        Scheduler(Celery Beat)

        subgraph "Data Fetching (Every 2 Hours)"
            Scheduler -- "Triggers" --> Scraper[Scrape Articles] & NewsFetcher[Fetch News]
            Scraper --> StagingDB[(RawContent Staging DB)]
            NewsFetcher --> StagingDB
        end

        subgraph "Data Processing (Every 5 Mins)"
            Scheduler -- "Triggers" --> Processor[Process ONE Item]
            Processor -- "1. Get Raw Content" --> StagingDB
            Processor -- "2. Clean with AI" --> GeminiAPI[Gemini API]
            GeminiAPI -- "Cleaned Text" --> Processor
            Processor -- "3. Create Embedding" --> EmbeddingAPI[Embedding API]
            EmbeddingAPI -- "Vector" --> Processor
            Processor -- "4. Save" --> FinalVectorDB[(Knowledge Base)]
        end
    end
```

---

## Technology Stack

-   **Framework:** Django & Django Rest Framework
-   **Asynchronous Server:** Daphne
-   **Background Tasks:** Celery with Redis as the broker & Celery Beat for scheduling.
-   **Database:** PostgreSQL with the `pgvector` extension for vector similarity search.
-   **Generative AI:** Google Gemini (`gemini-2.0-flash-001`) for content processing and conversational responses.
-   **Async HTTP Client:** `httpx` for high-performance external API calls.
-   **Deployment:** Railway.app

---

## Getting Started Locally

### Prerequisites

-   Python 3.10+
-   PostgreSQL (with `pgvector` extension enabled)
-   Redis
-   A Google AI Studio API Key.

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/zichdan/hng-stage-3-agent.git
cd hng-stage-3-agent

# Create and activate a virtual environment
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the project root. You can copy the `env.example` file. It must contain the following keys:

```ini
# Django Settings
SECRET_KEY=your-django-secret-key
DEBUG=True
DATABASE_URL=postgres://user:password@host:port/dbname
REDIS_URL=redis://localhost:6379/0

# AI Service API Keys
GEMINI_API_KEY=your-google-ai-api-key

# News API Keys (Optional but Recommended)
FINNHUB_API_KEY=your-finnhub-api-key
ALPHA_VANTAGE_API_KEY=your-alpha-vantage-api-key
```

### 3. Set Up the Database

Connect to your PostgreSQL database and ensure the `pgvector` extension is enabled:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
Then, run the Django migrations:
```bash
python manage.py makemigrations
python manage.py migrate
```

### 4. Running the Application

You need to run three separate processes in three separate terminals.

**Terminal 1: Run the Django Development Server**
```bash
python manage.py runserver
```

**Terminal 2: Run the Celery Worker**
```bash
celery -A core worker --loglevel=info
```

**Terminal 3: Run the Celery Beat Scheduler**
```bash
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```
The application is now running locally, and the background tasks will automatically start populating the knowledge base.

---

## API Endpoints & Usage

The agent exposes two distinct endpoints, both using the `POST` method.

#### 1. RAG Agent (Knowledge Base Search)
This is the primary agent that uses the internal database for accurate, context-aware answers.

-   **URL:** `/api/v1/a2a/forex-compass`

#### 2. Direct Agent (Normal Search)
This agent is for faster, general-purpose conversation and bypasses the database.

-   **URL:** `/api/v1/direct/agent/forex-compass-direct`

### Example Request Body

Use this JSON payload in a tool like Postman to test either endpoint.

```json
{
  "jsonrpc": "2.0",
  "id": "postman-test-001",
  "method": "message/send",
  "params": {
    "taskId": "task-test-123",
    "contextId": "convo-test-abc-123",
    "configuration": { "blocking": true },
    "message": {
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "What is leverage in forex?"
        },
        {
          "kind": "data",
          "data": []
        }
      ]
    }
  }
}
```

---

## Telex.im Integration

To add this agent as a "colleague" in Telex.im, use the following workflow JSON, replacing the `url` with your deployed endpoint.

```json
{
  "active": true,
  "category": "Education",
  "description": "Your AI mentor for answering beginner questions about forex trading.",
  "id": "forex-compass-agent-001",
  "long_description": "I am Forex Compass, an AI mentor that provides clear answers to beginner questions about the forex market, leveraging a curated knowledge base or general knowledge when needed. I will NEVER give financial advice.",
  "name": "forex_compass_agent",
  "nodes": [
    {
      "id": "forex_compass_node",
      "name": "Forex Compass Agent",
      "type": "a2a/mastra-a2a-node",
      "url": "https://hng-stage-3-agent-production.up.railway.app/api/v1/a2a/forex-compass"
    }
  ],
  "short_description": "An AI mentor for forex trading beginners."
}
```
```
