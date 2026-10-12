import os
import sys
import struct
import re
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from leveldb_reader import read_sstable, read_leveldb_log, read_varint

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
EXAMPLE_CONFIG_FILE = BASE_DIR / "config.json.example"

def load_config():
    for cfg_path in [CONFIG_FILE, EXAMPLE_CONFIG_FILE]:
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {
        "default_topic": None,
        "default_thread_id": None,
        "output_base_dir": "extracted_chat"
    }

def get_v8_string(data, pos):
    """Reads a V8 serialized string at pos. Returns (string, new_pos)."""
    if pos >= len(data):
        return None, pos
    tag = data[pos]
    pos += 1
    if tag == ord('"'):  # One-byte ASCII/Latin1/UTF-8
        length, pos = read_varint(data, pos)
        val = data[pos : pos + length].decode('utf-8', errors='ignore')
        pos += length
        return val, pos
    elif tag == ord('c'):  # Two-byte UTF-16LE
        length_bytes, pos = read_varint(data, pos)
        val = data[pos : pos + length_bytes].decode('utf-16le', errors='ignore')
        pos += length_bytes
        return val, pos
    return None, pos

def clean_html_content(raw_html):
    """Cleans HTML tags into readable markdown/plain text while keeping mentions and links."""
    if not raw_html:
        return ""
    text = raw_html
    # Handle reply blockquote
    text = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', r'> [Cita: \1]\n', text, flags=re.DOTALL)
    # Mentions
    text = re.sub(r'<span[^>]*itemtype="http://schema\.skype\.com/Mention"[^>]*>(.*?)</span>', r'@\1', text)
    # Line breaks and paragraphs
    text = re.sub(r'</p>\s*<p>', '\n', text)
    text = re.sub(r'<br\s*/?>', '\n', text)
    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Unescape HTML entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    # Collapse multiple whitespace
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
    return '\n'.join([line for line in lines if line]).strip()

def extract_messages_from_record(val, target_thread_bytes):
    """
    Extracts message entries from an IndexedDB LevelDB value for the specified thread.
    """
    if target_thread_bytes not in val:
        return []

    messages = []
    content_matches = [m.start() for m in re.finditer(rb'\"content[\"c]', val)]
    if not content_matches:
        content_matches = [m.start() for m in re.finditer(rb'content[\"c]', val)]

    for c_pos in content_matches:
        w_start = max(0, c_pos - 1200)
        w_end = min(len(val), c_pos + 4000)
        win = val[w_start:w_end]

        tag_pos = c_pos + len(b'content')
        if val[c_pos:c_pos+1] == b'"':
            tag_pos += 1
        
        content_raw, _ = get_v8_string(val, tag_pos)
        if not content_raw:
            m_html = re.search(rb'(<p>.*?</p>)', val[c_pos:w_end])
            if m_html:
                content_raw = m_html.group(1).decode('utf-8', errors='ignore')
            else:
                continue

        content_raw = content_raw.strip()
        if not content_raw or content_raw in ["contentHash", "Text", "RichText/Html", "TEAMS"]:
            continue

        # Extract Author
        author = "Desconocido"
        for author_field in [b'imDisplayName', b'fromDisplayNameInToken']:
            p_auth = win.find(author_field)
            if p_auth != -1:
                auth_str, _ = get_v8_string(win, p_auth + len(author_field))
                if auth_str and len(auth_str.strip()) > 1:
                    author = auth_str.strip()
                    break

        # Extract Timestamp
        ts = None
        for time_key in [b'originalArrivalTime', b'clientArrivalTime', b'composeTime']:
            p_time = win.find(time_key)
            if p_time != -1:
                t_pos = p_time + len(time_key)
                if t_pos < len(win) and win[t_pos] == ord('N') and t_pos + 9 <= len(win):
                    val_dbl = struct.unpack('<d', win[t_pos+1 : t_pos+9])[0]
                    if 1.5e12 < val_dbl < 2.5e12:
                        ts = datetime.fromtimestamp(val_dbl / 1000.0, timezone.utc)
                        break

        # Extract Message ID
        msg_id = ""
        m_id = re.search(rb'id\"[\x00-\x20]*\"[\x00-\x20]*(\d{13})', win)
        if m_id:
            msg_id = m_id.group(1).decode('ascii')

        clean_text = clean_html_content(content_raw)
        if not clean_text:
            continue

        messages.append({
            'id': msg_id,
            'author': author,
            'timestamp': ts,
            'raw_content': content_raw,
            'content': clean_text
        })

    return messages

