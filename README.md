# EcomAssist 2.0 – Multi-Agent AI-Powered E-Commerce Customer Support and Analytics Assistant

## About the Project

**EcomAssist 2.0 is an AI-powered e-commerce customer support chatbot that helps customers manage shopping and order-related queries through natural language conversations.**

Customers often need to navigate multiple pages or contact customer support to track orders, request returns, report problems or find answers to common questions. EcomAssist brings these activities together through a conversational interface.

Customers can interact with the chatbot to:

- Retrieve order details and delivery information.
- View their previous orders.
- Check whether products are eligible for return.
- Initiate return requests for eligible products.
- Register complaints and check their status.
- Ask frequently asked questions.
- Analyse their spending, orders and product purchases.

The application combines **Flask, LangChain, LangGraph, Groq and PostgreSQL** to provide an integrated customer support and analytics experience.

It uses a combination of LLM-powered agents, deterministic Python workflows and database-backed tools to process customer requests.

## Key Features

### 1. Customer Authentication
- Customer login using email and password.
- Password hash verification.
- Session management using Flask-Login.
- Protected chatbot and customer-specific operations.
- Active account validation.

### 2. Order Management
- Retrieve individual order details.
- Check order and delivery information.
- View a customer's order history.
- Retrieve products associated with an order.
- Support order-related follow-up questions.

### 3. Return and Refund Management
- Check return eligibility for individual products.
- Retrieve orders containing return-eligible products.
- Select an order and a specific product for return.
- Collect the customer's reason for returning a product.
- Recheck eligibility before creating a return.
- Create return requests and provide confirmation details.
- Retrieve existing return status information.

### 4. Complaint Management
- Validate an order before accepting a complaint.
- Check complaint eligibility.
- Check for existing active complaints to prevent duplicate registrations.
- Collect complaint descriptions through a conversational workflow.
- Register complaints.
- Retrieve complaint status using a complaint ID or order ID.

### 5. FAQ Assistance
- Answer frequently asked questions.
- Retrieve relevant FAQ information using semantic search.
- Use Sentence Transformers to generate embeddings.
- Use the FAQ data stored in `data/faqs.csv`.

### 6. Customer Analytics
- Analyse customer spending patterns.
- Retrieve category-wise spending.
- Analyse spending trends over time.
- Retrieve top-purchased products.
- Explore order history and order statistics.
- Analyse orders over specified date ranges.
- Generate chart specifications based on actual analytics results.
- Return chart data for frontend visualisation.

### 7. Multi-Agent AI Architecture
- Use a supervisor node for request classification and routing.
- Coordinate six specialised LangGraph workflow nodes.
- Use LLM-powered FAQ and Complaint agents.
- Execute deterministic Python workflows for order and return operations.
- Use database-backed tools to retrieve and process customer information.
- Maintain conversational context during multi-step interactions.

---

## Application Workflow

The following diagram illustrates the actual EcomAssist 2.0 architecture, including Flask-managed workflows, LangGraph routing, specialised nodes, database tools and analytics processing.

![EcomAssist 2.0 Workflow Architecture](docs/EcomAssist%202.0%20Workflow%20Architecture.png)

### Workflow Explanation

**Step 1 – Customer Authentication**

Customers access the application through the login page. Flask-Login validates their account against the `customer_accounts` table, verifies the password hash and checks whether the account is active.

After successful authentication, a customer session is established and the chatbot becomes accessible.

**Step 2 – Customer Query Processing**

The customer submits a message through the chatbot interface. Flask processes the request, extracts relevant identifiers such as order IDs and complaint IDs, and maintains conversation state using the session.

**Step 3 – Direct Flask Workflows**

Some operations are handled directly by Flask before invoking LangGraph.

These include:

- Multi-step return requests, including order selection, product selection, reason collection, eligibility rechecking and return creation.
- Complaint registration, including order validation, complaint eligibility checks, duplicate complaint checks and complaint description collection.

**Step 4 – LangGraph Workflow**

Requests that are not completed through the direct Flask workflows are passed to the compiled LangGraph workflow.

The graph starts with the Supervisor Node, which classifies the request and routes it to one of six destination nodes.

**Step 5 – Specialised Workflow Nodes**

The compiled LangGraph workflow contains the following six nodes:

