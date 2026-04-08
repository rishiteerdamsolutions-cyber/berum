import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BargainResult:
    accepted: bool
    message: str
    accepted_price: Optional[float] = None


def _previous_customer_from_order_id(order_id: Optional[str]) -> bool:
    if not order_id:
        return False
    return bool(re.match(r"^A[1-9]\d{2}$", order_id.strip()))


def bargain(
    *,
    product_name: str,
    mrp: float,
    base_price: float,
    floor_price: float,
    offered_price: float,
    order_id: Optional[str] = None,
) -> BargainResult:
    if offered_price > mrp:
        return BargainResult(False, f"That's above MRP (₹{mrp}). Let's be realistic.")

    previous_customer = _previous_customer_from_order_id(order_id)

    if previous_customer:
        # Keep the original behavior: a previous customer can win between floor and base.
        if floor_price < offered_price < base_price:
            return BargainResult(True, f"Congrats! The {product_name} is yours at ₹{offered_price}.", offered_price)
        return BargainResult(False, "Good try, but try again.")

    # New customer: accept base price or above (up to MRP).
    if offered_price == base_price:
        return BargainResult(True, f"Congrats! The {product_name} is yours at ₹{offered_price}.", offered_price)
    if base_price < offered_price <= mrp:
        return BargainResult(True, f"Congrats! The {product_name} is yours at ₹{offered_price}.", offered_price)
    return BargainResult(False, "Good try, but try again.")


def dramatic_line(attempt_number: int, kind: str) -> str:
    """
    kind: intro | reject | accept | lowball
    """
    if kind == "intro":
        if attempt_number == 1:
            return "Salesperson: Tell me your best price — let's see if we can make it work."
        if attempt_number == 2:
            return "Salesperson: Hmm. That’s difficult. Give me a better number."
        return "Salesperson: Final chance — what’s your last price?"

    if kind == "lowball":
        return "Salesperson: That’s too low for this item. Let me show you something closer to your budget."

    if kind == "accept":
        return "Salesperson: Done. We have a deal."

    # reject
    if attempt_number < 3:
        return "Salesperson: I can’t do that. Try again — be realistic."
    return "Salesperson: I can’t go that low today."
