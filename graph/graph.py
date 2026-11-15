# Date utilities are used to parse customer-requested dates and format order dates.
from datetime import datetime, timedelta
from typing import Literal, TypedDict
from langchain_groq import ChatGroq
import json
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from tools.analytics_tools import (
    spending_summary_tool,
    category_spending_tool,
    spending_trends_tool,
    spending_for_period_tool,
    top_products_tool,
    order_analytics_tool,
    order_list_tool,)
from agents.order_agents import faq_agent, complaint_agent
from tools.order_tools import (
    get_order_details,
    get_my_orders,
    get_return_status,
    get_return_status_by_order,
    check_return_eligibility,
    create_return,
)
import re, logging

# Restrict routing to the request types the support workflow knows how to handle.
Intent = Literal["order", "my_orders", "faq", "return_refund", "complaint", "analytics"]

# Use a low-temperature model for more consistent routing and tool-selection decisions.
model = ChatGroq(model="openai/gpt-oss-20b", temperature=0)

# Define the chart specification
class AnalyticsChartSpec(BaseModel):
    show_chart: bool = Field(
        description="Whether the results support a meaningful chart."
    )
    title: str = Field(description="A concise chart title.")
    chart_type: Literal["bar", "line", "pie"]
    x_key: str = Field(description="Field for category labels.")
    y_key: str = Field(description="Field containing numeric values.")
    x_label: str = Field(default="", description="Readable label for the x-axis.")
    y_label: str = Field(default="", description="Readable label for the y-axis.")
    type_requested: bool = Field(
        default=False,
        description="True when the user explicitly named the chart type.",
    )
    note: str = Field(default="", description="Optional note shown under the chart.")

# Configure the chart-generation model
analytics_chart_model = model.with_structured_output(
    AnalyticsChartSpec,
    method="json_mode"
)


