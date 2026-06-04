# Course Selector Web

長庚大學選課輔助 Web 應用，透過 MOOCS 帳號同步修課紀錄，並提供課程查詢、畢業進度檢視及選課建議功能。

## 功能

- **登入同步**：使用 MOOCS 帳號登入，自動抓取修課紀錄與課表
- **已修課程**：列出所有已修課程、成績、學分
- **課程查詢**：搜尋長庚大學開課課程（呼叫課程目錄 API）
- **畢業進度**：上傳畢業學分 PDF 後，透過 CGU LLM API 分析修課紀錄、畢業門檻與缺修項目
- **榮譽學程**：可勾選是否為榮譽學程學生，並可上傳榮譽學程手冊 PDF；未上傳時使用系統預設規則檔
- **選課建議**：根據尚未修習的必修科目給出建議（開發中）

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. 設定 LLM API Key（畢業分析用）

畢業進度分析會呼叫 CGU OpenAI-compatible LLM API。可以選擇：

- 在 `.env` 或環境變數設定 `CGU_LLM_API_KEY`
- 或在 `/graduation` 頁面分析時手動輸入 API Key

可選設定：

```bash
CGU_LLM_API_KEY=你的長庚 LLM API Key
LLM_BASE_URL=https://air.cgu.edu.tw/cgullmapi/v1
LLM_MODEL=gpt-5.4-mini
```

若頁面輸入 API Key，會優先使用頁面輸入值；未輸入時才使用環境變數。

### 3. 同步修課資料

啟動服務後，前往 `/login` 輸入 MOOCS 帳號密碼，系統會自動抓取修課成績與課程詳細資料，並存到目前登入 session 的資料夾，例如 `data/sessions/{session_id}/taken_courses.csv` 與 `courses_detail.csv`。

> **注意**：資料抓取需要 1–2 分鐘，請耐心等待同步完成後再操作。

### 4. 啟動服務

```bash
uvicorn app.main:app --reload --port 8001
```

開啟瀏覽器前往 [http://127.0.0.1:8001](http://127.0.0.1:8001)

## 畢業進度分析流程

1. 登入後點選導覽列的「畢業進度」
2. 上傳個人科系的畢業學分規則 PDF
3. 如果是榮譽學程學生，勾選「我是榮譽學程學生」
   - 可額外上傳榮譽學程手冊 PDF
   - 未上傳時，系統會嘗試使用 `data/rules/榮譽學程學生手冊_112入學適用.pdf`
4. 可選填 CGU LLM API Key；未填時使用環境變數 `CGU_LLM_API_KEY`
5. 送出後系統會在背景進行：PDF 轉 Markdown → 建立規則索引 → 合併修課資料 → LLM 分析
6. 頁面會每 4 秒自動更新分析狀態，完成後顯示學分概覽、缺修項目與下學期建議

預設規則檔可放在：

```text
data/rules/
├── 榮譽學程學生手冊_112入學適用.pdf
└── 112學年度下學期通識課程表.pdf
```

## 專案結構

```
Course-Selector-Web/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 路徑設定
│   ├── routes/              # 路由（auth, courses, catalog, graduation, recommend）
│   ├── services/            # 業務邏輯（課程、畢業、MOOCS 同步）
│   ├── templates/           # Jinja2 HTML 模板
│   └── lib/
│       └── graduation/      # 畢業分析專用模組：PDF 轉換、規則索引、LLM 分析、報告輸出
├── lib/                     # MOOCS 抓取與課程目錄查詢（原有共享工具）
│   ├── scraper.py           # Playwright 登入抓取
│   ├── catalog.py           # 課程目錄 API 查詢
│   └── utils.py             # 工具函式
├── data/
│   ├── rules/               # 預設規則 PDF（可選，不納入個人 session）
│   └── sessions/            # 登入後自動產生，每個使用者 session 一個資料夾（不納入版控）
└── requirements.txt
```

### 為什麼有兩個 `lib` 資料夾？

目前專案中有兩個 `lib`，用途不同：

- `lib/`：專案原本就有的共享工具，負責 MOOCS 爬蟲與課程目錄 API 查詢。這些工具也可被命令列腳本或其他模組使用。
- `app/lib/graduation/`：FastAPI app 內部的畢業分析模組，從 Graduation-Credit-Calculator 的核心邏輯整合而來，負責 PDF 轉 Markdown、建立規則索引、呼叫 LLM、產生分析報告。

分開放是為了避免把畢業分析專用邏輯混進原本的 MOOCS/課程查詢工具，也讓 FastAPI 內部引用可以保持明確：`from app.lib.graduation...`。

## 注意事項

- `data/taken_courses.csv` 含個人資料，已加入 `.gitignore`，不會上傳至 GitHub
- 本專案僅供個人學習使用，請勿大量呼叫學校 API
