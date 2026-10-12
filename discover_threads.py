import os
import glob
import re
from pathlib import Path
from leveldb_reader import read_sstable, read_leveldb_log

def find_teams_leveldb_dir():
    """Busca dinámicamente el directorio de LevelDB de Teams con fallback a la ruta estándar."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    app_data = os.environ.get("APPDATA", "")

    search_patterns = [
        # 1. New Teams (MSIX / Store) - cualquier perfil (tfw, tfl, default, etc.)
        os.path.join(local_app_data, "Packages", "*Teams*", "LocalCache", "Microsoft", "MSTeams", "EBWebView", "*", "IndexedDB", "https_teams.microsoft.com_*.indexeddb.leveldb"),
        # 2. New Teams (Instalación Standalone / No MSIX)
        os.path.join(local_app_data, "Microsoft", "MSTeams", "EBWebView", "*", "IndexedDB", "https_teams.microsoft.com_*.indexeddb.leveldb"),
        # 3. Teams Web (Microsoft Edge)
        os.path.join(local_app_data, "Microsoft", "Edge", "User Data", "*", "IndexedDB", "https_teams.microsoft.com_*.indexeddb.leveldb"),
        # 4. Teams Clásico (Electron)
        os.path.join(app_data, "Microsoft", "Teams", "IndexedDB", "https_teams.microsoft.com_*.indexeddb.leveldb")
    ]

    for pattern in search_patterns:
        matches = glob.glob(pattern)
        if matches:
            # Ordenar por fecha de modificación para usar la base de datos más reciente
            matches.sort(key=os.path.getmtime, reverse=True)
            return Path(matches[0])

    # Fallback a la ruta estándar de New Teams
    return Path(local_app_data) / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfw" / "IndexedDB" / "https_teams.microsoft.com_0.indexeddb.leveldb"

def main():
    leveldb_dir = find_teams_leveldb_dir()
    print(f"[*] Usando directorio de base de datos: {leveldb_dir}")

    if not leveldb_dir.exists():
        print(f"[!] No se encontró el directorio de Teams en: {leveldb_dir}")
        return

    all_kvs = []
    for ldb in sorted(leveldb_dir.glob("*.ldb")):
        all_kvs.extend(read_sstable(ldb))
    for logf in sorted(leveldb_dir.glob("*.log")):
        all_kvs.extend(read_leveldb_log(logf))

    threads = {}

    for k, v in all_kvs:
        m_topic = re.findall(rb'(?:topic|sourceThreadTopic)\"[\x00-\x20]*\"?([^\x00-\x1f\"\\]{2,100})', v)
        m_tid = re.findall(rb'(19:[a-zA-Z0-9_\-\.]+@thread\.v2)', v)

        if m_tid:
            for tid in set(m_tid):
                tid_str = tid.decode('ascii')
                if tid_str not in threads:
                    threads[tid_str] = set()
                for top in m_topic:
                    t_clean = top.decode('utf-8', errors='ignore').strip()
                    if len(t_clean) > 2 and not t_clean.startswith('http'):
                        threads[tid_str].add(t_clean)

    print(f"\nSe encontraron {len(threads)} hilos únicos en la caché:")
    for tid, topics in list(threads.items())[:20]:
        topic_name = ", ".join(topics) if topics else "(Chat privado o sin título)"
        print(f"- {tid}: {topic_name}")

if __name__ == "__main__":
    main()
