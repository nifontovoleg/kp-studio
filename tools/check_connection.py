"""Check provider reachability without sending credentials."""
import socket
import urllib.error
import urllib.request

try:
    print('DNS addresses:', len(socket.getaddrinfo('api.proxyapi.ru', 443)), flush=True)
    request = urllib.request.Request('https://api.proxyapi.ru/v1/models', method='GET')
    with urllib.request.urlopen(request, timeout=20) as response:
        print('HTTPS:', response.status)
except urllib.error.HTTPError as exc:
    print('HTTPS reachable; HTTP:', exc.code)
except Exception as exc:
    print('Connection failed:', type(exc).__name__, str(exc))
