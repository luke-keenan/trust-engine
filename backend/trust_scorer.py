def score(policy_rate: float, risk_probability: float, uncertainty: float) -> tuple[float, str, bool]:
    value = round(
        0.4 * policy_rate * 1000
        + 0.3 * (1 - risk_probability) * 1000
        + 0.3 * (1 - uncertainty) * 1000,
        2,
    )
    maturity = "Untrusted" if value < 400 else "User" if value < 700 else "Supervisor" if value < 900 else "Kernel"
    return value, maturity, value >= 700
