"""Playwright: воронка v2 целиком (PROCESSES_PLAN.md, разделы 10–12). Запускать ТОЛЬКО против копии на 127.0.0.1:5051 —
создаёт тестовые записи, карточку «Репертуара» и файл райдера; живой сервер не трогает. python3 tests/check_processes_ui.py
"""
from pathlib import Path
import base64
import tempfile
import time
from playwright.sync_api import sync_playwright

TMP = Path(tempfile.mkdtemp())
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:5051/proto/#wkproc', wait_until='domcontentloaded')
    page.locator('[data-proc-open="procartists"]').wait_for(timeout=60000)
    assert page.locator('[data-proc-open="procvenues"]').count() == 1
    page.locator('[data-proc-open="procartists"]').click()
    assert page.locator('.proc-hero .wk-hstats').count() == 0          # плиток в шапке нет — числа в «Фильтре»
    if page.locator('[data-proc-action="ask-no"]').count():             # разовый вопрос о переносе «Позвонили + готовы»
        page.locator('[data-proc-action="ask-no"]').click()
        assert page.locator('[data-proc-action="ask-no"]').count() == 0
    prefix = 'PW ' + str(int(time.time()))
    for suffix in ('А', 'Б', 'В', 'Г'):
        page.locator('[data-proc-add] input').fill(prefix + suffix)
        page.locator('[data-proc-add] input').press('Enter')
        page.wait_for_function('title => Object.values(WK.leads).some(r => r.title === title)', arg=prefix+suffix)
    ids = {s: page.evaluate('t => Object.keys(WK.leads).find(id => WK.leads[id].title === t)', prefix+s) for s in 'АБВГ'}
    A, B, V, G = ids['А'], ids['Б'], ids['В'], ids['Г']
    stage = lambda lid, s: page.wait_for_function('a => WK.leads[a[0]] && WK.leads[a[0]].stage === a[1]', arg=[lid, s])
    calday = lambda iso: page.locator('.wk-cal [data-wkc-day="'+iso+'"]').first.click()
    today = page.evaluate('wkDay(0)')
    # галочка «Позвонил» в таблице — квадратик; ставит дату звонка; подсказка → «Позвонили» (29.10, п. 3, 8)
    box = page.locator('[data-lead-field="called"][data-id="'+A+'"]')
    assert box.evaluate('el => getComputedStyle(el).borderRadius') == '6px'
    box.check()
    page.locator('#cdOk').click(); stage(A, 'called')
    assert page.evaluate('id => WK.leads[id].called && WK.leads[id].called_at === wkDay(0)', A)
    assert page.locator('[data-proc-date="called"][data-id="'+A+'"]').inner_text().strip() != '—'   # «Дата звонка» видна сразу
    # «Дата звонка» — календарь сайта
    page.locator('[data-proc-date="called"][data-id="'+A+'"]').click()
    page.locator('.wk-cal .wkc-quick [data-wkc-day="'+page.evaluate('wkDay(-1)')+'"]').click()
    page.wait_for_function('id => WK.leads[id].called_at === wkDay(-1)', arg=A)
    # «Готовы» — пилюля; «Да» → подсказка «обсуждаем с руководителем»
    page.locator('[data-proc-action="ready-pick"][data-id="'+V+'"]').click()
    page.locator('.proc-rmenu [data-proc-action="ready-set:yes"]').click()
    page.locator('#cdOk').click(); stage(V, 'discuss')
    assert page.locator('[data-proc-action="ready-pick"][data-id="'+V+'"].yes').inner_text() == 'Да'
    # «+» в «Задачах» — быстрая задача записи
    page.locator('[data-proc-action="task-menu"][data-id="'+G+'"]').click()
    page.locator('.proc-tmenu [data-proc-action="task-quick:0"]').click()
    page.wait_for_function('a => Object.values(WK.tasks).some(t => t.lead === a[0] && t.text === "Отправить коллективу подборку городов — " + a[1])', arg=[G, prefix+'Г'])
    assert page.locator('[data-proc-action="task-menu"][data-id="'+G+'"]').count() == 1
    # «+» в «Карточке проекта» — поиск и «Создать карточку» без боковой карточки
    page.locator('[data-proc-action="pj-menu"][data-id="'+G+'"]').click()
    page.locator('.proc-pjmenu [data-wk-msearch]').fill('zzzнетткакой')
    assert page.locator('.proc-pjmenu .wk-mnone').is_visible()
    page.locator('.proc-pjmenu [data-proc-action="pj-create"]').click()
    page.wait_for_function('id => WK.leads[id].pj && MYP.projects[WK.leads[id].pj]', arg=G)
    assert page.locator('#drawer.open').count() == 0
    # «Перезвонить» в таблице: «+2» видны в строке (не уезжают), календарь, «×» — не нужно (п. 10–12)
    page.locator('[data-proc-date="next"][data-id="'+G+'"]').hover()
    q = page.locator('[data-proc-action="cb:2"][data-id="'+G+'"]')
    row = page.locator('[data-proc-date="next"][data-id="'+G+'"]').evaluate('el => el.closest("tr").getBoundingClientRect().toJSON()')
    qb = q.bounding_box()
    assert q.is_visible() and qb['y'] >= row['y'] and qb['y'] + qb['height'] <= row['y'] + row['height'] + 1, (qb, row)
    q.click(); page.wait_for_function('id => WK.leads[id].next_at === wkDay(2) && WK.leads[id].next === "Перезвонить"', arg=G)
    page.locator('[data-proc-date="next"][data-id="'+G+'"]').click()
    page.locator('.wk-cal .wkc-quick [data-wkc-day="'+page.evaluate('wkDay(7)')+'"]').click()
    page.wait_for_function('id => WK.leads[id].next_at === wkDay(7)', arg=G)
    page.locator('[data-proc-date="next"][data-id="'+G+'"]').hover()
    page.locator('[data-proc-action="cb-clear"][data-id="'+G+'"]').click()
    page.wait_for_function('id => !WK.leads[id].next_at && !WK.leads[id].next', arg=G)
    # граница столбца: как в Safari (<col> без ширины) — остальные столбцы не пропадают (п. 5)
    page.evaluate('() => { window.__colRect = HTMLTableColElement.prototype.getBoundingClientRect; HTMLTableColElement.prototype.getBoundingClientRect = function () { return new DOMRect(0, 0, 0, 0); }; }')
    h = page.locator('.proc-funnel [data-plresize="fee"]').first.bounding_box()
    page.mouse.move(h['x'] + 2, h['y'] + 5); page.mouse.down(); page.mouse.move(h['x'] + 40, h['y'] + 5, steps=4)
    widths = page.evaluate('() => [...document.querySelectorAll(".proc-funnel table thead th")].map(th => Math.round(th.getBoundingClientRect().width))')
    page.mouse.up()
    page.evaluate('() => { HTMLTableColElement.prototype.getBoundingClientRect = window.__colRect; }')
    assert all(w > 30 for w in widths), widths
    # 1–3. «Да» → обсуждаем с руководителем; «Интересен» → ждут предложения + предложенная задача
    page.locator('[data-proc-action="lead"][data-id="'+A+'"]').first.click()
    page.locator('#drawer [data-proc-action="stage:discuss"]').click(); stage(A, 'discuss')
    page.locator('#drawer [data-proc-action="stage:ready"]').click(); stage(A, 'ready')
    page.locator('#pjDlg [data-lead-task] button.btn-dark').click()
    page.wait_for_function('id => Object.values(WK.tasks).some(t => t.lead === id && t.text.indexOf("Отправить коллективу подборку городов") === 0)', arg=A)
    page.locator('#drawer [data-proc-action="close"]').click()
    # отказ: выбор в таблице открывает окно; без причины не сохраняется; быстрый вариант → «Отказы»
    page.locator('select[data-lead-field="stage"][data-id="'+B+'"]').evaluate('el=>{el.value="declined";el.dispatchEvent(new Event("change",{bubbles:true}));}')
    page.locator('#pjDlg [data-lead-why]').wait_for()
    page.locator('#pjDlg [data-lead-why] button.btn-dark').click()
    assert page.evaluate('id => WK.leads[id].stage', B) == 'found'
    page.locator('#pjDlg [data-proc-action="why-q"]').first.click()
    page.locator('#pjDlg [data-lead-why] button.btn-dark').click(); stage(B, 'declined')
    assert page.evaluate('id => WK.leads[id].why', B) == 'Работают с другим организатором'
    assert page.locator('.tb-grid [data-proc-action="lead"][data-id="'+B+'"]').count() == 0
    # «В работе · Резерв · Отказы» — в «Фильтре»; открыт другой список — плашка с крестиком (п. 1)
    assert page.locator('.proc-tools [data-proc-action="filter"]').inner_text().strip() == ''   # значок без слова (п. 2)
    page.locator('.proc-tools [data-proc-action="filter"]').click()
    page.locator('.proc-fmenu [data-proc-action="f:view:declined"]').click()
    assert page.locator('.tb-grid [data-proc-action="lead"][data-id="'+B+'"]').count() == 1
    assert 'Отказы' in page.locator('.proc-listchip').inner_text()
    page.locator('.proc-listchip [data-proc-action="list:work"]').click()
    # доска: перетаскивание «Г» в «Позвонили»
    page.locator('[data-proc-action="board"]').click()
    assert page.locator('[data-lead-drop]').count() == 8
    page.locator('[data-lead-drag="'+G+'"]').drag_to(page.locator('[data-lead-drop="called"] .wkp-gh'), source_position={'x':20,'y':12})
    stage(G, 'called')
    page.locator('[data-proc-action="table"]').click()
    page.locator('[data-proc-action="lead"][data-id="'+V+'"]').first.click()
    page.locator('#drawer [data-proc-action="stage:reserve"]').click()
    page.locator('#pjDlg [data-lead-hold] textarea').fill('Мало городов сейчас')
    page.locator('#pjDlg [data-lead-hold] [data-proc-date="form"]').click(); calday(today)
    page.locator('#pjDlg [data-lead-hold] button.btn-dark').click(); stage(V, 'reserve')
    assert page.evaluate('id => WK.leads[id].why === "Мало городов сейчас" && WK.leads[id].next_at === wkDay(0)', V)
    page.locator('#drawer [data-proc-action="close"]').click()
    # «Фильтр»: несколько этапов, «Готовы», сброс (п. 4, 13); в работе остались «А» (ждут предложения) и «Г» (позвонили)
    page.locator('#procQ').fill(prefix)
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 2')
    page.locator('.proc-tools [data-proc-action="filter"]').click()
    page.locator('.proc-fmenu [data-proc-action="fs:stage:called"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 1')
    page.locator('.proc-fmenu [data-proc-action="fs:stage:ready"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 2')
    assert page.locator('.proc-fmenu [aria-checked="true"][data-proc-action^="fs:stage:"]').count() == 2
    assert page.locator('.proc-fbadge').inner_text() == '1'
    page.locator('.proc-fmenu [data-proc-action="f:ready:yes"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 1')   # у «Г» «Готовы» не указано
    page.locator('.proc-fmenu [data-proc-action="reset"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 2')
    page.locator('#procQ').fill('')
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length > 3')
    # гонорар, подбор, предложение → «перезвонить через 2 дня»
    page.locator('[data-proc-action="lead"][data-id="'+A+'"]').first.click()
    for key, value in [('fee','300000'), ('cashless','13')]:
        page.locator('#drawer [data-lead-field="'+key+'"]').first.fill(value)
        page.locator('#drawer [data-lead-field="'+key+'"]').first.press('Tab')
        page.wait_for_function('a => String(WK.leads[a.id][a.key]) === a.value', arg={'id':A,'key':key,'value':value})
    page.locator('#drawer [data-proc-action="pick-create"]').click()
    page.locator('#drawer [data-proc-action="pick"]').wait_for()
    page.locator('#drawer [data-proc-action="pick"]').click()
    page.locator('.tb-wchip [data-proc-action="lead"]').wait_for()
    city_keys = page.locator('select[data-plf$="|dec"]').evaluate_all('(els) => els.slice(0,2).map(e=>e.dataset.plf)')
    assert len(city_keys) == 2
    for key in city_keys:
        page.locator('select[data-plf="'+key+'"]').evaluate('(el)=>{el.value="yes";el.dispatchEvent(new Event("change",{bubbles:true}));}')
        page.wait_for_function('key => PLAN.lists[key.split("|")[1]].cities[key.split("|")[2]].dec === "yes"', arg=key)
    page.locator('.tb-wchip [data-proc-action="lead"]').click()
    page.locator('#drawer [data-proc-action="stage:offer"]').click()
    page.locator('#cdOk').click()
    page.wait_for_function('id => WK.leads[id].next_at === wkDay(2) && WK.leads[id].next === "Перезвонить"', arg=A)
    page.locator('#drawer [data-proc-action="cb:7"]').first.click()
    page.wait_for_function('id => WK.leads[id].next_at === wkDay(7)', arg=A)
    page.locator('#drawer .proc-sfull [data-proc-action="cb-clear"]').click()   # перезванивать не нужно
    page.wait_for_function('id => !WK.leads[id].next_at && !WK.leads[id].next', arg=A)
    page.locator('#drawer [data-proc-action="stage:answered"]').click(); stage(A, 'answered')
    # ответ коллектива: города (в подборе), диапазон дат, следующий сезон
    page.locator('#drawer [data-proc-action="art:ok"]').first.click()
    page.wait_for_function('id => Object.values(PLAN.lists[WK.leads[id].list].cities).some(c => c.art === "ok")', arg=A)
    page.locator('#drawer [data-proc-action="art:busy"]').nth(1).click()
    page.locator('#drawer [data-art-org]').wait_for()
    page.locator('#drawer [data-art-org]').fill('Иванов-концерт'); page.locator('#drawer [data-art-org]').press('Tab')
    page.wait_for_function('id => Object.values(PLAN.lists[WK.leads[id].list].cities).some(c => c.art === "busy" && c.art_org === "Иванов-концерт")', arg=A)
    page.locator('#drawer [data-proc-action="date-add"]').click()
    page.wait_for_function('id => (WK.leads[id].dates || []).length === 1', arg=A)
    page.locator('#drawer [data-proc-date="range"][data-k="from"]').click()
    page.locator('.wk-cal .wkc-in').fill('10.11.2026'); page.locator('.wk-cal .wkc-in').press('Enter')
    page.wait_for_function('id => WK.leads[id].dates[0].from === "2026-11-10"', arg=A)
    page.locator('#drawer [data-lead-ns="ok"]').check()
    page.wait_for_function('id => WK.leads[id].ns.ok === true', arg=A)
    page.locator('#drawer [data-proc-action="ns-m:3"]').click()
    page.wait_for_function('id => WK.leads[id].ns.months.join() === "3"', arg=A)
    # согласование: задача предложена, возможные города, «Согласовано» → финал
    page.locator('#drawer [data-proc-action="stage:approve"]').click(); stage(A, 'approve')
    page.locator('#pjDlg [data-lead-task] button.btn-dark').click()
    page.wait_for_function('id => Object.values(WK.tasks).some(t => t.lead === id && t.text.indexOf("Подготовить отчёт по возможным городам для руководителя") === 0)', arg=A)
    page.locator('#drawer [data-proc-action="cities"]').click()
    page.wait_for_function('id => WK.leads[id].cities.length === 2', arg=A)
    page.locator('#drawer [data-proc-action="stage:booking"]').click(); stage(A, 'booking')
    assert page.locator('#drawer [data-proc-action="project-create"]').count() == 0
    # карточка «Репертуара»: создать, гонорар уходит туда, райдер файлом
    page.locator('#drawer [data-proc-action="pj-create"]').click()
    page.wait_for_function('id => WK.leads[id].pj && MYP.projects[WK.leads[id].pj]', arg=A)
    pj = page.evaluate('id => WK.leads[id].pj', A)
    page.wait_for_function('pj => (MYP.projects[pj].profile || {}).fee === "300 000 ₽ + 13 %"', arg=pj)
    rider = TMP / 'Технический райдер.pdf'; rider.write_bytes(b'%PDF-1.4 test rider')
    page.locator('#drawer [data-lead-rider]').set_input_files(str(rider))
    page.wait_for_function('pj => (MYP.projects[pj].profile.riders || []).some(r => r.file && r.label === "Технический райдер.pdf")', arg=pj)
    href = page.locator('#drawer .proc-file a').first.get_attribute('href')
    assert page.evaluate('u => fetch(u).then(r => r.text())', href) == '%PDF-1.4 test rider'
    page.locator('#drawer [data-proc-action="pj-open"]').first.click()
    page.locator('.proc-coop').wait_for()
    coop = page.locator('.proc-coop').inner_text()
    assert 'готово к бронированию' in coop.lower() and '300 000 ₽ + 13 %' in coop and 'Перезвонить' not in coop, coop
    page.locator('.proc-coop [data-proc-action="lead"]').click()
    page.locator('#drawer .proc-dhead').wait_for()
    assert page.evaluate('id => WorkProcesses && document.querySelector("#drawer h2").textContent === WK.leads[id].title', A)
    # задача записи: в окне задачи — ссылка на воронку
    page.locator('#drawer [data-proc-action="task-open"]').first.click()
    assert page.locator('#pjDlg [data-proc-action="lead"]').count() >= 1
    page.locator('#pjDlg [data-pj="close"]').first.click()
    # «Пул проектов» и «Обзор → Что горит»
    page.evaluate('goView("pool")')
    page.locator('.proc-pool').first.wait_for()
    pool = page.locator('#view').inner_text()
    assert prefix+'А' in pool and prefix+'Б' in pool and prefix+'В' in pool
    page.evaluate('goView("wkhome")')
    page.wait_for_function('t => document.querySelector("#view").innerText.indexOf(t) >= 0', arg=prefix+'В')
    assert page.locator('.wh-fi[data-proc-action="lead"][data-id="'+V+'"]').count() >= 1
    page.locator('.wh-fi[data-proc-action="lead"][data-id="'+V+'"]').first.click()
    page.locator('#drawer .proc-banner').wait_for()
    page.locator('#drawer [data-proc-action="close"]').click()
    # задачи и заметки процесса — прежние компоненты
    page.evaluate('WorkProcesses.open("procartists")')
    page.locator('[data-proc-action="tasks"]').click()
    page.locator('[data-wk-add="tasks"] input[name="text"]').fill(prefix+' задача из таблицы')
    page.locator('[data-wk-add="tasks"] input[name="text"]').press('Enter')
    page.wait_for_function('t => Object.values(WK.tasks).some(r=>r.text===t && r.proc==="procartists")', arg=prefix+' задача из таблицы')
    page.locator('[data-wkn-new]').click()
    page.locator('[data-wkn-add="quick"]').click()
    page.locator('[data-wkn-ed-title]').fill(prefix+' заметка')
    page.locator('[data-wkn-ed-create]').click()
    page.locator('.wkn-body').fill('Заметка процесса')
    page.locator('.wkn-body').press('Enter')
    page.wait_for_function('t=>Object.values(WK.notes).some(n=>n.title===t && n.proc==="procartists" && n.body==="Заметка процесса")', arg=prefix+' заметка')
    # перезагрузка — всё на месте
    page.reload(wait_until='domcontentloaded')
    page.wait_for_function('id=>WK_OK && WK.leads[id] && WK.leads[id].cities.length===2', arg=A)
    assert page.evaluate('a => WK.leads[a[0]].stage==="booking" && WK.leads[a[1]].stage==="declined" && WK.leads[a[2]].stage==="reserve" && WK.leads[a[0]].ns.ok', [A, B, V])
    # телефон: без прокрутки вбок
    page.evaluate('WorkProcesses.open("procartists")')
    page.set_viewport_size({'width':390,'height':844})
    for act in ('table','board','f:view:reserve','f:view:declined','list:work','tasks'):
        if act.startswith('f:'):
            page.locator('.proc-tools [data-proc-action="filter"]').click()
        page.locator('[data-proc-action="'+act+'"]').first.click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), act
    page.locator('[data-proc-action="funnel"]').click()
    page.locator('[data-proc-action="lead"][data-id="'+A+'"]').first.click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'drawer'
    page.screenshot(path=str(TMP / 'processes-mobile.png'), full_page=True)
    page.locator('#drawer [data-proc-action="close"]').click()
    page.set_viewport_size({'width':1440,'height':1000})
    # свой процесс с обложкой
    page.locator('[data-proc-action="back"]').click()
    page.locator('[data-proc-action="new"]').click()
    page.locator('[data-proc-edit] input[name="title"]').fill(prefix+' процесс')
    image = TMP / 'cover.png'
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN3sAAAAASUVORK5CYII='))
    page.locator('[data-proc-edit] input[type="file"]').set_input_files(str(image))
    page.locator('[data-proc-edit] button.btn-dark').click()
    page.wait_for_function('t=>Object.values(WK.procs).some(p=>p.title===t && p.media && p.media.cover)', arg=prefix+' процесс')
    assert not errors, errors
    print('ok: v2 — «Позвонил» с датой, «Готовы»-пилюля, «+» задач и карточки, календарь, «не нужно», граница столбца (Safari), '
          'списки и несколько этапов в фильтре; этапы, отказ с причиной, резерв, доска, подбор, перезвонить, ответ коллектива, согласование, '
          'бронирование, карточка «Репертуара» (гонорар, райдер), «Сотрудничество», пул, «Что горит», задачи, заметки, '
          'перезагрузка, 390 px, обложка')
    browser.close()
