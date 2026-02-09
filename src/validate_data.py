def validate_value(indicator_id, value):
    """
    Validate that economic data values are reasonable
    
    Args:
        indicator_id: The indicator being validated
        value: The numeric value to check
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    
    # Define reasonable ranges for each indicator
    validation_rules = {
        'GDP': {
            'min': 1000,      # GDP in billions, should be > $1 trillion
            'max': 100000,    # GDP shouldn't exceed $100 trillion
            'name': 'GDP (billions USD)'
        },
        'FEDFUNDS': {
            'min': 0,         # Interest rates can't be negative (typically)
            'max': 20,        # Fed funds rate unlikely to exceed 20%
            'name': 'Federal Funds Rate (%)'
        },
        'UMCSENT': {
            'min': 0,         # Sentiment index can't be negative
            'max': 150,       # Historical max is around 112
            'name': 'Consumer Sentiment Index'
        }
    }
    
    # Check if indicator has validation rules
    if indicator_id not in validation_rules:
        return True, None  # No rules defined, accept value
    
    rules = validation_rules[indicator_id]
    
    # Check minimum
    if value < rules['min']:
        return False, f"{rules['name']} value {value} is below minimum {rules['min']}"
    
    # Check maximum
    if value > rules['max']:
        return False, f"{rules['name']} value {value} exceeds maximum {rules['max']}"
    
    return True, None


def validate_date(date_str):
    """
    Validate that date is reasonable (not too old, not in future)
    
    Args:
        date_str: Date string in YYYY-MM-DD format
    
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    from datetime import datetime, timedelta
    
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return False, f"Invalid date format: {date_str}"
    
    # Data shouldn't be from before 1950
    if date.year < 1950:
        return False, f"Date {date_str} is suspiciously old (before 1950)"
    
    # Data shouldn't be more than 1 year in the future
    one_year_future = datetime.now() + timedelta(days=365)
    if date > one_year_future:
        return False, f"Date {date_str} is too far in the future"
    
    return True, None