| Node | Responsibility |
|---|---|
| Order Node | Retrieves order details and associated return information using database tools. |
| My Orders Node | Retrieves and summarises the authenticated customer's order history. |
| FAQ Node | Uses the FAQ agent to retrieve relevant answers through semantic search. |
| Complaint Node | Uses the Complaint agent to handle complaint-related requests and follow-ups. |
| Return/Refund Node | Handles return and refund status enquiries and return-related operations. |
| Analytics Node | Executes analytics tools to retrieve customer spending, order and product information. |

**Step 6 – Database and Tool Execution**

The relevant workflow uses its database-backed tools to retrieve or process information from PostgreSQL.

The database contains customer accounts, customers, orders, order items, products, payments, shipments, returns and complaints.

The FAQ functionality also uses `data/faqs.csv` and Sentence Transformer embeddings for semantic retrieval.

**Step 7 – Response Generation**

The graph returns the result to Flask.

Flask formats the response and returns it to the frontend. For analytics requests, it additionally generates a chart specification and extracts the corresponding chart rows.

**Step 8 – Frontend Visualisation**

The chatbot displays the conversational answer. When suitable analytics chart information is available, the frontend uses Chart.js to render the visualisation.

---

## Understanding the Multi-Agent Architecture

EcomAssist combines LLM-powered agents with deterministic workflow nodes. Not every graph node is an independent AI agent.

### Supervisor Node

The Supervisor Node uses a Groq-hosted language model with structured output and routing rules to classify customer requests.

It identifies one of the following six supported intents:

| Intent | Destination |
|---|---|
| `order` | Order Node |
| `my_orders` | My Orders Node |
| `faq` | FAQ Node |
| `return_refund` | Return/Refund Node |
| `complaint` | Complaint Node |
| `analytics` | Analytics Node |

The supervisor uses explicit intent information when provided by Flask, deterministic phrase and ordinal rules where applicable, and model-based classification for other requests.

### LLM-Powered Agents

The application defines three agents in `agents/order_agents.py`:

- **Order Support Agent:** Defined with order-related tools, but not currently connected to the compiled LangGraph workflow.
- **FAQ Agent:** Used by the FAQ Node to answer questions using FAQ retrieval.
- **Complaint Agent:** Used by the Complaint Node to process complaint-related requests.

### Deterministic Workflow Nodes

The compiled graph also contains Python workflow nodes that execute application logic and database tools directly.

These include:

- Order Node.
- My Orders Node.
- Return/Refund Node.

The Analytics Node uses a custom tool-calling workflow to select and execute relevant analytics tools.

**Architecture clarification:** Although an Order Support Agent is defined in the project, the compiled graph currently uses a dedicated `order_node()` function rather than invoking that agent. The active Order Node executes Python logic and calls database tools directly.

Similarly, some return and complaint registration steps are handled directly in Flask before LangGraph is invoked.

---

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
| Environment Configuration | python-dotenv |
| Data Processing | Pandas, NumPy |
| FAQ Semantic Search | Sentence Transformers |
| Data Validation | Python |
| Frontend | HTML, CSS, JavaScript |
| Chart Visualisation | Chart.js |

---

## Project Structure

```text
Multi-Agent-AI-Powered-E-Commerce-Customer-Support-and-Analytics-Assistant/
│
├── agents/
│   ├── __init__.py
│   └── order_agents.py
│
├── data/
│   ├── __init__.py
│   ├── faqs.csv
│   ├── inspect_dataset.py
│   └── validate_dataset.py
│
├── docs/
│   ├── DATABASE_SETUP.md
│   ├── REPOSITORY_CLEANUP.md
│   ├── design.md
│   ├── ux-contract.md
│   └── ecomassist_workflow.png
│
├── graph/
│   ├── __init__.py
│   └── graph.py
│
├── scripts/
│   ├── __init__.py
│   ├── create_test_account.py
│   ├── reset_test_password.py
│   │
│   └── manual_checks/
│       ├── __init__.py
│       ├── check_analytics.py
│       └── check_database_tables.py
│
├── templates/
│   ├── design.md
│   ├── ecom_index.html
│   ├── login.html
│   └── ux-contract.md
│
├── tools/
│   ├── __init__.py
│   ├── analytics_tools.py
│   └── order_tools.py
│
├── app.py
├── db.py
├── .env.example
├── .gitignore
├── LICENSE
├── requirements.txt
└── README.md
```

---

## Requirements

Before running the application, make sure you have:

- Python 3.11 or newer.
- PostgreSQL installed and running.
- A Groq API key.
- The required PostgreSQL database and tables.
- The dataset files required by the application.

