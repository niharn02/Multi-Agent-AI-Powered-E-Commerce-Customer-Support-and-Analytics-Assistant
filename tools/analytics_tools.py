from db import get_connection
from tools.order_tools import get_authenticated_customer_id
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from langchain_core.tools import tool


# DATE HANDLING: Convert supported date strings to Python date objects.
# If a format does not match, try the next one; raise an error if none match.
def parse_analytics_date(value: str) -> date:
    """Accept DD-MM-YYYY and YYYY-MM-DD date strings."""
    for date_format in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(
        "Invalid date. Use DD-MM-YYYY, for example 01-08-2026."
    )

# LIFETIME SPENDING: Return overall spending totals plus a month-by-month breakdown.
# The two SQL queries calculate totals first, then group eligible orders by month.
def get_customer_spending_summary():
    """
    Retrieve the authenticated customer's total and monthly spending.
    Cancelled orders are excluded.
    """

    # Get the customer ID from the authenticated session.
    # Never accept a customer ID supplied by the LLM.
    customer_id = get_authenticated_customer_id()

    with get_connection() as conn:
        with conn.cursor() as cur:

            # Calculate total spending and eligible order count.
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(final_amount), 0),
                    COUNT(*)
                FROM orders
                WHERE customer_id = %s
                  AND LOWER(TRIM(COALESCE(order_status, '')))
                      NOT IN ('cancelled', 'canceled');
                """,
                (customer_id,)
            )

            total_spending, total_orders = cur.fetchone()

            # Calculate spending for each month.
            cur.execute(
                """
                SELECT
                    TO_CHAR(
                        DATE_TRUNC('month', order_date),
                        'YYYY-MM'
                    ) AS month,
                    COALESCE(SUM(final_amount), 0) AS spending,
                    COUNT(*) AS order_count
                FROM orders
                WHERE customer_id = %s
                  AND LOWER(TRIM(COALESCE(order_status, '')))
                      NOT IN ('cancelled', 'canceled')
                GROUP BY DATE_TRUNC('month', order_date)
                ORDER BY DATE_TRUNC('month', order_date);
                """,
                (customer_id,)
            )

            monthly_rows = cur.fetchall()
    
    return {
        "total_spending": float(total_spending),
        "total_orders": total_orders,
        "average_order_value": (
            float(total_spending) / total_orders
            if total_orders
            else 0.0
        ),
        "monthly_spending": [
            {
                "month": row[0],
                "spending": float(row[1]),
                "order_count": row[2],
            }
            for row in monthly_rows
        ],
    }


# PRODUCT SUMMARY: Combine repeated purchases of each product into one result row.
# Joins connect orders -> order items -> products; totals are calculated per product.
def get_customer_product_summary():
    """Summarise the authenticated customer's product purchases."""

    customer_id = get_authenticated_customer_id()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.product_name,
                    p.category,
                    SUM(oi.quantity) AS quantity_purchased,
                    COALESCE(SUM(oi.item_revenue), 0) AS total_spent
                FROM orders AS o
                JOIN order_items AS oi
                    ON oi.order_id = o.order_id
                JOIN products AS p
                    ON p.product_id = oi.product_id
                WHERE o.customer_id = %s
                  AND LOWER(TRIM(COALESCE(o.order_status, '')))
                      NOT IN ('cancelled', 'canceled')
                GROUP BY p.product_id, p.product_name, p.category
                ORDER BY total_spent DESC, quantity_purchased DESC;
                """,
                (customer_id,)
            )

            rows = cur.fetchall()

    return [
        {
            "product_name": row[0],
            "category": row[1],
            "quantity_purchased": int(row[2]),
            "total_spent": float(row[3]),
        }
        for row in rows
    ]


# CATEGORY SUMMARY: Group the customer's item purchases by product category.
# Missing category names receive a fallback label so those purchases are still counted.
def get_customer_category_summary():
    """Summarise the authenticated customer's spending by category."""

    customer_id = get_authenticated_customer_id()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(p.category, 'Uncategorised') AS category,
                    SUM(oi.quantity) AS quantity_purchased,
                    COALESCE(SUM(oi.item_revenue), 0) AS total_spent
                FROM orders AS o
                JOIN order_items AS oi
                    ON oi.order_id = o.order_id
                JOIN products AS p
                    ON p.product_id = oi.product_id
                WHERE o.customer_id = %s
                  AND LOWER(TRIM(COALESCE(o.order_status, '')))
                      NOT IN ('cancelled', 'canceled')
                GROUP BY COALESCE(p.category, 'Uncategorised')
                ORDER BY total_spent DESC;
                """,
                (customer_id,)
            )

            rows = cur.fetchall()

    return [
        {
            "category": row[0],
            "quantity_purchased": int(row[1]),
            "total_spent": float(row[2]),
        }
        for row in rows
    ]

# SPENDING TRENDS: Build a continuous monthly timeline and compare each month to the previous one.
# If a date range is provided, both dates are required; the end date is exclusive.
def get_customer_spending_trends(
    start_date: str = "",
    end_date: str = "",
):
    """Calculate monthly spending trends, optionally within a date range."""

    customer_id = get_authenticated_customer_id()

    if bool(start_date) != bool(end_date):
        raise ValueError("Provide both start_date and end_date, or neither.")

    start = None
    end = None

    # When dates are supplied, use the period-specific helper and reshape its output.
    if start_date and end_date:
        try:
            start = parse_analytics_date(start_date)
            end = parse_analytics_date(end_date)
        except ValueError:
            raise ValueError("Dates must use YYYY-MM-DD format.")

        if start >= end:
            raise ValueError("The end date must be later than the start date.")

    # Build the base SQL query; optional date filters are appended only when supplied.
    query = """
        SELECT
            DATE_TRUNC('month', order_date)::date AS month,
            COALESCE(SUM(final_amount), 0) AS spending,
            COUNT(*) AS order_count
        FROM orders
        WHERE customer_id = %s
          AND LOWER(TRIM(COALESCE(order_status, '')))
              NOT IN ('cancelled', 'canceled')
    """
    params = [customer_id]

    if start and end:
        query += """
          AND order_date >= %s
          AND order_date < %s
        """
        params.extend([start, end])

    query += """
        GROUP BY DATE_TRUNC('month', order_date)
        ORDER BY DATE_TRUNC('month', order_date)
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

    # Index rows by YYYY-MM so each month can be looked up quickly, including empty months.
    monthly_data = {
        row[0].strftime("%Y-%m"): {
            "spending": float(row[1]),
            "order_count": int(row[2]),
        }
        for row in rows
    }

    if start and end:
        first_month = start.replace(day=1)
        # The end date is exclusive. Do not include its month
        # when it is the first day of that month.
        last_month = (end - relativedelta(days=1)).replace(day=1)

        if first_month > last_month:
            return []
    else:
        if not rows:
            return []

        first_month = rows[0][0].replace(day=1)
        last_month = rows[-1][0].replace(day=1)

    # Walk month-by-month; the first month has no previous month for comparison.
    trends = []
    current_month = first_month
    previous_spending = None

    while current_month <= last_month:
        month_key = current_month.strftime("%Y-%m")
        month_data = monthly_data.get(
            month_key,
            {"spending": 0.0, "order_count": 0},
        )

        spending = round(month_data["spending"], 2)

        if previous_spending is None:
            change_amount = None
            change_percentage = None
        else:
            change_amount = round(spending - previous_spending, 2)
            change_percentage = (
                round(change_amount / previous_spending * 100, 2)
                if previous_spending != 0
                else None
            )

        trends.append({
            "month": month_key,
            "spending": spending,
            "order_count": month_data["order_count"],
            "change_from_previous_month": change_amount,
            "change_percentage": change_percentage,
        })

        previous_spending = spending
        current_month += relativedelta(months=1)

    return trends


