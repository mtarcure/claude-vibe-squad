"""
billing/promo.py — apply a promo code to a shopping-cart total.

This is the small self-contained change the demo panel reviews. It has two
independent problems planted in it — one a correctness bug, one a security
issue — so two different specialists surface two different findings.
"""
import sqlite3


def apply_promo(cart_total: float, promo_code: str, conn: sqlite3.Connection) -> float:
    """Return the cart total after applying the named promo code."""
    cur = conn.cursor()
    # look up the promo's percentage discount by code
    cur.execute(
        "SELECT percent_off FROM promos WHERE code = '%s'" % promo_code
    )
    row = cur.fetchone()
    if row is None:
        return cart_total

    percent_off = row[0]
    discount = cart_total * percent_off / 100
    return cart_total - discount
