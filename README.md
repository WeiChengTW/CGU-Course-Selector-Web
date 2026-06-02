# Course Selector Web

長庚大學選課輔助 Web 應用，透過 MOOCS 帳號同步修課紀錄，並提供課程查詢、畢業進度檢視及選課建議功能。

## 功能

- **登入同步**：使用 MOOCS 帳號登入，自動抓取修課紀錄與課表
- **已修課程**：列出所有已修課程、成績、學分
- **課程查詢**：搜尋長庚大學開課課程（呼叫課程目錄 API）
- **畢業進度**：依畢業規定分類統計已修學分（開發中，詳見 [Graduation-Credit-Calculator](https://github.com/WeiChengTW/Graduation-Credit-Calculator)）
- **選課建議**：根據尚未修習的必修科目給出建議（開發中，詳見 [Graduation-Credit-Calculator](https://github.com/WeiChengTW/Graduation-Credit-Calculator)）

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. 同步修課資料

啟動服務後，前往 `/login` 輸入 MOOCS 帳號密碼，系統會自動抓取修課成績並產生 `data/taken_courses.csv`。

> **注意**：資料抓取需要 1–2 分鐘，請耐心等待同步完成後再操作。

### 3. 啟動服務

```bash
uvicorn app.main:app --reload --port 8001
```

開啟瀏覽器前往 [http://127.0.0.1:8001](http://127.0.0.1:8001)

## 專案結構

```
Course-Selector-Web/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 路徑設定
│   ├── routes/              # 路由（auth, courses, catalog, graduation, recommend）
│   ├── services/            # 業務邏輯（課程、畢業、MOOCS 同步）
│   └── templates/           # Jinja2 HTML 模板
├── lib/                     # MOOCS 抓取與課程目錄查詢
│   ├── scraper.py           # Playwright 登入抓取
│   ├── catalog.py           # 課程目錄 API 查詢
│   └── utils.py             # 工具函式
├── data/
│   └── taken_courses.csv    # 登入後自動產生，個人修課紀錄（不納入版控）
└── requirements.txt
```

## 注意事項

- `data/taken_courses.csv` 含個人資料，已加入 `.gitignore`，不會上傳至 GitHub
- 本專案僅供個人學習使用，請勿大量呼叫學校 API
