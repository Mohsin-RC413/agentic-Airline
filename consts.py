# consts.py
from datetime import datetime

def get_instruction_preamble() -> str:
    """Return instruction preamble with current date formatted cleanly."""
    current_date = datetime.now().strftime("%B %d, %Y")
    return f"CURRENT DATE: {current_date}"
WELCOME_MESSAGE = """Hello and welcome aboard! I am your **Aroya Air Travel Companion**, your personal assistant for planning the perfect flight in seconds. ✈️

**Here’s what I can help you with:**
- 🌍 **Find flights** by city pair and exact travel date
- ⚡ **Book your ticket in seconds**
- 🧾 **Review baggage rules and amenities (Wi‑Fi, IFE)**
- 📊 **Compare options and prices**
- 🔔 **Track flight status for your booking**
- 👤 **Update your traveler profile and preferences**
- 🤖 **Answer all your airline-related questions**
- 🧑‍💼 **Connect you to a human agent**—share your email or phone for a callback

**Try asking me:**
- "Find flights from Hong Kong to Tokyo on 2025-11-09."
- "Book the YYZ → SIN flight on Nov 26."
- "Update my profile email."

**What can I do for you today?**"""

AGENT_NAME = "airline_agent"

INSTRUCTION_PREAMBLE = get_instruction_preamble()

# Response versioning for consistent front‑end parsing
# RESPONSE_VERSION = "1.0.0"
