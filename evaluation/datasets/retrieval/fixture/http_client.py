"""A tiny HTTP helper with retries for the retrieval eval fixture."""

import time


def retry_request(send, attempts=3, backoff=0.5):
    """Send a request, retrying with exponential backoff on failure."""
    last_error = None
    for attempt in range(attempts):
        try:
            return send()
        except ConnectionError as error:
            last_error = error
            time.sleep(backoff * (2**attempt))
    raise last_error


def parse_response(raw):
    """Split a raw HTTP response into a status code and a header mapping."""
    head, _, body = raw.partition("\r\n\r\n")
    status_line, *header_lines = head.splitlines()
    status = int(status_line.split()[1])
    headers = dict(line.split(": ", 1) for line in header_lines if ": " in line)
    return status, headers, body