def discover_available_threads(all_kvs):
    """Discovers all conversations and groups present in the cache, including participants."""
    threads = {}
    for k, v in all_kvs:
        m_tid = re.findall(rb'(19:[a-zA-Z0-9_\-\.]+@thread\.v2)', v)
        if not m_tid:
            continue
        m_topic = re.findall(rb'(?:topic|sourceThreadTopic)\"[\x00-\x20]*\"?([^\x00-\x1f\"\\]{2,120})', v)
        m_auth = re.findall(rb'(?:imDisplayName|fromDisplayNameInToken)\"[\x00-\x20]*\"?([A-Za-z\s,\(\)\.\'\-\_]{3,40})\"', v)

        for tid in set(m_tid):
            tid_str = tid.decode('ascii')
            if tid_str not in threads:
                threads[tid_str] = {
                    'topics': set(),
                    'participants': set(),
                    'mentions': 0
                }
            threads[tid_str]['mentions'] += 1
            for top in m_topic:
                t_clean = top.decode('utf-8', errors='ignore').strip()
                if len(t_clean) > 2 and not t_clean.startswith(('http', 'TEAMS')):
                    threads[tid_str]['topics'].add(t_clean)
            for a in m_auth:
                a_clean = a.decode('utf-8', errors='ignore').strip()
                if len(a_clean) > 2 and not a_clean.startswith(('http', 'TEAMS', 'true', 'false', 'valid', 'message')):
                    threads[tid_str]['participants'].add(a_clean)
    return threads

def sanitize_filename(name):
    clean = re.sub(r'[^a-zA-Z0-9_\-]+', '_', name).strip('_')
    return clean if clean else "conversacion"

def read_teams_leveldb():
    leveldb_dir = Path(os.environ["LOCALAPPDATA"]) / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfw" / "IndexedDB" / "https_teams.microsoft.com_0.indexeddb.leveldb"
    if not leveldb_dir.exists():
        raise FileNotFoundError(f"No se encontró el directorio de LevelDB en: {leveldb_dir}")

    all_kvs = []
    for ldb in sorted(leveldb_dir.glob("*.ldb")):
        all_kvs.extend(read_sstable(ldb))

    for logf in sorted(leveldb_dir.glob("*.log")):
        all_kvs.extend(read_leveldb_log(logf))

    return all_kvs

