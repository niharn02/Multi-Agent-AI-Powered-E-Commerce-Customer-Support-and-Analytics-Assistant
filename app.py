# ============================================================
# IMPORTS AND DEPENDENCIES
# ============================================================

from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from werkzeug.security import check_password_hash
from db import get_connection
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
)
from tools.order_tools import (
    get_order_details,
    get_complaint_status_by_order,
    check_complaint_eligibility,
    get_order_products,
    select_order_product,
    check_return_eligibility,
    create_return,
)
from graph.graph import support_graph, generate_analytics_chart_spec
import traceback
import os
import re
import secrets

# ============================================================
# FLASK CONFIGURATION AND SESSION SECURITY
# ============================================================

# Flask application and session security
app = Flask(__name__)

# Configure the session secret key
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Enable this when deployed over HTTPS.
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("COOKIE_SECURE", "false").lower() == "true"
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ============================================================
# USER AUTHENTICATION AND ACCOUNT MANAGEMENT
# ============================================================

# Authentication: connect Flask-Login users to customer_accounts records
class CustomerUser(UserMixin):
    # Initialise a user object using details retrieved from the database.
    def __init__(self, account_id, customer_id, email, is_active=True):

        # Flask-Login uses this ID to identify the logged-in account.
        self.id = str(account_id)

        # Store the customer ID linked to this account.
        self.customer_id = customer_id

        # Store the email address associated with the account.
        self.email = email

        # Save whether this account is active.
        self._is_active = is_active

    # Expose the account's active status through the is_active property.
    # Flask-Login checks this property when determining whether the
    # user account is active.
    @property
    def is_active(self):
        return self._is_active

# Register this function with Flask-Login.
# Flask-Login calls it when it needs to reload a user from the
# account ID stored in the login session.
@login_manager.user_loader
def load_user(account_id):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                # Retrieve the account details needed to rebuild the CustomerUser object.
                # The %s placeholder safely binds account_id as a parameter.
                cur.execute(
                    """
                    SELECT
                        account_id,
                        customer_id,
                        email,
                        is_active
                    FROM customer_accounts
                    WHERE account_id = %s;
                    """,
                    (account_id,),
                )

                # Fetch the matching account row and if no account matches, fetchone() returns None.
                row = cur.fetchone()

        # Check whether the account exists and is active.
        # row[3] corresponds to is_active in the SELECT statement.
        if row is None or not row[3]:
            return None

        # Rebuild the user object from the database values.
        # Flask-Login can then use this object as the current user.
        return CustomerUser(
            account_id=row[0],  # Database account ID
            customer_id=row[1], # Customer ID linked to the account
            email=row[2],       # Account email address
            is_active=row[3],   # Whether the account is active
        )

    except Exception:

        # Record the full error details in the application logs
        # to help diagnose database or account-loading problems.
        app.logger.exception("Failed to load customer account")

        # Return None if loading the user fails.
        return None

# ============================================================
# LOGIN, LOGOUT AND HOME ROUTES
# ============================================================

# Handle customer login requests.
# GET displays the login page, while POST processes the submitted credentials.
@app.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate a customer using their email and stored password hash."""

    # If the customer is already logged in, redirect them to the chatbot instead of asking to login again.
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    # Process the login form when the customer submits their credentials.
    if request.method == "POST":

        # Read the email and password submitted through the login form.
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # Ensure both fields have been provided before querying the database.
        if not email or not password:
            return render_template(
                "login.html",
                error="Please enter your email and password.",
            )

        try:
            # Connect to PostgreSQL and look up the account using its email.
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            account_id,
                            customer_id,
                            email,
                            password_hash,
                            is_active
                        FROM customer_accounts
                        WHERE LOWER(email) = LOWER(%s);
                        """,
                        (email,),
                    )

                    # Retrieve the matching account, or None if it does not exist.
                    row = cur.fetchone()

        except Exception:

            # Log the technical error for debugging without exposing database details to the customer.
            app.logger.exception("Customer login lookup failed")

            # Inform the customer that login is temporarily unavailable.
            return render_template(
                "login.html",
                error="Login is temporarily unavailable. Please try again.",
            ), 500

        # Reject the login if the account does not exist, is inactive, or the submitted password
        #  does not match its stored password hash.
        if (
            row is None
            or not row[4]
            or not check_password_hash(row[3], password)
        ):
            return render_template(
                "login.html",
                error="Invalid email or password.",
            ), 401

        # Create the application user object from the verified database record.
        # Flask-Login uses this object to identify the authenticated account,
        # while customer_id links it to the customer's EcomAssist data.
        user = CustomerUser(
            account_id=row[0],
            customer_id=row[1],
            email=row[2],
            is_active=row[4],
        )

        # Clear previous session data so stale conversation state does not carry over into the
        # newly authenticated session.
        session.clear()

        # Log the customer in and establish a fresh authenticated session.
        # remember=False means the login is not persisted using a remember cookie.
        login_user(user, remember=False, fresh=True)

        # Redirect the authenticated customer to the chatbot home page.
        return redirect(url_for("home"))

    # For a GET request, display the login page without processing credentials.
    return render_template("login.html")

# Log out the authenticated customer and clear their session data.
# POST prevents logout from being triggered through a simple page visit or link.
@app.route("/logout", methods=["POST"])
@login_required
def logout():
    """End the authenticated session."""

    # Remove the customer's authenticated status from Flask-Login.
    logout_user()
    session.clear()
    return redirect(url_for("login"))

# Serve the main EcomAssist chatbot page to authenticated customers.
@app.route("/")
def home():
    """Render the main chatbot interface."""

    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    return render_template("ecom_index.html")

