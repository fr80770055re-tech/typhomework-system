# typhomework-system
typhomework-system


## 家長查詢端的資料公開範圍

教師端只把家長查詢需要的資料發布到 `public_board/my_class`（產生規則見 `parent-board.js`）：

- `shared`：作業清單、指派日期、宣導事項、人數，任何人可讀。
- `students/{key}`：單一學生的作業狀態。`key` 由座號與查詢密碼以 PBKDF2 算出，資料庫規則禁止列出 `students`，所以要知道座號和密碼才找得到。

密碼、輔導記事、出缺勤、成績只存在教師自己的 `users/{uid}`。

已知限制：沒有後端，無法限制嘗試次數，4 位數密碼仍可能被逐一猜中，猜中後只能看到該生的作業狀態。

### 更新資料庫規則

`firebase-rules-public-board.json` 是規則中 `public_board` 區段的內容。同一個 Firebase 專案還有其他應用的規則，只能替換這個區段，不可整份覆蓋。

順序：

1. 合併並確認網站已更新。
2. 教師登入一次教師端，舊格式的公開資料會自動被取代。
3. 在 Firebase 主控台替換規則的 `public_board` 區段並發布。
