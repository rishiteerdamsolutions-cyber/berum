import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent
PRODUCTS_FILE = DATA_DIR / "products.json"
LOCKOUTS_FILE = DATA_DIR / "lockouts.json"
DEVICE_ID_FILE = DATA_DIR / ".berum_device_id"


DEFAULT_PRODUCTS = {
    "1": {"name": "Lenovo V15 Laptop", "mrp": 90540, "base_price": 51990, "last_price": 48500},
    "2": {"name": "US Polo Shirt", "mrp": 2299, "base_price": 1429, "last_price": 1199},
    "3": {"name": "Titan Watch", "mrp": 3075, "base_price": 2695, "last_price": 2200},
    "4": {"name": "iPhone 15 Pro Max", "mrp": 159900, "base_price": 131900, "last_price": 128000},
    "5": {"name": "Millets Super Pack", "mrp": 1632, "base_price": 1345, "last_price": 1100},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json_file(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_products() -> dict:
    products = _read_json_file(PRODUCTS_FILE, default=None)
    if products is None:
        _write_json_file(PRODUCTS_FILE, DEFAULT_PRODUCTS)
        return dict(DEFAULT_PRODUCTS)
    if not isinstance(products, dict):
        _write_json_file(PRODUCTS_FILE, DEFAULT_PRODUCTS)
        return dict(DEFAULT_PRODUCTS)
    return products


def save_products(products: dict) -> None:
    _write_json_file(PRODUCTS_FILE, products)


def get_device_id() -> str:
    if DEVICE_ID_FILE.exists():
        value = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = str(uuid.uuid4())
    DEVICE_ID_FILE.write_text(value, encoding="utf-8")
    return value


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_mobile(mobile: str) -> str:
    return re.sub(r"\D+", "", mobile.strip())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_email(email: str) -> bool:
    # Not perfect; good enough for a CLI demo.
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def validate_mobile(mobile: str) -> bool:
    digits = normalize_mobile(mobile)
    return len(digits) >= 10


@dataclass(frozen=True)
class CustomerIdentity:
    device_id: str
    email: str
    mobile: str

    @property
    def email_norm(self) -> str:
        return normalize_email(self.email)

    @property
    def mobile_norm(self) -> str:
        return normalize_mobile(self.mobile)

    @property
    def email_hash(self) -> str:
        return _hash(self.email_norm)

    @property
    def mobile_hash(self) -> str:
        return _hash(self.mobile_norm)

    @property
    def device_hash(self) -> str:
        return _hash(self.device_id)


class LockoutManager:
    def __init__(self, lockout_duration_days: int = 7):
        self.lockout_duration = timedelta(days=lockout_duration_days)

    def _load(self) -> list[dict]:
        data = _read_json_file(LOCKOUTS_FILE, default=[])
        if isinstance(data, list):
            return data
        return []

    def _save(self, records: list[dict]) -> None:
        _write_json_file(LOCKOUTS_FILE, records)

    def _parse_dt(self, value: str) -> datetime | None:
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def is_locked(self, product_id: str, identity: CustomerIdentity) -> tuple[bool, datetime | None]:
        records = self._load()
        now = _utcnow()
        for record in records:
            if record.get("product_id") != product_id:
                continue
            purchased_at = self._parse_dt(str(record.get("purchased_at", "")))
            if purchased_at is None:
                continue
            until = purchased_at + self.lockout_duration
            if now >= until:
                continue

            # Block if the same product was purchased in the past week by:
            # - same device OR same email OR same mobile
            if record.get("device_hash") == identity.device_hash:
                return True, until
            if record.get("email_hash") == identity.email_hash:
                return True, until
            if record.get("mobile_hash") == identity.mobile_hash:
                return True, until

        return False, None

    def record_purchase(self, product_id: str, identity: CustomerIdentity, purchase_price: float) -> None:
        records = self._load()
        records.append(
            {
                "product_id": product_id,
                "purchased_at": _utcnow().isoformat(),
                "purchase_price": float(purchase_price),
                "device_hash": identity.device_hash,
                "email_hash": identity.email_hash,
                "mobile_hash": identity.mobile_hash,
            }
        )
        self._save(records)


class Berum:
    def __init__(self, product_name, actual_price, base_price, last_price, discount_rate=0.05):
        self.product_name = product_name
        self.actual_price = actual_price
        self.base_price = base_price
        self.last_price = last_price
        self.discount_rate = discount_rate
        self.previous_customer = False
        self.max_attempts = 3
        self.purchased = False
        self.purchase_price = None  # Track the price at which the product was purchased

    def check_previous_customer(self, order_id):
        pattern = r"^A[1-9]\d{2}$"
        self.previous_customer = bool(re.match(pattern, order_id))

    def bargain(self, offered_price):
        if offered_price > self.actual_price:
            return f"You have entered more than MRP (₹{self.actual_price}). Please try again."

        if self.previous_customer:
            if self.last_price < offered_price < self.base_price:
                self.purchase_price = offered_price
                return f"Congrats! The {self.product_name} is yours at ₹{offered_price}."
            else:
                return "Good try, but try again."
        else:
            if offered_price == self.base_price:
                self.purchase_price = offered_price
                return f"Congrats! The {self.product_name} is yours at ₹{offered_price}."
            elif self.base_price < offered_price <= self.actual_price:
                self.purchase_price = offered_price
                return f"Congrats! The {self.product_name} is yours at ₹{offered_price}."
            else:
                return "Good try, but try again."


class BerumSessionManager:
    def __init__(self, session_duration=5, max_customers=5, max_discounts=2):
        self.session_start = datetime.now()
        self.session_duration = timedelta(minutes=session_duration)
        self.max_customers = max_customers
        self.max_discounts = max_discounts
        self.discount_given = 0
        self.customer_count = 0
        self.max_customers_message_shown = False
        self.admin_mode = False
        self.purchased_products = []

    def reset_session(self):
        self.session_start = datetime.now()
        self.discount_given = 0
        self.customer_count = 0
        self.max_customers_message_shown = False
        self.admin_mode = False
        self.purchased_products = []
        print("\nNew session started.\n")

    def is_session_active(self):
        return datetime.now() - self.session_start < self.session_duration

    def can_offer_discount(self):
        return self.discount_given < self.max_discounts

    def increment_discount_count(self):
        self.discount_given += 1

    def increment_customer_count(self):
        self.customer_count += 1

    def max_customers_reached(self):
        return self.customer_count >= self.max_customers

    def toggle_admin_mode(self):
        self.admin_mode = True

    def add_purchased_product(self, product):
        self.purchased_products.append(product)

    def display_admin_dashboard(self):
        print("\nAdmin Dashboard:")
        if not self.purchased_products:
            print("No products were purchased in this session.")
        else:
            for product in self.purchased_products:
                if product.purchase_price:
                    profit_loss = product.purchase_price - product.base_price
                    percentage = (profit_loss / product.base_price) * 100
                    status = "Profit" if profit_loss > 0 else "Loss"
                    print(f"Product: {product.product_name}")
                    print(f"Base Price: ₹{product.base_price}, Purchase Price: ₹{product.purchase_price}")
                    print(f"Status: {status}, Amount: ₹{abs(profit_loss)}, Percentage: {abs(percentage):.2f}%\n")


def _prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def prompt_customer_identity() -> CustomerIdentity:
    device_id = get_device_id()

    while True:
        email = _prompt_nonempty("Enter your email id: ").strip()
        if validate_email(email):
            break
        print("Please enter a valid email id.")

    while True:
        mobile = _prompt_nonempty("Enter your mobile number: ").strip()
        if validate_mobile(mobile):
            break
        print("Please enter a valid mobile number (at least 10 digits).")

    return CustomerIdentity(device_id=device_id, email=email, mobile=mobile)


def format_in_local_time(dt: datetime) -> str:
    # Best-effort: show local time if tzinfo is available; otherwise show ISO.
    try:
        local = dt.astimezone()
        return local.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return dt.isoformat()


def manage_products(products: dict) -> dict:
    while True:
        print("\nProduct Manager:")
        if not products:
            print("(No products yet)")
        else:
            for product_id in sorted(products.keys(), key=lambda x: int(x) if x.isdigit() else x):
                p = products[product_id]
                print(f"- {product_id}. {p['name']} | MRP ₹{p['mrp']} | Base ₹{p['base_price']} | Last ₹{p['last_price']}")

        print("\nOptions: add | update | delete | back")
        choice = input("Enter option: ").strip().lower()
        if choice == "back":
            save_products(products)
            print("Saved products.\n")
            return products

        if choice == "add":
            product_id = input("New product number/id (e.g. 6): ").strip()
            if not product_id:
                print("Product id cannot be empty.")
                continue
            if product_id in products:
                print("That product id already exists.")
                continue
            name = _prompt_nonempty("Product name: ")
            try:
                mrp = float(_prompt_nonempty("MRP: ₹"))
                base_price = float(_prompt_nonempty("Base price: ₹"))
                last_price = float(_prompt_nonempty("Last price: ₹"))
            except ValueError:
                print("Please enter valid numeric prices.")
                continue
            products[product_id] = {"name": name, "mrp": mrp, "base_price": base_price, "last_price": last_price}
            print("Added product.")
            continue

        if choice == "update":
            product_id = input("Product id to update: ").strip()
            if product_id not in products:
                print("Unknown product id.")
                continue
            p = products[product_id]
            print("Press Enter to keep the existing value.")
            name = input(f"Name [{p['name']}]: ").strip() or p["name"]
            mrp_raw = input(f"MRP [{p['mrp']}]: ₹").strip()
            base_raw = input(f"Base price [{p['base_price']}]: ₹").strip()
            last_raw = input(f"Last price [{p['last_price']}]: ₹").strip()
            try:
                mrp = float(mrp_raw) if mrp_raw else float(p["mrp"])
                base_price = float(base_raw) if base_raw else float(p["base_price"])
                last_price = float(last_raw) if last_raw else float(p["last_price"])
            except ValueError:
                print("Please enter valid numeric prices.")
                continue
            products[product_id] = {"name": name, "mrp": mrp, "base_price": base_price, "last_price": last_price}
            print("Updated product.")
            continue

        if choice == "delete":
            product_id = input("Product id to delete: ").strip()
            if product_id not in products:
                print("Unknown product id.")
                continue
            confirm = input(f"Type DELETE to confirm removing {products[product_id]['name']}: ").strip()
            if confirm != "DELETE":
                print("Cancelled.")
                continue
            products.pop(product_id, None)
            print("Deleted product.")
            continue

        print("Unknown option.")


def select_product(products: dict):
    if not products:
        print("No products are available. Ask the admin to add products.")
        return None, None

    print("Select a product to bargain for:")
    for key in sorted(products.keys(), key=lambda x: int(x) if x.isdigit() else x):
        p = products[key]
        print(f"{key}. {p['name']} - M.R.P: ₹{p['mrp']}")

    choice = input("Enter the product number (or type 'admin'): ").strip()
    if choice.lower() == "admin":
        return "admin", None
    return choice, products.get(choice)


def suggest_alternate_product(original_product_number):
    alternate_products = {
        "1": ("Y Laptop", 45000),
        "2": ("T-Shirt", 1100),
        "3": ("Watch", 1500),
        "4": ("iPhone 10", 60000),
        "5": ("Millets Set", 800),
    }

    alternate_product = alternate_products.get(original_product_number, None)
    if alternate_product:
        print(
            f"This is a product that matches your requirement and price range: {alternate_product[0]} at M.R.P: ₹{alternate_product[1]}"
        )


def dramatic_try_label(attempt: int) -> str:
    if attempt == 1:
        return "First try (Customer opens the negotiation)"
    if attempt == 2:
        return "Second try (Salesperson pushes back)"
    return "Final try (Last chance at the counter)"


def demo():
    session_manager = BerumSessionManager()
    lockouts = LockoutManager(lockout_duration_days=7)

    while True:
        products = load_products()

        if not session_manager.is_session_active():
            session_manager.reset_session()

        if session_manager.max_customers_reached():
            if not session_manager.max_customers_message_shown:
                print("I am sure you like Berum! Visit again!")
                session_manager.max_customers_message_shown = True
            time.sleep(5)
            continue

        product_choice, product_details = select_product(products)

        if product_choice == "admin":
            session_manager.toggle_admin_mode()
            print("\nAdmin Mode:")
            print("1) View dashboard")
            print("2) Manage products")
            admin_choice = input("Choose 1/2 (or anything else to go back): ").strip()
            if admin_choice == "1":
                session_manager.display_admin_dashboard()
            elif admin_choice == "2":
                manage_products(products)
            continue

        if product_details is None:
            print("Invalid selection. Please restart the program.")
            return

        identity = prompt_customer_identity()

        locked, until = lockouts.is_locked(product_choice, identity)
        if locked:
            until_str = format_in_local_time(until) if until else "later"
            print(
                f"\nBargain locked for this product for 1 week on this device/email/mobile.\n"
                f"You can bargain for other products. Try again after: {until_str}\n"
            )
            print("\n" + "-" * 40 + "\n")
            continue

        product_name = product_details["name"]
        actual_price = float(product_details["mrp"])
        base_price = float(product_details["base_price"])
        last_price = float(product_details["last_price"])
        berum_system = Berum(product_name, actual_price, base_price, last_price)

        session_manager.increment_customer_count()
        print(f"\nWelcome to Berum! You are customer #{session_manager.customer_count}")
        print(f"Product Name: {product_name}, M.R.P: ₹{actual_price}\n")
        print("Salesperson: Tell me your best price — let's see if we can make it work.\n")

        attempts = 0

        while attempts < berum_system.max_attempts:
            attempts += 1
            print(f"\n{dramatic_try_label(attempts)}:")

            user_input = input(
                "Enter your bargain price (or type 'deny' to cancel, 'exit' to leave, 'admin' for dashboard): ₹"
            ).strip()

            if user_input.lower() == "admin":
                session_manager.toggle_admin_mode()
                session_manager.display_admin_dashboard()
                continue

            if user_input.lower() == "exit":
                print("Thank you for using Berum! Have a great day!")
                break

            if user_input.lower() == "deny":
                print("No worries. Maybe next time — thanks for visiting!")
                break

            try:
                offered_price = float(user_input)
            except ValueError:
                print("Please enter a valid number.")
                continue

            if offered_price > actual_price:
                print(f"Salesperson: That's above MRP (₹{actual_price}). Let's be realistic.")
                continue

            if offered_price < (actual_price * 0.5):
                print("Salesperson: That's too low for this item. Let me show something closer to your budget.")
                suggest_alternate_product(product_choice)
                continue

            if attempts == 1:
                print(f"Customer: I can do ₹{offered_price}.")
            elif attempts == 2:
                print(f"Customer: Okay, how about ₹{offered_price}?")
            else:
                print(f"Customer: Final price — ₹{offered_price}.")

            response = berum_system.bargain(offered_price)
            if "Congrats!" in response:
                print(f"Salesperson: Done. We have a deal at ₹{offered_price}.")
            else:
                if attempts < berum_system.max_attempts:
                    print("Salesperson: I can't do that. Give me your best next number.")
                else:
                    print("Salesperson: I can't go that low today.")
                print(response)

            if "Congrats!" in response:
                final_decision = input(
                    "Type 'pay' to confirm purchase, or 'deny' to cancel this deal: "
                ).strip().lower()

                if final_decision == "admin":
                    session_manager.toggle_admin_mode()
                    session_manager.display_admin_dashboard()
                    continue

                if final_decision == "pay":
                    print("Thank you for completing your purchase with Berum!")
                    berum_system.purchased = True
                    session_manager.add_purchased_product(berum_system)
                    if berum_system.purchase_price is not None:
                        lockouts.record_purchase(product_choice, identity, berum_system.purchase_price)
                    break

                if final_decision == "deny" and attempts < berum_system.max_attempts:
                    print("Deal cancelled. You can try again — but don't make me call the manager!")
                    continue
                if final_decision == "deny" and attempts == berum_system.max_attempts:
                    print("Deal cancelled. That was your final attempt.")
                    break
                print("Please type 'pay' or 'deny'.")

        print("\n" + "-" * 40 + "\n")


if __name__ == "__main__":
    demo()

