# EcomAssist 2.0 – Database Setup

## Database

EcomAssist uses PostgreSQL for storing and retrieving application data.

**Database name:** `ecomassist_v2`

## Prerequisites

- PostgreSQL installed and running.
- Access to the EcomAssist database.
- Python dependencies installed from `requirements.txt`.

## Configuration

Configure the following environment variables in your local `.env` file:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ecomassist_v2
DB_USER=your_postgres_username
DB_PASSWORD=your_postgres_password
```

## Dataset

The application uses the Indian E-Commerce Sales & Customer Analytics dataset.

Source: https://www.kaggle.com/datasets/shiyalkishan01/indian-e-commerce-sales-and-customer-analytics

Download the dataset from Kaggle and follow the database import instructions provided with the project.

## Note

The database schema and import instructions must match the SQL queries and table definitions used by the current application. Refer to the project source code when configuring the database.