def generate_analytics_chart_spec(question, analytics_results):
    """Build a chart configuration from actual analytics results, or disable charts when data is unsuitable."""
    print("DEBUG analytics_results:", repr(analytics_results))

    # Return this safe default whenever the results cannot support a meaningful chart.
    no_chart = {
        "show_chart": False,
        "title": "",
        "chart_type": "bar",
        "x_key": "",
        "y_key": "",
        "x_label": "",
        "y_label": "",
        "type_requested": False,
        "note": "",
    }

    if not analytics_results:
        return no_chart

    # Extract actual tabular data returned by the analytics tools.
    datasets = []

    # Tool outputs can have different shapes, so normalize them into a common list of row dictionaries.
    for result in analytics_results:
        if not isinstance(result, dict):
            continue

        raw_data = result.get("data", {})

        if isinstance(raw_data, list):
            rows = raw_data
      
        elif isinstance(raw_data, dict):
            # Handle category spending for a specific date range.
            category_spending = raw_data.get("category_spending", [])

            if isinstance(category_spending, list) and category_spending:
                rows = category_spending

            # Handle top-products analytics results.
            else:
                products = raw_data.get("products", [])

                if isinstance(products, list) and products:
                    rows = products

                # Handle order status analytics results.
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

        rows = [
            row for row in rows
            if isinstance(row, dict)
        ]

        if rows:
            datasets.append({
                "tool": result.get("tool", ""),
                "rows": rows,
                "fields": list(rows[0].keys()),
            })

    if not datasets:
        return no_chart

    # Keep pie charts limited to a small number of categories so labels remain readable.
    # Part-to-whole data with at most this many categories is shown as a pie.
    AUTO_PIE_MAX_CATEGORIES = 4

    question_lower = question.lower()

    year_wise_requested = any(
        phrase in question_lower
        for phrase in (
            "year-wise",
            "year wise",
            "each year",
            "every year",
            "by year",
            "per year",
            "annually",
            "annual spending",
            "yearly spending",
        )
    )

    quarter_wise_requested = any(
        phrase in question_lower
        for phrase in (
            "quarter-wise",
            "quarter wise",
            "each quarter",
            "every quarter",
            "by quarter",
            "per quarter",
            "quarterly spending",
            "quarterly breakdown",
        )
    )

    # Explicit year/quarter breakdowns should use a bar chart.
    if year_wise_requested or quarter_wise_requested:
        for dataset in datasets:
            rows = dataset["rows"]
            fields = dataset["fields"]

            if not rows:
                continue

            # Find the time field and spending field from actual data.
            time_fields = (
                ("year", "order_year", "spending_year")
                if year_wise_requested
                else ("quarter", "order_quarter", "spending_quarter")
            )

            x_key = next(
                (field for field in time_fields if field in fields),
                None,
            )

            y_key = next(
                (
                    field for field in (
                        "spending",
                        "total_spent",
                        "total_amount",
                        "amount",
                    )
                    if field in fields
                ),
                None,
            )

            if x_key and y_key:
                numeric_rows = [
                    row for row in rows
                    if row.get(x_key) is not None
                    and isinstance(row.get(y_key), (int, float))
                    and not isinstance(row.get(y_key), bool)
                ]

                if len(numeric_rows) >= 2:
                    return {
                        "show_chart": True,
                        "title": (
                            "Year-wise Spending"
                            if year_wise_requested
                            else "Quarter-wise Spending"
                        ),
                        "chart_type": "bar",
                        "x_key": x_key,
                        "y_key": y_key,
                        "x_label": (
                            "Year" if year_wise_requested else "Quarter"
                        ),
                        "y_label": "Spending (₹)",
                        "type_requested": True,
                        "note": "",
                    }
    
    # --------------------------------------------------
    # Percentage / part-to-whole questions: prefer pie.
    # Keep the existing year/quarter bar-chart logic above.
    # --------------------------------------------------
    percentage_requested = any(
        phrase in question_lower
        for phrase in (
            "what percentage",
            "what percent",
            "percentage of",
            "percentage share",
            "percent of",
            "proportion",
            "distribution",
            "share of",
            "breakdown by percentage",
        )
    )

    if percentage_requested:
        category_candidates = (
            "order_status",
            "status",
            "category",
            "product_category",
            "category_name",
            "payment_method",
            "product_name",
            "product",
        )

        value_candidates = (
            "count",
            "order_count",
            "total_orders",
            "orders_count",
            "spending",
            "total_spent",
            "total_spending",
            "total_amount",
            "amount",
            "value",
            "percentage",
            "percent",
            "share",
        )

        def normalise_field(field):
            return "".join(
                char.lower()
                for char in str(field)
                if char.isalnum()
            )

        for dataset in datasets:
            rows = dataset["rows"]
            fields = dataset["fields"]

            normalised_fields = {
                normalise_field(field): field
                for field in fields
            }

            # Identify the category/status field.
            x_key = next(
                (
                    normalised_fields[normalise_field(candidate)]
                    for candidate in category_candidates
                    if normalise_field(candidate) in normalised_fields
                ),
                None,
            )

            # Identify the numeric measure.
            y_key = next(
                (
                    normalised_fields[normalise_field(candidate)]
                    for candidate in value_candidates
                    if normalise_field(candidate) in normalised_fields
                ),
                None,
            )

            if not x_key or not y_key:
                continue

            valid_rows = [
                row for row in rows
                if row.get(x_key) is not None
                and isinstance(row.get(y_key), (int, float))
                and not isinstance(row.get(y_key), bool)
                and row.get(y_key) >= 0
            ]

            # A pie needs at least two categories and a positive total.
            if len(valid_rows) < 2:
                continue

            if sum(row[y_key] for row in valid_rows) <= 0:
                continue

            return {
                "show_chart": True,
                "title": (
                    "Order Status Distribution"
                    if normalise_field(x_key) in (
                        "status",
                        "orderstatus",
                    )
                    else "Spending Distribution by Category"
                    if normalise_field(x_key) in (
                        "category",
                        "productcategory",
                        "categoryname",
                    )
                    else f"Distribution by {x_key.replace('_', ' ').title()}"
                ),
                "chart_type": "pie",
                "x_key": x_key,
                "y_key": y_key,
                "x_label": x_key.replace("_", " ").title(),
                "y_label": y_key.replace("_", " ").title(),
                "type_requested": False,
                "note": "",
            }


    # Only treat wording as an explicit chart request when the user names a chart/graph type.
    def detect_requested_chart_type(text):
        """Return 'pie', 'bar' or 'line' only when the user names a chart type."""
        text = text.lower()

        if re.search(r"\b(pie|donut|doughnut)\b", text):
            return "pie"

        if re.search(r"\b(bar|column)\s+(chart|graph|plot)\b|\bhistogram\b", text):
            return "bar"

        if re.search(r"\bline\s+(chart|graph|plot)\b|\btrend\s*line\b", text):
            return "line"

        return None

    # Choose a chart that fits the data shape while respecting supported user preferences.
    def choose_chart_type(rows, x_key, y_key, requested_type=None, explicit=False):
        """
        Select a chart from the data and the wording of the question.

        Order of decisions:
        1. A chart type the user named explicitly wins if the data supports it.
        2. A soft hint ("share", "proportion") selects a pie if possible.
        3. Time series: bars when sparse or short, otherwise a line.
        4. Two to AUTO_PIE_MAX_CATEGORIES additive categories: a pie.
        5. Everything else: bars.
        """
        usable_rows = [
            row for row in rows
            if isinstance(row, dict)
            and isinstance(row.get(y_key), (int, float))
            and not isinstance(row.get(y_key), bool)
            and row.get(x_key) is not None
        ]

        if len(usable_rows) < 2:
            return "bar" if usable_rows else None

        values = [row[y_key] for row in usable_rows]

        # A pie needs non-negative values and a positive total.
        pie_possible = all(value >= 0 for value in values) and sum(values) > 0

        # 1 and 2. Requested type (explicit request or wording hint).
        if requested_type == "pie" and pie_possible:
            return "pie"

        if explicit and requested_type in ("bar", "line"):
            return requested_type

        x_name = x_key.lower()
        y_name = y_key.lower()
        is_time_series = any(
            term in x_name
            for term in ("date", "time", "month", "week", "year")
        )

        # 3. Time series.
        if is_time_series:
            nonzero_ratio = sum(value != 0 for value in values) / len(values)

            if len(usable_rows) < 6 or nonzero_ratio < 0.6:
                return "bar"

            return "line"

        # 4. A few categories that add up to a whole read best as a pie.
        # Averages and rates are not parts of a whole, and product lists
        # are rankings, so both stay as bars.
        is_additive = not any(
            term in y_name
            for term in ("avg", "average", "rate", "ratio", "percent", "per_")
        )
        is_ranking = "product" in x_name

        if (
            len(usable_rows) <= AUTO_PIE_MAX_CATEGORIES
            and pie_possible
            and is_additive
            and not is_ranking
        ):
            return "pie"

        # 5. Default comparison chart.
        return "bar"


    # Check model-generated chart fields against the real dataset before passing them to the frontend.
    def valid_chart_spec(raw_spec):
        """Validate the specification against the actual returned rows."""
        if hasattr(raw_spec, "model_dump"):
            raw_spec = raw_spec.model_dump()

        if not isinstance(raw_spec, dict):
            return None

        try:
            spec = AnalyticsChartSpec.model_validate(raw_spec).model_dump()
        except Exception:
            return None

        if not spec["show_chart"]:
            return no_chart.copy()

        chart_type = spec["chart_type"]
        x_key = spec["x_key"]
        y_key = spec["y_key"]

        if chart_type not in {"bar", "line", "pie"}:
            return None

        # Both axes must exist in the same returned dataset.
        for dataset in datasets:
            rows = dataset["rows"]

            if x_key not in dataset["fields"]:
                continue

            if y_key not in dataset["fields"]:
                continue

            # A chart needs at least one usable numeric value.
            numeric_values = [
                row.get(y_key)
                for row in rows
                if isinstance(row.get(y_key), (int, float))
                and not isinstance(row.get(y_key), bool)
            ]

            if numeric_values:
                selected_type = choose_chart_type(
                    rows=rows,
                    x_key=x_key,
                    y_key=y_key,
                    requested_type=spec["chart_type"],
                )

                if selected_type is None:
                    return None

                spec["chart_type"] = selected_type

                print(
                    "DEBUG chart type selected from data:",
                    selected_type,
                    "| rows:",
                    len(rows),
                    "| x_key:",
                    x_key,
                    "| y_key:",
                    y_key,
                )

                return spec
        return None

    # If automatic/model-based chart selection is unavailable, infer a chart from verified fields.
    def fallback_chart_spec():
        """Choose a chart using verified fields and actual data characteristics."""
        question_lower = question.lower()

        measure_preferences = [
            "spending",
            "revenue",
            "total_spent",
            "total_amount",
            "amount",
            "quantity_purchased",
            "order_count",
            "count",
            "total",
        ]

        label_preferences = [
            "product_name",
            "product",
            "month",
            "date",
            "week",
            "year",
            "category",
            "status",
            "name",
        ]

        # Interpret the user's question as a chart preference.
        explicit_type = detect_requested_chart_type(question)

        if explicit_type:
            requested_type = explicit_type

        elif any(term in question_lower for term in (
            "percentage share",
            "proportion",
            "composition",
            "breakdown share",
            "distribution",
        )):
            requested_type = "pie"

        elif any(term in question_lower for term in (
            "trend",
            "over time",
            "monthly",
            "weekly",
            "daily",
            "yearly",
        )):
            requested_type = "line"

        else:
            requested_type = None

        for dataset in datasets:
            rows = dataset["rows"]
            fields = dataset["fields"]

            # Find fields containing actual numeric measurements.
            numeric_fields = [
                field
                for field in fields
                if any(
                    isinstance(row.get(field), (int, float))
                    and not isinstance(row.get(field), bool)
                    for row in rows
                )
            ]

            if not numeric_fields:
                continue

            # Choose a measure that best matches common analytics outputs.
            y_key = next(
                (
                    field
                    for field in measure_preferences
                    if field in numeric_fields
                ),
                numeric_fields[0],
            )

            # Prefer a time or category field for the horizontal axis.
            x_key = next(
                (
                    field
                    for field in label_preferences
                    if field in fields and field != y_key
                ),
                None,
            )

            # If no preferred label exists, use another suitable field.
            if x_key is None:
                x_key = next(
                    (
                        field
                        for field in fields
                        if field != y_key
                        and any(
                            row.get(field) is not None
                            and isinstance(
                                row.get(field),
                                (str, int, float),
                            )
                            and not isinstance(row.get(field), bool)
                            for row in rows
                        )
                    ),
                    None,
                )

            if x_key is None:
                continue

            # Select the chart type based on the returned data.
            chart_type = choose_chart_type(
                rows=rows,
                x_key=x_key,
                y_key=y_key,
                requested_type=requested_type,
                explicit=bool(explicit_type),
            )

            if chart_type is None:
                continue

            # Tell the user when their requested chart cannot show this data.
            note = ""
            if explicit_type and chart_type != explicit_type:
                note = (
                    f"A {explicit_type} chart cannot show this data, "
                    f"so a {chart_type} chart is shown instead."
                )

            spec = {
                "show_chart": True,
                "title": (
                    question.strip().rstrip("?.!")
                    or "Analytics Results"
                ),
                "chart_type": chart_type,
                "x_key": x_key,
                "y_key": y_key,
                "x_label": x_key.replace("_", " ").title(),
                "y_label": y_key.replace("_", " ").title(),
                "type_requested": bool(explicit_type),
                "note": note,
            }

            print(
                "DEBUG fallback chart specification:",
                repr(spec),
            )

            return spec

        print("DEBUG: No suitable chart could be generated.")
        print("DEBUG question:", repr(question))
        print("DEBUG available datasets:", repr([
            {
                "tool": dataset["tool"],
                "fields": dataset["fields"],
                "sample_rows": dataset["rows"][:3],
            }
            for dataset in datasets
        ]))
        return no_chart.copy()
    return fallback_chart_spec()


