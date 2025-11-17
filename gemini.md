# Gemini Code Assistant Project Overview

This document provides a comprehensive overview of the Reddit Moderator Bot project, designed to help Gemini understand its structure, purpose, and operational procedures.

## 1. Project Purpose

This project is a Python-based Reddit bot that monitors specified subreddits for new submissions. It applies a configurable set of rules to each new post, automatically removing, approving, or replying to submissions based on those rules. It is designed for extensibility and robust operation, featuring structured logging, a health/metrics endpoint, and graceful shutdown capabilities.

The bot can be run directly using Python or as a Docker container.

## 2. Key Technologies

- **Language:** Python 3
- **Core Reddit Integration:** `praw`
- **Dependencies:** `python-dotenv` (for environment variable management), `better-profanity` (for content filtering), `pytz`.
- **Containerization:** Docker and Docker Compose

## 3. Project Structure

The project is organized into several key directories and files:

```
reditbot/
├── .env                  # Environment variables (user-created)
├── .gitignore
├── docker-compose.yml    # Docker Compose configuration
├── Dockerfile            # Docker build instructions
├── README                # Project documentation
├── reddit.py             # Main application entry point
├── requirements.txt      # Python dependencies
├── seen_submissions.json # Cache of processed submission IDs
│
├── rules/
│   ├── handle_posts.py      # Core moderation logic for submissions
│   └── subreddit_rules.json # JSON configuration for subreddit-specific rules
│
├── utilities/
│   ├── globals.py        # Global objects (e.g., Reddit instance)
│   ├── ratelimiter.py    # PRAW API rate limiting helper
│   └── spam_offensive.py # Spam and offensive content detection logic
│
└── logs/
    └── log.py            # Logging configuration (though some modules use local logging)
```

- **`reddit.py`**: The main executable. It initializes the bot, starts the health check server, and spawns monitoring threads for each configured subreddit. It also manages graceful shutdown.
- **`rules/handle_posts.py`**: Contains the `handle_submission` function, which is the central logic for processing each new Reddit post. It checks the post against rules like rate limits, account age, karma, NSFW content, and banned patterns.
- **`rules/subreddit_rules.json`**: A crucial configuration file where you define the moderation rules for each subreddit the bot monitors.
- **`utilities/`**: A package of helper modules for tasks like rate limiting, content analysis, and managing global state.
- **`Dockerfile` & `docker-compose.yml`**: Files for building and running the bot in a containerized environment.
- **`requirements.txt`**: Lists all Python packages required to run the project.

## 4. Setup and Execution

### 4.1. Configuration

1.  **Create a `.env` file** in the `reditbot/` directory.
2.  **Add Reddit API Credentials** and other settings to the `.env` file. Refer to the `README` for the full list of required and optional variables. At a minimum, you will need:
    ```
    CLIENT_ID="your_client_id"
    CLIENT_SECRET="your_client_secret"
    USER_AGENT="your_user_agent"
    USERNAME="your_bot_username"
    PASSWORD="your_bot_password"
    SUBREDDIT="subreddit1,subreddit2"
    ```
3.  **Configure Moderation Rules** by editing `rules/subreddit_rules.json`.

### 4.2. Running the Bot

#### Local Python Execution

1.  **Set up a virtual environment:**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the bot:**
    ```bash
    python reddit.py
    ```

#### Docker Execution

1.  Ensure Docker and Docker Compose are installed.
2.  Run the helper script (if available) or use Docker Compose directly:
    ```bash
    # Using the provided script
    ./reddit.sh

    # Or manually with Docker Compose
    docker-compose up --build
    ```

## 5. Core Commands & Workflows

### Modifying Moderation Logic

- To change how submissions are handled, edit the `handle_submission` function in **`rules/handle_posts.py`**.
- To add, remove, or change rules for a specific subreddit, modify the **`rules/subreddit_rules.json`** file.

### Checking Bot Health

- The bot exposes a health and metrics endpoint. By default, it is available at `http://127.0.0.1:8520/health`.
- You can query it with `curl http://127.0.0.1:8520/health` to see uptime, processed submissions, and other operational data.

### Viewing Logs

- The bot logs to the console by default.
- When running with Docker, you can view logs using `docker-compose logs -f`.
- The logging behavior can be customized in the `logs/` directory or directly within the modules.
