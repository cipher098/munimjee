"""Price negotiation decision logic. Floor price never leaves this module."""


def decide_negotiation_move(
    offered_price: int,   # customer's offer in paise
    listed_price: int,
    floor_price: int,
    round_number: int,
) -> dict:
    margin = listed_price - floor_price

    if offered_price >= floor_price:
        return {"accept": True, "final_price": offered_price}

    if round_number == 1:
        counter = listed_price - int(margin * 0.3)
        return {"accept": False, "counter_price": counter}

    if round_number == 2:
        counter = floor_price + 5000   # floor + ₹50 buffer
        return {"accept": False, "counter_price": counter}

    # Round 3+ — hold firm at floor
    return {"accept": False, "hold_firm": True, "counter_price": floor_price}