# State fields are shared between graph nodes; total=False allows nodes to update only relevant fields.
class SupportState(TypedDict, total=False):
    question: str
    intent: Intent | str
    answer: str
    order_id: str
    return_id: str
    return_status: str
    analytics_results: list

class SupervisorDecision(BaseModel):
    intent: Intent


class AnalyticsPlan(BaseModel):
    metric: Literal[
        "spending",
        "order_count",
        "category_spending",
        "summary",
    ]

    start_date: str | None = None
    end_date: str | None = None

    group_by: Literal[
        "month",
        "category",
        "none",
    ] = "none"

    chart_type: Literal[
        "line",
        "bar",
        "pie",
        "none",
    ] = "none"

# These are the analytics tools the LLM is allowed to call for customer spending and order questions.
analytics_tools = [
    spending_summary_tool,
    category_spending_tool,
    spending_trends_tool,
    spending_for_period_tool,
    top_products_tool,
    order_analytics_tool,
    order_list_tool,
    
]

# TEMPORARY DEBUG: Print analytics tool schemas
for analytics_tool in analytics_tools:
    print(
        "TOOL SCHEMA:",
        analytics_tool.name,
        analytics_tool.args
    )

analytics_agent_model = model.bind_tools(
    analytics_tools,
    tool_choice="auto"
)


def run_analytics_agent(question: str) -> str:
    """Let the model choose analytics tools, execute calls, and collect their results for the final answer/chart."""
    """Let the LLM select analytics tools, execute them, and answer."""
    messages = [
        (
            "system",
            
            """You are an ecommerce analytics assistant.

            Use the available tools to answer questions about the authenticated customer's data.
            Choose the appropriate tools based on the question. You may call multiple tools when
            needed to provide a complete answer.

            Rules:
            1. All monetary values are in Indian rupees (INR). Always use ₹, never $ or USD.
            2. For date-specific questions, use ISO dates (YYYY-MM-DD). The start date is inclusive
                and the end date is exclusive.
            3. Never invent figures. Base all numerical answers on tool results.
            4. Answer every part of the user's question. Do not stop mid-sentence or leave
                calculations or comparisons incomplete.
            5. For category comparisons, include category, quantity purchased, total spending,
                and average spending per item when the tool results provide the necessary data.
            6. Calculate averages using total spending divided by quantity. Format averages
                to two decimal places when necessary.
            7. Use clean Markdown formatting:
                - Use proper Markdown tables with no escaped pipe characters.
                - Use clear headings and concise bullet points where appropriate.
                - Format currency consistently, e.g. ₹1,982.50.
                - Avoid mentioning internal tool names, tool calls, or implementation details.
            8. For monthly trends, distinguish months with zero recorded spending from future
                months that have not yet occurred.
            9. End with a complete sentence and ensure the response is readable.
            10. For a simple spending question, answer directly with the total amount,
                date range, and order count when available. Do not add a chart heading
                or discuss chart data in the text response. The frontend handles charts
                separately.
            11. For order analytics:
                - Use metric='total' for the number of orders, excluding cancelled orders.
                - Use metric='cancelled' for cancelled order counts.
                - Use metric='status' for counts grouped by order status.
                - For date-specific questions, provide start_date and end_date in YYYY-MM-DD format.
                - Interpret "last month" relative to the current date, 2026-10-21.
                - Never claim that total orders include cancelled orders when using metric='total'.
            12. For individual order details:
                - Use the order-listing tool when the user asks for specific order IDs, dates,
                statuses, delivery locations, or individual order amounts.
                - For "most recent order", retrieve orders sorted by date descending and report
                the first result.
                - For requests about shipped or delivered orders, filter by the requested status.
                - For date-specific requests, ALWAYS pass start_date and end_date
                to the order-listing tool. Never retrieve all orders and filter them
                yourself after retrieval.

                - If the user specifies a calendar year, convert it to a date range:
                    - "in 2025" or "for the year 2025":
                        start_date="2025-01-01"
                        end_date="2026-01-01"

                - If the user specifies a single month:
                    - "in March 2023":
                        start_date="2023-03-01"
                        end_date="2023-04-01"

                - If the user specifies a month-to-month range:
                    - "from March 2023 to September 2024":
                        start_date="2023-03-01"
                        end_date="2024-10-01"

                - For month ranges, include the entire starting month and
                the entire ending month. Set end_date to the first day
                of the month following the requested ending month.

                - If the user specifies an exact date range, use the requested
                start date and the day immediately after the final date as
                end_date, so the final date is included.

                - The start date is inclusive and the end date is exclusive.

                - Apply the requested status filter and date range together
                when both are specified.

                - If no matching orders are returned, clearly say no orders
                were found for the requested period. Never substitute orders
                from other years or months.
                - Do not invent order details or claim an order exists unless the tool returns it.
                - Format final_amount in Indian rupees (₹) with two decimal places.
                - For ranking questions such as "top 3 orders by price", "most expensive
                orders", or "cheapest order", call the order-listing tool with
                sort_by='amount', limit set to the requested number, and
                sort_order='desc' for highest or 'asc' for lowest. Never fetch a
                longer list and pick the top results yourself.
                - For those ranking questions set include_cancelled=False, and
                mention that cancelled orders were excluded. Include cancelled
                orders only if the user asks for them.
                - When the user asks for N orders, list exactly N orders, in the
                order the tool returned them.
            13. For analytics follow-up questions, use the conversation history to resolve
                references such as "that month", "that category", and "compare it".
                If the previous answer identified a specific month, use that month when
                answering a follow-up instead of asking the user to specify it again.

            14. When asked to compare a previously identified month with the previous month,
                retrieve or use the actual spending figures for both months and calculate
                the percentage change. Never invent missing figures.

            15. If the conversation history does not identify the referenced month clearly,
                ask the user for clarification.

            16. For questions asking for monthly order counts or monthly spending
                trends, prefer spending_trends_tool when it provides the required
                date range and monthly order_count data.

                Do not call order_analytics_tool separately for each month when
                one tool can provide the complete monthly breakdown.

                Use the exact date range requested by the customer.
                For the year 2025, use start_date='2025-01-01' and
                end_date='2026-01-01'.
            """

        ),
        ("human", question),
    ]

    tool_map = {tool.name: tool for tool in analytics_tools}

    analytics_results = []

    # Allow several rounds because one answer may require multiple related tool calls.
    for _ in range(5):
        response = analytics_agent_model.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return {
                "answer": response.content or "I couldn't generate an analytics answer.",
                "analytics_results": analytics_results,
            }
   
        for call in response.tool_calls:
            tool_name = call.get("name", "")
            raw_args = call.get("args", {})

            print("Analytics tool selected:", tool_name)
            print("Raw analytics tool arguments:", repr(raw_args))

            # Resolve the requested tool by name instead of executing an arbitrary function name from the model.
            selected_tool = tool_map.get(tool_name)

            if selected_tool is None:
                result = {"error": "Unknown analytics tool."}

            else:
                try:
                    # Validate the arguments returned by the model.
                    if not isinstance(raw_args, dict):
                        raise ValueError(
                            f"Tool arguments must be a dictionary, got: {type(raw_args).__name__}"
                        )

                    args = {
                        key: value
                        for key, value in raw_args.items()
                        if isinstance(key, str) and key.strip()
                    }

                    print("Validated analytics tool arguments:", args)

                    # Execute the selected tool with validated arguments and keep the raw result for chart generation.
                    result = selected_tool.invoke(args)

                    analytics_results.append({
                        "tool": tool_name,
                        "arguments": args,
                        "data": result,
                    })

                except Exception as exc:
                    logging.exception(
                        "Analytics tool execution failed: %s",
                        tool_name,
                    )
                    result = {"error": str(exc)}

            messages.append(
                ToolMessage(
                    content=json.dumps(result, default=str),
                    tool_call_id=call["id"],
                )
            )


    return {
        "answer": "I couldn't complete the analytics request within the allowed tool calls.",
        "analytics_results": analytics_results,
    }

