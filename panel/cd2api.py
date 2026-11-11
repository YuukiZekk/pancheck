"""CD2 直连（gRPC，clouddrive.CloudDriveFileSrv）：只用于第二期执行时的「搬移」和必要的「列目录 / 建排查区子目录」。

接口定义取自官方 https://www.clouddrive2.com/api/clouddrive.proto（只用到下面几个方法，消息字段手写编解码，不需要生成代码）：
  GetApiTokenInfo(StringValue{1 value}) → TokenInfo{1 token, 2 rootDir, 3 TokenPermissions{1 allow_list, 4 allow_create_folder, 9 allow_move}}
  FindFileByPath(FindFileByPathRequest{1 parentPath, 2 path}) → CloudDriveFile
  GetSubFiles(ListSubFileRequest{1 path, 2 forceRefresh}) → stream SubFilesReply{1 repeated CloudDriveFile}
  CreateFolder(CreateFolderRequest{1 parentPath, 2 folderName}) → CreateFolderResult{1 folderCreated, 2 FileOperationResult}
  MoveFile(MoveFileRequest{1 theFilePaths, 2 destPath, 3 conflictPolicy, 4 moveAcrossClouds}) → FileOperationResult{1 success, 2 errorMessage, 3 resultFilePaths}
  CloudDriveFile: 2 name, 3 fullPathName, 4 size, 5 fileType(0 目录 / 1 文件), 30 isDirectory
鉴权：metadata  authorization: Bearer <token>。

红线：
  - 不调用任何删除 / 复制 / 写文件接口；MoveFile 固定 conflictPolicy=Skip、moveAcrossClouds=false（不覆盖、不跨云）。
  - 令牌只在内存里用：从 CD2 配置目录的 api_tokens.json 读（或环境变量 CD2_API_TOKEN），不写进配置、计划、日志。
  - 令牌要有 allow_list + allow_create_folder + allow_move，否则拒用（不需要也不接受删除权限去做任何事）。
"""
import json
import os

SVC = '/clouddrive.CloudDriveFileSrv/'
SKIP = 2


class CD2Error(Exception):
    pass


# ---------------- 极简 protobuf 编解码 ----------------
def _varint(n):
    out = bytearray()
    n &= (1 << 64) - 1
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def enc(fields):
    """fields: [(编号, 值)]；值 str/bytes → length-delimited，bool/int → varint。"""
    out = bytearray()
    for num, v in fields:
        if v is None:
            continue
        if isinstance(v, str):
            v = v.encode('utf-8')
        if isinstance(v, (bytes, bytearray)):
            out += _varint(num << 3 | 2) + _varint(len(v)) + v
        else:
            out += _varint(num << 3 | 0) + _varint(int(v))
    return bytes(out)


def dec(buf):
    """→ {编号: [值...]}；varint 为 int，length-delimited 为 bytes（嵌套消息再 dec）。"""
    out, i, n = {}, 0, len(buf)

    def rv(i):
        shift = val = 0
        while True:
            b = buf[i]
            i += 1
            val |= (b & 0x7F) << shift
            if not b & 0x80:
                return val, i
            shift += 7
    while i < n:
        key, i = rv(i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            v, i = rv(i)
        elif wt == 2:
            ln, i = rv(i)
            v = bytes(buf[i:i + ln])
            i += ln
        elif wt == 1:
            v = buf[i:i + 8]; i += 8
        elif wt == 5:
            v = buf[i:i + 4]; i += 4
        else:
            raise CD2Error('无法解析 CD2 返回（wire type %d）' % wt)
        out.setdefault(num, []).append(v)
    return out


def _s(d, k):
    v = d.get(k)
    return v[0].decode('utf-8', 'replace') if v else ''


def _i(d, k):
    v = d.get(k)
    return v[0] if v else 0


def file_info(b):
    d = dec(b)
    is_dir = bool(_i(d, 30)) or _i(d, 5) == 0
    return {'name': _s(d, 2), 'path': _s(d, 3), 'size': _i(d, 4), 'dir': is_dir}


# ---------------- 令牌 ----------------
def _token_candidates(cd2_config):
    env = os.environ.get('CD2_API_TOKEN', '').strip()
    if env:
        return [env]
    from . import sources as S
    f = S.find_file(cd2_config, 'api_tokens.json')
    if not f:
        return []
    try:
        data = json.load(open(f, encoding='utf-8'))
    except (OSError, ValueError):
        return []
    out = []          # [(令牌, 元数据或 None)]
    META = ('friendly_name', 'permissions', 'root_dir', 'rootDir', 'expires_in')

    def walk(x):
        if isinstance(x, dict):
            t = x.get('token') or x.get('Token')
            if isinstance(t, str) and t:
                out.append((t, x))
            for k, v in x.items():
                # CD2 真实格式：{ 令牌本体: {friendly_name, root_dir, permissions, ...} }（反馈 7 实测）
                if isinstance(k, str) and len(k) >= 8 and isinstance(v, dict) and any(m in v for m in META):
                    out.append((k, v))
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)

    def can_move(meta):
        perm = (meta or {}).get('permissions') or {}
        return bool(isinstance(perm, dict) and (perm.get('allow_move') or perm.get('allowMove')))
    # 元数据里写明能「移动」的排前面；最终以 connect() 里向 CD2 实查的权限为准
    out.sort(key=lambda t: not can_move(t[1]))
    return list(dict.fromkeys(t for t, _ in out))


