import sys

from .server import serve

if __name__ == "__main__":
    try:
        serve()
    except KeyboardInterrupt:
        pass
    except Exception as error:  # noqa: BLE001 - never print provider credentials
        print(
            f"启动失败（{type(error).__name__}），请检查 model/.env 和依赖。",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