analytics_planner_model = model.with_structured_output(
    AnalyticsPlan,
    method="json_mode"
)


def plan_analytics_question(question: str) -> AnalyticsPlan:
    """Convert a natural-language analytics question into structured metric, date, grouping, and chart preferences."""
    current_date = "2026-10-21"

    planner_prompt = f"""
    You are an analytics planner for an e-commerce customer support chatbot.
    Today's date is {current_date}.

    Convert the user's analytics question into a structured plan.
    Return the result as valid JSON matching the AnalyticsPlan schema.
    Return only a JSON object, with no Markdown code fences or additional text.

    Rules:
    - metric:
    - spending: total money spent
    - order_count: number of orders
    - category_spending: spending grouped by product category
    - summary: a general overview of spending and orders
    - group_by:
    - month for monthly breakdowns or trends
    - category for category breakdowns
    - none when no grouping is required
    - chart_type:
    - line for trends over time
    - bar for comparisons or monthly breakdowns
    - pie for category proportions
    - none when no chart is needed
    - Extract explicit date ranges into start_date and end_date.
    - Dates must use YYYY-MM-DD.
    - start_date is inclusive; end_date is exclusive.
    - For a month, use its first day as start_date and the first day of the following month as end_date.
    - For a year, use January 1 of that year as start_date and January 1 of the following year as end_date.
    - Resolve relative dates using today's date.
    - If no date range is specified, set both dates to null.
    - Do not invent dates or assume a date range when none is requested.
    - Return only fields defined by the schema.
    """

    return analytics_planner_model.invoke(
        [
            ("system", planner_prompt),
            ("human", question),
        ]
    )

supervisor_model = model.with_structured_output(SupervisorDecision)

# The supervisor prompt defines the routing rules and examples used to classify each customer message.
supervisor_prompt = """
You are a customer support supervisor. Classify the customer's question into exactly one category.

- order: questions about a specific order, order status, delivery status, or order details.
- faq: general company policies, payment or shipping policies, return policies, return eligibility, refund methods, refund policies, and general product-support information.
- return_refund: requests to initiate or process a return or refund, or questions about the status of an existing return/refund request.
- complaint: requests to report a problem, express dissatisfaction, register a complaint, or check an existing complaint.
- analytics: questions about the logged-in customer's total spending, monthly spending, spending trends, and order frequency.

Classification rules:
- Asking "What is the return policy?" is faq.
- Asking "Can I return a damaged or defective product?" is faq.
- Asking whether an item is eligible for return is faq.
- my_orders: requests to view or list all orders belonging to the logged-in customer.
- Mentioning a return does not by itself mean the customer wants to initiate one.
- "I want to return this product" is return_refund.
- "Please initiate a return for order ORD1005" is return_refund.
- Asking for the status of an already-created return is return_refund.
- Asking where a refund will be received is faq.
- Asking which payment method will be used for a refund is faq.
- Asking how a Cash on Delivery refund can be received is faq.
- Asking about refund timelines or general refund policies is faq.
- "Where will I receive my refund?" is faq.
- "How will I get my money back?" is faq.
- "Can I receive my COD refund in my bank account?" is faq.
- "What is the status of my refund?" is return_refund.
- "Has my refund been processed?" is return_refund.
- Explicitly asking to file a complaint about a damaged product is complaint.
- Asking about shipping policy is faq.
- Asking where an order is or when it will arrive is order.
- General policy questions must remain faq even if they mention an order, return, damaged product, or refund.
- Checking the status of a specific order, return, or refund is different from asking about its general policy.

Examples:
- "Where will I receive my refund?" -> faq
- "How will I get my money back?" -> faq
- "Show my orders" -> my_orders
- "List all my orders" -> my_orders
- "What orders have I placed?" -> my_orders
- "Can I receive my COD refund in my bank account?" -> faq
- "What is the status of my refund?" -> return_refund
- "I want to return order ORD1005." -> return_refund
- "What is the return policy?" -> faq
- "Where is my order ORD1005?" -> order
- "I want to file a complaint about my damaged product." -> complaint
- "How much have I spent?" -> analytics
- "Show my monthly spending." -> analytics
- "How many orders have I placed?" -> analytics

Return the classification using the required structured output.
"""

VALID_INTENTS = {"order", "my_orders", "faq", "return_refund", "complaint", "analytics"}


def _text(value) -> str:
    """Normalize optional values to trimmed strings so routing logic handles None and non-string inputs safely."""
    """Convert possibly missing values into safe strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _message_content_to_text(content) -> str:
    """Convert common model content formats into one plain-text string."""
    """Handle either string content or a list of content blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(part.strip() for part in parts if part.strip())
    return _text(content)


