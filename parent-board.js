// 家長查詢端的公開資料：教師端發布、家長端讀取，兩端共用同一套產生規則。
// shared 只放全班共用資訊；每位學生的繳交狀態存在由「座號＋密碼」算出的位置，
// 資料庫規則禁止列出 students 底下的項目，因此不知道密碼就找不到該筆資料。
// 密碼、輔導記事、出缺勤、成績都不會離開教師自己的 users/{uid}。
(function (root) {
    const KEY_SALT = 'typhomeworksystem/parent-board/v1';
    const KEY_ITERATIONS = 200000;
    const keyCache = new Map();

    const safeName = (name) => String(name).replace(/[.#$/\[\]]/g, '_');

    async function deriveStudentKey(sid, password) {
        const cacheId = `${sid}\n${password}`;
        if (keyCache.has(cacheId)) return keyCache.get(cacheId);
        const enc = new TextEncoder();
        const material = await root.crypto.subtle.importKey('raw', enc.encode(`${sid}:${password}`), 'PBKDF2', false, ['deriveBits']);
        const bits = await root.crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: enc.encode(KEY_SALT), iterations: KEY_ITERATIONS }, material, 256);
        const key = Array.from(new Uint8Array(bits)).map(b => b.toString(16).padStart(2, '0')).join('');
        keyCache.set(cacheId, key);
        return key;
    }

    async function buildBoard(data) {
        const tasks = (data.tasks || []).map(safeName);
        const count = parseInt(data.studentCount) || 30;
        const rawDates = data.taskDates || {};
        const taskDates = {};
        Object.keys(rawDates).forEach(t => { if (tasks.includes(safeName(t))) taskDates[safeName(t)] = rawDates[t]; });

        const passwords = data.studentPasswords || {};
        const allStatus = data.globalTaskData || {};
        const students = {};
        for (let sid = 1; sid <= count; sid++) {
            const own = {};
            Object.keys(allStatus[sid] || {}).forEach(t => {
                const s = allStatus[sid][t];
                if (tasks.includes(safeName(t)) && s) own[safeName(t)] = s;
            });
            // v 讓沒有任何繳交紀錄的學生也有一筆資料，家長端才能區分「密碼錯誤」
            students[await deriveStudentKey(sid, passwords[sid] || '0000')] = { v: 1, tasks: own };
        }
        return { shared: { tasks, taskDates, announcements: data.announcements || '', studentCount: String(count) }, students };
    }

    root.ParentBoard = { deriveStudentKey, buildBoard };
})(globalThis);
