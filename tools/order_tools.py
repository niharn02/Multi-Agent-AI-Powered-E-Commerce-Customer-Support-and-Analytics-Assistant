# Import the libraries
from db import get_connection
from flask_login import current_user
import pandas as pd
from pathlib import Path
from langchain_core.tools import tool
from sentence_transformers import SentenceTransformer
from datetime import date
import numpy as np
import uuid

# Resolve the project root so the FAQ file can be loaded consistently.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read the FAQs CSV file
faq = pd.read_csv(BASE_DIR / "data" / "faqs.csv")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

# Centralize authentication checks before customer-specific database access.
def get_authenticated_customer_id():
    """Return the customer ID of the authenticated customer."""

    if not current_user.is_authenticated:
        raise PermissionError("Authentication is required.")
    
    return current_user.customer_id
    

# Standardize order IDs so numeric and prefixed formats can be handled consistently.
def normalize_order_id(order_id):
    """Normalize order IDs such as 1006 and ORD1006."""
    order_id = str(order_id).strip().upper()

    if order_id.isdigit():
        order_id = f"ORD{order_id}"

    return order_id


# ============================================================
# FAQ EMBEDDINGS
# ============================================================

faq_model = SentenceTransformer("all-MiniLM-L6-v2")

# Precompute normalized vectors for the FAQ questions for faster semantic search.
faq_embeddings = faq_model.encode(
    faq["question"].tolist(),
    normalize_embeddings=True
)


# ============================================================
# ORDER DETAILS
# ============================================================

@tool
def get_order_details(order_id):
    """
    Retrieve order details, products, and delivery information
    from PostgreSQL using an order ID.
    """
    order_id = normalize_order_id(order_id)
    customer_id = get_authenticated_customer_id()

    # Fetch the order details and its latest available shipment dates.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.order_date,
                    o.order_time,
                    o.order_status,
                    o.shipping_method,
                    o.delivery_city,
                    o.delivery_state,
                    o.subtotal,
                    o.shipping_fee,
                    o.tax_amount,
                    o.final_amount,
                    s.expected_delivery_date,
                    s.actual_delivery_date
                FROM orders AS o
                LEFT JOIN LATERAL (
                    SELECT
                        sh.expected_delivery_date,
                        sh.actual_delivery_date
                    FROM shipments AS sh
                    WHERE sh.order_id = o.order_id
                    ORDER BY sh.dispatch_date DESC NULLS LAST
                    LIMIT 1
                ) AS s ON TRUE
                WHERE o.order_id = %s
                  AND o.customer_id = %s;
                """,
                (order_id, customer_id)
            )
            row = cur.fetchone()

    if row is None:
        return f"Order {order_id} was not found."

    # Retrieve the products and prepare a concise product summary for the response.
    products = get_order_products(order_id)

    product_names = [
        f"{item['product_name']} (Qty: {item['quantity']})"
        for item in products
    ]
    product_text = ", ".join(product_names) if products else None

    final_amount = (
        f"₹{row[11]:,.2f}" if row[11] is not None else None
    )

    return {
        # Existing fields
        "order_id": row[0],
        "customer_id": row[1],
        "order_date": str(row[2]) if row[2] else None,
        "order_time": str(row[3]) if row[3] else None,
        "order_status": row[4],
        "shipping_method": row[5],
        "delivery_city": row[6],
        "delivery_state": row[7],
        "subtotal": float(row[8]) if row[8] is not None else None,
        "shipping_fee": float(row[9]) if row[9] is not None else None,
        "tax_amount": float(row[10]) if row[10] is not None else None,
        "final_amount": final_amount,

        # Chatbot response fields
        "products": products,
        "product": product_text,
        "amount": final_amount,
        "status": row[4],
        "delivery_date": (
            row[12].isoformat() if row[12] else None
        ),
        "actual_delivery_date": (
            row[13].isoformat() if row[13] else None
        ),
    }


# ============================================================
# GET MY ORDERS
# ============================================================

@tool
def get_my_orders(start_date: str = "", end_date: str = ""):
    """Retrieve the authenticated customer's orders, newest first.
    Optional start_date is inclusive and end_date is exclusive.
    Use ISO format YYYY-MM-DD for dates."""

    customer_id = get_authenticated_customer_id()

    # Build the query first, then append optional date filters when supplied.
    query = """
        SELECT
            o.order_id,
            o.order_date,
            o.order_time,
            o.order_status,
            o.final_amount,
            s.expected_delivery_date,
            s.actual_delivery_date
        FROM orders AS o
        LEFT JOIN LATERAL (
            SELECT
                sh.expected_delivery_date,
                sh.actual_delivery_date
            FROM shipments AS sh
            WHERE sh.order_id = o.order_id
            ORDER BY sh.dispatch_date DESC NULLS LAST
            LIMIT 1
        ) AS s ON TRUE
        WHERE o.customer_id = %s
    """

    params = [customer_id]

    if start_date:
        query += " AND o.order_date >= %s"
        params.append(start_date)

    if end_date:
        query += " AND o.order_date < %s"
        params.append(end_date)

    query += """
        ORDER BY
            o.order_date DESC NULLS LAST,
            o.order_time DESC NULLS LAST,
            o.order_id DESC
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

    # Return a different message for an empty date range versus an account with no orders.
    if not rows:
        if start_date or end_date:
            message = "No orders were found for the requested date range."
        else:
            message = "You don't have any orders yet."

        return {
            "found": False,
            "orders": [],
            "message": message
        }

    orders = []

    for row in rows:
        orders.append({
            "order_id": str(row[0]),
            "order_date": str(row[1]) if row[1] else None,
            "order_time": str(row[2]) if row[2] else None,
            "order_status": str(row[3]) if row[3] else "Not available",
            "amount": float(row[4]) if row[4] is not None else None,
            "expected_delivery_date": (
                str(row[5]) if row[5] else None
            ),
            "actual_delivery_date": (
                str(row[6]) if row[6] else None
            )
        })

    return {
        "found": True,
        "orders": orders,
        "message": f"Found {len(orders)} order(s)."
    }


