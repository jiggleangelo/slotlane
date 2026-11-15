from .taxonomy import ORGANIC, classify

def organic_answer(query):
    category = classify(query)
    if not category:
        return "I couldn't match this question to the demo's fixed developer-tool catalog.", []
    return "Here are independently selected options from the fixed demo catalog:", list(ORGANIC.get(category, ()))
