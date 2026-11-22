"""Shared read-only queries over the path contracts."""
import json
from ai_lib_qor.sources.layout import library_folder
from ai_lib_qor.versions.store import locked
from .minimal_file_index import build_index, index_manifest_matches, read_manifest


class PathDataQuery:
    def __init__(self, work):
        self.work = work

    def index(self, vendor, library, *, verify='manifest'):
        folder = library_folder(self.work, vendor, library)
        path = folder/'file_index.json'
        if path.is_symlink() or not path.is_file():
            raise ValueError('文件索引不存在')
        with locked(folder):
            if verify == 'manifest':
                matched, _ = index_manifest_matches(self.work, vendor, library)
                if matched:
                    return json.loads(path.read_text(encoding='utf-8'))
            saved = json.loads(path.read_text(encoding='utf-8'))
            try:
                current = build_index(self.work, vendor, library)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ValueError('文件索引过期或来源无效: ' + str(exc)) from exc
            if saved != current:
                raise ValueError('文件索引过期或格式不兼容')
        return saved

    def index_status(self, vendor, library):
        folder = library_folder(self.work, vendor, library)
        path = folder/'file_index.json'
        if path.is_symlink() or not path.is_file():
            return {'status': 'MISSING', 'refreshed_at': None}
        matched, manifest = index_manifest_matches(self.work, vendor, library)
        if matched:
            return {'status': 'FRESH', 'refreshed_at': manifest.get('refreshed_at')}
        return {'status': 'UNVERIFIED' if manifest is None else 'STALE',
                'refreshed_at': manifest.get('refreshed_at') if manifest else None}

    def get_check_context(self, vendor, library, revision, baseline=None):
        index = self.index(vendor, library)
        revisions = index['revisions']
        if revision not in revisions:
            raise ValueError('有效版本不存在')
        n = revisions.index(revision)
        if baseline is None:
            baseline = revisions[n-1] if n else None
        elif baseline == '__none__':
            baseline = None
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

    def file(self,vendor,library,view,path,*,revision=None,version=None):
        from .minimal_file_index import _relative
        if revision is not None and version is not None:raise ValueError('只能指定 Effective 版本或交付版本')
        index=self.index(vendor,library)
        row=index['views'].get(view,{}).get(_relative(path))
        if row is None:raise ValueError('文件不在索引中')
        result={'vendor':vendor,'library':library,'view':view,'path':path,**row}
        if revision is not None:
            if revision not in index['revisions']:raise ValueError('有效版本不存在')
            matches=[r for r in row['effective'] if r['revision']==revision]
            if len(matches)>1:raise ValueError('有效版本来源不唯一')
            result['effective']=matches[0] if matches else None
        if version is not None:
            order=[item['version'] for item in index['deliveries']]
            if version not in order:raise ValueError('交付版本不存在')
            rank={v:i for i,v in enumerate(order)};at=rank[version]
            candidates=[item for item in row['raw'] if rank[item['version']]<=at]
            result['as_of']=candidates[-1] if candidates else None
        return result
