import os
import re
from pathlib import Path
from leveldb_reader import read_sstable, read_leveldb_log

leveldb_dir = Path(os.environ["LOCALAPPDATA"]) / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams" / "EBWebView" / "WV2Profile_tfw" / "IndexedDB" / "https_teams.microsoft.com_0.indexeddb.leveldb"

all_kvs = []
for ldb in sorted(leveldb_dir.glob("*.ldb")):
    all_kvs.extend(read_sstable(ldb))
for logf in sorted(leveldb_dir.glob("*.log")):
    all_kvs.extend(read_leveldb_log(logf))

threads = {}

for k, v in all_kvs:
    # Match thread definitions: topic / sourceThreadTopic
    # Example: topic" <varint> Name ... teamId" 19:...@thread.v2 or id" 19:...@thread.v2
    # In V8: topic" <name> ... id" <thread_id>
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

print(f"Found {len(threads)} unique threads in cache:")
for tid, topics in list(threads.items())[:15]:
    topic_name = ", ".join(topics) if topics else "(Chat privado o sin título)"
    print(f"- {tid}: {topic_name}")
