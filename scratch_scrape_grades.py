import os
import sys
import csv
from pathlib import Path
from playwright.sync_api import sync_playwright

def scrape_grades():
    print("正在啟動 Playwright 瀏覽器...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        url = "https://catalog.cgu.edu.tw/stugrade"
        print(f"正在前往 {url} ...")
        page.goto(url)
        
        is_redirected = False
        print("偵測登入狀態中...")
        for _ in range(50):
            if "microsoftonline.com" in page.url:
                is_redirected = True
                break
            page.wait_for_timeout(100)
            
        if is_redirected:
            print("\n" + "="*60)
            print("提示：已重導向至 Microsoft 登入頁面！")
            print("請在彈出的瀏覽器視窗中輸入 M365 帳密並完成驗證。")
            print("登入成功後，腳本將繼續自動執行。")
            print("="*60 + "\n")
            
            timeout_ms = 300000
            elapsed = 0
            login_success = False
            while elapsed < timeout_ms:
                if "catalog.cgu.edu.tw/stugrade" in page.url and "microsoftonline.com" not in page.url:
                    page.wait_for_timeout(2000)
                    if "microsoftonline.com" not in page.url:
                        login_success = True
                        break
                page.wait_for_timeout(500)
                elapsed += 500
                
            if not login_success:
                print("等待登入逾時，結束執行。")
                browser.close()
                return
            print("登入成功！已返回目標頁面。")
        else:
            print("已是登入狀態，直接進行資料讀取。")
            page.wait_for_timeout(2000)

        # Wait for #tabh0 or #tab0 to be visible
        try:
            tab_button = page.locator("#tabh0")
            tab_button.wait_for(state="visible", timeout=30000)
            print("成功定位成績查詢頁籤 (#tabh0)。")
            tab_button.click()
            page.wait_for_timeout(1500)
        except Exception as e:
            print("定位 #tabh0 發生錯誤：", e)

        # Evaluate JS to get table content from #tab0
        EXTRACT_TABLE_JS = """
        () => {
          const tab = document.querySelector('#tab0');
          if (!tab) return { error: "找不到 #tab0 元素" };
          
          const table = tab.querySelector('table');
          if (!table) {
            const allTables = document.querySelectorAll('table');
            if (allTables.length > 0) {
              return { warning: "在 #tab0 中找不到表格，但頁面中有其他表格", count: allTables.length };
            }
            return { error: "找不到任何 table 元素" };
          }
          
          const rows = [];
          const trs = Array.from(table.querySelectorAll('tr'));
          for (const tr of trs) {
            const cells = Array.from(tr.querySelectorAll('td, th')).map(c => (c.textContent || '').trim());
            if (cells.length > 0) {
              rows.push(cells);
            }
          }
          return { success: true, rows: rows, html: tab.innerHTML, text: tab.innerText };
        }
        """
        
        result = page.evaluate(EXTRACT_TABLE_JS)
        
        out_dir = Path("data")
        out_dir.mkdir(exist_ok=True)
        
        html_content = result.get("html") or page.content()
        html_file = out_dir / "grade_results.html"
        html_file.write_text(html_content, encoding="utf-8")
        print(f"原始 HTML 已儲存至：{html_file}")
        
        if result.get("success"):
            rows = result["rows"]
            print(f"成功取得表格數據，共 {len(rows)} 行。")
            
            csv_file = out_dir / "grade_results.csv"
            with csv_file.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            print(f"成績查詢結果已儲存至 CSV 檔案：{csv_file}")
            
            print("\n" + "="*30 + " 成績查詢結果 " + "="*30)
            for idx, row in enumerate(rows[:15]):
                print(f"[{idx+1:02d}] " + " | ".join(row))
            if len(rows) > 15:
                print(f"... 還有 {len(rows) - 15} 筆資料")
            print("="*78 + "\n")
        else:
            print(f"抓取失敗：{result.get('error') or result.get('warning')}")
            text_content = result.get("text") or page.locator("body").inner_text()
            txt_file = out_dir / "grade_results.txt"
            txt_file.write_text(text_content, encoding="utf-8")
            print(f"已儲存頁面純文字至：{txt_file}")
            
        print("抓取完成！5秒後關閉瀏覽器。")
        page.wait_for_timeout(5000)
        browser.close()

if __name__ == "__main__":
    scrape_grades()
