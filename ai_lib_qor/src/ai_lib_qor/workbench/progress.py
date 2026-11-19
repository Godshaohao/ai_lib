"""Ephemeral, session-bound progress for one local workbench process."""
from copy import deepcopy
from threading import Lock
from time import monotonic


class OperationProgress:
    def __init__(self):
        self._lock=Lock()
        self._items={}

    def start(self,ident,owner,label):
        with self._lock:
            now=monotonic()
            self._items={k:v for k,v in self._items.items() if v['data']['state']=='RUNNING' or now-v['updated']<3600}
            if ident in self._items:return False
            self._items[ident]={'owner':owner,'updated':now,'data':{'state':'RUNNING','label':label,
                'message':'正在准备操作','completed':None,'total':None,'events':[]}}
            return True

    def update(self,ident,message,completed=None,total=None):
        with self._lock:
            item=self._items.get(ident)
            if not item or item['data']['state']!='RUNNING':return
            data=item['data'];data['message']=str(message)
            if completed is not None:data['completed']=completed
            if total is not None:data['total']=total
            if not data['events'] or data['events'][-1]!=str(message):
                data['events'].append(str(message));data['events']=data['events'][-50:]
            item['updated']=monotonic()

    def finish(self,ident,state,message):
        with self._lock:
            item=self._items.get(ident)
            if not item or item['data']['state']!='RUNNING':return
            data=item['data'];data['state']=state;data['message']=str(message)
            data['events'].append(str(message));data['events']=data['events'][-50:]
            item['updated']=monotonic()

    def get(self,ident,owner):
        with self._lock:
            item=self._items.get(ident)
            if not item or item['owner']!=owner:return None
            return deepcopy(item['data'])
