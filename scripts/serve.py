"""Serve built UI and API on one loopback port; offline replay is the default."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build_app(*, live=False, database=None, static_dir=None):
    if not live:
        os.environ["FEEDBACK_OFFLINE"] = "1"
    else:
        os.environ.pop("FEEDBACK_OFFLINE", None)
    path = Path(database) if database else ROOT / "data" / ("local-live.db" if live else "offline-demo.db")
    os.environ["DATABASE_PATH"] = str(path.resolve())
    from server.main import create_app
    app = create_app(path, offline=not live, static_dir=static_dir or ROOT / "app/dist", restore_saved_model=True)
    if not live:
        from server.demo import seed_demo
        seed_demo(app.state.db)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use configured AI; requests may consume quota")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    if not (ROOT / "app/dist/index.html").exists():
        parser.error("Missing app/dist. Run npm run build in app first, or use the delivery package.")
    import uvicorn
    uvicorn.run(build_app(live=args.live, database=args.database), host="127.0.0.1", port=args.port)
