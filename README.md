# EcomAssist 2.0

EcomAssist is a Flask-based e-commerce customer-support chatbot backed by PostgreSQL. It uses LangGraph to orchestrate support workflows and LangChain agents/tools for order support, complaints, FAQs and customer analytics. The language model is accessed through Groq.

## Features

- Customer login and session-based authentication with Flask-Login.
- Order detail and delivery-status lookup.
- Return eligibility and return-related support.
- Complaint creation and complaint-status lookup.
- FAQ search using sentence-transformer embeddings.
- Customer spending, order and product analytics.
- Analytics chart specifications returned to the web frontend.

## Technology stack

- Python and Flask
- LangChain and LangGraph
- Groq API (`openai/gpt-oss-20b` model configured in the application)
- PostgreSQL with Psycopg 3
- Pandas, NumPy and Sentence Transformers
- HTML, CSS and JavaScript templates

## Project structure

```text
EcomAssist_2.0/
├── agents/                 # LangChain agent definitions and prompts
├── data/                   # FAQ data and dataset validation utility
├── graph/                  # LangGraph workflow and routing
├── scripts/                # Account administration and manual checks
├── templates/              # Flask HTML templates
├── tools/                  # Database-backed LangChain tools
├── app.py                  # Flask application entry point
├── db.py                   # PostgreSQL connection helper
├── .env.example            # Environment variable template
├── requirements.txt        # Python dependencies
└── README.md
```

## Requirements

- Python 3.11 or newer (Python 3.12 is a sensible starting point; newer versions may require dependency compatibility checks).
- PostgreSQL.
- A Groq API key.
- The EcomAssist database tables and dataset described below.

## Setup

1. Clone the repository and enter the project directory:

   ```bash
   git clone <YOUR_GITHUB_REPOSITORY_URL>
   cd EcomAssist_2.0
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Create your local environment file:

   ```bash
   # Windows PowerShell
   Copy-Item .env.example .env
   # macOS / Linux
   cp .env.example .env
   ```

   Edit `.env` and supply your own Groq API key, PostgreSQL credentials and a strong `FLASK_SECRET_KEY`. Never commit `.env`.

5. Create/configure the PostgreSQL database and load the required dataset. See [Database and dataset setup](docs/DATABASE_SETUP.md).

6. Start the Flask application from the project root:

   ```bash
   python app.py
   ```

   Debug mode is disabled by default. For local development only, set `FLASK_DEBUG=true` in `.env` if you need Flask's debugger. Never enable Flask debug mode in production. Open the local address printed by Flask in your browser.

## Utility scripts

The account-management scripts are intended for controlled development/admin use and require a configured database:

```bash
python -m scripts.create_test_account
python -m scripts.reset_test_password
```

Manual database checks are available under `scripts/manual_checks/` and should be run as Python modules from the project root.

## Database and dataset

The application expects an `ecomassist_v2` PostgreSQL database. It uses customer, account, order, order-item, product, payment, shipment and return data. The current repository does not include a complete database schema/migration script, so the database tables must be created and populated separately before the application can be fully exercised. Refer to `docs/DATABASE_SETUP.md`.

The project uses the following Kaggle dataset:

- **Dataset:** [Indian E-Commerce Sales & Customer Analytics](https://www.kaggle.com/datasets/shiyalkishan01/indian-e-commerce-sales-and-customer-analytics)
- **Kaggle publisher:** `shiyalkishan01`
- **Platform:** Kaggle

The dataset CSV exports have intentionally been left out of this GitHub repository to keep the source-code repository lightweight. Download the dataset from the original Kaggle page and place the required CSV files in `data/` locally, following [Database and dataset setup](docs/DATABASE_SETUP.md).

**Licence note:** The dataset's exact licence and redistribution conditions must be checked on its Kaggle page before redistributing the CSV files or using them in a way beyond the licence's permissions. A dataset being publicly viewable or downloadable does not, by itself, mean it is public domain. This repository therefore links to the original source rather than republishing the dataset files.

`data/faqs.csv` is retained because the FAQ tool loads it at application startup.

## Environment variables

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | API key for the Groq-hosted language model |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | Database name (default used by the project: `ecomassist_v2`) |
| `DB_USER` | PostgreSQL username |
| `DB_PASSWORD` | PostgreSQL password |
| `FLASK_SECRET_KEY` | Flask session signing key |
| `COOKIE_SECURE` | Set to `true` when deployed over HTTPS |

## Security notes

- Do not commit `.env`, credentials, customer exports, database backups or production data.
- Use a unique, strong `FLASK_SECRET_KEY` outside local development.
- Enable secure cookies when deploying behind HTTPS.
- Keep customer authorization checks in place for all customer-specific tools.
- Do not expose database credentials or API keys in logs or screenshots.

## Current verification status

The Python source files were syntax-checked during repository preparation. This does not confirm that the full application starts or that database-backed workflows work: those checks require a configured PostgreSQL database, the expected schema/data and a valid Groq API key.

## License

No project licence has been selected. Add a licence file only after deciding how you want others to use, modify and redistribute this project.
