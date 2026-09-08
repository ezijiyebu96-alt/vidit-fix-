"""Terminal mode — talk to Vidit without the GUI (also handy over SSH / for testing).

    python -m vidit --cli

Commands inside the CLI:  /soul  /memories  /forget <x>  /people  /skills  /health  /export  /stop  /quit
"""
from __future__ import annotations

import sys
from typing import Optional

from .constitution import NAME
from .core import Vidit
from .guardian import Decision, PermissionRequest


def _terminal_prompter(request: PermissionRequest) -> Decision:
    print(f"\n🔐 {NAME} asks: {request.question}")
    if request.detail:
        print(f"   {request.detail[:300]}")
    answer = input("   [y]es once / [s]ession / [a]lways / [n]o / ne[v]er > ").strip().lower()
    return {"y": Decision.ALLOW_ONCE, "s": Decision.ALLOW_SESSION, "a": Decision.ALLOW_ALWAYS,
            "v": Decision.DENY_ALWAYS}.get(answer[:1], Decision.DENY)


def run_cli(home: Optional[str] = None, quiet: bool = False) -> int:
    vidit = Vidit(home=home, prompter=_terminal_prompter, quiet=quiet)
    vidit.on_proactive(lambda text: print(f"\n💬 {NAME} (proactive): {text}\n> ", end=""))
    greeting = vidit.wake_up()
    status = vidit.llm.status()
    print(f"— {NAME} v0.1 · brain: {status['backend']}/{status['model']} · home: {vidit.config.home}")
    if status["backend"] == "echo":
        print("  (fallback mind: install Ollama and run `ollama pull qwen2.5:7b` for his full brain)")
    if greeting:
        print(f"\n{NAME}: {greeting}\n")
    try:
        while True:
            try:
                text = input("> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("/quit", "/exit", "/bye"):
                break
            if text == "/soul":
                d = vidit.soul_dashboard()
                print(f"mood: {d['mood']['describe']} · knows you {d['understanding']['percent']}% · {d['memory']['count']} memories · age {d['self']['age']}")
                print("top feelings:", ", ".join(f"{k} {v:.0%}" for k, v in d["mood"]["top"]))
                continue
            if text == "/memories":
                for m in vidit.memory.all_memories()[:40]:
                    print(f"  [{m.kind}] {m.content}{' ★' if m.favorite else ''}")
                continue
            if text.startswith("/forget "):
                print(f"forgot {vidit.forget(text[8:])} memories")
                continue
            if text == "/people":
                for p in vidit.memory.people():
                    print(f"  {p['name']} ({p['relation']}) — {p['notes'][:80]}")
                continue
            if text == "/skills":
                print(vidit.repair.list_skills() or "none yet")
                continue
            if text == "/health":
                print(vidit.repair.heal(llm_status=vidit.llm.status()).summary())
                continue
            if text == "/export":
                print("exported to", vidit.export_everything())
                continue
            if text == "/stop":
                vidit.stop()
                print("stopped.")
                continue
            if text == "/think":
                vidit.show_thinking = not vidit.show_thinking
                print("thinking shown" if vidit.show_thinking else "thinking hidden")
                continue
            reply = vidit.chat(text)
            if reply.thinking and vidit.show_thinking:
                print(f"  💭 {reply.thinking[:800]}")
            tag = f" [{reply.emotion}{' · ' + ', '.join(reply.tools_used) if reply.tools_used else ''}]"
            print(f"\n{vidit.self_model.data.get('name', NAME)}: {reply.text}{tag}\n")
            if reply.learned:
                print(f"  (learned: {'; '.join(reply.learned)})")
    except KeyboardInterrupt:
        print()
    finally:
        vidit.sleep()
        print("Goodnight.")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
