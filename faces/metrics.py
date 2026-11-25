"""Read only this container's cgroup. Never exposes processes, paths or environment."""
from pathlib import Path
import os
import threading
import time


def raw(root=Path('/sys/fs/cgroup')):
    def number(name):return int((root/name).read_text().strip())
    def values(name):return dict(line.split() for line in (root/name).read_text().splitlines())
    try:
        if (root/'cpu.stat').exists():
            cpu=int(values('cpu.stat')['usage_usec'])*1000;memory=number('memory.current');cache=int(values('memory.stat').get('inactive_file',0));limit=(root/'memory.max').read_text().strip();limit=int(limit) if limit!='max' else None
        else:
            cpu=number('cpuacct/cpuacct.usage');memory=number('memory/memory.usage_in_bytes');cache=int(values('memory/memory.stat').get('total_inactive_file',0));limit=number('memory/memory.limit_in_bytes')
            if limit>2**60:limit=None
        return dict(cpuNs=cpu,memory=max(0,memory-cache),limit=limit,scope='container')
    except (OSError,ValueError,KeyError):
        usage=os.times()
        try:rss=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        except (OSError,ValueError,IndexError):rss=None
        return dict(cpuNs=int((usage.user+usage.system)*1e9),memory=rss,limit=None,scope='process')


class Monitor:
    def __init__(self):self.lock=threading.Lock();self.previous=None

    def sample(self):
        with self.lock:
            now=time.monotonic();data=raw();prior=self.previous;self.previous=(now,data['cpuNs'])
            cpu=max(0,(data['cpuNs']-prior[1])/(now-prior[0])/1e7) if prior and now-prior[0]>.01 else None
            return dict(cpu=cpu,memory=data['memory'],limit=data['limit'],scope=data['scope'],cores=os.cpu_count() or 1)
