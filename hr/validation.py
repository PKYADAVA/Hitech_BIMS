"""adding validation functionality"""


def validate_employee_data(data):
    """
    Validates employee form data before processing.
    """
    required_fields = ["full_name", "designation"]
    for field in required_fields:
        if not data.get(field):
            return False, f"{field.replace('_', ' ').title()} is required"

    contact_fields = ["personal_contact", "emergency_contact"]
    for field in contact_fields:
        if data.get(field) and (
            len(str(data[field])) < 10 or len(str(data[field])) > 15
        ):
            return False, f"Invalid {field.replace('_', ' ')} number"

    if data.get("aadhar_number") and len(str(data["aadhar_number"])) != 12:
        return False, "Aadhar number must be 12 digits"

    if data.get("pan_card") and len(data["pan_card"]) != 10:
        return False, "PAN card number must be 10 characters"

    if data.get("salary") and float(data["salary"]) < 0:
        return False, "Salary cannot be negative"

    return True, ""
