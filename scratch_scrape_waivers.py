import os
import sys
import csv
from pathlib import Path
from playwright.sync_api import sync_playwright

def scrape_waivers():
    print("正在啟動 Playwright 瀏覽器...")
    with sync_playwright() as p:
        # Launch browser with headless=False so the user can interactively log in
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        url = "https://catalog.cgu.edu.tw/stugrade"
        print(f"正在前往 {url} ...")
        page.goto(url)
        
        # Check if we redirect to Microsoft login
        is_redirected = False
        print("偵測登入狀態中...")
        for _ in range(50):  # wait up to 5 seconds
            if "microsoftonline.com" in page.url:
                is_redirected = True
                break
            page.wait_for_timeout(100)
            
        if is_redirected:
            print("\n" + "="*60)
            print("提示：已重導向至 Microsoft 登入頁面！")
            print("請在彈出的瀏覽器視窗中輸入 M365 帳密並完成雙因子驗證。")
            print("登入成功後，瀏覽器會自動跳回 stugrade 頁面，腳本將繼續執行。")
            print("="*60 + "\n")
            
            # Poll the URL to see if it redirects back
            timeout_ms = 300000  # 5 minutes
            elapsed = 0
            login_success = False
            while elapsed < timeout_ms:
                if "catalog.cgu.edu.tw/stugrade" in page.url and "microsoftonline.com" not in page.url:
                    # Wait another 2 seconds to ensure no further redirects and page loads completely
                    page.wait_for_timeout(2000)
                    if "microsoftonline.com" not in page.url:
                        login_success = True
                        break
                page.wait_for_timeout(500)
                elapsed += 500
                
            if not login_success:
                print("等待登入逾時（5分鐘），腳本結束。")
                browser.close()
                return
            print("登入成功！已返回目標頁面。")
        else:
            print("偵測到已是登入狀態，直接進行資料讀取。")
            page.wait_for_timeout(2000)

        # Wait for #tabh1 to be visible
        try:
            tab_button = page.locator("#tabh1")
            tab_button.wait_for(state="visible", timeout=30000)
            print("成功定位抵免學分頁籤按鈕 (#tabh1)。")
        except Exception as e:
            print("找不到 #tabh1 按鈕，可能是頁面載入不完整，嘗試直接抓取頁面內容...")
            tab_button = None

        if tab_button:
            # Click the tab to make sure it's active
            tab_button.click()
            print("已點擊抵免學分頁籤，等待內容載入...")
            page.wait_for_timeout(1500)
            
        # Evaluate JavaScript in browser to extract the table under #tab1
        EXTRACT_TABLE_JS = """
        () => {
          const tab = document.querySelector('#tab1');
          if (!tab) return { error: "找不到 #tab1 元素" };
          
          const table = tab.querySelector('table');
          if (!table) {
            // Try searching globally on the page just in case
            const allTables = document.querySelectorAll('table');
            if (allTables.length > 0) {
              return { warning: "在 #tab1 中找不到表格，但在頁面中找到其他表格", count: allTables.length };
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
        
        # Save HTML for debugging
        html_content = result.get("html") or page.content()
        html_file = out_dir / "waiver_results.html"
        html_file.write_text(html_content, encoding="utf-8")
        print(f"原始 HTML 已儲存至：{html_file}")
        
        if result.get("success"):
            rows = result["rows"]
            print(f"成功取得表格數據，共 {len(rows)} 行。")
            
            csv_file = out_dir / "waiver_results.csv"
            with csv_file.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            print(f"抵免學分結果已儲存至 CSV 檔案：{csv_file}")
            
            # Print table content to console
            print("\n" + "="*30 + " 抵免學分核准結果 " + "="*30)
            for idx, row in enumerate(rows):
                print(f"[{idx+1:02d}] " + " | ".join(row))
            print("="*78 + "\n")
            
        else:
            print(f"抓取失敗或有警告：{result.get('error') or result.get('warning')}")
            # Save raw page text as fallback
            text_content = result.get("text") or page.locator("body").inner_text()
            txt_file = out_dir / "waiver_results.txt"
            txt_file.write_text(text_content, encoding="utf-8")
            print(f"已將頁面純文字備份儲存至：{txt_file}")
            print("\n純文字內容摘要：")
            print(text_content[:2000])

        print("抓取完成！瀏覽器將在 5 秒後自動關閉。")
        page.wait_for_timeout(5000)
        browser.close()

if __name__ == "__main__":
    scrape_waivers()
