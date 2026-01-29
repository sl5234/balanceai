from balanceai.models.category import Category


def build_categorization_prompt(categories: list[Category], transaction_description: str) -> str:
    category_list = "\n".join(f"- {c.name}: {c.description}" for c in categories)
    return f"""You are a transaction categorizer. Given a transaction description, assign it to exactly one of the provided categories.

Categories:
{category_list}

Transaction description: {transaction_description}

Return ONLY a JSON object with the category name. Example: {{"category": "groceries"}}
The category MUST be one of the names listed above. No explanations or additional text."""
