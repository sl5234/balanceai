from balanceai.models.category import Category

DEFAULT_CATEGORIES = [
    Category(name="income", description="Salary, wages, direct deposits, and other income"),
    Category(name="transfer", description="Transfers between accounts"),
    Category(name="groceries", description="Grocery stores and supermarkets"),
    Category(name="dining", description="Restaurants, cafes, and food delivery"),
    Category(name="utilities", description="Electric, gas, water, internet, and phone bills"),
    Category(name="rent", description="Rent and mortgage payments"),
    Category(name="transportation", description="Gas, public transit, rideshare, and parking"),
    Category(name="entertainment", description="Streaming services, movies, games, and events"),
    Category(name="shopping", description="Retail purchases, clothing, and electronics"),
    Category(name="health", description="Medical, dental, pharmacy, and fitness"),
    Category(name="travel", description="Flights, hotels, and travel expenses"),
    Category(name="subscriptions", description="Recurring subscription services"),
    Category(name="fees", description="Bank fees, service charges, and penalties"),
    Category(name="other", description="Transactions that don't fit other categories"),
]
