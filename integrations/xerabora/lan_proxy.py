#!/usr/bin/env python3
"""Server-wide xeRAbora LAN forwarder. Track its loopback listener after profile switches."""
import argparse
import asyncio
import ipaddress
import re


def parse_xerabora_port(ss_output):
    """Only select loopback TCP listeners owned by the actual xeRAbora process."""
    ports = []
    for line in ss_output.splitlines():
        if "xerabora-linux-" not in line:
            continue
        # ss -H -ltnp prints Local Address:Port before Peer Address:Port.
        columns = line.split()
        if len(columns) < 5:
            continue
        local = columns[3]
        match = re.fullmatch(r"(?:127\.0\.0\.1|\[::1\]):(\d+)", local)
        if match:
            port = int(match.group(1))
            if 18280 <= port <= 18299:
                ports.append(port)
    return min(ports) if ports else None


async def discover_upstream():
    proc = await asyncio.create_subprocess_exec(
        "/usr/bin/ss", "-H", "-ltnp",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    output, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    return parse_xerabora_port(output.decode("utf-8", errors="replace"))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=18280)
    args = parser.parse_args()
    bind = ipaddress.ip_address(args.bind)
    if bind.version != 4 or bind.is_unspecified or bind.is_loopback or bind.is_multicast:
        parser.error("--bind must be a specific non-loopback IPv4 address")

    async def handle(reader, writer):
        upstream_writer = None
        try:
            port = await discover_upstream()
            if port is None:
                raise ConnectionError("xeRAbora loopback Web UI is not listening")
            upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
        except (OSError, ConnectionError) as error:
            print(f"LAN forwarding unavailable: {error}", flush=True)
            writer.close()
            await writer.wait_closed()
            return

        async def relay(src, dst):
            try:
                while chunk := await src.read(65536):
                    dst.write(chunk)
                    await dst.drain()
            except (OSError, ConnectionError):
                pass
            finally:
                dst.close()

        await asyncio.gather(
            relay(reader, upstream_writer),
            relay(upstream_reader, writer),
            return_exceptions=True,
        )
        writer.close()
        upstream_writer.close()
        for stream in (writer, upstream_writer):
            try:
                await stream.wait_closed()
            except (OSError, ConnectionError):
                pass

    server = await asyncio.start_server(handle, host=str(bind), port=args.port)
    print(f"xeRAbora LAN proxy listening at {bind}:{args.port}, upstream dynamically discovered", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
