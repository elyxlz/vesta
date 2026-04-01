"""Phone number normalization for robust matching.

Handles Italian and international phone number formats:
- +39 333 123 4567
- 0039 333 1234567
- 333-123-4567
- (333) 123 4567
- +1 (555) 123-4567
"""

import re


def normalize_phone(phone: str) -> str:
    """Normalize a phone number for storage and comparison.

    Strips all formatting characters, then handles country code variations.
    Returns a canonical form: digits only, with leading country code if present.

    Examples:
        "+39 333 123 4567"  -> "393331234567"
        "0039 333 1234567"  -> "393331234567"
        "333 123 4567"      -> "3331234567"
        "+1 (555) 123-4567" -> "15551234567"
        "06 1234 5678"      -> "0612345678"
    """
    if not phone:
        return ""

    # Strip all non-digit characters except leading +
    stripped = phone.strip()
    has_plus = stripped.startswith("+")
    digits = re.sub(r"[^\d]", "", stripped)

    if not digits:
        return ""

    # Handle 00XX international prefix -> +XX
    if digits.startswith("00"):
        digits = digits[2:]
        has_plus = True

    # Handle + prefix (already stripped but flagged)
    if has_plus:
        # digits already has the country code as first digits
        return digits

    return digits


def normalize_for_search(query: str) -> str:
    """Normalize a search query that might be a phone number.

    Same logic as normalize_phone but also returns the original
    if it doesn't look like a phone number.
    """
    return normalize_phone(query)


def phone_variants(normalized: str) -> list[str]:
    """Generate variant forms of a normalized phone number for matching.

    Given a normalized number, generate forms that might match in the database:
    - The number as-is
    - With Italian country code (+39) added/removed
    - With leading zero added/removed (for Italian local numbers)
    """
    if not normalized:
        return []

    variants = [normalized]

    # If starts with Italian country code 39, also try without it
    if normalized.startswith("39") and len(normalized) > 4:
        without_cc = normalized[2:]
        variants.append(without_cc)
        # Italian landlines start with 0 after country code
        # Mobile numbers start with 3
        # If it starts with 0, also try without the 0
        if without_cc.startswith("0"):
            variants.append(without_cc[1:])

    # If doesn't start with country code, try adding Italian +39
    if not normalized.startswith("39"):
        variants.append("39" + normalized)

    # If starts with 0 (Italian landline), try without 0 and with +39
    if normalized.startswith("0"):
        without_zero = normalized[1:]
        variants.append(without_zero)
        variants.append("39" + without_zero)
        variants.append("39" + normalized)

    # If starts with 3 and is 10 digits (Italian mobile without country code)
    if normalized.startswith("3") and len(normalized) == 10:
        variants.append("39" + normalized)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    return unique


def looks_like_phone(query: str) -> bool:
    """Check if a query string looks like it could be a phone number."""
    # Strip common formatting
    cleaned = re.sub(r"[\s\-\(\)\.\+]", "", query)
    # If mostly digits (allow some non-digit chars in original)
    if not cleaned:
        return False
    digit_ratio = sum(c.isdigit() for c in cleaned) / len(cleaned)
    return digit_ratio >= 0.7 and len(cleaned) >= 3
