# The Catalyst 🔥

A personalized AI mentor with living memory, designed to be your partner in achieving extraordinary goals. The Catalyst learns from every conversation, adapts to your personality, and provides uniquely tailored guidance.

## 🚀 Features

-   **Adaptive AI Mentor**: Dynamic personality that shifts between tough coach and wise strategist
-   **Living Memory System**: Two-tier memory that evolves and learns from every interaction

## Features

-   **AI-Powered Conversations** — Interactive chat with customizable session types (morning ignition, evening reflection, catch-up)
-   **Memory Management** — Long-term memory synthesis that learns and adapts to user patterns
-   **Goal Tracking** — Hierarchical goal management with North Star methodology
-   **Daily Logging** — Track wins, challenges, gratitude, energy levels, and focus ratings
-   **Insight Extraction** — Automatic pattern recognition and breakthrough identification
-   **Session Tracking** — Streak counting and completion rate monitoring
-   **Function Calling** — Rich AI interactions with database integration
-   **Rate Limiting & Retry Logic** — Intelligent API quota management with automatic retry on overload errors
-   **Function Calling**: AI can manage its own memory and track your progress
-   **Goal-Agnostic**: Set any ambitious goal and let The Catalyst help you achieve it
-   **Powered by Gemini 2.0**: Latest AI technology with thinking capabilities

## 🛠️ Setup & Installation

### Prerequisites

-   Python 3.9+
-   Google Gemini API key ([Get one here](https://aistudio.google.com/app/apikey))

### Quick Start

1. **Clone and install dependencies**

    ```bash
    git clone <your-repo-url>
    cd TheCatalyst
    pip install -r requirements.txt
    ```

2. **Configure environment variables**

    ```bash
    copy .env.example .env  # Windows
    # or
    cp .env.example .env    # macOS / Linux
    ```

    Edit `.env` and add your `GEMINI_API_KEY` value.

3. **Start the FastAPI backend**

    ```bash
    uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
    ```

4. **Launch the frontend**

    - Open `frontend/index.html` directly in your browser, **or**
    - Serve the frontend: `python -m http.server 3000`

## 🧠 How It Works

### The Core Loop

1. **Initialization**: Set your North Star goal and define success metrics
2. **Morning Ignition**: 5-minute sessions to set daily intentions
3. **Evening Reflection**: 15-minute deep sessions to process the day
4. **Memory Synthesis**: AI automatically updates its understanding of you

### The Living Memory System

-   **Short-term Memory**: Current conversation context
-   **Long-term Memory**: Evolving profile with patterns, breakthroughs, and insights
-   **Function Calling**: AI can call Python functions to manage its own memory

### Personality Modes

-   **Tough Coach** (Default): Direct, challenging, action-oriented
-   **Wise Strategist**: Activated when you need guidance through setbacks
-   **Guardian**: Kicks in when burnout signals are detected

## �️ Project Structure

```
the-catalyst/
├── backend/                 # FastAPI backend
│   ├── app.py               # FastAPI application & routes
│   ├── catalyst_ai.py       # Gemini integration & prompting
│   ├── config.py            # Settings and constants
│   ├── database.py          # SQLAlchemy engine/session helpers
│   ├── functions.py         # Function-calling registry
│   ├── memory_manager.py    # Memory/query utilities
│   ├── models.py            # SQLAlchemy ORM models
│   ├── rate_limiter.py      # API quota management
│   ├── rate_limit_config.py # Rate limiting configuration utilities
│   └── schemas.py           # Pydantic request/response models
├── frontend/
│   ├── index.html         # Chat UI shell
│   ├── app.js             # Frontend logic
│   └── style.css          # Styling
├── prompts/               # Core prompts for the agent
│   ├── system_prompt.txt
│   └── templates.py
├── data/                  # SQLite database (auto-created)
├── app.py                 # Convenience entrypoint for uvicorn
└── tests & scripts        # Developer tooling
```

## 📊 API Endpoints

-   `GET /` – health/metadata
-   `POST /initialize` – set the North Star goal
-   `POST /chat` – primary interaction endpoint
-   `GET /goals` – retrieve ordered goals
-   `GET /stats` – rolling progress metrics
-   `GET /memory/profile` – latest long-term memory snapshot
-   `GET /health` – backend/system health information

## 🎯 Usage Tips

1. **Be honest**: The more authentic you are, the better The Catalyst can help
2. **Daily consistency**: Regular morning and evening sessions maximize effectiveness
3. **Embrace the challenge**: The Catalyst will push you - that's by design
4. **Trust the process**: The memory system needs time to understand your patterns

## 🔧 Configuration

Edit your `.env` file:

```bash
GEMINI_API_KEY=your_api_key_here
SHOW_THINKING=false  # Set to true to see AI's thinking process
DATABASE_PATH=data/catalyst.db

# Rate limiting (optional - defaults are set for Gemini's published limits)
GEMINI_2_5_PRO_RPM=5         # Requests per minute
GEMINI_2_5_PRO_TPM=250000    # Tokens per minute
GEMINI_2_5_PRO_RPD=100       # Requests per day

GEMINI_2_5_FLASH_RPM=10      # Higher limits for Flash model
GEMINI_2_5_FLASH_TPM=250000
GEMINI_2_5_FLASH_RPD=250
```

### Rate Limiting & Retry Logic

The Catalyst automatically manages API usage and handles service overload:

-   **Rate Limiting**: Respects Gemini's quotas (5 RPM for Pro, 10 RPM for Flash)
-   **Intelligent Retries**: Automatically retries on 503 "model overloaded" errors
-   **Model Fallback**: Falls back to Gemini 2.5 Flash when Pro is overloaded
-   **Quota-Aware Retries**: Every retry reserves quota and switches models if the primary is saturated
-   **Exponential Backoff**: Uses smart delays (1s, 2s, 4s...) with jitter to prevent thundering herd

**Default Limits:**

-   **Gemini 2.5 Pro**: 5 RPM, 250K TPM, 100 RPD
-   **Gemini 2.5 Flash**: 10 RPM, 250K TPM, 250 RPD

Rate limits are enforced per model and can be customized via environment variables. The system will automatically queue requests when limits are approached and retry failed requests due to temporary overload.

## 🚨 Troubleshooting

-   **"Connection error"**: Check your Gemini API key and internet connection
-   **Database issues**: Delete `data/catalyst.db` to reset (loses all data)
-   **Frontend not loading**: Try serving with `python -m http.server` from the root directory

## 🤝 Contributing

This is a personal project, but if you're inspired to build something similar:

1. Fork the repository
2. Focus on the function calling system - it's the key to the living memory
3. Experiment with different personality frameworks
4. Consider adding voice interactions or mobile apps

## 📈 Roadmap

-   [ ] Voice interaction support
-   [ ] Mobile app companion
-   [ ] Advanced analytics dashboard
-   [ ] Multi-goal management
-   [ ] Team/coaching features
-   [ ] Integration with productivity tools

---

_"The Catalyst isn't just software - it's your partner in transformation."_