# ============================================================
# GET ORDER DETAILS BY POSITION
# ============================================================

# Retrieve an order by its position after applying the optional year and status filters.
def get_customer_order_by_position(
    position: int = 1,
    year: int | None = None,
    status: str | None = None,
):
    """Retrieve a customer's order by position, with optional filters."""

    if position < 1:
        return {
            "success": False,
            "message": "Order position must be at least 1."
        }

    customer_id = get_authenticated_customer_id()

    query = """
        SELECT
            order_id,
            order_date,
            order_status,
            final_amount
        FROM orders
        WHERE customer_id = %s
    """
    params = [customer_id]

    if year is not None:
        if year < 1900 or year > 2100:
            return {
                "success": False,
                "message": "Please provide a valid year."
            }

        query += """
            AND order_date >= %s
            AND order_date < %s
        """
        params.extend([f"{year}-01-01", f"{year + 1}-01-01"])

    if status:
        query += " AND LOWER(TRIM(order_status)) = LOWER(%s)"
        params.append(status.strip())

    query += """
        ORDER BY order_date ASC, order_time ASC, order_id ASC
        LIMIT 1 OFFSET %s
    """
    params.append(position - 1)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            row = cur.fetchone()

    if not row:
        return {
            "success": False,
            "message": "No matching order was found at that position."
        }

    return {
        "success": True,
        "position": position,
        "order_id": row[0],
        "order_date": row[1].isoformat() if row[1] else None,
        "order_status": row[2],
        "final_amount": float(row[3]) if row[3] is not None else 0.0,
    }


# ============================================================
# GET ORDER PRODUCTS
# ============================================================