def _extract_order_id(question: str, previous_order_id: str = "") -> str:
    """Extract flexible order IDs without requiring exactly four digits
    after ORD. Avoid interpreting years or unrelated numbers as order IDs.
    """
    question = _text(question)

    # Match IDs such as ORD123, ORD2026ABC, ORD-12345,
    # and TSTORDTRANSIT01.
    match = re.search(
        r"\b(?:TST)?ORD[A-Z0-9]*(?:-[A-Z0-9]+)*\b",
        question,
        re.IGNORECASE,
    )
    if match:
        return match.group(0).upper()

    # Accept a standalone numeric ID only when the entire message
    # consists of digits.
    if re.fullmatch(r"\s*\d+\s*", question):
        return f"ORD{question.strip()}"

    # Accept a numeric ID when explicitly associated with an order.
    # Do not treat a four-digit year as an order ID.
    order_context = re.search(
        r"\b(?:order(?:\s*(?:id|number|no\.?))?|purchase)"
        r"\s*(?:id|number|no\.?)?\s*[:#-]?\s*(\d+)\b",
        question,
        re.IGNORECASE,
    )

    if order_context:
        numeric_id = order_context.group(1)

        # Avoid interpreting a year as an order ID.
        if not re.fullmatch(r"(?:19|20)\d{2}", numeric_id):
            return f"ORD{numeric_id}"

    return _text(previous_order_id).upper()


def supervisor_node(state: SupportState):
    """Choose the workflow for a message, applying deterministic rules before asking the LLM to classify it."""
    question = _text(state.get("question"))

    print(
        "DEBUG: Supervisor received:",
        question,
        flush=True
    )

    if not question:
        return {
            "intent": "",
            "answer": "Please enter a question so I can help.",
        }
    
    # If the frontend or an earlier step already chose a valid intent, keep it instead of reclassifying.
    # Preserve an explicit intent supplied by the application
    existing_intent = _text(state.get("intent")).lower()

    if existing_intent in VALID_INTENTS:
        return {"intent": existing_intent, "answer": ""}
    
    # Route general return-policy questions to FAQ.
    question_lower = question.lower()

    # Phrases like 'my second order' are order-list queries, not requests for a literal order ID.
    # Route ordinal order-history questions before order-ID extraction.
    ordinal_pattern = (
        r"\b(?:first|second|third|fourth|fifth|sixth|"
        r"seventh|eighth|ninth|tenth|"
        r"1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th)\b"
    )

    if (
        re.search(ordinal_pattern, question_lower)
        and re.search(r"\borders?\b", question_lower)
        and re.search(
            r"\b(which|what|show|find|tell me|list)\b",
            question_lower,
        )
    ):
        print("DEBUG: Routing ordinal order query to my_orders", flush=True)
        return {"intent": "my_orders", "answer": ""}


    return_policy_phrases = (
        "return policy",
        "return eligibility",
        "what is the return window",
        "what is your return window",
        "how many days do i have to return",
    )

    if any(
        phrase in question_lower
        for phrase in return_policy_phrases
    ):
        return {"intent": "faq", "answer": ""}


    # Route product and sales analytics questions to analytics.
    analytics_phrases = (
        "highest sales volume",
        "highest in revenue",
        "highest revenue",
        "top 10 products",
        "top products",
        "products by revenue",
        "compare revenue",
        "sales volume",
        "units sold",
        "product sales",
        "sales analytics",
        "revenue comparison",
        "largest order",
        "order with largest amount",
        "order with the largest amount",
        "highest order amount",
        "highest-value order",
        "highest value order",
        "most expensive order",
        "biggest order",
        "order with the highest amount",
        "order with the highest value",
        "lowest order",
        "order with lowest amount",
        "order with the lowest amount",
        "lowest order amount",
        "lowest-value order",
        "lowest value order",
        "least expensive order",
        "smallest order",
        "order with the lowest value",
        "order with the smallest amount",
    )

    if any(
        phrase in question_lower
        for phrase in analytics_phrases
    ):
        return {"intent": "analytics", "answer": ""}
    

    # Route requests about returning a specific order
    # to the return workflow.
    explicit_order_id = _extract_order_id(question)

    
    # Route analytics, rankings, comparisons, and chart requests.
    analytics_phrases = (
        # Product rankings and comparisons
        "top product",
        "top 10 product",
        "best-selling product",
        "best selling product",
        "highest sales volume",
        "highest in revenue",
        "highest revenue",
        "products by revenue",
        "products by quantity",
        "units sold",
        "most sold",
        "most purchased",
        "purchase frequency",
        "average price",
        "top-selling",
        "top selling",

        # Sales and revenue analytics
        "sales analytics",
        "sales volume",
        "revenue comparison",
        "compare revenue",
        "total revenue",
        "monthly revenue",
        "highest sales",
        "sales trend",

        # Order rankings and comparisons
        "top order",
        "top 10 order",
        "largest order",
        "highest order amount",
        "orders by amount",
        "orders by quantity",
        "order analytics",

        # Charts and visual comparisons
        "create a chart",
        "show a chart",
        "plot a chart",
        "draw a chart",
        "chart comparing",
        "graph comparing",
        "visualise",
        "visualize",
    )

    if any(
        phrase in question_lower
        for phrase in analytics_phrases
    ):
        return {"intent": "analytics", "answer": ""}

    # An order-return question without an ID should enter
    # the return workflow and ask for the required details.
    if (
        "can i return my order" in question_lower
        or "can i return this order" in question_lower
    ):
        return {"intent": "return_refund", "answer": ""}

    try:
        response = supervisor_model.invoke([
            ("system", supervisor_prompt),
            ("human", question),
        ])
        intent = _text(getattr(response, "intent", "")).lower()
        print(
            "DEBUG: Supervisor classified intent:",
            repr(intent),
            "| Valid intents:",
            VALID_INTENTS,
            flush=True
        )

        if intent not in VALID_INTENTS:
            return {
                "intent": "",
                "answer": "Sorry, I couldn't determine the type of request. Please rephrase your question.",
            }
        return {"intent": intent, "answer": ""}
    except Exception:
        logging.exception("Agent node failed")
        return {
            "intent": "",
            "answer": "Sorry, customer support is temporarily unavailable. Please try again shortly.",
        }


def route_after_supervisor(state: SupportState):
    """Send the graph to the selected intent node, or end early if there is no question or an answer already exists."""
    if not _text(state.get("question")) or _text(state.get("answer")):
        return "end"
    intent = _text(state.get("intent")).lower()
    return intent if intent in VALID_INTENTS else "end"

def format_delivery_date(date_value):
    """Format valid ISO dates for display and preserve the original value if parsing fails."""
    if not date_value:
        return "Not available"

    try:
        return datetime.fromisoformat(
            str(date_value)
        ).strftime("%d %B %Y").lstrip("0")
    except (ValueError, TypeError):
        return str(date_value)

