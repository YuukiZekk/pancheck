"""演练用的假 CD2 gRPC 服务：在本地目录上实现 GetApiTokenInfo / FindFileByPath / GetSubFiles / CreateFolder / MoveFile
（字段编号同官方 clouddrive.proto），校验 Bearer 令牌与权限，并把每次调用记进日志，供演练核对。不实现任何删除接口。
用法：python tools/fake_cd2.py <根目录> <端口> <令牌> <日志文件> [权限: list,mkdir,move]"""
import json
import os
import sys
import time
from concurrent import futures

import grpc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from panel.cd2api import dec, enc   # noqa: E402

ROOT, PORT, TOKEN, LOG = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
PERMS = set((sys.argv[5] if len(sys.argv) > 5 else 'list,mkdir,move').split(','))
DIE_AFTER = int(sys.argv[6]) if len(sys.argv) > 6 else 0     # 演练：搬了 N 次后整个服务退出（模拟 CD2 中途断）
MOVES = [0]


def log(method, **kw):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(dict(m=method, t=time.time(), **kw), ensure_ascii=False) + '\n')


def real(vp):
    return os.path.join(ROOT, *[x for x in vp.split('/') if x])


def fileinfo(vp):
    r = real(vp)
    d = os.path.isdir(r)
    return enc([(2, vp.rstrip('/').rsplit('/', 1)[-1]), (3, vp), (4, 0 if d else os.path.getsize(r)), (5, 0 if d else 1), (30, d)])


def auth(ctx):
    if DIE_AFTER and MOVES[0] >= DIE_AFTER:
        ctx.abort(grpc.StatusCode.UNAVAILABLE, 'cd2 went away')      # 演练：模拟 CD2 中途断
    md = dict(ctx.invocation_metadata())
    if md.get('authorization') != 'Bearer ' + TOKEN:
        ctx.abort(grpc.StatusCode.UNAUTHENTICATED, 'bad token')


def need(ctx, p):
    if p not in PERMS:
        ctx.abort(grpc.StatusCode.PERMISSION_DENIED, 'no permission: ' + p)


def s(d, k):
    return d[k][0].decode('utf-8') if d.get(k) else ''


def GetApiTokenInfo(req, ctx):
    if DIE_AFTER and MOVES[0] >= DIE_AFTER:
        ctx.abort(grpc.StatusCode.UNAVAILABLE, 'cd2 went away')
    d = dec(req)
    log('GetApiTokenInfo')
    if s(d, 1) != TOKEN:
        ctx.abort(grpc.StatusCode.NOT_FOUND, 'unknown token')
    perm = enc([(1, 'list' in PERMS), (4, 'mkdir' in PERMS), (9, 'move' in PERMS)])
    return enc([(1, TOKEN), (2, '/'), (3, perm), (5, 'drill')])


def FindFileByPath(req, ctx):
    auth(ctx); need(ctx, 'list')
    d = dec(req)
    vp = s(d, 1).rstrip('/') + '/' + s(d, 2)
    log('FindFileByPath', path=vp)
    if not os.path.exists(real(vp)):
        ctx.abort(grpc.StatusCode.NOT_FOUND, 'not found')
    return fileinfo(vp)


def GetSubFiles(req, ctx):
    auth(ctx); need(ctx, 'list')
    vp = s(dec(req), 1)
    log('GetSubFiles', path=vp)
    r = real(vp)
    if not os.path.isdir(r):
        ctx.abort(grpc.StatusCode.NOT_FOUND, 'not found')
    yield enc([(1, fileinfo(vp.rstrip('/') + '/' + n)) for n in sorted(os.listdir(r))])


def CreateFolder(req, ctx):
    auth(ctx); need(ctx, 'mkdir')
    d = dec(req)
    vp = s(d, 1).rstrip('/') + '/' + s(d, 2)
    log('CreateFolder', path=vp)
    os.makedirs(real(vp), exist_ok=True)
    return enc([(1, fileinfo(vp)), (2, enc([(1, True)]))])


def MoveFile(req, ctx):
    auth(ctx); need(ctx, 'move')
    d = dec(req)
    srcs = [x.decode('utf-8') for x in d.get(1, [])]
    dest = s(d, 2)
    policy = d.get(3, [0])[0]
    log('MoveFile', src=srcs, dest=dest, policy=policy, across=d.get(4, [0])[0])
    out = []
    for vp in srcs:
        dst = dest.rstrip('/') + '/' + vp.rsplit('/', 1)[1]
        if os.path.exists(real(dst)):
            return enc([(1, False), (2, 'target exists (policy %d)' % policy)])
        os.rename(real(vp), real(dst))
        out.append(dst)
    MOVES[0] += 1
    return enc([(1, True)] + [(3, x) for x in out])


ident = lambda b: b
handlers = {
    'GetApiTokenInfo': grpc.unary_unary_rpc_method_handler(GetApiTokenInfo, ident, ident),
    'FindFileByPath': grpc.unary_unary_rpc_method_handler(FindFileByPath, ident, ident),
    'GetSubFiles': grpc.unary_stream_rpc_method_handler(GetSubFiles, ident, ident),
    'CreateFolder': grpc.unary_unary_rpc_method_handler(CreateFolder, ident, ident),
    'MoveFile': grpc.unary_unary_rpc_method_handler(MoveFile, ident, ident),
}
server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('clouddrive.CloudDriveFileSrv', handlers),))
server.add_insecure_port('127.0.0.1:%d' % PORT)
server.start()
print('fake cd2 on', PORT, flush=True)
server.wait_for_termination()
