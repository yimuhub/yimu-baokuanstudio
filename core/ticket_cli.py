"""每日工单 CLI（launchd 调度入口）：python -m core.ticket_cli"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    from core import ticket
    res = ticket.run_ticket(emit=lambda m: print(f"[ticket] {m}", flush=True))
    print("TICKET_DONE:", res.get("date"), "| 稿件:", len(res.get("drafts", [])))


if __name__ == "__main__":
    main()
