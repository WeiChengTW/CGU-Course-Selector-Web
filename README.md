# Course Selector Web

長庚大學選課輔助 Web 應用，透過 MOOCS 帳號同步修課紀錄，並提供課程查詢、畢業進度檢視及選課建議功能。

## 功能

- **登入同步**：使用 MOOCS 帳號登入，自動抓取修課紀錄與課表
- **已修課程**：列出所有已修課程、成績、學分
- **課程查詢**：搜尋長庚大學開課課程（呼叫課程目錄 API）
- **畢業進度**：依畢業規定分類統計已修學分（開發中）
- **選課建議**：根據尚未修習的必修科目給出建議（開發中）

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. 準備修課資料（選擇其一）

**方式 A：手動建立 CSV**

複製範例檔並填入自己的修課紀錄：

```bash
cp data/taken_courses_sample.csv data/taken_courses.csv
```

CSV 格式：

| 學年學期 | 課程名稱 | 學分數 | 修課成績 |
|----------|----------|--------|----------|
| 1131     | 計算機概論 | 3   | 85       |
| 1132     | 資料結構   | 3   |          |

（修課成績留空表示修課中）

**方式 B：透過 Web 介面登入自動同步**

啟動服務後，前往 `/login` 輸入 MOOCS 帳號密碼，系統會自動抓取成績並產生 `taken_courses.csv`。

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
│   ├── taken_courses.csv        # 個人修課紀錄（不納入版控）
│   └── taken_courses_sample.csv # 格式範例
├── tests/                   # 單元測試
└── requirements.txt
```

## 注意事項

- `data/taken_courses.csv` 含個人資料，已加入 `.gitignore`，不會上傳至 GitHub
- MOOCS 登入同步需要較長時間（約 1–2 分鐘），請耐心等待
- 本專案僅供個人學習使用，請勿大量呼叫學校 API
