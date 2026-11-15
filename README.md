# EcomAssist 2.0 – Multi-Agent AI-Powered E-Commerce Customer Support and Analytics Assistant

## About the Project

**EcomAssist 2.0 is an AI-powered e-commerce customer support chatbot that helps customers manage their shopping and order-related queries through natural language conversations.**

In a typical e-commerce platform, customers may need to navigate multiple pages or contact customer support to track an order, request a return, register a complaint or find answers to common questions.

EcomAssist aims to simplify this experience by bringing these activities into one conversational interface.

Customers can interact with the chatbot to:

- Check order details and delivery status.
- Check whether products are eligible for return.
- Initiate return requests for eligible products.
- Register complaints and check their status.
- Ask frequently asked questions.
- Explore their spending, order and product analytics.

The application uses a **multi-agent architecture** with LangChain and LangGraph. Different support and analytics capabilities are coordinated through a workflow that processes customer requests and directs them to the relevant functionality.

PostgreSQL provides the underlying customer and e-commerce data, while Groq provides access to the language model used by the application.

The goal is to make e-commerce customer support more conversational, accessible and efficient.

## Application Workflow

The following diagram illustrates how a customer request moves through the EcomAssist application.

![EcomAssist 2.0 Application Workflow](docs/ecomassist_workflow.png)

### Workflow Overview

1. **Customer authentication:** Customers log in using their registered email and password. Flask-Login manages authenticated sessions.
2. **Message submission:** Customers submit questions through the chatbot interface.
3. **Request processing:** Flask extracts relevant information, identifies common request types and maintains conversation state.
4. **Workflow handling:** Order, return and complaint requests are processed through their respective application workflows. Other requests are passed to LangGraph for further routing.
5. **Agent and tool execution:** The relevant workflow uses specialised agents and tools to retrieve information or perform supported operations.
6. **Database interaction:** PostgreSQL supplies the required customer, order, product, payment, shipment and return information.
7. **Response generation:** The application returns a conversational response to the customer.
8. **Analytics visualisation:** For analytics requests, the backend also returns analytical results and chart specifications for frontend visualisation.

## Key Features

### 1. Customer Authentication
- Customer login using email and password.
- Password hash verification.
- Session-based authentication using Flask-Login.
- Protected chatbot and customer-specific operations.

### 2. Order Management
- Retrieve order details.
- Check order and delivery status.
- Retrieve products associated with an order.
- Support order-related follow-up questions.

### 3. Return and Refund Assistance
- Check return eligibility for individual products.
- List orders containing products eligible for return.
- Select a particular order and product.
- Collect the reason for a return.
- Create a return request after validating eligibility.
- Check the status of existing return requests.

### 4. Complaint Management
- Validate an order before registering a complaint.
- Check complaint eligibility.
- Collect complaint details through a conversational workflow.
- Prevent duplicate active complaints for an order.
- Register complaints through the complaint workflow.
- Retrieve existing complaint status.

### 5. FAQ Assistance
- Retrieve answers to frequently asked questions.
- Use sentence-transformer embeddings for FAQ retrieval.
- Use the FAQ data provided in `data/faqs.csv`.

### 6. Customer Analytics
- Analyse customer spending patterns.
- Explore order history and purchasing activity.
- Retrieve product-related analytics.
- Generate chart specifications based on analytical results.
- Return chart data for frontend visualisation.

### 7. Multi-Agent AI Architecture
- Coordinate different support and analytics workflows.
- Route general requests through LangGraph.
- Use specialised agents and database-backed tools.
- Maintain conversational context for multi-step operations.
- Combine deterministic application logic with AI-driven request processing.

## Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python |
| Backend Framework | Flask |
| Authentication | Flask-Login |
| Agent Framework | LangChain |
| Workflow Orchestration | LangGraph |
| Language Model Provider | Groq |
| Configured Language Model | `openai/gpt-oss-20b` |
| Database | PostgreSQL |
| Database Driver | Psycopg 3 |
| Data Processing | Pandas, NumPy |
| FAQ Retrieval | Sentence Transformers |
| Frontend | HTML, CSS, JavaScript |
| Chart Visualisation | Chart.js |

## Project Structure

