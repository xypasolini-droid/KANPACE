#!/usr/bin/env python3
"""Consistent SQLite backup + immutable uploaded originals, stored locally."""
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import zipfile

BASE = Path(__file__).resolve().parent

def main():
    source = BASE / 'data' / 'cabinet-flow.sqlite3'
    if not source.exists():
        raise SystemExit('尚未找到本地数据库。请先启动KANPACE。')
    output = BASE / 'backups'
    output.mkdir(exist_ok=True)
    target = output / ('cabinet-flow-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.zip')
    with tempfile.TemporaryDirectory() as temp:
        snapshot = Path(temp) / source.name
        src = sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True)
        dest = sqlite3.connect(snapshot)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot, 'data/' + snapshot.name)
            for file in (BASE / 'data' / 'uploads').glob('*.source'):
                z.write(file, 'data/uploads/' + file.name)
    print('本地备份已保存：' + str(target))
    print('恢复时先停止服务，再把备份中的 data 文件夹复制到一个新的KANPACE目录，保留旧目录以便回退。')

if __name__ == '__main__':
    main()