# ============================================================
# MESSAGE PARSING AND INTENT DETECTION
# ============================================================

# Message parsing helpers: identify IDs and common customer intents
def extract_complaint_id(text):
    """
      Extract a complaint ID from text, such as CMP123 or CMP-123.
  
      Supports different hyphen characters and matches IDs case-insensitively.
      Returns an empty string when no complaint ID is found.
    """

    # Find a complaint ID beginning with 'CMP', optionally followed by a hyphen, and then one or more ters or digits.
    match = re.search(
        r"\bCMP[-\u2010-\u2015\u2212]?[A-Z0-9]+\b",
        text,
        re.IGNORECASE,
    )

    # Return an empty string if the text contains no matching complaint ID.
    if not match:
        return ""

    # Standardize the extracted ID to uppercase and replace supported unicode hyphens with regular hyphen.
    return (
        match.group(0)
        .upper()
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )


def is_complaint_status_question(question):
    """Identify requests to check the status of an existing complaint."""

    q = question.lower()

    # Check whether the question refers to a complaint.
    mentions_complaint = bool(
        re.search(r"\b(complaint|complaints|complain)\b", q)
    )

    # Check whether the customer is asking for a status, update, tracking
    # information, or what has happened to the complaint.
    asks_status = bool(
        re.search(
            r"\b(status|update|progress|track|tracking)\b",
            q
        )
        or re.search(
            r"\b(where is|what happened to|how is)\b",
            q
        )
    )

    # Treat the question as a complaint-status request only when both a complaint reference
    # and a status-related phrase are detected.
    return mentions_complaint and asks_status



def extract_order_id(question):
    """Extract an order ID from common customer message formats."""
    question = str(question or "").strip()

    # Match order IDs such as ORD1000001, ORD-ABC123, or TSTORD1000001.
    match = re.search(
    r"\b(?:TST)?ORD[A-Z0-9-]*\d[A-Z0-9-]*\b",
    question,
    re.IGNORECASE,
    )

    # Return the matched order ID in uppercase for consistent processing.
    if match:
        return match.group(0).upper()

    # Also support a standalone seven-digit order ID by adding the ORD prefix.
    if re.fullmatch(r"\d{7}", question):
        return f"ORD{question}"

    # Return an empty string when no supported order ID format is found.
    return ""


def is_return_request(question):
    """Recognize return requests and specific return-eligibility questions."""

    # Detect common ways customers ask to return an item or initiate a return.
    return bool(
        re.search(
            r"\b("
            r"can i return(?: it| this| my order| this order)?|"
            r"could i return(?: it| this| my order| this order)?|"
            r"may i return(?: it| this| my order| this order)?|"
            r"is it eligible for return|"
            r"is this eligible for return|"
            r"i want to return|"
            r"i'd like to return|"
            r"i would like to return|"
            r"i need to return|"
            r"return this item|"
            r"return this product|"
            r"initiate a return|"
            r"start a return|"
            r"request a return|"
            r"create a return request|"
            r"send (?:this item|this product|it) back"
            r")\b",
            question,
            re.IGNORECASE,
        )
    )


def is_order_tracking_request(question):
    """Recognize explicit order tracking and delivery questions."""

    # Identify common tracking questions, such as asking where an order is,
    # whether it has arrived, or when it is expected to arrive.
    return bool(
        re.search(
            r"where is my ord(?:er|e)\b|"
            r"\b(where is my order|where's my order|"
            r"track my order|order status|delivery status|"
            r"has my order arrived|when will my order arrive)\b",
            question,
            re.IGNORECASE,
        )
    )


def is_explicit_order_status_request(question):
    """Recognize requests specifically about order or delivery status."""

    # Detect explicit requests for order status or delivery updates.
    # This overlaps with is_order_tracking_request(), but is maintained
    # separately because the application may use it for a distinct routing decision.
    return bool(
        re.search(
            r"where is my ord(?:er|e)\b|"
            r"\b(order status|delivery status|status of "
            r"(?:my )?order|track my order|where is my order|"
            r"where's my order|has my order arrived|"
            r"when will my order arrive)\b",
            question,
            re.IGNORECASE,
        )
    )


def is_return_status_question(question: str) -> bool:
    """Identify read-only return and refund status questions."""

    # Detect questions about an existing return or refund, including requests to check progress,
    # get an update, or ask when money will arrive.
    return bool(
        re.search(
            r"\b(return status|refund status|status of (?:my )?"
            r"(?:return|refund)|what is the status of (?:my )?"
            r"(?:return|refund)|what's the status of (?:my )?"
            r"(?:return|refund)|where is my refund|where's my refund|"
            r"track my refund|check my refund|"
            r"refund update|return update|"
            r"has my refund|when will i (?:get|receive) my refund)\b",
            question,
            re.IGNORECASE,
        )
    )

def is_return_policy_question(question: str) -> bool:
    """Identify questions about return and refund policies."""

    # Detect questions about the rules governing returns and refunds, such as the allowed return window,
    # eligibility period, or conditions.
    return bool(
        re.search(
            r"\b(return|refund)\s+policy\b|"
            r"\bpolicy\s+(?:for|on)\s+(?:returns?|refunds?)\b|"
            r"\b(return|refund)\s+(?:window|period|rules|conditions)\b",
            question,
            re.IGNORECASE,
        )
    )


def is_general_status_request(question):
    """Recognize a general status follow-up."""

    # Detect broad status-related wording that may need additional context
    # to determine whether the customer means an order, return, or complaint.
    return bool(
        re.search(
            r"\b(status|track|tracking|update)\b",
            question,
            re.IGNORECASE,
        )
    )


