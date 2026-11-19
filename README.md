<p align="center">
  <img src="frontend/public/app-icon.png" width="104" height="104" alt="题题的库：绿色底板上的 T 字题页"/>
</p>

# 题题的库

把手头的教材和习题册建成自己的多学科题库。上传后可校对识别结果，搜索教材原文、刷题、组练习卷，并从错题回到对应考点。

- **分科导入**：支持 PDF、DOCX、TXT、Markdown 和常见图片；扫描件用本地 RapidOCR，不把资料发送给第三方识别服务。PDF 上限 256 MiB、1,000 页。
- **复习流程**：搜索原文、按章节刷题、客观题自动判分、错题回看与备考建议。军理押题是独立策略，不与通用练习卷混用。
- **技术栈**：Vue 3、FastAPI、SQLite。面向个人使用，前端适配手机。

## 本地启动

需要 Python 3.10+ 和适用于 Vite 6 的 Node.js（建议 Node.js 22）。在项目根目录执行（Windows PowerShell）：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements-ocr.txt
npm --prefix frontend ci
npm --prefix frontend run build:only
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

macOS / Linux 把命令中的 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`。打开本机的 `http://127.0.0.1:8000`；API 文档在 `/docs`。

首次启动会创建数据库，只带学科结构，不附带原项目的教材、真题、题库数据库、个人作答或正式押题数据。可以先在「资料库」新建一个学科，依次导入 [样例教材](examples/textbook.txt) 和 [样例习题](examples/workbook.txt)，用它们体验关联教材和练习卷。

- [分科导入和 API 说明](docs/20-分科资料导入.md)
- [SVG 图标](frontend/public/app-icon.svg) · [Windows ICO](tools/app.ico)
- 自检：`python tools/selftest_material_import.py`（使用临时数据库，含 OCR 和练习卷判分）

此仓库是源码展示，不是在线题库。应用默认按本机单人使用，不要把无访问保护的实例暴露到公网。