# Limit product retrieval to orders owned by the authenticated customer.
def get_order_products(order_id: str):
    """Retrieve products belonging to the authenticated customer's order."""

    order_id = normalize_order_id(order_id)
    customer_id = get_authenticated_customer_id()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    oi.product_id,
                    p.product_name,
                    oi.quantity
                FROM order_items AS oi
                JOIN products AS p
                    ON oi.product_id = p.product_id
                JOIN orders AS o
                    ON oi.order_id = o.order_id
                WHERE oi.order_id = %s
                  AND o.customer_id = %s;
                """,
                (order_id, customer_id),
            )

            rows = cur.fetchall()

    products = []

    for row in rows:
        products.append({
            "product_id": row[0],
            "product_name": row[1],
            "quantity": row[2],
        })

    return products


# ============================================================
# SELECT ORDER PRODUCTS
# ============================================================

# Match the customer reply to one of the products offered in the current return flow.
def select_order_product(product_selection: str, products: list):
    """Identify a product from its displayed number or name."""

    product_selection = product_selection.strip()

    # Option 1: Customer selects by number
    if product_selection.isdigit():
        product_number = int(product_selection)

        if 1 <= product_number <= len(products):
            return products[product_number -1]

        return {
            "error": "Invalid product number. Please select a number from the list."
        }

    # Option 2: Customer selects by product name
    matching_products = [
        product
        for product in products
        if product_selection.casefold() == product["product_name"].casefold()
    ]

    if len(matching_products) == 1:
        return matching_products[0]

    if len(matching_products) > 1:
        return {
            "error": "Multiple products match that name. Please specify which product you mean."
        }

    return {
        "error": "Product not found in this order. Please enter a product number or the exact product name."
    }


# ============================================================
# FAQ SEARCH
# ============================================================

@tool
def search_faq(question: str):

    """Search the FAQ knowledge base using semantic similarity."""

    # Convert the incoming question into an embedding using the same model as the FAQ data.
    query_embedding = faq_model.encode(
        [question],
        normalize_embeddings=True
    )[0]

    # Rank FAQ questions by similarity and select the closest match.
    similarities = np.dot(faq_embeddings, query_embedding)
    best_index = np.argmax(similarities)

    return faq.iloc[best_index]["answer"]


# ============================================================
# DELIVERY STATUS
# ============================================================

@tool
# Retrieve order status together with the latest shipment status and delivery dates.
def get_delivery_status(order_id: str):
    """
    Retrieve delivery status and dates from PostgreSQL.
    """
    order_id = normalize_order_id(order_id)

    customer_id = get_authenticated_customer_id()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    o.order_id,
                    o.order_status,
                    s.delivery_status,
                    s.expected_delivery_date,
                    s.actual_delivery_date,
                    s.delayed_flag
                FROM orders AS o
                LEFT JOIN shipments AS s
                    ON o.order_id = s.order_id
                WHERE o.order_id = %s
                    AND o.customer_id = %s
                ORDER BY s.dispatch_date DESC NULLS LAST
                LIMIT 1;
                """,
                (order_id,)
            )

            row = cur.fetchone()

    if row is None:
        return f"Order {order_id} was not found."

    return {
        "order_id": row[0],
        "order_status": row[1],
        "delivery_status": row[2],
        "expected_delivery_date": (
            str(row[3]) if row[3] else None
        ),
        "actual_delivery_date": (
            str(row[4]) if row[4] else None
        ),
        "delayed": row[5],
    }


# ============================================================
# CHECK COMPLAINT ELEGIBILITY
# ============================================================