def order_node(state: SupportState):
    """Retrieve one order, then include any return request linked to that order."""
    question = _text(state.get("question"))
    order_id = _extract_order_id(question, _text(state.get("order_id")))

    if not order_id:
        return {
            "answer": "Please provide your order ID so I can look up its status.",
            "order_id": "",
        }

    try:
        order_result = get_order_details.invoke(order_id)
        if isinstance(order_result, str):
            return {"answer": order_result, "order_id": order_id}
        if not isinstance(order_result, dict):
            return {
                "answer": "I couldn't retrieve the order details right now. Please try again.",
                "order_id": order_id,
            }

        return_result = get_return_status_by_order.invoke(order_id)
        if not isinstance(return_result, dict):
            return_result = {"exists": False}

        delivery_date = format_delivery_date(
            order_result.get("delivery_date")
        )

        actual_delivery_date = format_delivery_date(
            order_result.get("actual_delivery_date")
        )
        if hasattr(delivery_date, "strftime"):
            delivery_date = delivery_date.strftime("%d %B %Y").lstrip("0")
        elif delivery_date not in (None, "", "Not available"):
            try:
                delivery_date = datetime.fromisoformat(str(delivery_date)).strftime("%d %B %Y").lstrip("0")
            except (ValueError, TypeError):
                delivery_date = str(delivery_date)
        else:
            delivery_date = "Not available"

        answer = (
            "**Order Details**\n\n"
            f"**Order ID:** {order_result.get('order_id', order_id)}\n\n"
            f"**Product:** {order_result.get('product', 'Not available')}\n\n"
            f"**Amount:** {order_result.get('amount', 'Not available')}\n\n"
            f"**Order Status:** {order_result.get('status', 'Not available')}\n\n"
            f"**Scheduled Delivery:** {delivery_date}\n\n"
            f"**Actual Delivery:** {actual_delivery_date}"
        )

        if return_result.get("exists"):
            answer += (
                "\n\n---\n\n"
                "**Return Details**\n\n"
                f"**Return ID:** {return_result.get('return_id', 'Not available')}\n\n"
                f"**Return Status:** {return_result.get('status', 'Not available')}"
            )
        return {"answer": answer, "order_id": order_id}
    except Exception:
        return {
            "answer": "Sorry, I couldn't retrieve your order details right now. Please try again shortly.",
            "order_id": order_id,
        }