Python 3.12 is a sensible starting point. Other Python versions may require dependency compatibility checks.

---

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

Upgrade pip and install the required packages:

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

The application uses the following environment variables:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | API key for the Groq-hosted language model |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | PostgreSQL database name |
| `DB_USER` | PostgreSQL username |
| `DB_PASSWORD` | PostgreSQL password |
| `FLASK_SECRET_KEY` | Flask session signing key |
| `COOKIE_SECURE` | Enables secure cookies when deployed over HTTPS |
| `FLASK_DEBUG` | Controls Flask debug mode during local development |

Example configuration:

```env
GROQ_API_KEY=your_groq_api_key

DB_HOST=localhost
DB_PORT=5432
DB_NAME=ecomassist_v2
DB_USER=postgres
DB_PASSWORD=your_database_password

FLASK_SECRET_KEY=your_long_random_secret
COOKIE_SECURE=false
FLASK_DEBUG=false
```

Never upload your actual `.env` file or expose API keys and database credentials.

### 5. Configure PostgreSQL

EcomAssist uses a PostgreSQL database named:

```text
ecomassist_v2
```

The application expects tables for:

- `customer_accounts`
- `customers`
- `orders`
- `order_items`
- `products`
- `payments`
- `shipments`
- `returns`
- `complaints`

The database must be configured and populated before the application can fully operate.

Refer to [Database Setup](docs/DATABASE_SETUP.md) for further information.

**Important:** The repository does not currently contain a complete SQL schema or migration script. You must obtain the original database schema or create a reviewed schema based on the SQL queries used by the application and tools.

### 6. Prepare the dataset

The FAQ functionality reads:

```text
data/faqs.csv
```

The larger e-commerce dataset CSV exports are intentionally excluded from the repository.

Download the required dataset files from their original source, verify the applicable licence and attribution requirements, and place the files in the local `data/` directory before importing them into PostgreSQL.

The repository includes dataset inspection and validation utilities:

```bash
python data/inspect_dataset.py
```

```bash
python data/validate_dataset.py
```

Run these utilities after placing the required dataset files in `data/`.

### 7. Run the application

From the project root, execute:

```bash
python app.py
```

Open the local address printed by Flask in your browser.

Flask debug mode is disabled by default. Enable it only for local development and never in production.

---

## Utility and Testing Scripts

The project includes additional scripts for development and database checks.

### Account Management

Create a test customer account:

```bash
python -m scripts.create_test_account
```

Reset a test customer's password:

```bash
python -m scripts.reset_test_password
```

These scripts require a configured PostgreSQL database and should only be used for controlled development or administrative purposes.

### Manual Database and Analytics Checks

Check the database tables:

```bash
python -m scripts.manual_checks.check_database_tables
```

Run analytics checks:

```bash
python -m scripts.manual_checks.check_analytics
```

Run these scripts from the project root with the required database configuration.

---

## Security Considerations

- Never commit `.env` files, API keys or database credentials.
- Use a strong and unique Flask secret key.
- Keep Flask debug mode disabled in production.
- Enable secure session cookies when deploying over HTTPS.
- Do not upload real customer records, private database exports or backups.
- Maintain customer authorisation checks for customer-specific operations.
- Use appropriately licensed datasets and follow their redistribution conditions.

---

## Current Verification Status

The Python source files were syntax-checked during repository preparation. This does not establish that the complete application starts successfully or that every database-backed workflow works correctly.

Full application verification requires:

- A configured PostgreSQL database.
- The expected database schema and records.
- Correct environment variables.
- Installed Python dependencies.
- A valid Groq API key.
- Testing of login, order support, returns, complaints, FAQ retrieval and analytics workflows.

The project should be tested in a fresh local environment before being considered production-ready.

---

## Future Enhancements

Potential areas for further development include:

- Connecting the defined Order Support Agent to the compiled LangGraph workflow.
- Expanding specialised agent capabilities.
- Improving conversational context and memory.
- Adding further customer support workflows.
- Enhancing analytics and reporting.
- Exploring Model Context Protocol (MCP) integration.

---

## Licence

This project is licensed under the **MIT License**.

Copyright (c) 2026 Nihar Arun Nandanwar (niharn02).

See the [LICENSE](LICENSE) file for the complete licence terms.

The MIT License applies to the project's original code. Third-party libraries, language models and external datasets remain subject to their respective licences and terms.