# ---------------- 客户端 ----------------
class Client:
    def __init__(self, addr, token, timeout=60):
        import grpc
        self.grpc = grpc
        self.ch = grpc.insecure_channel(addr)
        self.md = [('authorization', 'Bearer ' + token)]
        self.timeout = timeout
        self.root = '/'
        self._dirs = set()          # 本客户端（一个批次）里确认存在 / 已建的目录，免得每次搬移都逐级查一遍

    def _call(self, method, payload, stream=False):
        g = self.grpc
        try:
            if stream:
                f = self.ch.unary_stream(SVC + method)
                return [b for b in f(payload, metadata=self.md, timeout=self.timeout)]
            return self.ch.unary_unary(SVC + method)(payload, metadata=self.md, timeout=self.timeout)
        except g.RpcError as e:
            code = e.code() if hasattr(e, 'code') else None
            if code == g.StatusCode.NOT_FOUND:
                raise FileNotFoundError(method)
            if code in (g.StatusCode.UNAUTHENTICATED, g.StatusCode.PERMISSION_DENIED):
                raise CD2Error('CD2 拒绝了令牌（%s）：令牌失效或权限不够' % code.name)
            if code == g.StatusCode.UNAVAILABLE:
                raise CD2Error('连不上 CD2 接口（%s）' % (e.details() if hasattr(e, 'details') else e))
            raise CD2Error('CD2 接口出错：%s %s' % (code.name if code else '', e.details() if hasattr(e, 'details') else e))

    def token_info(self, token):
        d = dec(self._call('GetApiTokenInfo', enc([(1, token)])))
        perm = dec(d[3][0]) if d.get(3) else {}
        return {'rootDir': _s(d, 2) or '/', 'allow_list': bool(_i(perm, 1)),
                'allow_create_folder': bool(_i(perm, 4)), 'allow_move': bool(_i(perm, 9)),
                'friendly_name': _s(d, 5)}

    # 面板用的是 CD2 的虚拟全路径（/115/...）；令牌若限定了 rootDir，要换成相对 rootDir 的路径
    def p(self, vp):
        if self.root in ('', '/'):
            return vp
        r = self.root.rstrip('/')
        if vp != r and not vp.startswith(r + '/'):
            raise CD2Error('路径 %s 不在令牌允许的根目录 %s 下' % (vp, r))
        return vp[len(r):] or '/'

    def stat(self, vp):
        parent, name = vp.rstrip('/').rsplit('/', 1)
        try:
            b = self._call('FindFileByPath', enc([(1, self.p(parent or '/')), (2, name)]))
        except FileNotFoundError:
            return None
        info = file_info(b)
        return info if info['name'] or info['path'] else None

    def exists(self, vp):
        return self.stat(vp) is not None

    def list(self, vp):
        out = []
        for b in self._call('GetSubFiles', enc([(1, self.p(vp)), (2, False)]), stream=True):
            for fb in dec(b).get(1, []):
                out.append(file_info(fb))
        return out

    def walk(self, vp, rel=''):
        """[(相对路径, 字节)]，递归。"""
        res = []
        for f in self.list(vp):
            r = (rel + '/' + f['name']) if rel else f['name']
            if f['dir']:
                res += self.walk(vp.rstrip('/') + '/' + f['name'], r)
            else:
                res.append((r, f['size']))
        return res

    def size(self, vp):
        st = self.stat(vp)
        if st is None:
            raise FileNotFoundError(vp)
        return sum(s for _, s in self.walk(vp)) if st['dir'] else st['size']

    def makedirs(self, vp):
        parts = [x for x in vp.strip('/').split('/') if x]
        cur = ''
        for name in parts:
            nxt = cur + '/' + name
            if nxt in self._dirs:
                cur = nxt
                continue
            if not self.exists(nxt):
                d = dec(self._call('CreateFolder', enc([(1, self.p(cur or '/')), (2, name)])))
                r = dec(d[2][0]) if d.get(2) else {}
                if r and not _i(r, 1) and not self.exists(nxt):
                    raise CD2Error('建目录失败：%s %s' % (nxt, _s(r, 2)))
            self._dirs.add(nxt)
            cur = nxt

    def move(self, src, dst):
        """把 src 移到 dst（同名，父目录不同）。CD2 的 MoveFile 是「移进 destPath 目录」，名字不变。"""
        if src.rsplit('/', 1)[1] != dst.rsplit('/', 1)[1]:
            raise CD2Error('直连搬移只支持同名移动')
        parent = dst.rsplit('/', 1)[0]
        self.makedirs(parent)
        d = dec(self._call('MoveFile', enc([(1, self.p(src)), (2, self.p(parent)), (3, SKIP), (4, False)])))
        if not _i(d, 1):
            raise CD2Error('CD2 搬移失败：%s' % (_s(d, 2) or '没有返回原因'))
        if not self.exists(dst) or self.exists(src):
            raise CD2Error('CD2 说搬成了，但实地核对不符（目标不在或源还在）')