# Apply the delivery and time-window rules before allowing complaint registration.
def check_complaint_eligibility(order_id: str):
    """Check delivery-related eligibility before collecting complaint details."""

    from datetime import date

    order_id = normalize_order_id(order_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    o.order_status,
                    s.actual_delivery_date
                FROM orders AS o
                LEFT JOIN shipments AS s
                    ON o.order_id = s.order_id
                WHERE o.order_id = %s;
                """,
                (order_id,)
            )
            row = cur.fetchone()

    if row is None:
        return {
            "eligible": False,
            "reason": f"Order {order_id} was not found."
        }

    order_status, delivery_date = row

    if str(order_status).strip().lower() != "delivered":
        return {
            "eligible": False,
            "reason": (
                "A complaint cannot be registered under this policy "
                "until the order has been delivered."
            )
        }

    if delivery_date is None:
        return {
            "eligible": False,
            "reason": (
                "Cannot verify eligibility because the delivery date "
                "is missing."
            )
        }

    days_since_delivery = (date.today() - delivery_date).days

    if days_since_delivery < 0:
        return {
            "eligible": False,
            "reason": (
                "The delivery date is in the future. Complaint "
                "eligibility cannot be verified."
            )
        }

    if days_since_delivery > 30:
        return {
            "eligible": False,
            "reason": (
                f"Complaint registration is not available for order {order_id}. "
                f"It was delivered on {delivery_date.strftime('%d/%m/%Y')}, "
                f"{days_since_delivery} days ago. Complaints must be "
                "registered within 30 days of delivery."
            )
        }

    return {
        "eligible": True,
        "reason": "The order is eligible for complaint registration."
    }


# ============================================================
# CREATE COMPLAINT
# ============================================================

@tool
# Validate the complaint, check for an existing active complaint, and save it if eligible.
def create_complaint(order_id: str, complaint: str):
    """Create a complaint only for an eligible order within 30 days of delivery."""

    order_id = normalize_order_id(order_id)
    complaint = str(complaint).strip()

    if not order_id:
        return {
            "success": False,
            "complaint_created": False,
            "message": "Please provide a valid order ID."
        }

    if not complaint:
        return {
            "success": False,
            "complaint_created": False,
            "message": "Please describe the issue with your order."
        }

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                # 1. Retrieve the order, customer, and delivery details.
                # Lock the order row to help prevent concurrent duplicate
                # complaint creation for the same order.
                cur.execute(
                    """
                    SELECT
                        o.customer_id,
                        o.order_status,
                        s.actual_delivery_date
                    FROM orders AS o
                    LEFT JOIN shipments AS s
                        ON o.order_id = s.order_id
                    WHERE o.order_id = %s
                    FOR UPDATE OF o;
                    """,
                    (order_id,)
                )

                order = cur.fetchone()

                if order is None:
                    return {
                        "success": False,
                        "complaint_created": False,
                        "order_id": order_id,
                        "message": f"Order {order_id} was not found."
                    }

                customer_id, order_status, delivery_date = order

                # 2. Require the order to be delivered.
                if str(order_status).strip().lower() != "delivered":
                    return {
                        "success": False,
                        "complaint_created": False,
                        "order_id": order_id,
                        "message": (
                            "A complaint cannot be registered under this "
                            "policy until the order has been delivered."
                        )
                    }

                # 3. Verify the delivery date exists.
                if delivery_date is None:
                    return {
                        "success": False,
                        "complaint_created": False,
                        "message": (
                            "Cannot verify complaint eligibility because "
                            "the delivery date is missing."
                        )
                    }

                # PostgreSQL DATE values are returned as Python date objects.
                today = date.today()
                days_since_delivery = (today - delivery_date).days

                # 4. Reject future delivery dates.
                if days_since_delivery < 0:
                    return {
                        "success": False,
                        "complaint_created": False,
                        "message": (
                            "The delivery date is in the future. "
                            "Complaint eligibility cannot be verified."
                        )
                    }

                # 5. Enforce the 30-day complaint window.
                if days_since_delivery > 30:
                    return {
                        "success": False,
                        "complaint_created": False,
                        "order_id": order_id,
                        "days_since_delivery": days_since_delivery,
                        "message": (
                            f"Complaint registration is not available for "
                            f"order {order_id}. It was delivered on "
                            f"{delivery_date.strftime('%d/%m/%Y')}, "
                            f"{days_since_delivery} days ago. Complaints "
                            "must be registered within 30 days of delivery."
                        )
                    }

                # 6. Prevent duplicate active complaints.
                cur.execute(
                    """
                    SELECT
                        complaint_id,
                        complaint_reference,
                        complaint_status
                    FROM complaints
                    WHERE order_id = %s
                      AND LOWER(TRIM(complaint_status))
                          IN ('open', 'in progress')
                    ORDER BY created_at ASC
                    LIMIT 1;
                    """,
                    (order_id,)
                )

                existing = cur.fetchone()

                if existing is not None:
                    internal_id, reference, status = existing
                    reference = reference or str(internal_id)

                    return {
                        "success": False,
                        "complaint_created": False,
                        "existing_complaint_id": reference,
                        "order_id": order_id,
                        "status": status,
                        "message": (
                            f"An active complaint already exists for order "
                            f"{order_id}. Complaint ID: {reference}, "
                            f"Status: {status}."
                        )
                    }

                # 7. Generate the existing complaint reference format.
                complaint_reference = (
                    f"CMP-{uuid.uuid4().hex[:8].upper()}"
                )

                # 8. Insert the complaint into PostgreSQL.
                cur.execute(
                    """
                    INSERT INTO complaints (
                        complaint_reference,
                        customer_id,
                        order_id,
                        description,
                        complaint_status
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING complaint_id;
                    """,
                    (
                        complaint_reference,
                        customer_id,
                        order_id,
                        complaint,
                        "Open"
                    )
                )

                cur.fetchone()

        # The connection context commits when it exits successfully.
        return {
            "success": True,
            "complaint_created": True,
            "complaint_id": complaint_reference,
            "order_id": order_id,
            "status": "Open",
            "message": (
                f"Complaint {complaint_reference} has been registered "
                f"successfully for order {order_id}. The order was "
                f"delivered {days_since_delivery} days ago and is within "
                "the 30-day complaint window."
            )
        }

    except Exception:
        # The connection context rolls back when a database error escapes it.
        return {
            "success": False,
            "complaint_created": False,
            "message": (
                "The complaint could not be saved. Please try again."
            )
        }


# ============================================================
# GET COMPLAINT STATUS
# ============================================================

@tool
# Find a complaint by its public reference or its database ID.
def get_complaint_status(complaint_id: str):
    """Get the current status of a complaint using its ID."""

    complaint_id = str(complaint_id).strip().upper()

    complaint_id = (
    complaint_id
    .replace("‑", "-")
    .replace("–", "-")
    .replace("—", "-")
    .replace("−", "-")
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(complaint_reference, complaint_id::text),
                    order_id,
                    description,
                    complaint_status,
                    created_at
                FROM complaints
                WHERE UPPER(complaint_reference) = %s
                   OR complaint_id::text = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (complaint_id, complaint_id)
            )

            row = cur.fetchone()

    if row is None:
        return {
            "found": False,
            "complaint_id": complaint_id,
            "message": (
                f"Complaint {complaint_id} was not found. "
                "Please check the complaint ID and try again."
            )
        }

    stored_reference, order_id, description, status, created_at = row

    return {
        "found": True,
        "complaint_id": str(stored_reference),
        "order_id": str(order_id),
        "complaint": str(description),
        "status": str(status),
        "created_date": str(created_at),
        "message": (
            f"Complaint {stored_reference} for order "
            f"{order_id} has status: {status}."
        )
    }


@tool
# Return the most relevant complaint for an order, prioritizing active complaints.
def get_complaint_status_by_order(order_id: str):
    """Retrieve the existing complaint status using an order ID."""

    order_id = normalize_order_id(order_id)

    if not order_id:
        return {
            "found": False,
            "message": "Please provide a valid order ID."
        }

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(complaint_reference, complaint_id::text),
                    description,
                    complaint_status,
                    created_at
                FROM complaints
                WHERE order_id = %s
                ORDER BY
                    CASE
                        WHEN LOWER(TRIM(complaint_status))
                            IN ('open', 'in progress')
                        THEN 0
                        ELSE 1
                    END,
                    created_at DESC
                LIMIT 1;
                """,
                (order_id,)
            )

            row = cur.fetchone()

    if row is None:
        return {
            "found": False,
            "order_id": order_id,
            "message": f"No complaint was found for order {order_id}."
        }

    complaint_id, description, status, created_at = row

    return {
        "found": True,
        "order_id": order_id,
        "complaint_id": str(complaint_id),
        "complaint": str(description),
        "status": str(status),
        "created_date": str(created_at),
        "message": (
            f"Complaint {complaint_id} for order "
            f"{order_id} has status: {status}."
        )
    }


# ============================================================
# FIND EXISTING RETURN
# ============================================================

# Find existing return records for this order and product to avoid duplicate requests.
def find_existing_return(order_id: str, product_id: str):
    """Find all existing returns for the specified order and product."""

    order_id = normalize_order_id(order_id)
    product_id = product_id.strip().upper()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT return_id, return_status
                FROM returns
                WHERE order_id = %s
                  AND product_id = %s
                  AND LOWER(TRIM(return_status)) IN (
                      'requested',
                      'returned',
                      'approved',
                      'refund completed'
                  )
                ORDER BY return_date DESC NULLS LAST, return_id;
            """, (order_id, product_id))

            rows = cur.fetchall()

    return [
        {
            "return_id": row[0],
            "return_status": row[1]
        }
        for row in rows
    ]


# ============================================================
# CHECK RETURN ELIGIBILITY
# ============================================================

@tool
# Check product membership, delivery status, return window, and existing return records.
def check_return_eligibility(order_id: str, product_id: str):
    """Check whether a specific product in an order is eligible for return."""

    order_id = normalize_order_id(order_id)
    product_id = product_id.strip().upper()

    with get_connection() as conn:
        with conn.cursor() as cur:

            # 1. Verify that the order exists and the product belongs to it.
            cur.execute("""
                SELECT
                    o.order_status,
                    s.actual_delivery_date
                FROM orders AS o
                JOIN order_items AS oi
                    ON o.order_id = oi.order_id
                LEFT JOIN shipments AS s
                    ON o.order_id = s.order_id
                WHERE o.order_id = %s
                  AND oi.product_id = %s
                ORDER BY s.dispatch_date DESC NULLS LAST
                LIMIT 1;
            """, (order_id, product_id))

            row = cur.fetchone()

            if row is None:
                return {
                    "eligible": False,
                    "reason": (
                        f"Product {product_id} was not found "
                        f"in order {order_id}."
                    )
                }

            order_status, delivery_date = row

            # 2. Verify delivery status.
            if str(order_status).strip().lower() != "delivered":
                return {
                    "eligible": False,
                    "reason": "The order must be delivered before it can be returned."
                }

            # 3. Verify the delivery date.
            if delivery_date is None:
                return {
                    "eligible": False,
                    "reason": "The order has no recorded delivery date."
                }

            days_since_delivery = (date.today() - delivery_date).days

            if days_since_delivery < 0:
                return {
                    "eligible": False,
                    "reason": "The recorded delivery date is in the future."
                }

            if days_since_delivery >= 30:
                return {
                    "eligible": False,
                    "reason": (
                        "The return window has expired. "
                        f"The order was delivered on {delivery_date}."
                    )
                }

            # 4. Check for an existing return for this product.
            cur.execute("""
                SELECT return_id, return_status
                FROM returns
                WHERE order_id = %s
                  AND product_id = %s
                  AND LOWER(TRIM(return_status)) IN (
                      'requested',
                      'returned',
                      'approved',
                      'refund completed'
                )
                ORDER BY return_date DESC NULLS LAST
                LIMIT 1;
            """, (order_id, product_id))

            existing_return = cur.fetchone()

            
            if existing_return is not None:
                return_id, return_status = existing_return

                return {
                    "eligible": False,
                    "return_id": str(return_id),
                    "status": return_status,
                    "reason": (
                        f"A return already exists for product {product_id} "
                        f"in order {order_id}. Status: {return_status}."
                    )
                }
            
    return {
        "eligible": True,
        "reason": "The selected product is eligible for return.",
        "order_id": order_id,
        "product_id": product_id,
        "days_since_delivery": days_since_delivery
    }


# ============================================================
# CREATE RETURN
# ============================================================

@tool
# Recheck eligibility and create a return request with the calculated refund amount.
def create_return(order_id: str, product_id: str, reason: str):
    """Create a return request for a specific product in an order."""

    order_id = normalize_order_id(order_id)
    product_id = product_id.strip().upper()
    reason = reason.strip()

    if not reason:
        return {
            "success": False,
            "message": "Please provide a reason for the return."
        }
        
    # Check all eligibility rules in one place.
    eligibility = check_return_eligibility.invoke({
        "order_id": order_id,
        "product_id": product_id
    })

    if not eligibility.get("eligible"):
        return {
            "success": False,
            "message": eligibility["reason"],
            "return_id": eligibility.get("return_id"),
            "status": eligibility.get("status")
        }


    with get_connection() as conn:
        with conn.cursor() as cur:

            # Retrieve the customer and refund amount.
            cur.execute("""
                SELECT
                    o.customer_id,
                    oi.item_revenue
                FROM orders AS o
                JOIN order_items AS oi
                    ON o.order_id = oi.order_id
                WHERE o.order_id = %s
                  AND oi.product_id = %s;
            """, (order_id, product_id))

            row = cur.fetchone()

            if row is None:
                return {
                    "success": False,
                    "message": "The selected product was not found in this order."
                }

            customer_id, refund_amount = row

            # Generate a unique return reference.
            return_id = f"RET{uuid.uuid4().hex[:12].upper()}"

            # Insert the new return request.
            cur.execute("""
                INSERT INTO returns (
                    return_id,
                    order_id,
                    customer_id,
                    product_id,
                    return_date,
                    return_reason,
                    refund_amount,
                    return_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                return_id,
                order_id,
                customer_id,
                product_id,
                date.today(),
                reason,
                refund_amount,
                "Requested"
            ))

    return {
        "success": True,
        "return_id": return_id,
        "order_id": order_id,
        "product_id": product_id,
        "refund_amount": float(refund_amount),
        "status": "Requested",
        "message": (
            f"Return request {return_id} has been created successfully. "
            f"Refund amount: ₹{refund_amount:.2f}. "
            "The request is awaiting review."
        )
    }


