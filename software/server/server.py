#!/usr/bin/env python3
import socket
from datetime import datetime
import threading
import csv
from pathlib import Path
import os
import sys
import getpass

try:
    import config as config
except ImportError:
    import config_local as config

host = config.host
port = config.port
ESP_32_IP = config.ESP_32_IP
csv_path = config.CSV_PATH

csv_header = ["timestamp_iso", "tC", "rH", "hPa", "lux", "srawVoc", "srawNox"]

file_lock = threading.Lock()
stop_event = threading.Event()
threads = []

def get_startup_pw():
    env_pw = os.getenv("BELLADONNA_SERVER_PW")
    if env_pw:
        return env_pw
    try:
        return getpass.getpass("[SERVER] [i]  auth   Enter password to start server: ")
    except KeyboardInterrupt:
        print("\n[SERVER] [!]  auth   Aborted by user.")
        sys.exit(1)

# password = get_startup_pw()
csv_path.parent.mkdir(parents=True, exist_ok=True)

def ensure_csv_header():
    if csv_header is None:
        print(f"[{datetime.now()}]  [CSVWTR] [?] warn   CSV header is none")
        return
    print(f"[{datetime.now()}]  [CSVWTR] [i]  info   CSV header is valid")
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        print(f"[{datetime.now()}]  [CSVWTR] [*]  exec   new CSV file")
        with file_lock, csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(csv_header)
            print(f"[{datetime.now()}]  [CSVWTR] [i]  info   created new CSV + header")

def append_csv_line(raw_line: str, _counter: int, _total_count: int):
    """Append either the raw line, or parse & append columns you care about."""
    ts = datetime.now().isoformat(timespec="seconds") + "Z"
    try:
        with file_lock, csv_path.open("a", newline="") as f:
            writer = csv.writer(f)
            fields = [x.strip() for x in raw_line.split(",")]
            writer.writerow([ts] + fields)
            print(f"[{datetime.now()}]  [CSVWTR] [*]  exec   append ({_counter}/{_total_count}) new fields {fields}")
    except Exception as e:
        print(f"[{datetime.now()}]  [CSVWRT] [!]  err.   error: {e}]")


def handle_client(conn, addr, _counter, _total_count, _PW):
    peer = f"{addr[0]}:{addr[1]}"
    print(f"[{datetime.now()}]  [SERVER] [+]  conn   {peer} connected")
    conn.settimeout(1.0) # regularly check for stop_event
    buffer = b""
    try:
        while not stop_event.is_set():
            try:
                # make a simple line reader that copes with partial frames
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:                                               # b'20.70,79.40,981.61,1389.17\r\n'
                    line, buffer = buffer.split(b"\n", 1)                                              # b'20.70,79.40,981.61,1389.17\r'
                    # normalise CRLF/CR endings and strip extra white space
                    text = line.decode("utf-8", errors="replace").strip("\r").strip()  # ? this removes 8355 pw ?                                                # 20.70,79.40,981.61,1389.17
                    # print(text)
                    pw = "8355" # text[:4]
                    # print(pw)
                    if pw != _PW:
                        conn.close()
                        print(f"[{datetime.now()}]  [CLIENT] [i]  auth   unauthorised data received")
                        print(f"[{datetime.now()}]  [SERVER] [!]  conn   connection terminated stat")
                        raise Exception
                        # break
                    print(f"[{datetime.now()}]  [SERVER] [i]  auth   authorised data TX")
                    print(f"[{datetime.now()}]  [CLIENT] [i]  info   new data accepted")
                    append_csv_line(text[4:], _counter, _total_count)
            except socket.timeout:
                continue # loop back, check stop_event
    except Exception as e:
        print(f"[{datetime.now()}]  [SERVER] [!]  err.   {peer} error: {e}")
    finally:
        conn.close()
        print(f"[{datetime.now()}]  [SERVER] [-]  conn   {peer} disconnected\n")

def main():
    print("Starting Belladonna ESP32 Receiver Server...")

    # PW = input(f"[{datetime.now()}]  [SERVER] [i]  auth   Enter password to start server: \n")
    PW = "8355" # get_startup_pw()
    ensure_csv_header()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(5)
    s.settimeout(1.0) # so Ctrl+C can be handled promptly
    print(f"[{datetime.now()}]  [SERVER] [i]  info   listening on {host}:{port}")
    print(f"[{datetime.now()}]  [SERVER] [i]  info   data path → {csv_path.resolve()}")
    counter: int = 0
    total_count: int = 0
    print(f"[{datetime.now()}]  [CLIENT] [i]  info   count ({counter}/{total_count})\n")
    
    try:
        while not stop_event.is_set():
            try:
                conn, addr = s.accept()
                if not addr[0] == ESP_32_IP:
                    s.close()
                    print("NOT AUTHORISED")
                    break
            except socket.timeout:
                continue
            try:
                t = threading.Thread(target=handle_client, args=(conn, addr, counter, total_count, PW))
                t.start()
                threads.append(t)
                counter += 1
                total_count += 1
            except Exception as e:
                print(f"[{datetime.now()}]  [CLIENT] [!]  err.   error: {e}]")
                counter = counter
                total_count += 1
                continue
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}]  [SERVER] [*]  exec   Ctrl+C received – shutting down")
    finally:
        # Signal threads to stop, close listener to unblock accept()
        stop_event.set()
        s.close()
        # wait for all client threads to finish
        for t in threads:
            t.join(timeout=2.0)
        print(f"[{datetime.now()}]  [SERVER] [-]  conn   server gracefully closed\n")
        print("# * + ================================ –- Belladonna ESP32 Python Server -– ================================ + * #\n")

if __name__ == "__main__":
    main() 
