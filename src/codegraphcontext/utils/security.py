import re
from typing import Any, Dict, Optional

def validate_cypher_read_only(cypher_query: str) -> Optional[Dict[str, Any]]:
    """
    Validates that a Cypher query is read-only.

    Returns None if the query is valid (read-only),
    or a dictionary with an "error" key if it's invalid.
    """
    if not cypher_query:
        return {"error": "Cypher query cannot be empty."}

    # Combined regex to match strings, backticked identifiers, and comments in a single pass.
    # This prevents markers of one type (e.g., //) from being misinterpreted when
    # they appear inside another type (e.g., a string literal).
    #
    # 1. Strings: "(?:\\.|[^"\\])*" or '(?:\\.|[^\'\\])*'
    # 2. Backticked identifiers: `(?:``|[^`])*` (handles escaped backticks ``)
    # 3. Multi-line comments: /\*[\s\S]*?\*/ (using [\s\S] to match across newlines)
    # 4. Single-line comments: //.*
    pattern = r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:``|[^`])*`|/\*[\s\S]*?\*/|//.*)'

    # We replace all these matched "ignored" sections with a single space.
    # This preserves word boundaries while removing potentially deceptive content.
    query_cleaned = re.sub(pattern, ' ', cypher_query)

    # Now check for forbidden keywords using word boundaries on the cleaned query.
    # We include keywords that mutate the graph or can be used for exfiltration (LOAD).
    forbidden_keywords = [
        'CREATE',
        'MERGE',
        'DELETE',
        'SET',
        'REMOVE',
        'DROP',
        'LOAD',
        r'CALL\s+apoc'
    ]

    for keyword in forbidden_keywords:
        # Use regex with word boundaries and case-insensitivity
        if re.search(r'\b' + keyword + r'\b', query_cleaned, re.IGNORECASE):
            return {
                "error": "This tool only supports read-only queries. Prohibited operations or keywords are not allowed."
            }

    return None
