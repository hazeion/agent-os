"""Fixed credential-free inspection worker. Never launches observed work."""

import json
import math
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from mentat.project_scope_readback import _inspect_reference


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:
            raise ValueError()
        result[key]=value
    return result


def main():
    if sys.platform!='linux':
        return 1
    import resource
    for name,maximum in ((resource.RLIMIT_AS,256*1024*1024),(resource.RLIMIT_CPU,8),
                         (resource.RLIMIT_NOFILE,64),(resource.RLIMIT_CORE,0)):
        _,hard=resource.getrlimit(name)
        bound=maximum if hard==resource.RLIM_INFINITY else min(maximum,hard)
        resource.setrlimit(name,(bound,bound))
    while True:
        line=sys.stdin.buffer.readline(4097)
        if not line:
            return 0
        identifier=None
        try:
            if len(line)>4096 or not line.endswith(b'\n'):
                raise ValueError()
            outer=json.loads(line,object_pairs_hook=_pairs)
            if (not isinstance(outer,dict) or set(outer)!={'id','kind','url'} or outer['kind']!='scope_readback'
                    or not isinstance(outer['id'],str) or re.fullmatch('[0-9a-f]{32}',outer['id']) is None):
                raise ValueError()
            identifier=outer['id']
            reference=json.loads(outer['url'],object_pairs_hook=_pairs)
            if (not isinstance(reference,dict) or set(reference)!={'root','run','generation','revision','deadline'}
                    or not isinstance(reference['root'],str) or not Path(reference['root']).is_absolute()
                    or len(reference['root'].encode())>1024
                    or not isinstance(reference['run'],str) or re.fullmatch(r'run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}',reference['run']) is None
                    or not isinstance(reference['generation'],str) or re.fullmatch('[0-9a-f]{32}',reference['generation']) is None
                    or type(reference['revision']) is not int or not 1<=reference['revision']<=5
                    or type(reference['deadline']) not in (int,float) or not math.isfinite(reference['deadline'])
                    or not time.monotonic()<reference['deadline']<=time.monotonic()+10):
                raise ValueError()
            observed=_inspect_reference(Path(reference['root']),reference['run'],reference['generation'],reference['revision'],reference['deadline'])
            value={'state':observed.state,'reason':observed.reason,'sampled_at':observed.sampled_at}
        except Exception:
            value={'state':'unknown','reason':'unverified','sampled_at':time.time()}
        raw=json.dumps({'id':identifier,'type':'result','result':value},separators=(',',':')).encode()
        if len(raw)>4096:
            return 1
        sys.stdout.buffer.write(raw+b'\n')
        sys.stdout.buffer.flush()


if __name__=='__main__':
    raise SystemExit(main())
