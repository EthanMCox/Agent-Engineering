# Superbowl "database"
superbowls = {
    2025: {
            "found": True,
            "year": 2025,
            "winner": "Philadelphia Eagles",
            "opponent": "Kansas City Chiefs",
            "venue": "Caesars Superdome in New Orleans, LA",
            "score": "40-22",
            "notes": "Super Bowl LIX (2025)",
            "confidence": 0.95
        },
    2024: {
        "found": True,
        "year": 2024,
        "winner": "San Francisco 49ers",
        "opponent": "Kansas City Chiefs",
        "venue": "Allegiant Stadium in Las Vegas, Nevada",
        "score": "25–22",
        "notes": "Super Bowl LVIII (2024) was a thrilling overtime victory for the 49ers.",
        "confidence": 0.95
    },
    0: {
        "found": False,
        "year": 0,
        "winner": "",
        "opponent": "",
        "score": "",
        "notes": "No internal data for that year.",
        "confidence": 0.0
    }
}

def get_superbowl_info(year: int) -> dict:
    """Get superbowl information for a given year. Return the data in structured format. Years supported are 2024-2025.
    {
        'found': True/False,
        'year': int,
        'winner': str,
        'opponent': str,
        'venue': str,
        'notes': str,
        'confidence': float,
    If the function doesn't have information for a named year it will
    return a dictionary with the 'found' flag set to False.
    In this case, you should call web_search as a fallback strategy to answer the query.
    """
    if year in superbowls:
        return superbowls[year]
    else:
        no_data = superbowls[0]
        no_data['year'] = year
        return no_data