def main():
    parser = argparse.ArgumentParser(description="Extractor y analizador de conversaciones de Microsoft Teams desde la caché local.")
    parser.add_argument("--list", action="store_true", help="Lista todas las conversaciones y grupos encontrados en la caché local.")
    parser.add_argument("--topic", type=str, default=None, help="Nombre o palabra clave del grupo/conversación a extraer (ej: 'Proyecto Cloud').")
    parser.add_argument("--id", type=str, default=None, help="ID exacto del hilo (ej: '19:abcdef0123456789abcdef0123456789@thread.v2').")
    parser.add_argument("--output", type=str, default=None, help="Directorio de destino donde guardar los reportes.")
    args = parser.parse_args()

    config = load_config()

    print("[*] Leyendo datos de la base de datos de Teams...")
    all_kvs = read_teams_leveldb()
    print(f"[*] Registros cargados desde LevelDB: {len(all_kvs)}")

    threads_discovered = discover_available_threads(all_kvs)

    if args.list:
        print("\n" + "="*80)
        print(f"{'CONVERSACIONES / GRUPOS EN LA CACHÉ':^80}")
        print("="*80)
        sorted_threads = sorted(threads_discovered.items(), key=lambda item: item[1]['mentions'], reverse=True)
        for tid, data in sorted_threads:
            topic_name = " / ".join(data['topics']) if data['topics'] else "(Chat privado sin título)"
            print(f"• Tópico       : {topic_name}")
            print(f"  ID           : {tid}")
            if data['participants']:
                print(f"  Participantes: {', '.join(sorted(data['participants'])[:4])}")
            print(f"  Eventos      : {data['mentions']}")
            print("-" * 80)
        print(f"\nTotal: {len(threads_discovered)} hilos encontrados.")
        print("Usa: python parse_teams_chat.py --topic \"<Nombre>\" o --id \"<ID>\" para extraer cualquiera de ellos.\n")
        return

    # Determine which conversation to extract
    target_thread_id = None
    target_topic_name = None

    if args.id:
        target_thread_id = args.id
        if target_thread_id in threads_discovered and threads_discovered[target_thread_id]['topics']:
            target_topic_name = list(threads_discovered[target_thread_id]['topics'])[0]
        else:
            target_topic_name = target_thread_id
    elif args.topic:
        query = args.topic.lower()
        matched = []
        for tid, data in threads_discovered.items():
            for t in data['topics']:
                if query in t.lower():
                    matched.append((tid, t))
        if not matched:
            print(f"\n[!] No se encontró ningún grupo que coincida con '{args.topic}'.")
            print("Ejecuta 'python parse_teams_chat.py --list' para ver todos los disponibles.")
            sys.exit(1)
        target_thread_id, target_topic_name = matched[0]
        if len(matched) > 1:
            print(f"[*] Se encontraron {len(matched)} coincidencias. Seleccionando: '{target_topic_name}' ({target_thread_id})")
    else:
        # Use defaults from config
        default_topic = config.get("default_topic")
        default_tid = config.get("default_thread_id")
        if default_tid and default_tid in threads_discovered:
            target_thread_id = default_tid
            target_topic_name = default_topic or default_tid
        elif default_topic:
            for tid, data in threads_discovered.items():
                for t in data['topics']:
                    if default_topic.lower() in t.lower():
                        target_thread_id = tid
                        target_topic_name = t
                        break
                if target_thread_id:
                    break

    if not target_thread_id:
        print("[!] No se pudo determinar el hilo a extraer. Especifica --topic o --id.")
        sys.exit(1)

    print(f"\n[*] Extrayendo conversación: '{target_topic_name}'")
    print(f"[*] Thread ID: {target_thread_id}")

    # Extract short ID for byte matching
    short_id = target_thread_id.replace("19:", "").replace("@thread.v2", "").encode('ascii')

    extracted = {}
    for k, v in all_kvs:
        msgs = extract_messages_from_record(v, short_id)
        for m in msgs:
            dedupe_key = m['id'] if m['id'] else f"{m['author']}_{m['content'][:40]}"
            if dedupe_key not in extracted or (m['timestamp'] and not extracted[dedupe_key]['timestamp']) or (m['author'] != 'Desconocido' and extracted[dedupe_key]['author'] == 'Desconocido'):
                extracted[dedupe_key] = m

    messages = list(extracted.values())
    messages.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min.replace(tzinfo=timezone.utc))

    print(f"[*] Mensajes únicos extraídos: {len(messages)}")

    if not messages:
        print("[!] No se encontraron mensajes en caché para este hilo.")
        return

    # PR Pattern detector
    pr_regex = re.compile(r'(?:github\.com/[^\s]+/pull/|gitlab\.com/[^\s]+/merge_requests/|pull\s*request\s*#?|PR\s*#?)(\d+)', re.IGNORECASE)

    by_day = defaultdict(list)
    by_user = defaultdict(list)
    by_pr = defaultdict(list)

    for m in messages:
        dt = m['timestamp']
        day_str = dt.strftime('%Y-%m-%d') if dt else "Fecha Desconocida"
        author = m['author']
        content = m['content']

        by_day[day_str].append(m)
        by_user[author].append(m)

        pr_matches = pr_regex.findall(content)
        if pr_matches:
            for pr_id in set(pr_matches):
                by_pr[f"PR #{pr_id}"].append(m)
        elif "pull request" in content.lower() or re.search(r'\bpr\b', content, re.IGNORECASE):
            by_pr["Discusión general de PRs (sin ID explícito)"].append(m)
        else:
            by_pr["Otras consultas y operaciones"].append(m)

    # Destination folder
    base_out = Path(args.output if args.output else config.get("output_base_dir", "extracted_chat"))
    folder_name = sanitize_filename(target_topic_name)
    output_dir = base_out if len(threads_discovered) == 1 else (base_out / folder_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = output_dir / f"chat_{folder_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json_dump_data = [
            {
                'id': m['id'],
                'timestamp': m['timestamp'].isoformat() if m['timestamp'] else None,
                'author': m['author'],
                'content': m['content']
            }
            for m in messages
        ]
        json.dump(json_dump_data, f, ensure_ascii=False, indent=2)

    # Save Report by Day
    day_report_path = output_dir / "reporte_por_dia.md"
    with open(day_report_path, "w", encoding="utf-8") as f:
        f.write(f"# Conversación: {target_topic_name}\n")
        f.write("## Organizado por Día\n\n")
        for day in sorted(by_day.keys()):
            f.write(f"### 📅 {day} ({len(by_day[day])} mensajes)\n\n")
            for m in by_day[day]:
                ts_str = m['timestamp'].strftime('%H:%M:%S UTC') if m['timestamp'] else "??"
                f.write(f"- **[{ts_str}] {m['author']}**:\n")
                for line in m['content'].split('\n'):
                    f.write(f"  {line}\n")
                f.write("\n")

    # Save Report by User
    user_report_path = output_dir / "reporte_por_usuario.md"
    with open(user_report_path, "w", encoding="utf-8") as f:
        f.write(f"# Conversación: {target_topic_name}\n")
        f.write("## Organizado por Usuario\n\n")
        sorted_users = sorted(by_user.keys(), key=lambda u: len(by_user[u]), reverse=True)
        for user in sorted_users:
            f.write(f"### 👤 {user} ({len(by_user[user])} mensajes)\n\n")
            for m in by_user[user]:
                ts_str = m['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC') if m['timestamp'] else "Fecha desconocida"
                f.write(f"- **[{ts_str}]**:\n")
                for line in m['content'].split('\n'):
                    f.write(f"  {line}\n")
                f.write("\n")

    # Save Report by PR / Topic
    pr_report_path = output_dir / "reporte_por_pull_request.md"
    with open(pr_report_path, "w", encoding="utf-8") as f:
        f.write(f"# Conversación: {target_topic_name}\n")
        f.write("## Organizado por Pull Request y Temas\n\n")
        def pr_sort_key(k):
            m = re.search(r'\d+', k)
            return (0, int(m.group(0))) if m else (1, k)

        sorted_pr_keys = sorted(by_pr.keys(), key=pr_sort_key)
        for pr_key in sorted_pr_keys:
            f.write(f"### 🔀 {pr_key} ({len(by_pr[pr_key])} mensajes)\n\n")
            for m in by_pr[pr_key]:
                ts_str = m['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC') if m['timestamp'] else "Fecha desconocida"
                f.write(f"- **[{ts_str}] {m['author']}**:\n")
                for line in m['content'].split('\n'):
                    f.write(f"  {line}\n")
                f.write("\n")

    print(f"\n[OK] Informes generados con éxito en {output_dir}:")
    print(f" - {json_path.name}")
    print(f" - {day_report_path.name}")
    print(f" - {user_report_path.name}")
    print(f" - {pr_report_path.name}")

if __name__ == "__main__":
    main()