def is_complaint_request(question):
    """Recognize a request to start a complaint."""

    # Detect wording associated with reporting a problem or filing a complaint.
    # This function identifies the intent; it does not create the complaint.
    return bool(
        re.search(
            r"\b(complain|complaint|file a complaint|"
            r"raise a complaint|report a problem)\b",
            question,
            re.IGNORECASE,
        )
    )

# ============================================================
# MAIN CHAT ENDPOINT AND WORKFLOW ORCHESTRATION
# ============================================================

# Main chat endpoint: handle multi-step flows, then invoke LangGraph if needed
@app.route("/ask", methods=["POST"])
@login_required
def ask():
    """Process one customer message and return an answer (plus chart data)."""

    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()

    if not question:
        return jsonify({"answer": "Please enter a question."}), 400

    # Load the conversation state. Restore conversation details needed to continue ongoing workflows.
    previous_order_id = session.get("last_order_id", "")
    pending_intent = session.get("pending_intent", "")
    last_workflow = session.get("last_workflow", "")
    complaint_step = session.get("complaint_step", "")
    complaint_order_id = session.get("complaint_order_id", "")

    # Return conversation state
    return_step = session.get("return_step", "")
    return_order_id = session.get("return_order_id", "")
    return_product_id = session.get("return_product_id", "")
    return_product_name = session.get("return_product_name", "")

    extracted_order_id = extract_order_id(question)

    # Extract a return ID separately so it isn't mistaken for an order ID.
    return_id_match = re.search(
        r"\bRET[A-Z0-9-]*\d[A-Z0-9-]*\b",
        question.upper(),
    )

    extracted_return_id = (
        return_id_match.group(0)
        if return_id_match
        else ""
    )

    # Detect an ID-like value that was explicitly provided
    # but was not recognised as a valid-format order ID.
    possible_id_match = re.search(
        r"\b[A-Z][A-Z0-9-]*\d[A-Z0-9-]*\b",
        question.upper(),
    )

    if (
        not extracted_order_id
        and possible_id_match
        and not extracted_return_id
        and (
            is_explicit_order_status_request(question)
            or is_order_tracking_request(question)
            or pending_intent == "order_status_id"
        )
    ):
        session["pending_intent"] = "order_status_id"
        session["last_workflow"] = "order"

        return jsonify({
            "answer": "Please verify your order ID and try again."
        })

    # If the customer corrects an order ID after a verification prompt,
    # resume the order-status lookup without asking them to repeat the request.
    if (
        pending_intent == "order_status_id"
        and extracted_order_id
    ):
        session["last_order_id"] = extracted_order_id
        session["last_workflow"] = "order"
        session.pop("pending_intent", None)

        try:
            result = support_graph.invoke({
                "question": (
                    f"What is the status of order "
                    f"{extracted_order_id}?"
                ),
                "intent": "order",
                "answer": "",
                "order_id": extracted_order_id,
                "return_id": "",
                "return_status": "",
            })

            return jsonify({
                "answer": result.get(
                    "answer",
                    "Sorry, I couldn't retrieve the order status."
                )
            })

        except Exception:
            traceback.print_exc()  # Prints the full error in the terminal
            return jsonify({
                "answer": (
                    "Sorry, I couldn't retrieve the order status "
                    "right now. Please try again."
                )
            }), 500

    graph_question = question
    graph_intent = ""

    # Save a newly supplied order ID so follow-up messages can use it.
    if extracted_order_id:
        previous_order_id = extracted_order_id
        session["last_order_id"] = extracted_order_id

    # Check complaint status BEFORE starting a new complaint
    is_status_followup = (
        pending_intent == "complaint"
        and complaint_order_id
        and bool(
            re.search(
                r"\b(just status|status only|only status)\b",
                question,
                re.IGNORECASE,
            )
        )
    )

    extracted_complaint_id = extract_complaint_id(question)

    # If the customer supplies a complaint ID, check that specific complaint
    # directly rather than starting a new complaint or requesting an order ID.
    if extracted_complaint_id and is_complaint_status_question(question):
        graph_question = (
            f"Check the status of existing complaint "
            f"{extracted_complaint_id}. Use get_complaint_status "
            f"with complaint_id='{extracted_complaint_id}'. "
            "Do not ask for an order ID. Do not create a complaint."
        )

        try:
            result = support_graph.invoke({
                "question": graph_question,
                "intent": "complaint",
                "answer": "",
                "order_id": "",
                "return_id": "",
                "return_status": "",
            })

            return jsonify({
                "answer": result.get(
                    "answer",
                    "Sorry, I couldn't retrieve the complaint status."
                )
            })

        except Exception:
            app.logger.exception("Error checking complaint ID status")
            return jsonify({
                "answer": (
                    "Sorry, I couldn't retrieve the complaint status "
                    "right now. Please try again."
                )
            }), 500

    # Check the status of an existing complaint using its order ID.
    if is_complaint_status_question(question) or is_status_followup:
        status_order_id = (
            extracted_order_id
            or complaint_order_id
            or previous_order_id
        )

        if not status_order_id:
            return jsonify({
                "answer": (
                    "Please provide your order ID so I can check "
                    "your complaint status."
                )
            })

        graph_question = (
            f"Check the existing complaint status for order "
            f"{status_order_id}. Use get_complaint_status_by_order "
            "to retrieve the existing complaint. Do not create a "
            "new complaint or ask for the complaint reason."
        )

        # Clear any complaint-registration questions that were pending
        session.pop("pending_intent", None)
        session.pop("complaint_step", None)
        session.pop("complaint_order_id", None)

        try:
            result = support_graph.invoke({
                "question": graph_question,
                "intent": "complaint",
                "answer": "",
                "order_id": status_order_id,
                "return_id": "",
                "return_status": "",
            })

            return jsonify({
                "answer": result.get(
                    "answer",
                    "Sorry, I couldn't retrieve the complaint status."
                )
            })

        except Exception:
            app.logger.exception("Error checking complaint status")
            return jsonify({
                "answer": (
                    "Sorry, I couldn't retrieve the complaint status "
                    "right now. Please try again."
                )
            }), 500


    # Retrieve the current conversation state
    pending_intent = session.get("pending_intent")
    complaint_step = session.get("complaint_step")
    complaint_order_id = session.get("complaint_order_id")
    previous_order_id = (
        extracted_order_id or session.get("last_order_id", "")
    )

    # ============================================================
    # RETURN ELIGIBILITY CHECKS
    # ============================================================

    # Handle read-only return-eligibility questions without creating a return.
    asks_return_eligibility = bool(
        re.search(
            r"\b(eligible|eligibility)\b.*\b(return|returned)\b"
            r"|\b(return|returned)\b.*\b(eligible|eligibility)\b",
            question,
            re.IGNORECASE,
        )
    )

    if asks_return_eligibility and extracted_order_id:
        try:
            products = get_order_products(extracted_order_id)

            if not products:
                return jsonify({
                    "answer": (
                        f"I couldn't find order {extracted_order_id}. "
                        "Please check your order ID."
                    )
                })

            eligible_products = []
            ineligible_reasons = []

            # Check each product separately because eligibility can differ between items belonging to the same order.
            for product in products:
                eligibility = check_return_eligibility.invoke({
                    "order_id": extracted_order_id,
                    "product_id": str(product["product_id"]),
                })

                if eligibility.get("eligible"):
                    eligible_products.append(product["product_name"])
                else:
                    reason = eligibility.get(
                        "reason",
                        "This product is not eligible for return."
                    )
                    if reason not in ineligible_reasons:
                        ineligible_reasons.append(reason)

            if eligible_products:
                product_list = "\n".join(
                    f"- {name}" for name in eligible_products
                )

                answer = (
                    f"Order {extracted_order_id} has products "
                    "eligible for return:\n\n"
                    f"{product_list}\n\n"
                    "This was an eligibility check only. "
                    "No return request has been created."
                )
            else:
                reasons = "\n".join(
                    f"- {reason}" for reason in ineligible_reasons
                )

                answer = (
                    f"Order {extracted_order_id} is not eligible "
                    f"for return.\n\n{reasons}"
                    "\n\nNo return request has been created."
                )

            return jsonify({"answer": answer})

        except Exception:
            app.logger.exception(
                "Failed to check return eligibility for %s",
                extracted_order_id,
            )

            return jsonify({
                "answer": (
                    "Sorry, I couldn't check return eligibility "
                    "right now. Please try again."
                )
            }), 500

    # ============================================================
    # LIST RETURN-ELIGIBLE ORDERS
    # ============================================================

    # Handle requests to list orders eligible for return
    is_eligible_orders_question = bool(
        re.search(
            r"\b(show|list|find|get)\b.*\borders?\b.*\b(return|eligible)\b"
            r"|\b(which|what)\s+orders?\b.*\b(return|eligible)\b"
            r"|\borders?\b.*\b(eligible|returnable)\b",
            question,
            re.IGNORECASE,
        )
    )

    if is_eligible_orders_question:
        try:
            # Fetch only this customer's orders and their products
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            o.order_id,
                            o.order_status,
                            o.final_amount,
                            oi.product_id,
                            p.product_name
                        FROM orders AS o
                        JOIN order_items AS oi
                            ON oi.order_id = o.order_id
                        JOIN products AS p
                            ON p.product_id = oi.product_id
                        WHERE o.customer_id = %s
                        ORDER BY o.order_date DESC, o.order_id;
                    """, (current_user.customer_id,))
                    rows = cur.fetchall()

            eligible_orders = {}

            # Check eligibility for every product
            for row in rows:
                order_id, status, amount, product_id, product_name = row

                eligibility = check_return_eligibility.invoke({
                    "order_id": order_id,
                    "product_id": str(product_id),
                })

                if not eligibility.get("eligible"):
                    continue

                if order_id not in eligible_orders:
                    eligible_orders[order_id] = {
                        "status": status,
                        "amount": amount,
                        "products": [],
                    }

                eligible_orders[order_id]["products"].append(
                    product_name
                )

            if not eligible_orders:
                return jsonify({
                    "answer": (
                        "You don't have any orders currently eligible "
                        "for return. Only delivered products within the "
                        "30-day return window can be returned, subject "
                        "to the return policy."
                    )
                })

            # Format the eligible orders and remember the selection step so the customer
            # can choose an order in their next message.
            order_sections = []

            for index, (order_id, details) in enumerate(
                eligible_orders.items(), start=1
            ):
                product_names = ", ".join(details["products"])

                order_sections.append(
                    f"**{index}. Order ID:** {order_id}\n"
                    f"- **Status:** {details['status']}\n"
                    f"- **Amount:** ₹{float(details['amount']):,.2f}\n"
                    f"- **Eligible products:** {product_names}"
                )
            session["pending_intent"] = "return_refund"
            session["return_step"] = "awaiting_eligible_order_selection"
            session["eligible_return_order_ids"] = list(eligible_orders.keys())

            return jsonify({
                "answer": (
                    "**Your Orders Eligible for Return**\n\n"
                    + "\n\n".join(order_sections)
                    + "\n\nTo start a return, tell me which order "
                    "you want to return."
                )
            })

        except Exception:
            app.logger.exception(
                "Failed to retrieve return-eligible orders"
            )
            return jsonify({
                "answer": (
                    "Sorry, I couldn't retrieve your return-eligible "
                    "orders right now. Please try again."
                )
            }), 500

    # ============================================================
    # MULTI-STEP RETURN WORKFLOW
    # ============================================================
    
    # Continue an active return conversation based on the current step stored
    # in the session: order selection -> product -> reason -> confirmation/result.
    if (
        pending_intent == "return_refund"
        and return_step in (
            "awaiting_order_id",
            "awaiting_eligible_order_selection",
            "awaiting_product_selection",
            "awaiting_reason",
            "awaiting_confirmation",
        )
        and not is_return_status_question(question)
        and not is_return_policy_question(question)
    ):

        # Let the customer choose an order from the previously displayed list of orders eligible for return.
        if return_step == "awaiting_eligible_order_selection":
            order_ids = session.get("eligible_return_order_ids", [])

            if not question.strip().isdigit():
                return jsonify({
                    "answer": "Please select an order using its number."
                })

            # Convert the customer's 1-based selection into a list index.
            selected_index = int(question.strip()) - 1

            if selected_index < 0 or selected_index >= len(order_ids):
                return jsonify({
                    "answer": (
                        f"Please select a number between 1 and {len(order_ids)}."
                    )
                })

            selected_order_id = order_ids[selected_index]

            session["return_order_id"] = selected_order_id
            session["return_step"] = "awaiting_product_selection"

            # Retrieve the selected order's products and keep only return-eligible items.
            products = get_order_products(selected_order_id)

            eligible_products = []

            for product in products:
                eligibility = check_return_eligibility.invoke({
                    "order_id": selected_order_id,
                    "product_id": str(product["product_id"]),
                })

                if eligibility.get("eligible"):
                    eligible_products.append(product)

            # Stop the workflow if no products in the selected order are eligible.
            if not eligible_products:
                session.pop("pending_intent", None)
                session.pop("return_step", None)
                session.pop("return_order_id", None)
                session.pop("eligible_return_order_ids", None)

                return jsonify({
                    "answer": "This order has no products currently eligible for return."
                })

            # Save the eligible products so the customer can select one next.
            session["return_eligible_products"] = eligible_products

            product_list = "\n".join(
                f"{i}. {product['product_name']}"
                for i, product in enumerate(eligible_products, start=1)
            )

            return jsonify({
                "answer": (
                    f"You selected order **{selected_order_id}**.\n\n"
                    f"Eligible products:\n{product_list}\n\n"
                    "Which product would you like to return? Enter its number."
                )
            })

        # Stage 1: Collect the product selection
        if return_step == "awaiting_product_selection":

            # Ensure the workflow still has a valid order ID.
            if not return_order_id:
                session.pop("pending_intent", None)
                session.pop("return_step", None)
                session.pop("return_order_id", None)

                return jsonify({
                    "answer": (
                        "Please provide your order ID to continue "
                        "with your return."
                    )
                })

            # Reuse the saved eligible products, or fetch the order's products
            # if the eligible-product list is no longer available in the session.
            products = session.get("return_eligible_products")

            if not products:
                products = get_order_products(return_order_id)

            if not products:
                session.pop("pending_intent", None)
                session.pop("return_step", None)
                session.pop("return_order_id", None)

                return jsonify({
                    "answer": (
                        f"I couldn't find any products for order "
                        f"{return_order_id}."
                    )
                })

            # Match the customer's reply to a product by its number or name.
            selection = select_order_product(question, products)

            if selection.get("error"):
                product_list = "\n".join(
                    f"{i}. {product['product_name']}"
                    for i, product in enumerate(products, start=1)
                )

                return jsonify({
                    "answer": (
                        "I couldn't identify that product. "
                        "Please choose a number or enter the exact "
                        "product name:\n\n"
                        f"{product_list}"
                    )
                })

            # Save the selected product and move to collecting the return reason.
            return_product_id = selection["product_id"]
            return_product_name = selection["product_name"]

            session["return_product_id"] = return_product_id
            session["return_product_name"] = return_product_name
            session["return_step"] = "awaiting_reason"

            return jsonify({
                "answer": (
                    f"You selected **{return_product_name}**.\n\n"
                    "Please tell me why you'd like to return this product."
                )
            })

        # Stage 2: Collect the return reason and submit the return request.
        elif return_step == "awaiting_reason":

            # Verify that the order and product details are still available.
            if not return_order_id or not return_product_id:
                session.pop("pending_intent", None)
                session.pop("return_step", None)
                session.pop("return_order_id", None)
                session.pop("return_product_id", None)
                session.pop("return_product_name", None)

                return jsonify({
                    "answer": (
                        "Your return details are incomplete. "
                        "Please start the return request again."
                    )
                })

            reason = question.strip()

            if not reason:
                return jsonify({
                    "answer": "Please provide a reason for the return."
                })

            # Recheck eligibility before creating the return, since eligibility
            # may have changed since the product was initially selected.
            eligibility = check_return_eligibility.invoke({
                "order_id": return_order_id,
                "product_id": return_product_id,
            })

            if not eligibility.get("eligible"):
                session.pop("pending_intent", None)
                session.pop("return_step", None)
                session.pop("return_order_id", None)
                session.pop("return_product_id", None)
                session.pop("return_product_name", None)

                return jsonify({
                    "answer": eligibility.get(
                        "reason",
                        "This product is not eligible for return."
                    )
                })

            # Create the return only after the order, product, reason, and current eligibility have been checked.
            result = create_return.invoke({
                "order_id": return_order_id,
                "product_id": return_product_id,
                "reason": reason,
            })

            session.pop("pending_intent", None)
            session.pop("return_step", None)
            session.pop("return_order_id", None)
            session.pop("return_product_id", None)
            session.pop("return_product_name", None)

            if not result.get("success"):
                return jsonify({
                    "answer": result.get(
                        "message",
                        "Sorry, I couldn't create your return request."
                    )
                })

            # Confirm the successful request and show the customer its key details.
            return jsonify({
                "answer": (
                    f"Your return request has been created successfully!\n\n"
                    f"- **Return ID:** {result['return_id']}\n"
                    f"- **Order ID:** {result['order_id']}\n"
                    f"- **Product:** {return_product_name}\n"
                    f"- **Refund amount:** ₹{result['refund_amount']:.2f}\n"
                    f"- **Status:** {result['status']}"
                )
            })

    # ============================================================
    # INITIATE RETURN REQUEST
    # ============================================================

    # Start a return request or continue after receiving an order ID
    if (
            (
            is_return_request(question)
            and not is_return_status_question(question)
            )
        or (
            pending_intent == "return_refund"
            and return_step == "awaiting_order_id"
            and bool(extracted_order_id)
            )
        or (
            pending_intent == "return_refund"
            and not return_step
            and bool(extracted_order_id)
            and not is_return_status_question(question)
            )
        ):

        # Save the active workflow so the next message can continue the return process.
        session["pending_intent"] = "return_refund"
        session["last_workflow"] = "return_refund"

        # Use a newly supplied order ID, or the previously saved one.
        return_order_id = extracted_order_id or previous_order_id

        if not return_order_id:

            # Pause the workflow until the customer provides an order ID.
            session["return_step"] = "awaiting_order_id"

            return jsonify({
                "answer": (
                    "Please provide your order ID so I can help "
                    "with your return."
                )
            })

        
        # Save the order ID.
        session["return_order_id"] = return_order_id

        # Retrieve the products belonging to the specified order.
        products = get_order_products(return_order_id)

        if not products:

            # Reset the return workflow if the order has no retrievable products.
            session.pop("pending_intent", None)
            session.pop("return_step", None)
            session.pop("return_order_id", None)
            session.pop("return_product_id", None)
            session.pop("return_product_name", None)

            return jsonify({
                "answer": (
                    f"I couldn't find any products for order "
                    f"{return_order_id}. Please check your order ID."
                )
            })

        # Check whether at least one product is eligible for return
        eligible_products = []
        ineligible_reasons = []

        for product in products:
            eligibility = check_return_eligibility.invoke({
                "order_id": return_order_id,
                "product_id": str(product["product_id"]),
            })

            if eligibility.get("eligible"):
                eligible_products.append(product)
            else:
                ineligible_reasons.append(eligibility.get(
                    "reason",
                    "This product is not eligible for return."
                ))

        if not eligible_products:

            # End the workflow if none of the products can be returned.
            session.pop("pending_intent", None)
            session.pop("return_step", None)
            session.pop("return_order_id", None)
            session.pop("return_product_id", None)
            session.pop("return_product_name", None)

            # Remove duplicate reasons so the customer sees each explanation once.
            unique_reasons = list(dict.fromkeys(ineligible_reasons))

            return jsonify({
                "answer": (
                    f"Order {return_order_id} is not eligible for return.\n\n"
                    + "\n".join(f"- {reason}" for reason in unique_reasons)
                )
            })

        # Save the eligible products and display them as a numbered selection list.
        product_list = "\n".join(
            f"{i}. {product['product_name']}"
            for i, product in enumerate(eligible_products, start=1)
        )

        # Keep only the product details needed by the following selection step.
        session["return_eligible_products"] = [
            {
                "product_id": str(product["product_id"]),
                "product_name": product["product_name"],
            }
            for product in eligible_products
        ]

        session["return_step"] = "awaiting_product_selection"

        return jsonify({
            "answer": (
                f"Here are the products eligible for return in order "
                f"{return_order_id}:\n\n"
                f"{product_list}\n\n"
                "Please choose a product by entering its number "
                "or its exact name."
            )
        })

    # ============================================================
    # COMPLAINT REGISTRATION AND VALIDATION
    # ============================================================

    # Start a new complaint or continue an existing flow after receiving an order ID.
    if (
            (
            is_complaint_request(question)
            and not (
                pending_intent == "complaint"
                and complaint_step == "awaiting_details"
                    )
            )
        or  (
            pending_intent == "complaint"
            and complaint_step == "awaiting_order_id"
            and bool(extracted_order_id)
            )
        ):

        pending_intent = "complaint"
        session["pending_intent"] = "complaint"
        

        # Prefer the order ID in the current message over an order ID stored from an earlier message.
        complaint_order_id = (
            extracted_order_id
            or session.get("last_order_id")
        )

        # Log the selected ID and question to help diagnose complaint-flow issues.
        app.logger.info(
            "[COMPLAINT DEBUG] Question: %s | Extracted ID: %s | "
            "Selected ID: %s",
            question,
            extracted_order_id,
            complaint_order_id,
        )

        # Ask for the order ID if it hasn't been provided or saved.
        if not complaint_order_id:
            session.pop("complaint_order_id", None)
            session["complaint_step"] = "awaiting_order_id"

            return jsonify({
                "answer": "Sure, could you provide your order ID?"
            })

        # Verify that the order exists before proceeding with the complaint.
        try:
            order_result = get_order_details.invoke(
                {"order_id": complaint_order_id}
            )

            app.logger.info(
                "[COMPLAINT DEBUG] Order lookup result for %s: %s",
                complaint_order_id,
                order_result,
            )

        except Exception:

            # Log the failure and ask the customer to retry without exposing internal error details.
            app.logger.exception(
                "[COMPLAINT DEBUG] Order lookup failed for %s",
                complaint_order_id,
            )

            return jsonify({
                "answer": (
                    "Sorry, I couldn't verify that order right now. "
                    "Please try again."
                )
            }), 500

        # If the lookup didn't return an order record, ask the customer to verify the ID.
        if not isinstance(order_result, dict):
            session.pop("complaint_order_id", None)
            session["complaint_step"] = "awaiting_order_id"

            return jsonify({
                "answer": (
                    f"I couldn't find order {complaint_order_id}. "
                    "Please check the order ID and try again."
                )
            })

        # Check complaint eligibility BEFORE asking for the description
        complaint_eligibility = check_complaint_eligibility(
            complaint_order_id
            )

        if not complaint_eligibility["eligible"]:
            session.pop("pending_intent", None)
            session.pop("complaint_step", None)
            session.pop("complaint_order_id", None)

            return jsonify({
                "answer": complaint_eligibility["reason"]
            })

        
        # Check for an existing active complaint BEFORE asking for details
        try:
            existing_complaint = get_complaint_status_by_order.invoke({
                "order_id": complaint_order_id
            })

        except Exception:

            # Stop here if the existing-complaint check fails, so the workflow
            # doesn't proceed without confirming whether a complaint already exists.
            app.logger.exception(
                "Failed to check existing complaint for order %s",
                complaint_order_id
                                )

            return jsonify({
                "answer": (
                    "Sorry, I couldn't check whether this order already "
                    "has an active complaint. Please try again."
                          )
            }), 500

        # If an active complaint already exists for this order, prevent a duplicate registration.
        if (
            isinstance(existing_complaint, dict)
            and existing_complaint.get("found")
            and str(existing_complaint.get("status", "")).strip().lower()
            in ("open", "in progress")
            ):

            # Clear the complaint workflow before returning the existing complaint details.
            session.pop("pending_intent", None)
            session.pop("complaint_step", None)
            session.pop("complaint_order_id", None)

            return jsonify({
                "answer": (
                    f"An active complaint already exists for order "
                    f"{complaint_order_id}.\n\n"
                    f"- **Complaint ID:** "
                    f"{existing_complaint['complaint_id']}\n"
                    f"- **Status:** {existing_complaint['status']}\n\n"
                    "Please wait for the existing complaint to be "
                    "resolved before registering another one."
                    )
                })

        # Save the validated order ID and move to collecting the complaint description.
        session["complaint_order_id"] = complaint_order_id
        session["last_order_id"] = complaint_order_id
        session["complaint_step"] = "awaiting_details"

        app.logger.info(
            "[COMPLAINT DEBUG] Order %s validated and eligible. "
            "Waiting for complaint details.",
            complaint_order_id,
        )

        return jsonify({
            "answer": (
                f"What problem did you experience with "
                f"order {complaint_order_id}?"
            )
        })

    # ============================================================
    # COMPLAINT DETAILS AND REGISTRATION
    # ============================================================

    # This branch runs after the order has been validated and the user supplies
    # the complaint description in a follow-up message.
    # Collect the complaint description
    if (
        pending_intent == "complaint"
        and complaint_step == "awaiting_details"
        ):

        # Retrieve the validated order ID saved during the previous step.
        complaint_order_id = session.get("complaint_order_id")

        if not complaint_order_id:
            session["complaint_step"] = "awaiting_order_id"

            return jsonify({
                "answer": "Please provide your order ID."
            })

        # Pass the order ID and customer's description to the graph with instructions
        # to register a new complaint only.
        graph_question = (
            "Register a complaint for the customer.\n"
            f"Order ID: {complaint_order_id}\n"
            f"Complaint description: {question}\n"
            "Use the complaint registration tool. Do not modify an "
            "existing complaint. Confirm registration only if the "
            "tool succeeds."
        )

        previous_order_id = complaint_order_id
        graph_intent = "complaint"

        # Clear the complaint conversation state before invoking the graph
        # so the same complaint details are not processed again on a later message.
        session.pop("pending_intent", None)
        session.pop("complaint_step", None)
        session.pop("complaint_order_id", None)

    # ============================================================
    # INTENT ROUTING AND LANGGRAPH INVOCATION
    # ============================================================

    else:
        
        # Route order tracking and status questions directly to the order workflow.
        if (
            is_explicit_order_status_request(question)
            or is_order_tracking_request(question)
        ):
            graph_intent = "order"
            session["last_workflow"] = "order"

            if not previous_order_id:
                session["pending_intent"] = "order_status_id"

                return jsonify({
                    "answer": (
                        "Please provide your order ID so I can "
                        "check its status."
                    )
                })

            session.pop("pending_intent", None)

        # Handle return/refund status enquiries separately from requests to create a return.
        elif (
            is_return_status_question(question)
            or (
                is_general_status_request(question)
                and session.get("last_workflow") == "return_refund"
            )
            or (
                extracted_return_id
                and session.get("last_workflow") == "return_refund"
            )
        ):
            graph_intent = "return_refund"
            session["last_workflow"] = "return_refund"
            session["pending_intent"] = "return_refund"

        # Leave intent empty for general requests so the LangGraph supervisor
        # can decide which specialist workflow or analytics tool to use.
        # Route other questions through the supervisor
        else:
            graph_intent = ""

        # Convert a standalone return ID into a status question
        if extracted_return_id:
            graph_question = (
                f"What is the return status for {extracted_return_id}?"
            )
        
        else:
            graph_question = question


    # Invoke LangGraph to process the question using the selected intent and conversation context.
    try:
        print(
            "DEBUG: Chatbot request reached LangGraph:",
            graph_question,
            "| Intent:",
            graph_intent,
            flush=True
        )

        result = support_graph.invoke({
            "question": graph_question,
            "intent": graph_intent,
            "answer": "",
            "order_id": previous_order_id,
            "return_id": "",
            "return_status": "",
        })

        # Save an order ID returned by the graph for use in follow-up questions.
        returned_order_id = str(result.get("order_id") or "").strip()

        if returned_order_id:
            session["last_order_id"] = returned_order_id

        answer = result.get(
            "answer",
            "Sorry, I couldn't process your request right now.",
        )

        # Clear complaint state after the graph has processed the complaint request.
        if graph_intent == "complaint":
            session.pop("pending_intent", None)
            session.pop("complaint_step", None)
            session.pop("complaint_order_id", None)

        # Clear the pending return intent while preserving the last workflow
        # so follow-up return-status questions can still be recognized.
        elif graph_intent == "return_refund":
            session.pop("pending_intent", None)

        # Clear any pending order-status prompt after processing the order request.
        elif graph_intent == "order":
            session.pop("pending_intent", None)

        # ============================================================
        # RESPONSE FORMATTING AND ANALYTICS
        # ============================================================

        # Build the response returned to the frontend.
        response_data = {"answer": answer}

        # Include analytics data and chart information only for analytics responses.
        if str(result.get("intent", "")).strip().lower() == "analytics":
            analytics_results = result.get("analytics_results", [])

            response_data["analytics_results"] = analytics_results

            # Generate the chart configuration based on the question and analytics results.
            # The frontend uses these to render Chart.js.
            chart_spec = generate_analytics_chart_spec(
                question,
                analytics_results,
            )
            print("DEBUG chart_spec returned:", repr(chart_spec))

            response_data["chart_spec"] = chart_spec

            # Extract the rows that match the chart's selected X and Y axes.
            chart_rows = []

            if isinstance(chart_spec, dict) and chart_spec.get("show_chart"):
                x_key = chart_spec.get("x_key")
                y_key = chart_spec.get("y_key")

                # # Detect a requested year so the chart can exclude data from other years, e.g. "for 2026".
                year_match = re.search(
                    r"\b(?:for|in|during)\s+(20\d{2})\b",
                    question,
                    re.IGNORECASE,
                )

                # ============================================================
                # ANALYTICS CHART DATA PROCESSING
                # ============================================================

                requested_year = year_match.group(1) if year_match else None

                for result_item in analytics_results:
                    if not isinstance(result_item, dict):
                        continue

                    raw_data = result_item.get("data", [])

                    # Support the different data structures returned by analytics tools.
                    if isinstance(raw_data, list):
                        rows = raw_data

                    elif isinstance(raw_data, dict):

                        # Use category-level spending data when available.
                        category_spending = raw_data.get("category_spending", [])

                        if isinstance(category_spending, list) and category_spending:
                            rows = category_spending

                        # Otherwise, use product-level analytics data.
                        else:
                            products = raw_data.get("products", [])

                            if isinstance(products, list) and products:
                                rows = products

                            # Convert status counts into rows the chart can display.
                            elif isinstance(raw_data.get("status_counts"), dict):
                                status_counts = raw_data["status_counts"]

                                rows = [
                                    {
                                        "status": status.title(),
                                        "count": count,
                                    }
                                    for status, count in status_counts.items()
                                    if isinstance(count, (int, float))
                                    and not isinstance(count, bool)
                                ]

                            else:
                                rows = []

                    else:
                        rows = []

                    # Ignore entries that aren't individual data-row dictionaries.
                    rows = [
                        row for row in rows
                        if isinstance(row, dict)
                    ]

                    # Keep rows containing both chart axes and a numeric Y-axis value.
                    matching_rows = [
                        row for row in rows
                        if x_key in row
                        and y_key in row
                        and isinstance(row.get(y_key), (int, float))
                        and not isinstance(row.get(y_key), bool)
                    ]

                    # If a year was requested, keep only rows whose X-axis value starts with that year.
                    if requested_year:
                        matching_rows = [
                            row for row in matching_rows
                            if str(row.get(x_key, "")).startswith(requested_year)
                        ]

                    # Use the first dataset that contains matching chart rows.
                    if matching_rows:
                        chart_rows = matching_rows
                        break

            # Send the chart data and configuration to the frontend.
            response_data["chart_rows"] = chart_rows

            print(
                "DEBUG response chart_spec:",
                repr(response_data.get("chart_spec")),
            )
            print(
                "DEBUG response chart_rows:",
                repr(response_data.get("chart_rows")),
            )

        return jsonify(response_data)

    # Log unexpected processing errors and return a safe message to the customer.
    except Exception:
        app.logger.exception("Error while processing customer message")
        return jsonify({
            "answer": (
                "Sorry, something went wrong while processing your "
                "request. Please try again."
            )
        }), 500

# ============================================================
# CHAT RESET AND SESSION CLEANUP
# ============================================================

# Clear conversational workflow state while keeping the customer logged in.
@app.route("/reset", methods=["POST"])
@login_required
def reset_chat():

    # Clear conversation and workflow state while keeping the customer logged in.
    chat_keys = [
        "last_order_id",
        "pending_intent",
        "last_workflow",
        "complaint_step",
        "complaint_order_id",
        "return_step",
        "return_order_id",
        "return_product_id",
        "return_product_name",
        "eligible_return_order_ids",
        "return_eligible_products",
    ]

    for key in chat_keys:
        session.pop(key, None)

    return jsonify({"success": True})

# ============================================================
# APPLICATION STARTUP
# ============================================================

# Start the Flask development server when this file is run directly.
if __name__ == "__main__":
    # Debug mode is disabled by default; enable it explicitly for local development.
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)
