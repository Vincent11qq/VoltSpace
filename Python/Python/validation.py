def validate (appliance,power,quantity,minutes):
    if not isinstance(appliance, str) or not appliance.strip():
        raise ValueError("Appliance name cannot be empty")

    if power <= 0:
        raise ValueError("Power must be more than 0")

    if quantity < 1:
        raise ValueError("There must be at least 1 Quantity")

    if minutes < 0:
        raise ValueError("Usage time cannot be negative")

    return True