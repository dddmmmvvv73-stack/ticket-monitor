"""Playwright: воронка v2 целиком (PROCESSES_PLAN.md, раздел 10). Запускать ТОЛЬКО против копии на 127.0.0.1:5051 —
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
    for suffix in ('А', 'Б', 'В'):
        page.locator('[data-proc-add] input').fill(prefix + suffix)
        page.locator('[data-proc-add] input').press('Enter')
        page.wait_for_function('title => Object.values(WK.leads).some(r => r.title === title)', arg=prefix+suffix)
    ids = {s: page.evaluate('t => Object.keys(WK.leads).find(id => WK.leads[id].title === t)', prefix+s) for s in 'АБВ'}
    A, B, V = ids['А'], ids['Б'], ids['В']
    stage = lambda lid, s: page.wait_for_function('a => WK.leads[a[0]] && WK.leads[a[0]].stage === a[1]', arg=[lid, s])
    # 1–3. позвонил → подсказка → «Позвонили»; «Да» → обсуждаем с руководителем; «Интересен» → ждут предложения + задача
    page.locator('[data-proc-action="lead"][data-id="'+A+'"]').first.click()
    page.locator('#drawer [data-lead-field="called"]').check()
    page.locator('#drawer .proc-hints [data-proc-action="stage:called"]').click(); stage(A, 'called')
    assert page.evaluate('id => WK.leads[id].called_at === wkDay(0)', A)
    page.locator('#drawer [data-proc-action="stage:discuss"]').click(); stage(A, 'discuss')
    page.locator('#drawer [data-proc-action="stage:ready"]').click(); stage(A, 'ready')
    page.locator('#pjDlg [data-lead-task] button.btn-dark').click()
    page.wait_for_function('id => Object.values(WK.tasks).some(t => t.lead === id && t.text.indexOf("Подбор городов") === 0)', arg=A)
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
    page.locator('[data-proc-action="list:declined"]').first.click()
    assert page.locator('.tb-grid [data-proc-action="lead"][data-id="'+B+'"]').count() == 1
    page.locator('[data-proc-action="list:work"]').click()
    # доска: перетаскивание в «Обсуждаем», затем «Не сейчас — в резерв» с датой
    page.locator('[data-proc-action="board"]').click()
    assert page.locator('[data-lead-drop]').count() == 8
    page.locator('[data-lead-drag="'+V+'"]').drag_to(page.locator('[data-lead-drop="discuss"] .wkp-gh'), source_position={'x':20,'y':12})
    stage(V, 'discuss')
    page.locator('[data-proc-action="table"]').click()
    page.locator('[data-proc-action="lead"][data-id="'+V+'"]').first.click()
    page.locator('#drawer [data-proc-action="stage:reserve"]').click()
    page.locator('#pjDlg [data-lead-hold] textarea').fill('Мало городов сейчас')
    today = page.evaluate('wkDay(0)')
    page.locator('#pjDlg [data-lead-hold] input[name="at"]').fill(today)
    page.locator('#pjDlg [data-lead-hold] button.btn-dark').click(); stage(V, 'reserve')
    assert page.evaluate('id => WK.leads[id].why === "Мало городов сейчас" && WK.leads[id].next_at === wkDay(0)', V)
    page.locator('#drawer [data-proc-action="close"]').click()
    # «Фильтр» — меню сайта: «Пора перезвонить», этап, сброс
    page.locator('#procQ').fill(prefix)
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 1')
    page.locator('.proc-tools [data-proc-action="filter"]').click()
    page.locator('.proc-fmenu [data-proc-action="f:stage:found"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 0')
    assert page.locator('.proc-fmenu [data-proc-action="f:stage:found"][aria-checked="true"]').count() == 1
    page.locator('.proc-fmenu [data-proc-action="reset"]').click()
    page.wait_for_function('() => document.querySelectorAll(".tb-grid tbody tr").length === 1')
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
    page.locator('#drawer [data-lead-date="0"][data-k="from"]').fill('2026-11-10'); page.locator('#drawer [data-lead-date="0"][data-k="from"]').press('Tab')
    page.wait_for_function('id => WK.leads[id].dates[0].from === "2026-11-10"', arg=A)
    page.locator('#drawer [data-lead-ns="ok"]').check()
    page.wait_for_function('id => WK.leads[id].ns.ok === true', arg=A)
    page.locator('#drawer [data-proc-action="ns-m:3"]').click()
    page.wait_for_function('id => WK.leads[id].ns.months.join() === "3"', arg=A)
    # согласование: задача предложена, возможные города, «Согласовано» → финал
    page.locator('#drawer [data-proc-action="stage:approve"]').click(); stage(A, 'approve')
    page.locator('#pjDlg [data-lead-task] button.btn-dark').click()
    page.wait_for_function('id => Object.values(WK.tasks).filter(t => t.lead === id).length === 2', arg=A)
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
    for act in ('table','board','list:reserve','list:declined','list:work','tasks'):
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
    print('ok: v2 — этапы, отказ с причиной, резерв, доска, фильтр, подбор, перезвонить, ответ коллектива, согласование, '
          'бронирование, карточка «Репертуара» (гонорар, райдер), «Сотрудничество», пул, «Что горит», задачи, заметки, '
          'перезагрузка, 390 px, обложка')
    browser.close()