# CHART DATA: Convert analytics results into labels and values for frontend charts.
def get_customer_analytics_chart_data(
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Prepare chart-ready data for the authenticated customer."""

    if start_date and end_date:
        period_data = get_customer_spending_for_period(
            start_date,
            end_date,
        )

        monthly_data = period_data["monthly_spending"]

        # Fill every month in the requested date range,
        # including months with zero spending.
        from datetime import date

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        current_year = start.year
        current_month = start.month

        labels = []
        values = []
        order_values = []

        monthly_lookup = {
            item["month"]: item
            for item in monthly_data
        }

        while (current_year, current_month) < (end.year, end.month):
            month_label = f"{current_year:04d}-{current_month:02d}"
            labels.append(month_label)

            item = monthly_lookup.get(month_label, {})
            values.append(item.get("spending", 0))
            order_values.append(item.get("order_count", 0))

            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        return {
            "monthly_spending": {
                "labels": labels,
                "values": values,
            },
            "monthly_orders": {
                "labels": labels,
                "values": order_values,
            },
            "category_spending": {
                "labels": [],
                "values": [],
            },
        }

    spending_trends = get_customer_spending_trends()
    category_summary = get_customer_category_summary()

    return {
        "monthly_spending": {
            "labels": [
                item["month"] for item in spending_trends
            ],
            "values": [
                item["spending"] for item in spending_trends
            ],
        },
        "monthly_orders": {
            "labels": [
                item["month"] for item in spending_trends
            ],
            "values": [
                item["order_count"] for item in spending_trends
            ],
        },
        "category_spending": {
            "labels": [
                item["category"] for item in category_summary
            ],
            "values": [
                item["total_spent"] for item in category_summary
            ],
        },
    }


# PERIOD SPENDING: Return totals, monthly spending, and category spending for a date range.
# Three queries are used: overall totals, monthly totals, and category totals.
def get_customer_spending_for_period(
    start_date: str,
    end_date: str,
):
    """
    Retrieve the authenticated customer's spending and order counts
    within a date range. The start date is inclusive and the end
    date is exclusive.
    """
    customer_id = get_authenticated_customer_id()

    # Validate the dates before querying PostgreSQL.
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise ValueError(
            "Dates must use YYYY-MM-DD format."
        )

    if start >= end:
        raise ValueError(
            "The end date must be later than the start date."
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(final_amount), 0),
                    COUNT(*)
                FROM orders
                WHERE customer_id = %s
                  AND order_date >= %s
                  AND order_date < %s
                  AND LOWER(TRIM(COALESCE(order_status, '')))
                      NOT IN ('cancelled', 'canceled');
                """,
                (customer_id, start, end),
            )

            total_spending, total_orders = cur.fetchone()

            cur.execute(
                """
                SELECT
                    DATE_TRUNC('month', order_date)::date AS month,
                    COALESCE(SUM(final_amount), 0) AS spending,
                    COUNT(*) AS order_count
                FROM orders
                WHERE customer_id = %s
                  AND order_date >= %s
                  AND order_date < %s
                  AND LOWER(TRIM(COALESCE(order_status, '')))
                      NOT IN ('cancelled', 'canceled')
                GROUP BY DATE_TRUNC('month', order_date)
                ORDER BY DATE_TRUNC('month', order_date);
                """,
                (customer_id, start, end),
            )

            monthly_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                    COALESCE(p.category, 'Uncategorized') AS category,
                    COALESCE(SUM(oi.item_revenue), 0) AS total_spent

                FROM orders o
                JOIN order_items oi
                    ON oi.order_id = o.order_id
                JOIN products p
                    ON p.product_id = oi.product_id
                WHERE o.customer_id = %s
                AND o.order_date >= %s
                AND o.order_date < %s
                AND LOWER(TRIM(COALESCE(o.order_status, '')))
                    NOT IN ('cancelled', 'canceled')
                GROUP BY COALESCE(p.category, 'Uncategorized')
                ORDER BY total_spent DESC;
                """,
                (customer_id, start, end),
            )

            category_rows = cur.fetchall()

    total_spending = float(total_spending)
    total_orders = int(total_orders)

    return {
        "start_date": start.isoformat(),
        "end_date_exclusive": end.isoformat(),
        "total_spending": round(total_spending, 2),
        "total_orders": total_orders,
        "average_order_value": (
            round(total_spending / total_orders, 2)
            if total_orders else 0.0
        ),
        "monthly_spending": [
            {
                "month": row[0].strftime("%Y-%m"),
                "spending": round(float(row[1]), 2),
                "order_count": int(row[2]),
            }
            for row in monthly_rows
        ],
         "category_spending": [
        {
            "category": row[0],
            "total_spent": round(float(row[1]), 2),
        }
        for row in category_rows
        ],
    }

# TOP PRODUCTS: Rank the customer's products by quantity, revenue, frequency, or average price.
# The selected metric determines the ranking expression; all product metrics are returned.
def get_customer_top_products(
    metric: str = "revenue",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> dict:
    """Rank the authenticated customer's purchased products by a selected metric."""

    from datetime import date

    customer_id = get_authenticated_customer_id()

    # Allowlist supported metric names before selecting a ranking expression.
    allowed_metrics = {
        "quantity",
        "revenue",
        "purchase_frequency",
        "average_price",
    }

    metric = metric.strip().lower()

    if metric not in allowed_metrics:
        return {
            "error": (
                "Unsupported metric. Choose quantity, revenue, "
                "purchase_frequency, or average_price."
            )
        }

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        return {"error": "Limit must be an integer between 1 and 50."}

    if bool(start_date) != bool(end_date):
        return {"error": "Provide both start_date and end_date, or neither."}

    if start_date and end_date:
        try:
            start = parse_analytics_date(start_date)
            end = parse_analytics_date(end_date)

            if end <= start:
                return {"error": "The end date must be later than the start date."}
        except ValueError:
            return {"error": "Invalid dates. Use YYYY-MM-DD format."}

    # Start with a customer-scoped filter; optional filters are added alongside SQL parameters.
    conditions = [
        "o.customer_id = %s",
        "LOWER(o.order_status) NOT IN ('cancelled', 'canceled')",
    ]
    params = [customer_id]

    if start_date and end_date:
        conditions.extend([
            "o.order_date >= %s",
            "o.order_date < %s",
        ])
        params.extend([start_date, end_date])

    # Map each supported metric to a fixed SQL expression; do not use raw model text as SQL.
    metric_expressions = {
        "quantity": "SUM(oi.quantity)",
        "revenue": "SUM(oi.item_revenue)",
        "purchase_frequency": "COUNT(DISTINCT oi.order_id)",
        "average_price": (
            "SUM(oi.item_revenue) / NULLIF(SUM(oi.quantity), 0)"
        ),
    }

    # Run one grouped query, sort by the selected metric, and limit the number of results.
    sql = f"""
        SELECT
            p.product_id,
            p.product_name,
            p.category,
            SUM(oi.quantity) AS quantity_purchased,
            SUM(oi.item_revenue) AS total_revenue,
            COUNT(DISTINCT oi.order_id) AS purchase_frequency,
            SUM(oi.item_revenue) / NULLIF(SUM(oi.quantity), 0)
                AS average_price_paid,
            {metric_expressions[metric]} AS ranking_value
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE {" AND ".join(conditions)}
        GROUP BY p.product_id, p.product_name, p.category
        ORDER BY ranking_value DESC NULLS LAST, p.product_name ASC
        LIMIT %s
    """
    params.append(limit)

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

                products = [
                    {
                        "product_id": row[0],
                        "product_name": row[1],
                        "category": row[2],
                        "quantity_purchased": row[3],
                        "total_revenue": float(row[4] or 0),
                        "purchase_frequency": row[5],
                        "average_price_paid": float(row[6] or 0),
                    }
                    for row in rows
                ]

                return {
                    "metric": metric,
                    "start_date": start_date or None,
                    "end_date": end_date or None,
                    "limit": limit,
                    "product_count": len(products),
                    "products": products,
                }
        finally:
            conn.close()

    except Exception:
        import logging
        logging.exception("Failed to retrieve customer top products")
        return {"error": "Unable to retrieve product analytics right now."}


