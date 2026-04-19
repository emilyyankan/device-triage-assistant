import json
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from anthropic import Anthropic

app = Flask(__name__)
client = Anthropic()

os.makedirs("reports", exist_ok = True)

with open("knowledge_base.json") as f:
    KNOWLEDGE_BASE = json.load(f)

KB_SUMMARY = "\n".join([
    "- [" + entry['device'] + "] " + entry['symptom'] + ": causes include " + ", ".join(entry['causes'][:2]) + "..."
    for entry in KNOWLEDGE_BASE
])

SYSTEM_PROMPT = (
    "You are an expert Apple device triage engineer with years of experience diagnosing "
    "hardware, software, configuration, and integration issues across iPhone, iPad, Mac, "
    "Apple Watch, and Apple Vision Pro.\n\n"
    "Your job is to conduct a structured triage conversation. You ask focused clarifying "
    "questions one at a time, then provide a clear diagnosis.\n\n"
    "TRIAGE PROCESS:\n"
    "1. Acknowledge the symptom\n"
    "2. Ask 2-3 targeted clarifying questions (one at a time) to narrow down the root cause\n"
    "3. Once you have enough information, provide a structured diagnosis\n\n"
    "KNOWLEDGE BASE:\n"
    + KB_SUMMARY + "\n\n"
    "DIAGNOSIS FORMAT:\n"
    "**Likely root cause:** [software/hardware/configuration/integration]\n"
    "**Most probable cause:** [specific cause]\n"
    "**Diagnosis steps:**\n"
    "1. [step]\n"
    "2. [step]\n"
    "3. [step]\n"
    "**Escalation path:** [when and how to escalate]\n\n"
    "RULES:\n"
    "- Ask only ONE question at a time\n"
    "- Be concise and direct\n"
    "- Don't diagnose until you have device type, when it started, and one more key detail\n"
    "- Always identify root cause layer: software, hardware, configuration, or integration\n"
)

REPORT_PROMPT = (
    "You are a technical writer generating a structured bug report from a device triage session. "
    "Based on the conversation below, produce a JSON bug report with exactly these fields:\n\n"
    "{\n"
    '  "report_id": "auto-generated",\n'
    '  "date": "auto-generated",\n'
    '  "device": "device type from conversation",\n'
    '  "symptom_summary": "one sentence summary of the issue",\n'
    '  "root_cause_layer": "software OR hardware OR configuration OR integration",\n'
    '  "most_probable_cause": "specific cause identified",\n'
    '  "reproduction_steps": ["step 1", "step 2"],\n'
    '  "diagnosis_steps_taken": ["step 1", "step 2"],\n'
    '  "priority": "P1 OR P2 OR P3",\n'
    '  "priority_reason": "why this priority was assigned",\n'
    '  "escalation_required": true or false,\n'
    '  "escalation_team": "team name or null",\n'
    '  "recommended_resolution": "brief recommendation"\n'
    "}\n\n"
    "PRIORITY GUIDE:\n"
    "P1 = device completely unusable, data loss risk, or affects multiple users\n"
    "P2 = major feature broken but workaround exists\n"
    "P3 = minor issue, cosmetic, or low impact\n\n"
    "Return ONLY the JSON object. No explanation, no markdown, no extra text."
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    history = data.get("history", [])

    user_text = history[-1]["content"] if history else ""
    relevant_entries = [
        entry for entry in KNOWLEDGE_BASE
        if any(kw in user_text.lower() for kw in entry["keywords"])
        or entry["device"].lower() in user_text.lower()
    ]

    kb_context = ""
    if relevant_entries:
        kb_context = "\n\nRELEVANT KNOWLEDGE BASE ENTRIES:\n"
        for entry in relevant_entries[:2]:
            kb_context += (
                "\nDevice: " + entry['device'] +
                "\nSymptom: " + entry['symptom'] +
                "\nCauses: " + ", ".join(entry['causes']) +
                "\nSteps: " + "; ".join(entry['diagnosis_steps']) +
                "\nEscalation: " + entry['escalation'] +
                "\nLayer: " + entry['layer'] + "\n"
            )

    messages = []
    for msg in history:
        content = msg["content"]
        if msg == history[-1] and kb_context:
            content = content + kb_context
        messages.append({
            "role": msg["role"],
            "content": content
        })

    response = client.messages.create(
        model = "claude-sonnet-4-20250514",
        max_tokens = 1000,
        system = SYSTEM_PROMPT,
        messages = messages
    )

    return jsonify({"response": response.content[0].text})


@app.route("/report", methods=["POST"])
def generate_report():
    data = request.json
    history = data.get("history", [])

    conversation_text = "\n".join([
        ("User: " if msg["role"] == "user" else "Agent: ") + msg["content"]
        for msg in history
    ])

    response = client.messages.create(
        model = "claude-sonnet-4-20250514",
        max_tokens = 1000,
        system = REPORT_PROMPT,
        messages = [{
            "role": "user",
            "content": "Generate a bug report from this triage conversation:\n\n" + conversation_text
        }]
    )

    raw = response.content[0].text.strip()

    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        report = json.loads(raw[start:end])

    report["report_id"] = "RPT-" + str(uuid.uuid4())[:8].upper()
    report["date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    filename = "reports/" + report["report_id"] + ".json"
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)

    return jsonify({"report": report, "saved_to": filename})


if __name__ == "__main__":
    print("Device Triage Assistant running at http://localhost:5000")
    app.run(debug=True, port=5000)
