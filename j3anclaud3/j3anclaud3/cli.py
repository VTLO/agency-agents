"""Command line: serve the web chat, chat in the terminal, inspect lite skills.

    j3anclaud3 serve [--mode orchestre|conversation]              # web chat + HTTP API (:8080)
    j3anclaud3 chat  [--mode orchestre|conversation] [--as alice]  # terminal chat
    j3anclaud3 skills [query]                                      # compile skills / test the router

Mode "orchestre" (default): cadrage, plan, human validation, production with the lite skills.
Mode "conversation": plain natural-language chat, no skills. Default from J3_MODE.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import MODES, Settings
from .protocol import est_tokens


class ConsoleOutbox:
    async def send_text(self, to: str, text: str) -> None:
        print(f"\n\033[36m[J3anClaud3 → {to}]\033[0m\n{text}\n")

    async def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> None:
        await self.send_text(to, text + "\n" + "  ".join(f"[{t} ⇒ {i}]" for i, t in buttons))

    async def send_document(self, to: str, path: Path, caption: str = "") -> None:
        print(f"\033[36m[J3anClaud3 → {to}] 📎 {path}\033[0m")


async def _chat(user: str, mode: str | None) -> None:
    from .app import build_bot

    s = Settings()
    if mode:
        s.mode = mode
    bot = build_bot(s, ConsoleOutbox())
    await bot.recover()
    print(f"J3anClaud3 (terminal, mode {bot.mode}). Tapez AIDE, ou Ctrl-D pour quitter.")
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
    p = argparse.ArgumentParser(prog="j3anclaud3")
    sub = p.add_subparsers(dest="cmd", required=True)
    mode_help = "orchestre (plans + skills, défaut) ou conversation (chat libre, sans skills)"
    sv = sub.add_parser("serve", help="interface web + API HTTP")
    sv.add_argument("--mode", choices=MODES, help=mode_help)
    c = sub.add_parser("chat", help="discussion dans le terminal")
    c.add_argument("--mode", choices=MODES, help=mode_help)
    c.add_argument("--as", dest="user", default="moi")
    k = sub.add_parser("skills")
    k.add_argument("query", nargs="?")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING if args.cmd == "chat" else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "serve":
        from .app import main as serve
        serve(args.mode)
    elif args.cmd == "chat":
        asyncio.run(_chat(args.user, args.mode))
    else:
        _skills(args.query)


if __name__ == "__main__":
    main()
