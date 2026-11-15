
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent

customers = pd.read_csv(DATA_DIR / "customers.csv")
orders = pd.read_csv(DATA_DIR / "orders.csv")
order_items = pd.read_csv(DATA_DIR / "order_items.csv")
products = pd.read_csv(DATA_DIR / "products.csv")
payments = pd.read_csv(DATA_DIR / "payments.csv")
shipments = pd.read_csv(DATA_DIR / "shipments.csv")
returns = pd.read_csv(DATA_DIR / "returns.csv")


def check_missing_references(
    child_df, child_column, parent_df, parent_column, relationship
):
    missing = ~child_df[child_column].isin(parent_df[parent_column])
    print(f"\n{relationship}")
    print(f"  Records checked: {len(child_df):,}")
    print(f"  Missing references: {missing.sum():,}")


def check_duplicates(df, column, table):
    print(f"\n{table}.{column}")
    print(f"  Duplicate values: {df[column].duplicated().sum():,}")


print("========== ROW COUNTS ==========")
for name, df in {
    "customers": customers,
    "orders": orders,
    "order_items": order_items,
    "products": products,
    "payments": payments,
    "shipments": shipments,
    "returns": returns,
}.items():
    print(f"{name}: {len(df):,}")

print("\n========== DUPLICATE ID CHECKS ==========")
for df, column, table in [
    (customers, "customer_id", "customers"),
    (orders, "order_id", "orders"),
    (order_items, "order_item_id", "order_items"),
    (products, "product_id", "products"),
    (payments, "payment_id", "payments"),
    (shipments, "shipment_id", "shipments"),
    (returns, "return_id", "returns"),
]:
    check_duplicates(df, column, table)

print("\n========== RELATIONSHIP CHECKS ==========")
check_missing_references(
    orders, "customer_id", customers, "customer_id",
    "Orders -> Customers"
)
check_missing_references(
    order_items, "order_id", orders, "order_id",
    "Order Items -> Orders"
)
check_missing_references(
    order_items, "product_id", products, "product_id",
    "Order Items -> Products"
)
check_missing_references(
    payments, "order_id", orders, "order_id",
    "Payments -> Orders"
)
check_missing_references(
    shipments, "order_id", orders, "order_id",
    "Shipments -> Orders"
)
check_missing_references(
    returns, "order_id", orders, "order_id",
    "Returns -> Orders"
)
check_missing_references(
    returns, "customer_id", customers, "customer_id",
    "Returns -> Customers"
)
check_missing_references(
    returns, "product_id", products, "product_id",
    "Returns -> Products"
)

print("\n========== VALIDATION COMPLETE ==========")