def connect(cfg):
    """按设置拿一个可用的直连客户端；拿不到抛 CD2Error（说清楚差什么）。"""
    addr = (cfg.get('cd2_api_addr') or '').strip()
    if not addr:
        raise CD2Error('没填 CD2 接口地址（设置 → 高级 →「CD2 接口地址」，如 192.168.1.10:19798）')
    toks = _token_candidates(cfg.get('cd2_config'))
    if not toks:
        raise CD2Error('没找到 CD2 API 令牌：CD2 配置目录里没有 api_tokens.json（或没设 CD2_API_TOKEN）。'
                       '在 CD2 里建一个令牌，权限勾选「列目录 / 建文件夹 / 移动」')
    last = perm_err = None
    for t in toks:
        c = Client(addr, t)
        try:
            info = c.token_info(t)
        except FileNotFoundError:
            last = CD2Error('CD2 不认这个令牌（可能已删除或过期）')      # 换下一个试
            continue
        except CD2Error as e:
            last = e
            continue
        if info['allow_list'] and info['allow_create_folder'] and info['allow_move']:
            c.root = info['rootDir']
            c.name = info.get('friendly_name') or ''
            return c
        perm_err = CD2Error('令牌「%s」权限不够：需要 列目录 + 建文件夹 + 移动' % (info.get('friendly_name') or '未命名'))
    # 多个令牌都不行时，优先报「权限不够」（用户能直接去 CD2 里改），其次才是连不上 / 不认
    raise perm_err or last or CD2Error('CD2 令牌不可用')


def mode_status(cfg):
    """给界面看：直连可不可用、为什么（不含令牌内容）。"""
    try:
        c = connect(cfg)
        return {'ok': True, 'root': c.root, 'name': c.name}
    except CD2Error as e:
        return {'ok': False, 'error': str(e)}
    except Exception as e:
        return {'ok': False, 'error': 'CD2 直连出错：%s' % type(e).__name__}
