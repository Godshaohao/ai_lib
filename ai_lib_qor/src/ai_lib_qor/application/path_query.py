"""Shared read-only queries over the path contracts."""
import json
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import locked
from .minimal_file_index import build_index


class PathDataQuery:
    def __init__(self, work):
        self.work = work

    def index(self, vendor, library):
        folder = library_folder(self.work, vendor, library)
        path = folder/'file_index.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('文件索引不存在')
        with locked(folder):
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved != build_index(self.work, vendor, library):
                raise ValueError('文件索引过期或格式不兼容')
        return saved

    def get_check_context(self, vendor, library, revision, baseline=None):
        index = self.index(vendor, library)
        revisions = index['revisions']
        if revision not in revisions:
            raise ValueError('有效版本不存在')
        n = revisions.index(revision)
        if baseline is None:
            baseline = revisions[n-1] if n else None
        elif baseline not in revisions or revisions.index(baseline) >= n:
            raise ValueError('基线版本不存在或不是较早版本')
        members = []
        for view, group in index['views'].items():
            for path, history in group.items():
                matches = [row for row in history['effective'] if row['revision'] == revision]
                previous = [row for row in history['effective'] if row['revision'] == baseline]
                if matches:
                    members.append({'view':view, 'path':path, 'version':matches[0]['version'],
                                    'absolute_path':matches[0]['path'],
                                    'baseline':previous[0] if previous else None})
        return {'vendor':vendor, 'library':library, 'revision':revision,
                'baseline':baseline, 'members':members, 'index':index}
