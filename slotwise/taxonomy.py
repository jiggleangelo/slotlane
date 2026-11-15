CATEGORIES = ("error-monitoring", "auth", "email-api", "database", "analytics", "payments", "hosting", "feature-flags")
KEYWORDS = {
    "error-monitoring": ("crash", "exception", "sentry", "stack trace", "monitor errors", "error"),
    "auth": ("auth", "login", "oauth", "identity"),
    "email-api": ("email", "mail", "smtp"),
    "database": ("database", "postgres", "sql"),
    "analytics": ("analytics", "metrics", "tracking"),
    "payments": ("payment", "billing", "checkout"),
    "hosting": ("hosting", "deploy", "server"),
    "feature-flags": ("feature flag", "rollout"),
}
ORGANIC = {
    "error-monitoring": ["OpenTelemetry — open observability instrumentation", "GlitchTip — open-source error tracking"],
    "auth": ["Keycloak — open-source identity management"],
    "email-api": ["Postal — open-source mail delivery"],
    "database": ["PostgreSQL — relational database"],
    "analytics": ["Plausible — privacy-friendly analytics"],
    "payments": ["Use a PCI-compliant payment provider"],
    "hosting": ["Review your runtime's deployment guide"],
    "feature-flags": ["Unleash — open-source feature flags"],
}

def classify(query):
    text = query.casefold()
    for category, words in KEYWORDS.items():
        if any(word in text for word in words): return category
    return None
