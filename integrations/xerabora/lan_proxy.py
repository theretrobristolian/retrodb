#!/usr/bin/env python3
"""Minimal byte-transparent TCP forwarder for xeRAbora's loopback-only Web UI.

No HTTP parsing: WebSockets and streaming connections pass through unchanged.
"""
import argparse
import asyncio
import ipaddress
import signal


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=18280)
    args = parser.parse_args()
    bind = ipaddress.ip_address(args.bind)
    if bind.version != 4 or bind.is_unspecified or bind.is_loopback or bind.is_multicast:
        parser.error("--bind must be a specific, non-loopback IPv4 address")

    async def handle(reader, writer):
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", args.port)
        except OSError:
            writer.close()
            await writer.wait_closed()
            return

        async def relay(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except (OSError, ConnectionError):
                pass
            finally:
                dst.close()

        await asyncio.gather(relay(reader, upstream_writer), relay(upstream_reader, writer), return_exceptions=True)
        for stream in (writer, upstream_writer):
            stream.close()
            try:
                await stream.wait_closed()
            except (OSError, ConnectionError):
                pass

    server = await asyncio.start_server(handle, host=str(bind), port=args.port, reuse_address=True)
    print(f"xeRAbora LAN proxy listening at {bind}:{args.port} -> 127.0.0.1:{args.port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
