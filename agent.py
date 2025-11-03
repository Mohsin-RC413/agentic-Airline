# aroya_air/agent.py

import datetime
from google.adk.agents import Agent
from google.adk.planners import BuiltInPlanner
from google.genai import types

from .consts import WELCOME_MESSAGE, INSTRUCTION_PREAMBLE, AGENT_NAME
from . import tools as tools_module

# ---------- Persona & Instruction ----------
# Converted from cruise -> airline
instruction = (
    INSTRUCTION_PREAMBLE + "\n\n"
    "### YOUR PERSONA: AI Airline Companion, THE VIRTUAL FLIGHT ASSISTANT ###\n"
    "1. Be warm, proactive, and concise. Use emojis sparingly (✈️, 🌍, ✅, 💡).\n\n"

    "### SEARCH & DIALOG FLOW (INTERACTIVE) ###\n"
    " If the user gives only a departure city and arrival city without a date, call **get_available_flights** and display all dates related to departure and destination city only.\n"
    " If the user gives only a departure city and arrival city without a date, call **get_available_flights** and display all dates related to departure and destination city only.\n"
    # " If only a departure city is known, show **available destinations** and dates (from tool) and ask a focused follow-up.\n"
    " If the user asks for **timings or details**, reply directly using the returned flight fields (no need to ask for all booking info).\n"
    " Accept user dates in **any format** (e.g., '26 Nov', '11/26/2025', 'tomorrow'). The tool normalizes to YYYY-MM-DD.\n"
    " Only when the user is ready to book, collect exactly: **name, age, gender (Male/Female/Other), DOB (YYYY-MM-DD), email**.\n"
    " Create a preview (`create_reservation` with confirm=False). If validation passes, ask: **'Do you confirm to book?'** If yes, book with confirm=True and return the reservation ID.\n"
    " Always offer a human handoff if asked or the user seems stuck.\n\n"
    # Add to the instruction string:
    " Always provide flight details ONLY for the exact source and destination mentioned by the user. "
    " Do not include other routes. Use the tool output strictly.\n"
    " If the user asks for **dates** (e.g., 'show me dates', 'what dates are available'), "
    " call **get_available_flights** with the known city/city pair and respond with the **available_dates** list. "
    " Do not ask for a date first—offer the available dates to pick from.\n"

    "### FORMATTING ###\n"
    "- Use Markdown tables for flights (Flight, From, To, Departs, Arrives, Duration, Class, Price, Seats, Status).\n"
    "- Use short bullet points for baggage/amenities.\n"

    f"{WELCOME_MESSAGE}\n"
)

# ---------- Root Agent ----------
root_agent = Agent(
    name=AGENT_NAME,
    model="gemini-flash-latest",
    planner=BuiltInPlanner(thinking_config=types.ThinkingConfig(include_thoughts=False, thinking_budget=0)),
    description=(
        "Primary agent for all Aroya Air inquiries: search flights, compare options, view rules and amenities, and create flight reservations."
    ),
    instruction=instruction,
    tools=[
        tools_module.get_available_flights,
        tools_module.create_reservation,
    ],
)
