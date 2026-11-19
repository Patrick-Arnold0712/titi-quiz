"""局域网访问辅助：给「手机扫码打开」提供后端支持。

绑 127.0.0.1 时只有本机能用；改成 0.0.0.0 之后同一 WiFi 下的手机也能打开。
但用户得知道该输哪个地址，所以这里把本机可能可用的局域网地址列出来，
顺手生成二维码 —— 手机上扫码比手输 IP 靠谱得多。

注意：地址是从本机网卡读的，能不能真的连通还取决于
1. Windows 防火墙有没有放行（见 tools/allow_lan_firewall.ps1）
2. 路由器/校园网有没有开「客户端隔离」—— 开了的话同 WiFi 也互相连不通
所以接口同时返回这两条提示，前端要如实显示。
"""

from __future__ import annotations

import socket
from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/net", tags=["net"])

# 这些前缀不属于「局域网邻居能访问」的地址，列出来只会让人白试
SKIP_PREFIXES = ("127.", "169.254.")


def _local_ips() -> list[str]:
    """本机所有可用的 IPv4 地址（按可用性排序：私网地址排前面）。"""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    # 补一个「对外默认路由用的地址」——有些机器 getaddrinfo 拿不全
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    def rank(ip: str) -> tuple:
        a = ip_address(ip)
        private = a.is_private
        return (0 if private else 1, ip)

    return sorted((i for i in ips if not i.startswith(SKIP_PREFIXES)), key=rank)


def _bind_covers_lan(port: int) -> bool:
    """服务到底绑在哪？

    不能看「这次请求从哪个地址进来」—— 用户在电脑上用 127.0.0.1 打开，
    请求 host 就是 127.0.0.1，但服务可能其实绑在 0.0.0.0 上。
    判断依据应该是**监听地址**本身。

    这里用一个 TCP 连自己局域网地址的办法：能连上就说明 bind 覆盖了局域网网卡。
    （只绑 127.0.0.1 时，连 172.x 会立刻被拒。）
    """
    import socket

    for ip in _local_ips():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            s.connect((ip, port))
            return True
        except OSError:
            continue
        finally:
            s.close()
    return False


@router.get("/info")
def net_info(request: Request):
    """返回本机的局域网访问地址；如果当前只绑了 127.0.0.1，则如实说明。"""
    port = request.url.port or 80
    host = request.url.hostname or ""
    bound_local_only = not _bind_covers_lan(port)

    urls = [f"http://{ip}:{port}" for ip in _local_ips()]
    return {
        "port": port,
        # 当前这次请求是走哪个地址进来的
        "current_host": host,
        # 只绑回环时，局域网地址即使列出来也访问不到
        "lan_enabled": not bound_local_only,
        "urls": urls if not bound_local_only else [],
        "hint_bound_local_only": (
            "后端当前只监听 127.0.0.1，手机访问不到。"
            "用 tools/start_server.ps1 -Lan 重启即可（绑 0.0.0.0）。"
        ) if bound_local_only else "",
        "hint_firewall": (
            "手机打不开多半是 Windows 防火墙拦了入站。"
            "以管理员身份运行 tools/allow_lan_firewall.ps1 放行一次。"
        ),
        "hint_isolation": (
            "如果防火墙已放行还是打不开，可能是路由器/校园网开了「客户端隔离」，"
            "同一 WiFi 下的设备互相不通。换个热点或家用路由器试试。"
        ),
    }


@router.get("/qr")
def net_qr(url: str, scale: int = 4):
    """把任意地址渲染成 SVG 二维码。前端直接 <img src> 用。"""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url 必须是 http(s) 地址")
    if not (2 <= scale <= 12):
        raise HTTPException(400, "scale 取值 2~12")
    try:
        import segno  # 延迟导入：没装这库也不该让整个服务起不来
    except ImportError:
        raise HTTPException(503, "缺少 segno 依赖，无法生成二维码：pip install segno")

    qr = segno.make(url, error="m")
    import io
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, dark="#0b5c42", light="#ffffff", border=2)
    return Response(content=buf.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})
