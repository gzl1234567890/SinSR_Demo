"""Local SinSR classroom demo: check, prepare, then present."""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser


def main():
    sys.dont_write_bytecode = True
    # Keep Chinese messages readable in Windows terminals and captured logs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SinSR 中文课堂演示台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--verify-upstream", action="store_true", help="校验内置论文源码保持原样")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间")
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    if args.verify_upstream:
        from upstream_compat import verify_vendor_sources
        print(json.dumps(verify_vendor_sources(), ensure_ascii=False, indent=2))
        return 0
    try:
        from demo_backend import check_environment, create_app, frontend_version, prepare_demo
        import uvicorn
    except ImportError as exc:
        print(f"演示依赖尚未安装：{exc}\n请先运行 setup_demo.ps1，详见 README.md。")
        return 1
    if args.check:
        print(json.dumps(check_environment(), ensure_ascii=False, indent=2))
        return 0
    if args.prepare:
        try:
            prepare_demo(progress=print)
        except Exception as exc:
            print(f"准备未完成：{exc}\n请查看 README.md 中的排错步骤。")
            return 1
        return 0
    display_host = "localhost" if args.host in {"0.0.0.0", "127.0.0.1"} else args.host
    url = f"http://{display_host}:{args.port}/?v={frontend_version()}"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((args.host, args.port))
    except OSError:
        # A second double-click should reuse the running demo and its warm GPU.
        try:
            with urllib.request.urlopen(url, timeout=1) as existing:
                page = existing.read(4096).decode("utf-8", errors="replace")
            if "<title>SinSR · 图像超分辨率演示</title>" in page:
                print(f"演示台已经在运行：{url}")
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
        except OSError:
            pass
        print(f"无法使用 {args.host}:{args.port}。可尝试 python app.py --port {args.port + 1}")
        return 1
    if not args.no_browser:
        def open_when_ready():
            for _ in range(100):
                try:
                    with urllib.request.urlopen(url, timeout=0.5) as response:
                        if response.status == 200:
                            webbrowser.open(url)
                            return
                except OSError:
                    time.sleep(0.2)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"\nSinSR 演示台：{url}\n按 Ctrl+C 结束。上台前运行 python app.py --prepare。\n")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
