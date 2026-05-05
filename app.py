"""
Old Recipe Intelligence — Gradio Web UI

Calls the Cloud Run API (/v1/ask).
Deploy to Render via render.yaml.
"""
import os
import requests as http
import gradio as gr

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE = os.getenv("API_BASE", "")
API_KEY  = os.getenv("API_KEY", "")
HEADERS  = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

EXAMPLES = [
    "What can replace buttermilk in a 1900s biscuit recipe?",
    "Substitute for lard in Victorian pastry?",
    "What replaces suet in an old English pudding?",
    "What can I use instead of cream of tartar?",
    "Depression-era substitute for shortening?",
    "How much is a gill of liquid?",
    "What does 'lard the meat' mean in old recipes?",
    "What is a salamander in Victorian cooking?",
    "What is potted meat?",
]


def ask(question: str) -> tuple[str, str]:
    """Call /v1/ask and return (answer, sources_markdown)."""
    if not question.strip():
        return "", ""
    try:
        r = http.post(
            f"{API_BASE}/v1/ask",
            json={"question": question},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return f"Error: {e}", ""

    answer = data.get("answer", "")
    sources = data.get("sources", [])
    latency = data.get("latency_ms", 0)

    lines = []
    seen = set()
    for s in sources:
        ing  = s.get("ingredient", "")
        sub  = s.get("substitute", "")
        book = s.get("book", "")
        year = s.get("year", "")
        key  = (ing, sub, book)
        if key in seen or not ing or not book:
            continue
        seen.add(key)
        if sub and sub != "null":
            lines.append(f"**{ing}** → _{sub}_  \n*{book}* ({year})")
        else:
            lines.append(f"*{book}* ({year})")

    sources_md = "\n\n".join(lines) if lines else "_No source records found._"
    footer = f"\n\n---\n_Response time: {latency}ms_"
    return answer, sources_md + footer


# ── UI ────────────────────────────────────────────────────────────────────────
with gr.Blocks(title="Old Recipe Intelligence", theme=gr.themes.Soft()) as demo:

    gr.Markdown("""
    # Old Recipe Intelligence
    Ask anything about ingredient substitutions, old measurements, or historical cooking techniques.
    Powered by **36,000+ substitution records** from **466 public-domain cookbooks (1658–1929)**.
    """)

    with gr.Row():
        with gr.Column(scale=3):
            question = gr.Textbox(
                label="Your question",
                placeholder="e.g. What can replace buttermilk in a 1900s biscuit?",
                lines=2,
            )
            with gr.Row():
                ask_btn   = gr.Button("Ask", variant="primary")
                clear_btn = gr.Button("Clear")

    with gr.Row():
        with gr.Column(scale=2):
            answer_box = gr.Textbox(label="Answer", lines=8, interactive=False)
        with gr.Column(scale=2):
            sources_box = gr.Markdown(label="Sources")

    gr.Examples(examples=[[e] for e in EXAMPLES], inputs=question)

    gr.Markdown("_Sources: Project Gutenberg & Internet Archive. All books pre-1929 public domain._")

    ask_btn.click(fn=ask, inputs=question, outputs=[answer_box, sources_box])
    question.submit(fn=ask, inputs=question, outputs=[answer_box, sources_box])
    clear_btn.click(fn=lambda: ("", ""), outputs=[answer_box, sources_box])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.getenv("PORT", "7861")))