def my_orders_node(state: SupportState):
    """List a customer's orders with optional date, status, and ordinal-position filters."""
    """Display customer orders with date, status, and position filters."""

    try:
        question = _text(state.get("question"))
        question_lower = question.lower()

        # --------------------------------------------------
        # Convert words and numeric ordinals into a consistent one-based position.
        # 1. Detect an ordinal position (first, 2nd, third...)
        # --------------------------------------------------
        ordinal_map = {
            "first": 1, "1st": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
            "sixth": 6, "6th": 6,
            "seventh": 7, "7th": 7,
            "eighth": 8, "8th": 8,
            "ninth": 9, "9th": 9,
            "tenth": 10, "10th": 10,
        }

        position = None

        for ordinal, number in ordinal_map.items():
            if re.search(rf"\b{re.escape(ordinal)}\b", question_lower):
                position = number
                break

        # --------------------------------------------------
        # 2. Detect an explicitly requested order status
        # --------------------------------------------------
        status = None

        status_patterns = {
            "delivered": r"\bdelivered\b",
            "cancelled": r"\bcancelled\b|\bcanceled\b",
            "pending": r"\bpending\b",
            "shipped": r"\bshipped\b",
            "processing": r"\bprocessing\b",
            "returned": r"\breturned\b",
        }

        for candidate, pattern in status_patterns.items():
            if re.search(pattern, question_lower):
                status = candidate
                break

        # --------------------------------------------------
        # Convert dates mentioned in the question into database filters; the end date is exclusive.
        # 3. Parse date/month/year filters
        #    End date is exclusive in get_my_orders.
        # --------------------------------------------------
        start_date = ""
        end_date = ""
        year = None
        requested_month = None
        date_range_requested = False

        month_numbers = {
            "jan": 1, "january": 1,
            "feb": 2, "february": 2,
            "mar": 3, "march": 3,
            "apr": 4, "april": 4,
            "may": 5,
            "jun": 6, "june": 6,
            "jul": 7, "july": 7,
            "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10,
            "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }

        month_pattern = "|".join(
            sorted(month_numbers.keys(), key=len, reverse=True)
        )

        def next_month_start(y, m):
            if m == 12:
                return f"{y + 1}-01-01"
            return f"{y}-{m + 1:02d}-01"

        def parse_date(value):
            """Parse DD/MM/YYYY, DD-MM-YYYY or 15 October 2026."""
            value = value.strip()

            for fmt in (
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%d %B %Y",
                "%d %b %Y",
            ):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue

            return None

        def to_exclusive_end(value):
            return (value + timedelta(days=1)).isoformat()

        # Examples:
        # 15 October 2026 to 26/10/2026
        # 15/10/2026 till 26/10/2026
        month_name_date = rf"\d{{1,2}}\s+(?:{month_pattern})\.?\s+20\d{{2}}"
        numeric_date = r"\d{1,2}[/-]\d{1,2}[/-]20\d{2}"
        date_token = rf"(?:{numeric_date}|{month_name_date})"

        date_range_match = re.search(
            rf"\b(?:from\s+)?({date_token})\s+"
            rf"(?:to|till|until|through)\s+({date_token})\b",
            question_lower,
            re.IGNORECASE,
        )

        if date_range_match:
            first_date = parse_date(date_range_match.group(1))
            last_date = parse_date(date_range_match.group(2))

            if first_date and last_date and last_date >= first_date:
                start_date = first_date.isoformat()
                end_date = to_exclusive_end(last_date)
                year = first_date.year
                date_range_requested = True

        # Cross-year or same-year month ranges:
        # November 2025 to February 2026
        if not date_range_requested:
            month_range = re.search(
                rf"\b(?:from\s+)?({month_pattern})\.?\s+(20\d{{2}})\s+"
                rf"(?:to|till|until|through|-)\s+"
                rf"({month_pattern})\.?\s+(20\d{{2}})\b",
                question_lower,
                re.IGNORECASE,
            )

            if month_range:
                start_month_name, start_year, end_month_name, end_year = (
                    month_range.groups()
                )

                start_month = month_numbers[start_month_name.lower()]
                end_month = month_numbers[end_month_name.lower()]
                start_year = int(start_year)
                end_year = int(end_year)

                if (end_year, end_month) < (start_year, start_month):
                    return {
                        "answer": (
                            "The end month must not be earlier than "
                            "the start month."
                        )
                    }

                start_date = f"{start_year}-{start_month:02d}-01"
                end_date = next_month_start(end_year, end_month)
                year = start_year
                date_range_requested = True

        # Same-year month ranges:
        # October to December 2026
        if not date_range_requested:
            month_range = re.search(
                rf"\b({month_pattern})\.?\s+"
                rf"(?:to|through|until|and)\s+"
                rf"({month_pattern})\.?\s+(20\d{{2}})\b",
                question_lower,
                re.IGNORECASE,
            )

            if month_range:
                start_month_name, end_month_name, range_year = (
                    month_range.groups()
                )

                start_month = month_numbers[start_month_name.lower()]
                end_month = month_numbers[end_month_name.lower()]
                year = int(range_year)

                if end_month < start_month:
                    return {
                        "answer": (
                            "For a range crossing years, please include "
                            "the year for both months. Example: "
                            "'November 2025 to February 2026'."
                        )
                    }

                start_date = f"{year}-{start_month:02d}-01"
                end_date = next_month_start(year, end_month)
                date_range_requested = True

        # Single date:
        # Show my orders on 15 October 2026
        if not date_range_requested:
            single_date_match = re.search(
                rf"\b({date_token})\b",
                question_lower,
                re.IGNORECASE,
            )

            if single_date_match:
                parsed_date = parse_date(single_date_match.group(1))

                if parsed_date:
                    start_date = parsed_date.isoformat()
                    end_date = to_exclusive_end(parsed_date)
                    year = parsed_date.year
                    date_range_requested = True

        # Single month:
        # October 2026
        if not date_range_requested:
            single_month = re.search(
                rf"\b({month_pattern})\.?\s+(20\d{{2}})\b",
                question_lower,
                re.IGNORECASE,
            )

            if single_month:
                requested_month = month_numbers[
                    single_month.group(1).lower()
                ]
                year = int(single_month.group(2))

                start_date = f"{year}-{requested_month:02d}-01"
                end_date = next_month_start(year, requested_month)
                date_range_requested = True

        # Single year:
        # Show my orders in 2026
        if not date_range_requested:
            year_match = re.search(
                r"\b(?:in|for|during|year)\s+(20\d{2})\b"
                r"|\b(20\d{2})\b",
                question_lower,
            )

            if year_match:
                year = int(year_match.group(1) or year_match.group(2))
                start_date = f"{year}-01-01"
                end_date = f"{year + 1}-01-01"
                date_range_requested = True

        # --------------------------------------------------
        # Fetch only the requested date range when one was identified, rather than filtering unrelated orders later.
        # 4. Fetch orders using the existing database tool
        # --------------------------------------------------
        result = get_my_orders.invoke({
            "start_date": start_date,
            "end_date": end_date,
        })

        if not isinstance(result, dict):
            return {
                "answer": (
                    "Sorry, I couldn't retrieve your orders right now. "
                    "Please try again shortly."
                )
            }

        if not result.get("found"):
            return {
                "answer": result.get(
                    "message",
                    "No orders were found for the requested period."
                    if date_range_requested
                    else "You don't have any orders yet.",
                )
            }

        orders = result.get("orders", [])

        if not orders:
            return {
                "answer": (
                    "No orders were found for the requested period."
                    if date_range_requested
                    else "You don't have any orders yet."
                )
            }

        # --------------------------------------------------
        # 5. Apply status filter, sort orders, then select
        #    the requested ordinal from the correct list.
        # --------------------------------------------------

        # Filter by status before selecting an ordinal so 'second delivered order' means the second delivered order.
        # Apply status filter first, if requested.
        if status:
            orders = [
                order
                for order in orders
                if (order.get("order_status") or "").lower() == status
            ]

        # Detect an explicitly requested newest-first order.
        descending_requested = bool(
            re.search(
                r"\b(descending|newest first|latest first|"
                r"most recent first|most recent|latest)\b",
                question_lower,
            )
        )

        if position is not None:
            # Ordinal queries (first, second, third, etc.)
            # default to oldest-first unless the user explicitly
            # requests newest-first or descending order.
            orders.sort(
                key=lambda order: (
                    str(order.get("order_date") or ""),
                    str(order.get("order_id") or ""),
                ),
                reverse=descending_requested,
            )
        else:
            # Normal order-list queries retain newest-first order.
            orders.sort(
                key=lambda order: (
                    str(order.get("order_date") or ""),
                    str(order.get("order_id") or ""),
                ),
                reverse=True,
            )

        # Select the requested position only after filtering and sorting, so the result matches the user's wording.
        # Select the requested order after sorting.
        if position is not None:
            if position < 1 or position > len(orders):
                return {
                    **state,
                    "response": (
                        f"You requested the {position}"
                        f"{'st' if position % 10 == 1 and position % 100 != 11 else 'nd' if position % 10 == 2 and position % 100 != 12 else 'rd' if position % 10 == 3 and position % 100 != 13 else 'th'} "
                        f"order, but only {len(orders)} matching "
                        f"order(s) were found."
                    ),
                }

            order = orders[position - 1]

            # Keep only the selected order for the response logic
            # below, if that logic expects a single order.
            orders = [order]

        # --------------------------------------------------
        # 6. Format the order list
        # --------------------------------------------------
        if requested_month and year:
            month_name = next(
                name for name, number in month_numbers.items()
                if number == requested_month and len(name) > 3
            )
            title = f"**Your Orders for {month_name.title()} {year}**\n\n"
        elif year:
            title = f"**Your Orders for {year}**\n\n"
        else:
            title = "**Your Orders**\n\n"

        answer = title

        for index, order in enumerate(orders, start=1):
            order_date = order.get("order_date") or "Not available"
            order_status = order.get("order_status") or "Not available"

            amount = order.get("amount")
            amount_text = (
                f"₹{amount:,.2f}"
                if amount is not None
                else "Not available"
            )

            expected_date = format_delivery_date(
                order.get("expected_delivery_date")
            )
            actual_date = format_delivery_date(
                order.get("actual_delivery_date")
            )

            answer += (
                f"**{index}. Order ID:** {order.get('order_id', 'Not available')}\n\n"
                f"- **Order Date:** {order_date}\n"
                f"- **Status:** {order_status}\n"
                f"- **Amount:** {amount_text}\n"
                f"- **Expected Delivery:** {expected_date}\n"
                f"- **Actual Delivery:** {actual_date}\n\n"
                "---\n\n"
            )

        last_order_id = (
            _text(orders[0].get("order_id"))
            if len(orders) == 1
            else ""
        )

        return {
            "answer": answer.rstrip(),
            "order_id": last_order_id,
        }

    except Exception:
        logging.exception("Failed to retrieve customer orders")
        return {
            "answer": (
                "Sorry, I couldn't retrieve your orders right now. "
                "Please try again shortly."
            )
        }
    

def _agent_node(agent, question: str, fallback: str):
    try:
        response = agent.invoke({"messages": [{"role": "user", "content": question}]})
        messages = response.get("messages", []) if isinstance(response, dict) else []
        answer = _message_content_to_text(getattr(messages[-1], "content", "")) if messages else ""
        return {"answer": answer or fallback}
    except Exception:
        logging.exception("Supervisor node failed")
        return {"answer": "Sorry, customer support is temporarily unavailable. Please try again shortly."}


def faq_node(state: SupportState):
    """Handle general policy and frequently asked questions through the FAQ agent."""

    return _agent_node(
        faq_agent,
        _text(state.get("question")),
        "Sorry, I couldn't generate an answer right now.",
    )


def complaint_node(state: SupportState):
    """Create or check a complaint through the complaint agent, depending on the customer's request."""

    return _agent_node(
        complaint_agent,
        _text(state.get("question")),
        "Sorry, I couldn't process your complaint right now.",
    )


def analytics_node(state: SupportState):
    """Run analytics for the customer's question and attach the answer and any chart-ready results."""

    """Handle analytics requests and preserve the results used to answer."""
    try:
        question = _text(state.get("question"))
        result = run_analytics_agent(question)

        return {
            "answer": result["answer"],
            "analytics_results": result["analytics_results"],
        }

    except Exception:
        logging.exception("Failed to retrieve customer analytics")
        return {
            "answer": (
                "Sorry, I couldn't retrieve your spending "
                "summary right now. Please try again shortly."
            ),
            "analytics_results": [],
        }


def _is_return_status_question(question: str) -> bool:
    """Recognize read-only questions about an existing return's status."""
    text = _text(question).lower()
    status_patterns = (
        r"\breturn status\b",
        r"\bstatus of (?:my )?return\b",
        r"\bwhat(?: is|'s) the status of (?:my )?return\b",
        r"\bwhere(?:'s| is) my return\b",
        r"\bcheck (?:the )?status of (?:my )?return\b",
        r"\btrack my return\b",
        # Legacy refund-status wording is treated as a read-only return lookup.
        r"\brefund status\b",
        r"\bstatus of (?:my )?refund\b",
        r"\bwhere(?:'s| is) my refund\b",
        r"\btrack my refund\b",
        r"\bcheck my refund\b",
        r"\bhas my refund\b",
    )
    return any(re.search(pattern, text) for pattern in status_patterns)


def return_refund_node(state: SupportState):
    """Handle return/refund requests, including eligibility checks and existing request status."""

    """Handle return workflows and return-status lookups."""

    question = _text(state.get("question"))

    # 1. Check whether this is a read-only return-status request.
    if _is_return_status_question(question):
        try:
            # Prefer a return ID when the user provides one.  
            return_id_match = re.search(
                r"\bRET[A-Z0-9-]*\d[A-Z0-9-]*\b",
                question.upper(),
            )


            if return_id_match:
                requested_return_id = return_id_match.group(0)

                logging.info(
                    "Return status lookup: question=%s, return_id=%s",
                    question,
                    requested_return_id,
                )

                result = get_return_status.invoke({
                    "return_id": requested_return_id
                })

            else:
                # Fall back to an order ID for status lookup.
                order_id = _extract_order_id(
                    question,
                    _text(state.get("order_id")),
                )

                if not order_id:
                    return {
                        "answer": (
                            "Please provide your return ID or order ID "
                            "so I can check your return status."
                        ),
                        "order_id": "",
                        "return_id": "",
                        "return_status": "",
                    }

                result = get_return_status_by_order.invoke({
                    "order_id": order_id
                })

            # Handle tools that return plain text.
            if isinstance(result, str):
                return {
                    "answer": result,
                    "order_id": _text(state.get("order_id")),
                    "return_id": (
                        requested_return_id
                        if return_id_match
                        else ""
                    ),
                    "return_status": "",
                }

            # Handle an unsuccessful or missing lookup.
            if not isinstance(result, dict):
                return {
                    "answer": "No matching return request was found.",
                    "order_id": "",
                    "return_id": "",
                    "return_status": "",
                }

            if not result.get("exists"):
                return {
                    "answer": result.get(
                        "message",
                        "No matching return request was found.",
                    ),
                    "order_id": _text(result.get("order_id")),
                    "return_id": _text(
                        result.get("return_id")
                    ),
                    "return_status": "",
                }

            # Format the successful status result.
            return_id = _text(result.get("return_id"))
            result_order_id = _text(result.get("order_id"))
            return_status = _text(result.get("status"))

            if return_status.lower() == "requested":
                answer = (
                    f"Return **{return_id}** for order "
                    f"**{result_order_id}** has status: **Requested**."
                )
            elif return_status.lower() == "returned":
                answer = (
                    f"Return **{return_id}** for order "
                    f"**{result_order_id}** has status: **Returned**."
                )
            else:
                answer = (
                    f"Return **{return_id}** for order "
                    f"**{result_order_id}** has status: "
                    f"**{return_status or 'Not available'}**."
                )

            return {
                "answer": answer,
                "order_id": result_order_id,
                "return_id": return_id,
                "return_status": return_status,
            }

        except Exception:
            logging.exception("Failed to retrieve return status")

            return {
                "answer": (
                    "Sorry, I couldn't check the return status right now. "
                    "Please try again shortly."
                ),
                "order_id": _text(state.get("order_id")),
                "return_id": "",
                "return_status": "",
            }

    # 2. Only return creation requires an order ID.
    order_id = _extract_order_id(
        question,
        _text(state.get("order_id")),
    )

    if not order_id:
        return {
            "answer": (
                "Please provide your order ID so I can help with your return."
            ),
            "order_id": "",
            "return_id": "",
            "return_status": "",
        }

    # 3. Check order eligibility before creating a return.
    try:
        eligibility = check_return_eligibility.invoke(order_id)

        if isinstance(eligibility, str):
            return {
                "answer": eligibility,
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if not isinstance(eligibility, dict):
            return {
                "answer": (
                    "I couldn't check return eligibility right now. "
                    "Please try again."
                ),
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if not eligibility.get("eligible"):
            return {
                "answer": eligibility.get(
                    "reason",
                    "This order is not eligible for a return.",
                ),
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        # 4. Avoid creating a duplicate return for the same order.
        existing = get_return_status_by_order.invoke({
            "order_id": order_id
        })

        if isinstance(existing, str):
            return {
                "answer": existing,
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if not isinstance(existing, dict):
            return {
                "answer": (
                    "I couldn't check whether a return already exists. "
                    "Please try again."
                ),
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if existing.get("exists"):
            return_id = _text(existing.get("return_id"))
            return_status = _text(existing.get("status"))

            if return_status.lower() == "requested":
                answer = (
                    f"A return request already exists for order "
                    f"{order_id}. Return ID: "
                    f"{return_id or 'Not available'}. "
                    "Status: Requested."
                )
            elif return_status.lower() == "returned":
                answer = (
                    f"The return for order {order_id} has already "
                    f"been marked as Returned. Return ID: "
                    f"{return_id or 'Not available'}."
                )
            else:
                answer = (
                    f"An existing return was found for order {order_id}, "
                    f"but its status is "
                    f"{return_status or 'unavailable'}."
                )

            return {
                "answer": answer,
                "order_id": order_id,
                "return_id": return_id,
                "return_status": return_status,
            }

        # 5. Create the return only when no existing return is found.
        created = create_return.invoke({
            "order_id": order_id,
            "reason": question,
        })

        if isinstance(created, str):
            return {
                "answer": created,
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if not isinstance(created, dict):
            return {
                "answer": (
                    "I couldn't process your return request right now. "
                    "Please try again."
                ),
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        if not created.get("success"):
            return {
                "answer": created.get(
                    "message",
                    "I couldn't create the return request.",
                ),
                "order_id": order_id,
                "return_id": "",
                "return_status": "",
            }

        return {
            "answer": created.get(
                "message",
                f"Return request created for order {order_id}.",
            ),
            "order_id": order_id,
            "return_id": _text(created.get("return_id")),
            "return_status": "Requested",
        }

    except Exception:
        logging.exception("Failed to process return request")

        return {
            "answer": (
                "Sorry, I couldn't process your return request right now. "
                "Please try again shortly."
            ),
            "order_id": order_id,
            "return_id": "",
            "return_status": "",
        }

# Connect the support nodes into a LangGraph workflow with conditional routing.
builder = StateGraph(SupportState)
builder.add_node("supervisor", supervisor_node)
builder.add_node("order", order_node)
builder.add_node("my_orders", my_orders_node)
builder.add_node("faq", faq_node)
builder.add_node("complaint", complaint_node)
builder.add_node("return_refund", return_refund_node)
builder.add_node("analytics", analytics_node)
builder.add_edge(START, "supervisor")
builder.add_conditional_edges(
    "supervisor",
    route_after_supervisor,
    {
        "order": "order",
        "my_orders": "my_orders",
        "faq": "faq",
        "return_refund": "return_refund",
        "complaint": "complaint",
        "analytics": "analytics",
        "end": END,
    },
)
builder.add_edge("order", END)
builder.add_edge("my_orders", END)
builder.add_edge("faq", END)
builder.add_edge("complaint", END)
builder.add_edge("return_refund", END)
builder.add_edge("analytics", END)
support_graph = builder.compile()