```text
Multi-Agent-AI-Powered-E-Commerce-Customer-Support-and-Analytics-Assistant/
│
├── agents/
│   └── order_agents.py
│
├── data/
│   └── faqs.csv
│
├── docs/
│   ├── DATABASE_SETUP.md
│   ├── design.md
│   ├── ux-contract.md
│   └── ecomassist_workflow.png
│
├── graph/
│   └── graph.py
│
├── templates/
│   ├── ecom_index.html
│   └── login.html
│
├── tools/
│   ├── order_tools.py
│   └── analytics_tools.py
│
├── app.py
├── db.py
├── .env.example
├── .gitignore
├── LICENSE
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.11 or newer.
- PostgreSQL.
- A Groq API key.
- The EcomAssist PostgreSQL database and required tables.
- The dataset used by the application.

Python 3.12 is a sensible starting point. Other Python versions may require dependency compatibility checks.

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/niharn02/Multi-Agent-AI-Powered-E-Commerce-Customer-Support-and-Analytics-Assistant.git

cd Multi-Agent-AI-Powered-E-Commerce-Customer-Support-and-Analytics-Assistant
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate the environment.

**Windows PowerShell**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip

pip install -r requirements.txt
```

### 4. Configure environment variables

Create a local `.env` file using the example configuration.

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux**

```bash
cp .env.example .env
```

Open `.env` and provide your own credentials.

The application uses the following configuration:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | API key for the Groq language model |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | Database name |
| `DB_USER` | PostgreSQL username |
| `DB_PASSWORD` | PostgreSQL password |
| `FLASK_SECRET_KEY` | Flask session signing key |
| `COOKIE_SECURE` | Enables secure cookies over HTTPS |
| `FLASK_DEBUG` | Controls Flask debug mode for local development |

Refer to `.env.example` for the configuration template.

Never commit your actual `.env` file or expose API keys and database credentials.

### 5. Configure PostgreSQL

EcomAssist uses a PostgreSQL database named:

```text
ecomassist_v2
```

The database must contain the tables and records expected by the application.

Refer to [DATABASE_SETUP.md](docs/DATABASE_SETUP.md) for the database and dataset setup information.

**Important:** The repository does not currently include a complete database schema or migration script. The database must be created and populated separately before all application features can be tested.

### 6. Run the application

From the project root, execute:

```bash
python app.py
```

Open the local address printed by Flask in your browser.

Debug mode is disabled by default. Enable it only for local development, never in production.

## Database and Dataset

The application uses PostgreSQL to store and retrieve information related to:

- Customer accounts.
- Customers.
- Orders.
- Order items.
- Products.
- Payments.
- Shipments.
- Returns.
- Complaints.

The project uses the following dataset:

**Indian E-Commerce Sales & Customer Analytics**

- Publisher: `shiyalkishan01`
- Platform: Kaggle
- Dataset: [Indian E-Commerce Sales & Customer Analytics](https://www.kaggle.com/datasets/shiyalkishan01/indian-e-commerce-sales-and-customer-analytics)

The dataset CSV exports are not included in this repository. Download the required files from the original Kaggle page and place them in the local `data/` directory, following the database setup instructions.

The dataset's licence and redistribution conditions must be checked before redistributing its files. Public availability does not automatically mean that a dataset is public domain.

`data/faqs.csv` is included because the FAQ functionality uses it.

## Security Considerations

- Never commit `.env` files, API keys or database credentials.
- Use a strong and unique Flask secret key.
- Enable secure cookies when deploying over HTTPS.
- Do not expose customer information, database backups or private dataset exports.
- Maintain customer authorisation checks for customer-specific operations.
- Keep Flask debug mode disabled in production.

## Current Verification Status

The Python source files were syntax-checked during repository preparation. This does not confirm that the complete application starts successfully or that all database-backed workflows work.

Full application testing requires:

- A configured PostgreSQL database.
- The expected database schema and records.
- Installed Python dependencies.
- A valid Groq API key.
- Verification of the customer support and analytics workflows.

## Future Enhancements

Potential areas for further development include:

- Expanding specialised agent capabilities.
- Adding more customer support workflows.
- Improving conversational context and memory.
- Enhancing analytics and reporting.
- Exploring Model Context Protocol (MCP) integration.

## Licence

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

The MIT License applies to the project's original code. Third-party libraries, language models and external datasets remain subject to their respective licences and terms.
