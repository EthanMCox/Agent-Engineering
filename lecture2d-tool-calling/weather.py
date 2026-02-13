from datetime import datetime


# Define the tool in OpenAI function/tool schema
weather_tool = {
    "type": "function",
    "name": "get_weather",  # <– top-level for Responses API
    "description": "Get the current local weather for a given location.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "Location name, e.g., ‘Boston’ or ‘Paris, FR’",
            },
            "unit": {
                "type": ["string", "null"],
                "enum": ["f", "c"],
                "description": "Temperature unit: ‘f’ for Fahrenheit, ‘c’ for Celsius (default ‘f’).",
            },
        },
        "required": ["location", "unit"],
        "additionalProperties": False,
    },
}

def get_weather(location: str, unit: str = "f") -> dict:
    """Return a mocked weather report for a location.

    Parameters
    - location: city name or free-form location string
    - unit: "c" for Celsius or "f" for Fahrenheit. Defaults to Fahrenheit.

    Returns a JSON-serializable dict.
    """
    print(f"DEBUG: Generate weather report for {location} in units: {unit}")
    unit = (unit or "f").lower()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Simple deterministic temps based on hash of a location to make outputs vary
    base = (abs(hash(location)) % 45) + 40  # 40..85
    condition = "Sunny" if base > 70 else "Partly Cloudy"

    if unit == "c":
        temp = round((base - 32) * 5 / 9, 1)
        feels_like = round(temp - 1.3, 1)
        u_label = "°C"
    else:
        temp = base
        feels_like = base - 2
        u_label = "°F"

    return {
        "location": location,
        "observed_at": now,
        "condition": condition,
        "temperature": f"{temp}{u_label}",
        "feels_like": f"{feels_like}{u_label}",
        "source": "local-stub",
    }

