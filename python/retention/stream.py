"""Concatenated TAER packets: no uncharged container framing bytes."""

from retention.codec import HEADER, PREFIX, decode_packet


def read_packets(stream):
    previous_end = None
    while True:
        raw = stream.read(HEADER.size)
        if not raw:
            return
        if len(raw) != HEADER.size:
            raise ValueError("Truncated packet stream header")
        magic, version, size, start, duration, budget, count = HEADER.unpack(raw)
        if (
            magic != b"TAER"
            or version != 1
            or size != HEADER.size
            or budget < HEADER.size
        ):
            raise ValueError("Invalid packet stream header")
        if previous_end is not None and start < previous_end:
            raise ValueError("Packet epochs overlap or repeat")
        data = bytearray(raw)
        for _ in range(count):
            prefix = stream.read(PREFIX.size)
            if len(prefix) != PREFIX.size:
                raise ValueError("Truncated stream record prefix")
            _, _, length = PREFIX.unpack(prefix)
            if len(data) + PREFIX.size + length > budget:
                raise ValueError("Record exceeds packet stream budget")
            payload = stream.read(length)
            if len(payload) != length:
                raise ValueError("Truncated stream record payload")
            data.extend(prefix)
            data.extend(payload)
        packet = decode_packet(bytes(data))
        previous_end = packet.start_us + packet.duration_us
        yield packet
