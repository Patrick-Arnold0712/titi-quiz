"""移动端布局自检：在指定宽度下逐页检查有没有横向溢出。

## 为什么需要这个

headless Edge 的窗口有**最小宽度**（本机实测 504px）。
用 `--window-size=390` 截图，得到的是被裁切过的 390px 图，
看起来像是「页面溢出」，其实是假象 —— 我一开始就被这个骗了一次。

所以这里不靠截图，改成用 iframe 把应用塞进一个精确宽度的视口，
再量 `scrollWidth` 和每个元素的 `getBoundingClientRect().right`。

## 用法

    .venv\\Scripts\\python.exe tools/check_mobile_layout.py
    .venv\\Scripts\\python.exe tools/check_mobile_layout.py --widths 320,390,414

接新科目、加新页面之后都该跑一遍。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "backend" / "static"
PROBE = STATIC / "_probe.html"
EDGE = Path(r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe")

# 新增页面记得往这里加一条 —— 这个自检唯一的价值就是「逐页覆盖」，
# 漏了页面它就只是给人一个「都通过了」的错觉。
DEFAULT_ROUTES = ["overview", "practice", "papers", "wrong", "graph", "advice",
                  "subjective", "bits", "library", "exam/17"]

PROBE_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>pending</title>
<style>body{margin:0;background:#333}iframe{border:0;background:#fff;display:block}</style>
</head><body><div id="wrap"></div>
<script>
var W = parseInt((location.search.match(/w=(\\d+)/)||[])[1] || '390', 10);
var target = decodeURIComponent(location.hash.slice(1) || '/overview');
try { localStorage.setItem('ttk.subject', '__SUBJECT__'); } catch (e) {}
var f = document.createElement('iframe');
f.style.width = W + 'px'; f.style.height = '2000px';
document.getElementById('wrap').appendChild(f);
f.src = '__BASE__/#' + target;
setTimeout(function(){
  try{
    var d = f.contentDocument, de = d.documentElement, w = de.clientWidth;
    // 落在「横向滚动容器」里的元素不算溢出 —— 那是设计如此。
    // 只有跑到滚动容器外面的才算真的撑破页面。
    function clipped(e){
      var p = e.parentElement;
      while (p && p !== d.body){
        var cs = getComputedStyle(p);
        if (cs.overflowX === 'auto' || cs.overflowX === 'scroll' || cs.overflowX === 'hidden'){
          if (p.getBoundingClientRect().right <= w + 1) return true;
        }
        p = p.parentElement;
      }
      return false;
    }
    var bad = [];
    d.querySelectorAll('*').forEach(function(e){
      var r = e.getBoundingClientRect();
      if (r.right > w + 1 && !clipped(e)) {
        bad.push(e.tagName + '.' + (e.className||'') + '@' + Math.round(r.left) + '..' + Math.round(r.right));
      }
    });
    document.title = 'W=' + w + ' SW=' + de.scrollWidth + ' || ' + (bad.slice(0,6).join(' ; ') || 'OK');
  }catch(e){ document.title = 'ERR ' + e.message; }
}, 3200);
</script></body></html>"""


def measure(base: str, width: int, route: str, subject_id: int = 1) -> str:
    html = PROBE_HTML.replace("__BASE__", base).replace("__SUBJECT__", str(subject_id))
    PROBE.write_text(html, encoding="utf-8")
    url = f"{base}/static/_probe.html?w={width}#{route}"
    out = subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--virtual-time-budget=9000",
         "--window-size=1000,2100", "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    ).stdout
    m = re.search(r"<title>([^<]*)</title>", out)
    return m.group(1) if m else "(拿不到测量结果)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--widths", default="320,375,414")
    ap.add_argument("--routes", default=",".join(DEFAULT_ROUTES))
    ap.add_argument("--subject-id", type=int, default=1,
                    help="切换学科后逐页量布局；语文可用 2/3，并传 --routes 跳过军理专属页")
    a = ap.parse_args()

    if not EDGE.exists():
        raise SystemExit(f"找不到 Edge：{EDGE}")
    widths = [int(x) for x in a.widths.split(",") if x.strip()]
    routes = [x.strip() for x in a.routes.split(",") if x.strip()]

    bad_total = 0
    try:
        for w in widths:
            print(f"\n---- 视口宽度 {w} px ----")
            for r in routes:
                t = measure(a.base, w, r, a.subject_id)
                ok = t.endswith("|| OK")
                if not ok:
                    bad_total += 1
                print(f"  {'OK  ' if ok else '溢出'} {r:<10} {t}")
    finally:
        PROBE.unlink(missing_ok=True)

    print()
    if bad_total:
        print(f"共 {bad_total} 个页面存在横向溢出")
        return 1
    print("全部页面在测试宽度下均无横向溢出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