# ORDER LIST: Retrieve individual orders with optional status/date filters and sorting.
def get_customer_order_list(
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
    sort_by: str = "date",
    sort_order: str = "desc",
    include_cancelled: bool = True,
) -> dict:
    """Retrieve individual orders for the authenticated customer."""

    from datetime import date
    import logging

    customer_id = get_authenticated_customer_id()

    allowed_statuses = {
        "pending",
        "processing",
        "shipped",
        "delivered",
        "cancelled",
        "canceled",
    }

    status = status.strip().lower()

    if status and status not in allowed_statuses:
        return {
            "error": (
                "Unsupported status. Choose pending, processing, shipped, "
                "delivered, or cancelled."
            )
        }

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        return {"error": "Limit must be an integer between 1 and 100."}

    # Only these exact values are accepted, because they select SQL fragments below.
    sort_by = str(sort_by).strip().lower()
    sort_order = str(sort_order).strip().lower()

    if sort_by not in {"date", "amount"}:
        return {"error": "sort_by must be 'date' or 'amount'."}

    if sort_order not in {"asc", "desc"}:
        return {"error": "sort_order must be 'asc' or 'desc'."}

    if bool(start_date) != bool(end_date):
        return {
            "error": "Provide both start_date and end_date, or neither."
        }

    if start_date and end_date:
        try:
            start = parse_analytics_date(start_date)
            end = parse_analytics_date(end_date)

            if end <= start:
                return {
                    "error": "The end date must be later than the start date."
                }
        except ValueError:
            return {
                "error": "Invalid dates. Use YYYY-MM-DD format."
            }

    conditions = ["o.customer_id = %s"]
    params = [customer_id]

    if status:
        if status in {"cancelled", "canceled"}:
            conditions.append(
                "LOWER(o.order_status) IN ('cancelled', 'canceled')"
            )
        else:
            conditions.append("LOWER(o.order_status) = %s")
            params.append(status)

    # Ranking questions ("most expensive orders") normally exclude cancelled orders.
    if not include_cancelled and not status:
        conditions.append(
            "LOWER(o.order_status) NOT IN ('cancelled', 'canceled')"
        )

    if start_date and end_date:
        conditions.extend([
            "o.order_date >= %s",
            "o.order_date < %s",
        ])
        params.extend([start_date, end_date])

    # Sorting direction is chosen from fixed, validated values because it is an SQL keyword.
    direction = "ASC" if sort_order == "asc" else "DESC"

    # Add tie-breakers when sorting by amount so equal-value orders remain consistently ordered.
    if sort_by == "amount":
        order_clause = (
            f"o.final_amount {direction} NULLS LAST, "
            "o.order_date DESC, o.order_id DESC"
        )
    else:
        order_clause = f"o.order_date {direction}, o.order_id {direction}"

    sql = f"""
        SELECT
            o.order_id,
            o.order_date,
            o.order_status,
            o.delivery_city,
            o.delivery_state,
            o.final_amount
        FROM orders o
        WHERE {" AND ".join(conditions)}
        ORDER BY {order_clause}
        LIMIT %s
    """

    params.append(limit)

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

                orders = [
                    {
                        "order_id": row[0],
                        "order_date": (
                            row[1].isoformat()
                            if row[1] is not None
                            else None
                        ),
                        "status": row[2],
                        "delivery_city": row[3],
                        "delivery_state": row[4],
                        "final_amount": float(row[5] or 0),
                    }
                    for row in rows
                ]

                return {
                    "status_filter": status or None,
                    "start_date": start_date or None,
                    "end_date": end_date or None,
                    "limit": limit,
                    "sort_by": sort_by,
                    "sort_order": sort_order,
                    "include_cancelled": include_cancelled,
                    "order_count": len(orders),
                    "orders": orders,
                }
        finally:
            conn.close()

    except Exception:
        logging.exception("Failed to retrieve customer order list")
        return {
            "error": "Unable to retrieve order details right now."
        }

