"""Start OncoReady:  python run.py  [--port 8000] [--host 127.0.0.1]"""
import argparse

from app.server import create_app

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    create_app().run(host=a.host, port=a.port, debug=False, threaded=True)
