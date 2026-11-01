def format_data(data):
    return data.strip().lower()

def validate_token(token):
    return len(token) > 8
