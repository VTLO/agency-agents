"""Command line: serve the web chat, chat in the terminal, inspect lite skills.

    m3lvin serve                 # web chat + HTTP API (http://localhost:8080)
    m3lvin chat [--as alice]     # terminal chat (same brain, same database)
    m3lvin skills [query]        # compile skills / test the router
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import Settings
from .protocol import est_tokens


class ConsoleOutbox:
    async def send_text(self, to: str, text: str) -> None:
        print(f"\n\033[36m[M3LVin → {to}]\033[0m\n{text}\n")

    async def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
        await self.send_text(to, text + "\n" + "  ".join(f"[{t} ⇒ {i}]" for i, t in buttons))

    async def send_document(self, to: str, path: Path, caption: str = "") -> None:
        print(f"\033[36m[M3LVin → {to}] 📎 {path}\033[0m")


async def _chat(user: str) -> None:
    from .app import build_bot

    s = Settings()
    bot = build_bot(s, ConsoleOutbox())
    await bot.recover()
    print("M3LVin (terminal). Tapez AIDE, ou Ctrl-D pour quitter.")
    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "vous> ")
        except EOFError:
            break
        await bot.handle(user, line)
    if bot.tasks:
        print("…productions en cours, attente de la fin (Ctrl-C pour quitter)")
        await asyncio.gather(*bot.tasks)


def _skills(query: str | None) -> None:
    from .skills import SkillRegistry

    s = Settings()
    reg = SkillRegistry.open(s.agency_root, s.data_dir / f"skills-{s.skill_prompt_tokens}.json", s.skill_prompt_tokens)
    sk = list(reg.skills.values())
    print(f"{len(sk)} lite skills · avg prompt ≈ {sum(est_tokens(x.prompt) for x in sk)//len(sk)} tokens · "
          f"avg card ≈ {sum(est_tokens(x.card()) for x in sk)//len(sk)} tokens")
    if query:
        for x in reg.route(query, s.shortlist_size):
            print(" ", x.card())


def main() -> None:
    p = argparse.ArgumentParser(prog="m3lvin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    c = sub.add_parser("chat")
    c.add_argument("--as", dest="user", default="moi")
    k = sub.add_parser("skills")
    k.add_argument("query", nargs="?")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING if args.cmd == "chat" else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "serve":
        from .app import main as serve
        serve()
    elif args.cmd == "chat":
        asyncio.run(_chat(args.user))
    else:
        _skills(args.query)


if __name__ == "__main__":
    main()