# ============================================================
# GET RETURN STATUS BY RETURN ID
# ============================================================

@tool
# Retrieve the status and key details for a specific return ID.
def get_return_status(return_id: str):
    """Get the current status of a return request using its return ID."""

    return_id = str(return_id).strip().upper()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    return_id,
                    order_id,
                    return_reason,
                    return_status,
                    return_date
                FROM returns
                WHERE UPPER(TRIM(return_id)) = %s
                ORDER BY return_date DESC NULLS LAST
                LIMIT 1;
            """, (return_id,))

            row = cur.fetchone()

    if row is None:
        return {
            "exists": False,
            "message": f"Return {return_id} was not found."
        }

    return {
        "exists": True,
        "return_id": str(row[0]),
        "order_id": str(row[1]),
        "reason": str(row[2]),
        "status": str(row[3]),
        "created_date": str(row[4])
    }


@tool
# Retrieve the latest return request associated with an order ID.
def get_return_status_by_order(order_id: str):
    """Get the current return status using an order ID."""

    order_id = str(order_id).strip().upper()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    return_id,
                    order_id,
                    return_reason,
                    return_status,
                    return_date
                FROM returns
                WHERE UPPER(TRIM(order_id)) = %s
                ORDER BY return_date DESC NULLS LAST
                LIMIT 1;
            """, (order_id,))

            row = cur.fetchone()

    if row is None:
        return {
            "exists": False,
            "message": (
                f"No return request was found for order {order_id}."
            )
        }

    return {
        "exists": True,
        "return_id": str(row[0]),
        "order_id": str(row[1]),
        "reason": str(row[2]),
        "status": str(row[3]),
        "created_date": str(row[4])
    }



# ============================================================
# MARK RETURN AS RECEIVED
# ============================================================

@tool
# Mark a return as received only if its current status is Requested.
def mark_returned(return_id: str):
    """Mark a return as received after the seller gets the product."""

    return_id = str(return_id).strip().upper()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT return_status
                FROM returns
                WHERE UPPER(TRIM(return_id)) = %s
                FOR UPDATE;
            """, (return_id,))

            row = cur.fetchone()

            if row is None:
                return {
                    "success": False,
                    "message": f"Return {return_id} was not found."
                }

            current_status = str(row[0]).strip()
            normalized_status = current_status.lower()

            if normalized_status == "returned":
                return {
                    "success": False,
                    "message": (
                        f"Return {return_id} has already been "
                        "marked as returned."
                    )
                }

            if normalized_status != "requested":
                return {
                    "success": False,
                    "message": (
                        f"Return {return_id} cannot be marked as returned "
                        f"because its current status is '{current_status}'."
                    )
                }

            cur.execute("""
                UPDATE returns
                SET return_status = 'Returned'
                WHERE UPPER(TRIM(return_id)) = %s;
            """, (return_id,))

    return {
        "success": True,
        "return_id": return_id,
        "status": "Returned",
        "message": "The product has been marked as returned."
    }