# ORDER ANALYTICS: Count orders by status, with optional date filtering.
def get_customer_order_analytics(
    metric: str = "total",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Return order counts for the authenticated customer."""

    from datetime import date
    import logging

    customer_id = get_authenticated_customer_id()

    allowed_metrics = {
        "total",
        "cancelled",
        "status",
    }

    metric = metric.strip().lower()

    if metric not in allowed_metrics:
        return {
            "error": (
                "Unsupported metric. Choose total, cancelled, or status."
            )
        }

    if bool(start_date) != bool(end_date):
        return {
            "error": "Provide both start_date and end_date, or neither."
        }

    if start_date and end_date:
        try:
            start = parse_analytics_date(start_date)
            end = parse_analytics_date(end_date)

            if end <= start:
                return {
                    "error": "The end date must be later than the start date."
                }
        except ValueError:
            return {
                "error": "Invalid dates. Use YYYY-MM-DD format."
            }

    conditions = ["o.customer_id = %s"]
    params = [customer_id]

    if start_date and end_date:
        conditions.extend([
            "o.order_date >= %s",
            "o.order_date < %s",
        ])
        params.extend([start_date, end_date])

    if metric == "cancelled":
        conditions.append(
            "LOWER(o.order_status) IN ('cancelled', 'canceled')"
        )
    elif metric == "total":
        conditions.append(
            "LOWER(o.order_status) NOT IN ('cancelled', 'canceled')"
        )

    sql = f"""
        SELECT
            LOWER(o.order_status) AS order_status,
            COUNT(*) AS order_count
        FROM orders o
        WHERE {" AND ".join(conditions)}
        GROUP BY LOWER(o.order_status)
        ORDER BY LOWER(o.order_status)
    """

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

                status_counts = {
                    row[0]: row[1]
                    for row in rows
                }

                return {
                    "metric": metric,
                    "start_date": start_date or None,
                    "end_date": end_date or None,
                    "total_orders": sum(status_counts.values()),
                    "status_counts": status_counts,
                }
        finally:
            conn.close()

    except Exception:
        logging.exception("Failed to retrieve customer order analytics")
        return {
            "error": "Unable to retrieve order analytics right now."
        }

# LANGCHAIN TOOLS: @tool exposes these wrappers to the agent.
# Each tool's docstring guides the model on when to use it; the helper does the database work.
@tool
def order_list_tool(
    status: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
    sort_by: str = "date",
    sort_order: str = "desc",
    include_cancelled: bool = True,
) -> dict:
    """Retrieve individual orders for the authenticated customer.

    Use this tool when the user asks for order IDs, order dates,
    individual order details, or a list of orders.

    Use status='shipped', 'delivered', 'pending', 'processing',
    or 'cancelled' to filter by status. Leave status empty for all statuses.

    For lifetime results, leave start_date and end_date empty.
    For a date range, provide both dates in YYYY-MM-DD format.
    The start date is inclusive and the end date is exclusive.

    Use a limit between 1 and 100. The default is 10.

    Sorting is done by the database, so use it for ranking questions:
    - sort_by='date' (default) orders by order date. Use sort_order='desc'
      for newest first and 'asc' for oldest first.
    - sort_by='amount' orders by order value. Use sort_order='desc' for the
      highest-value or most expensive orders and 'asc' for the lowest.
    - For "top N" or "N most expensive orders", set limit=N together with
      sort_by='amount' and sort_order='desc'.
    - Set include_cancelled=False to leave cancelled orders out of a ranking.
    """
    return get_customer_order_list(
        status=status,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        include_cancelled=include_cancelled,
    )


@tool
def order_analytics_tool(
    metric: str = "total",
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Get order counts for the authenticated customer.

    Use metric='total' to count orders excluding cancelled orders.
    Use metric='cancelled' to count cancelled orders only.
    Use metric='status' to get counts grouped by order status.

    For lifetime results, leave start_date and end_date empty.
    For a date range, provide both dates in YYYY-MM-DD format.
    The start date is inclusive and the end date is exclusive.
    """
    return get_customer_order_analytics(
        metric=metric,
        start_date=start_date,
        end_date=end_date,
    )


@tool
def top_products_tool(
    metric: str = "revenue",
    start_date: str = "",
    end_date: str = "",
    limit: int = 10,
) -> dict:
    """Rank the authenticated customer's purchased products.

    Use metric='quantity' for most units purchased,
    metric='revenue' for highest total item revenue,
    metric='purchase_frequency' for most distinct orders,
    or metric='average_price' for highest average price paid.

    For lifetime results, leave start_date and end_date empty.
    For a date range, provide both as YYYY-MM-DD.
    The start date is inclusive and the end date is exclusive.
    Limit must be between 1 and 50.
    """
    return get_customer_top_products(
        metric=metric,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@tool
def spending_summary_tool() -> dict:
    """Get the authenticated customer's overall spending, order count, and average order value."""
    return get_customer_spending_summary()


@tool
def category_spending_tool(
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Get the authenticated customer's spending breakdown by product category.

    For all-time spending, leave start_date and end_date empty.
    For a specific year or date range, provide both dates in YYYY-MM-DD format.
    The start date is inclusive and the end date is exclusive.
    For calendar year 2025, use start_date='2025-01-01'
    and end_date='2026-01-01'.
    """
    if start_date and end_date:
        period_data = get_customer_spending_for_period(
            start_date,
            end_date,
        )
        return {
            "start_date": period_data["start_date"],
            "end_date_exclusive": period_data["end_date_exclusive"],
            "category_spending": period_data["category_spending"],
        }

    if bool(start_date) != bool(end_date):
        return {
            "error": "Provide both start_date and end_date."
        }

    return {
        "category_spending": get_customer_category_summary()
    }


@tool
def spending_trends_tool(
    start_date: str = "",
    end_date: str = ""
) -> dict:
    """
    Get monthly spending trends for the authenticated customer.

    Optional dates can use DD-MM-YYYY format.
    The end date is exclusive.
    """
    return get_customer_spending_trends(
        start_date=start_date,
        end_date=end_date
    )


@tool
def spending_for_period_tool(start_date: str, end_date: str) -> dict:
    """Get the authenticated customer's spending and eligible order count for a date range. Use ISO dates YYYY-MM-DD. The start date is inclusive and the end date is exclusive."""
    return get_customer_spending_for_period(start_date, end_date)
