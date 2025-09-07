import os
import socket
import threading
import time
import gevent  # Add this import
from django.conf import settings

# SSDP Multicast Address and Port
SSDP_MULTICAST = "239.255.255.250"
SSDP_PORT = 1900

DEVICE_TYPE = "urn:schemas-upnp-org:device:MediaServer:1"
SERVER_PORT = 8000

# Prefer this to be fetched via a environment variable. 
def get_host_ip():
    return os.environ.get("DISPATCHARR_HOST_IP", "dispatcharr")

def ssdp_response(addr, host_ip):
    response = (
        f"HTTP/1.1 200 OK\r\n"
        f"CACHE-CONTROL: max-age=1800\r\n"
        f"EXT:\r\n"
        f"LOCATION: http://{host_ip}:{SERVER_PORT}/hdhr/device.xml\r\n"
        f"SERVER: Dispatcharr/1.0 UPnP/1.0 HDHomeRun/1.0\r\n"
        f"ST: {DEVICE_TYPE}\r\n"
        f"USN: uuid:device1-1::{DEVICE_TYPE}\r\n"
        f"\r\n"
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.sendto(response.encode("utf-8"), addr)
    sock.close()

def ssdp_listener(host_ip):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((SSDP_MULTICAST, SSDP_PORT))
    while True:
        data, addr = sock.recvfrom(1024)
        if b"M-SEARCH" in data and DEVICE_TYPE.encode("utf-8") in data:
            print(f"Received M-SEARCH from {addr}")
            ssdp_response(addr, host_ip)

def ssdp_broadcaster(host_ip):
    notify = (
        f"NOTIFY * HTTP/1.1\r\n"
        f"HOST: {SSDP_MULTICAST}:{SSDP_PORT}\r\n"
        f"CACHE-CONTROL: max-age=1800\r\n"
        f"LOCATION: http://{host_ip}:{SERVER_PORT}/hdhr/device.xml\r\n"
        f"SERVER: Dispatcharr/1.0 UPnP/1.0 HDHomeRun/1.0\r\n"
        f"NT: {DEVICE_TYPE}\r\n"
        f"NTS: ssdp:alive\r\n"
        f"USN: uuid:device1-1::{DEVICE_TYPE}\r\n"
        f"\r\n"
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    while True:
        sock.sendto(notify.encode("utf-8"), (SSDP_MULTICAST, SSDP_PORT))
        gevent.sleep(30)  # Replace time.sleep with gevent.sleep

def start_ssdp():
    host_ip = get_host_ip()
    threading.Thread(target=ssdp_listener, args=(host_ip,), daemon=True).start()
    threading.Thread(target=ssdp_broadcaster, args=(host_ip,), daemon=True).start()
    print(f"SSDP services started on {host_ip}.")
